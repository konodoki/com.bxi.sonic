#!/usr/bin/env python3
"""Keep collection standby alive; recover only our cameras/recorder, never motion."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import yaml

from configure import configuration, add_gripper_arguments, resolve_devices, camera_command, FIXED_CAMERA_SHA256, COLLECTOR_RELEASE
from delivery_paths import require_site, runs_root, camera_prefix
from official_runtime import python, check_ros
from launch_collection import output, stop
from session_protocol import atomic_json
from collection_health import reason, exception_reason


class Supervisor:
    def __init__(self, cfg, folder, *, spawn=subprocess.Popen, sleep=time.sleep):
        self.cfg, self.folder = cfg, Path(folder)
        self.spawn, self.sleep = spawn, sleep
        self.children, self.logs = {}, []
        self.failure = None
        self.last_notice = None
        self.retry = 0
        self.config = self.folder/'config.yaml'
        self.config.write_text(yaml.safe_dump(cfg, sort_keys=False))
        self.stop_reason = self.folder/'stop_reason.json'

    def status(self, phase, failure=None):
        value = dict(phase=phase, reason=failure, listener_pid=os.getpid(),
            updated_unix=time.time(), collector_release=COLLECTOR_RELEASE,
            listener_log_dir=str(self.folder), retry=self.retry, recording=False,
            automatic_listener_recovery=True, automatic_recording=False,
            automatic_retry=False, controller_modified=False)
        atomic_json(self.folder.parent/'listener_status.json', value, durable=False)
        # Only write the common status after the recorder has finished/closed.
        if not self.children:
            atomic_json(self.folder.parent/'status.json', value, durable=False)
        notice=(phase, json.dumps(failure, sort_keys=True))
        if notice != self.last_notice:
            print('COLLECTION_SERVICE='+json.dumps(value, ensure_ascii=False), flush=True)
            self.last_notice=notice

    def start(self):
        try:
            devices = resolve_devices(self.cfg)  # Resolve USB paths again after every reconnect.
            for side, device in devices.items():
                result=output(['fuser', device])
                if result.returncode != 1 or result.stderr.strip():
                    raise RuntimeError(side+': camera occupied/access unknown: '+device)
        except (OSError, RuntimeError) as exc:
            self.failure=reason('camera_unavailable', exc)
            return False
        self.stop_reason.unlink(missing_ok=True)
        self.status('STARTING')
        for side, device in devices.items():
            log=(self.folder/('camera_'+side+'.log')).open('a');self.logs.append(log)
            self.children['camera_'+side]=self.spawn(camera_command(side,device),stdout=log,
                stderr=subprocess.STDOUT,start_new_session=True)
        env=dict(os.environ, PYTHONNOUSERSITE='1', COLLECTION_LISTENER_PID=str(os.getpid()),
                 COLLECTION_STOP_REASON=str(self.stop_reason))
        self.children['collector']=self.spawn([python(),'-B','-u',str(Path(__file__).with_name('official_node.py')),
                                               '--config',str(self.config)],env=env,start_new_session=True)
        return True

    def exited(self):
        for name, child in self.children.items():
            code=child.poll()
            if code is not None:
                detail=f'pid={child.pid}; exit_code={code}; logs={self.folder}'
                if name == 'collector':
                    try:
                        previous=json.loads((self.folder.parent/'status.json').read_text())
                        if previous.get('listener_pid') == os.getpid() and previous.get('reason'):
                            return previous['reason']
                    except (OSError, ValueError):
                        pass
                return reason(name+'_exit',detail)
        return None

    def cleanup(self, failure):
        # Pass the actual camera/launcher cause before SIGINT drains the writer.
        atomic_json(self.stop_reason, failure)
        self.status('RECOVERING', failure)
        for name in reversed(list(self.children)):
            stop(self.children[name])  # Only children created by this supervisor; no forced kill.
            del self.children[name]
        for log in self.logs:log.close()
        self.logs.clear()

    def run(self):
        try:
            while True:
                try:
                    if self.start():
                        self.failure=None
                        while True:
                            self.failure=self.exited()
                            if self.failure:break
                            self.status('LISTENING')
                            self.sleep(1.)
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    self.failure=exception_reason(exc, 'startup_error')
                finally:
                    if self.children or self.logs:
                        self.cleanup(self.failure or reason('operator_stop'))
                self.retry+=1
                self.status('WAITING_FOR_RECOVERY',self.failure)
                self.sleep(5.)  # Never replay a button or resume a recording automatically.
        except KeyboardInterrupt:
            pass
        finally:
            if self.children or self.logs:self.cleanup(reason('operator_stop'))
            self.status('LISTENER_STOPPED',reason('operator_stop'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    add_gripper_arguments(parser)
    args=parser.parse_args()
    require_site()
    with (runs_root()/'listener.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        cfg=configuration(args.left,args.right,args.left_id,args.right_id,left_bus=args.left_bus,right_bus=args.right_bus)
        if cfg['metadata']['capture_profile']!='sonic50_latest_rgb':
            raise RuntimeError('Production native66 requires sonic50_latest_rgb')
        check_ros()
        library=camera_prefix()/'lib/libusb_cam.so'
        if hashlib.sha256(library.read_bytes()).hexdigest()!=FIXED_CAMERA_SHA256:
            raise RuntimeError('Unexpected wrist camera binary; no camera started')
        folder=Path(tempfile.mkdtemp(prefix='listener_',dir=runs_root()))
        Supervisor(cfg,folder).run()


if __name__=='__main__':
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
    signal.signal(signal.SIGHUP,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
    try:main()
    except Exception as exc:
        print('COLLECTION_SERVICE_ERROR='+json.dumps(exception_reason(exc,'startup_error'),ensure_ascii=False),flush=True)
        raise
