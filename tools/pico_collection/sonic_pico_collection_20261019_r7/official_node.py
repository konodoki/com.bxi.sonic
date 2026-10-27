#!/usr/bin/env python3
"""Read-only ELF3 ROS transport for the official SONIC collector; never publishes commands."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import queue
import signal
import threading
import time

import numpy as np
import yaml
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from communication.msg import ActuatorStates, ActuatorCmds
from sensor_msgs.msg import Image, Imu
from std_msgs.msg import String

from delivery_paths import runs_root, data_root
from official_session import OfficialSession
from session_protocol import ButtonGate
from real_robot_collection.pico import PicoSubscriber, PackedSubscriber, PicoSnapshot
from real_robot_collection.contracts import canonicalize_named, sonic_projected_gravity
from real_robot_collection.synchronization import decode_raw_image, quaternion_multiply_wxyz
from real_robot_collection.gripper_identity import check_sample_identity
from contract import CAMERAS, MODEL_SHA
from collection_health import input_health, reason, exception_reason


def stamp(msg):
    return float(msg.header.stamp.sec)+float(msg.header.stamp.nanosec)*1e-9


class Collector(Node):
    def __init__(self, cfg):
        super().__init__('elf3_official_collection')
        if any(x.get('profile') != 'bxi_gripper_mm_v1' or x.get('position_unit') != 'mm'
               for x in cfg['gripper']['expected_identities']):
            raise ValueError('native66 mm recording requires both BXI mm profiles; DM/radian data needs its legacy contract')
        self.cfg=cfg
        self.session=OfficialSession(runs_root(),data_root(),cfg)
        self.cache={}
        self.lock=threading.Lock()
        self.queue=queue.Queue(maxsize=32)
        self.failure=None
        self.counts=Counter()
        self.last_inference=None
        self.performance={}
        self.last_health_notice=None
        self.state_info=None
        self.last_token_at=None
        self.quit=threading.Event()
        self.groups=[]
        self.subscriptions_owned=[]
        latest=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=1,reliability=ReliabilityPolicy.BEST_EFFORT)
        reliable=QoSProfile(depth=256)
        def sub(cls,topic,callback,qos=latest):
            group=MutuallyExclusiveCallbackGroup();self.groups.append(group)
            def guarded(msg):
                try:
                    self.counts[topic]+=1
                    callback(msg)
                except Exception as exc:
                    self.counts['invalid:'+topic]+=1
                    self.get_logger().error(f'{topic}: {exc}',throttle_duration_sec=5)
            self.subscriptions_owned.append(self.create_subscription(cls,topic,guarded,qos,callback_group=group))
        robot=cfg['robot']
        sub(ActuatorStates,robot['actuator_state_topic'],lambda m:self.put('state',m,stamp(m)))
        sub(ActuatorCmds,robot['actuator_command_topic'],lambda m:self.put('command',m,stamp(m)))
        sub(Imu,robot['imu_topic'],self.imu)
        sub(String,cfg['gripper']['sample_topic'],self.gripper)
        sub(String,cfg['motion_token']['topic'],self.inference,reliable)
        sub(String,robot['state_machine_topic'],self.robot_status)
        for key,raw in CAMERAS.items():
            sub(Image,cfg['cameras'][raw]['topic'],lambda m,k=key:self.put(k,decode_raw_image(m),stamp(m)))
        self.pico=PicoSubscriber(cfg['pico']['host'],cfg['pico']['port'],'pose')
        self.manager=PackedSubscriber(cfg['pico']['host'],cfg['pico']['port'],'manager_state',snapshot_type=PicoSnapshot)
        self.pico.start();self.manager.start()
        self.gate=ButtonGate(source_clock=False)
        self.manager_at=0.
        self.mode=None
        group=MutuallyExclusiveCallbackGroup();self.groups.append(group)
        self.create_timer(.01,self.buttons,callback_group=group)
        self.create_timer(1.,self.monitor,callback_group=group)
        self.worker=threading.Thread(target=self.write_loop,name='official-writer')
        self.worker.start()
        print('PICO_COLLECTION_LISTENER_READY: 已恢复按键监听，请先松开按键；输入是否齐全见COLLECTION_HEALTH。left grip+A starts/saves; left grip+B discards. No motor commands.',flush=True)

    def robot_status(self,msg):
        self.state_info=(str(json.loads(msg.data).get('current',{}).get('name','')),time.monotonic())

    def monitor(self):
        now=time.monotonic()
        with self.lock:snapshot=dict(self.cache)
        info=self.state_info
        health=input_health(snapshot,self.manager.latest(),now,CAMERAS,
            state_name=info[0] if info else None,state_age=now-info[1] if info else None)
        health['token_age_s']=None if self.last_token_at is None else now-self.last_token_at
        health['button_events']=dict(self.gate.events)
        health['button_last_reason']=self.gate.last_reason
        health['button_last_rejection']=self.gate.last_rejection
        health['button_rejected']=self.gate.rejected
        self.session.health=health
        self.session.missing=health['missing']
        notice=(tuple(health['missing']),tuple(health['stale']),health['manager_connected'],health['robot_state'])
        if notice!=self.last_health_notice:
            print('COLLECTION_HEALTH='+json.dumps(health,ensure_ascii=False),flush=True)
            self.last_health_notice=notice
        if self.session.recording and not self.session.busy and health['camera_stalled']:
            self.failure=reason('camera_stream_lost',','.join(health['camera_stalled']))
            self.quit.set()

    @staticmethod
    def body(values,names):
        value,_=canonicalize_named(values,names,label='body29')
        return value[:29]

    def put(self,key,value,source_time):
        with self.lock:
            self.cache[key]=(value,float(source_time),time.monotonic())

    def imu(self,msg):
        # The 1 kHz callbacks only retain the latest immutable message. Convert
        # the selected snapshot once per actual inference (50 Hz), not 1 kHz.
        self.put('imu',msg,stamp(msg))

    def gripper(self,msg):
        raw=json.loads(msg.data)
        if raw.get('schema') != 2 or raw.get('contract_id') != 'elf3_native66_bxi_opening_mm_v2':
            raise ValueError('wrong gripper telemetry ABI; do not relabel radians as mm')
        samples=raw['samples']
        if len(samples)!=2:raise ValueError('both motor fields required by this training contract')
        measured,command=[],[]
        for sample,expected in zip(samples,self.cfg['gripper']['expected_identities']):
            check_sample_identity(sample,expected)
            measured.append(float(sample['opening_mm']))
            command.append(float(sample['command']['position_mm']))
        if not np.isfinite(measured+command).all():raise ValueError('nonfinite gripper opening')
        # No 30/50ms freshness cutoff. Retain receipt/source times for offline inspection.
        self.put('gripper',(np.array(measured),np.array(command)),raw['monotonic'])
        self.put('gripper_sources',dict(training_eligible=raw.get('training_eligible'),
            channels=[dict(side=x['side'],feedback_monotonic=x['feedback_monotonic'],
                command_monotonic=x['command']['sent_monotonic']) for x in samples]),raw['monotonic'])

    def enqueue(self,item):
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            # Blocking here used to leave old tokens in DDS while state/images
            # advanced. Never silently mix them or grow memory without bounds.
            self.failure=reason('writer_overload','collection writer cannot keep up: receive queue full')
            self.quit.set()
            self.get_logger().error(json.dumps(self.failure,ensure_ascii=False))

    def inference(self,msg):
        self.last_token_at=time.monotonic()
        # Keep draining DDS while idle/saving. Those tokens belong to no episode.
        if not self.session.recording or self.session.busy or self.quit.is_set():
            return
        raw=json.loads(msg.data)
        if raw.get('motion_token_valid') is not True or raw.get('model_sha256')!=MODEL_SHA:
            raise ValueError('not a valid token from the configured SONIC model')
        seq=int(raw['inference_sequence']);st=raw['stamp'];source=float(st['sec'])+float(st['nanosec'])*1e-9
        identity=(seq,source)
        if self.last_inference is not None and seq==self.last_inference[0]:return
        # A controller re-entry may reset the sequence; timestamp distinguishes epochs.
        self.last_inference=identity
        token=np.asarray(raw['motion_token'],dtype=np.float32)
        if token.shape!=(64,) or not np.isfinite(token).all():raise ValueError('token must contain 64 finite values')
        received=time.monotonic()
        with self.lock:
            snapshot=dict(self.cache)  # Arrays are replaced, never mutated by callbacks.
        missing=sorted(set(['state','command','imu','gripper',*CAMERAS])-snapshot.keys())
        self.session.missing=missing
        if missing:
            self.counts['waiting_initial_inputs']+=1
            return
        pose=self.pico.latest(); manager=self.manager.latest()
        live=(pose is not None and received-pose.received_monotonic<=.1
              and pose.stream_mode==1 and pose.calibrated
              and manager is not None and received-manager.received_monotonic<=.5
              and manager.stream_mode==1 and raw.get('policy_status')=='live_reference')
        smpl=np.asarray(pose.fields['smpl_pose'],dtype=np.float32).reshape(-1,63)[0].copy() if live else np.zeros(63,dtype=np.float32)
        if smpl.size!=63:raise ValueError(f'Expected official 63 SMPL values, got {smpl.size}')
        state=snapshot['state'][0];command=snapshot['command'][0];imu=snapshot['imu'][0]
        body=self.body(state.position,state.name)
        target=self.body(command.pos,command.actuators_name)
        q=quaternion_multiply_wxyz([imu.orientation.w,imu.orientation.x,imu.orientation.y,imu.orientation.z],
            self.cfg['robot']['imu_orientation_correction_wxyz'])
        if not np.isfinite(q).all() or np.linalg.norm(q)<1e-6:raise ValueError('invalid IMU quaternion')
        grip,gripcmd=snapshot['gripper'][0]
        frame={'observation.state':np.concatenate((body,grip)).astype(np.float32),
            'observation.projected_gravity':sonic_projected_gravity(q,body).astype(np.float32),
            'action.wbc':np.concatenate((target,gripcmd)).astype(np.float32),
            'action.motion_token':token,'teleop.smpl_pose':smpl}
        for key in CAMERAS:frame['observation.images.'+key]=snapshot[key][0]
        provenance=dict(inference_sequence=seq,inference_stamp_unix=source,received_monotonic=received,
            source_stamps={k:v[1] for k,v in snapshot.items()},
            receipt_ages_s={k:received-v[2] for k,v in snapshot.items()},
            inference_receipt_delay_s=self.get_clock().now().nanoseconds*1e-9-source,
            source_clock_domains={'gripper':'robot_monotonic','other':'ROS_header'},
            live_pose=bool(live),gripper_sources=snapshot.get('gripper_sources',(None,))[0])
        self.enqueue(('frame',(frame,provenance)))

    def buttons(self):
        if self.quit.is_set():return
        for packet in self.manager.after(self.manager_at):
            self.manager_at=packet.received_monotonic
            mode=packet.stream_mode==1 and packet.calibrated
            if mode!=self.mode:
                self.enqueue(('command',('pose' if mode else 'pause',packet.received_monotonic)))
                self.mode=mode
            event=self.gate.accept(packet,time.monotonic(),time.time())
            if event:
                print('COLLECTION_BUTTON='+json.dumps(dict(event=event,recording=self.session.recording,
                    busy=self.session.busy,mode=packet.stream_mode)),flush=True)
                if self.session.busy:
                    self.counts['button_while_saving']+=1
                    print('COLLECTION_BUSY: official writer is finishing the previous episode',flush=True)
                else:self.enqueue(('command',(event,packet.received_monotonic)))

    def write_loop(self):
        try:
            last_status=0.
            while True:
                try:kind,value=self.queue.get(timeout=.2)
                except queue.Empty:
                    if self.quit.is_set():break
                    kind,value=None,None
                if kind=='stop':break
                if kind=='frame':
                    started=time.monotonic()
                    frame,provenance=value
                    provenance['writer_queue_age_s']=started-provenance['received_monotonic']
                    self.session.add(frame,provenance)
                    self.performance=dict(add_frame_ms=(time.monotonic()-started)*1000,
                        writer_queue_age_ms=provenance['writer_queue_age_s']*1000,
                        inference_receipt_delay_ms=provenance['inference_receipt_delay_s']*1000)
                elif kind=='command' and not self.quit.is_set():self.session.handle(*value)
                if time.monotonic()-last_status>=1:
                    status=self.session.publish_status()
                    print('COLLECTION_STATE='+json.dumps(dict(phase=status['phase'],accepted_rows=status['accepted_rows'],
                        missing=status['missing'],queue=self.queue.qsize(),counts=self.counts,
                        performance=self.performance,health=status.get('health'),reason=status.get('reason'),encoders={k:w.performance() for k,w in
                            (self.session.data_exporter.video_writers.items() if self.session.data_exporter is not None else [])})),flush=True)
                    last_status=time.monotonic()
        except BaseException as exc:
            self.failure=exception_reason(exc);self.quit.set()
        finally:
            try:
                if self.failure:
                    self.session.fail(self.failure)
                    if self.session.recording:self.session.handle('interrupt')
                self.session.close()
            except BaseException as exc:self.failure=str(exc);self.session.fail(exc)

    def close(self):
        # Supervisor writes the actual cause before asking us to drain/close.
        path=os.environ.get('COLLECTION_STOP_REASON')
        if path and Path(path).is_file() and not self.failure:
            try:self.failure=json.loads(Path(path).read_text())
            except (OSError,ValueError):self.failure=reason('operator_stop')
        self.pico.close();self.manager.close()
        # Stop ingress, drain already frozen frames, then finalize. No full-queue
        # sentinel and no backpressure in a ROS callback.
        self.quit.set()
        self.worker.join()
        self.quit.set()


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    rclpy.init();node=Collector(yaml.safe_load(a.config.read_text()))
    executor=SingleThreadedExecutor();executor.add_node(node)
    try:
        while rclpy.ok() and not node.quit.is_set():executor.spin_once(timeout_sec=.2)
    except KeyboardInterrupt:pass
    except Exception as exc:
        node.failure=exception_reason(exc,'ros_receive_error')
        node.quit.set()
    finally:
        node.quit.set() if node.failure else None
        executor.shutdown()
        node.close();node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
    if node.failure:raise SystemExit(node.failure)


if __name__=='__main__':main()
