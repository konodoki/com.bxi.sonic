"""Regression for the field backlog, using real callback bodies without ROS I/O."""
import ast,json,queue,sys,threading,time,unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R),str(R/'collector'),str(R.parents[1]/'gr00t_dataset')]
from contract import CAMERAS,MODEL_SHA,RAW_JOINTS
from collection_health import reason,exception_reason,input_health
from real_robot_collection.contracts import canonicalize_named,sonic_projected_gravity
from real_robot_collection.synchronization import quaternion_multiply_wxyz
ns=dict(np=np,json=json,queue=queue,time=time,CAMERAS=CAMERAS,MODEL_SHA=MODEL_SHA,
    canonicalize_named=canonicalize_named,sonic_projected_gravity=sonic_projected_gravity,
    quaternion_multiply_wxyz=quaternion_multiply_wxyz,reason=reason,exception_reason=exception_reason,input_health=input_health)
cls=next(n for n in ast.parse((R/'official_node.py').read_text()).body if isinstance(n,ast.ClassDef))
cls.bases=[]
exec(compile(ast.Module(body=[cls],type_ignores=[]),str(R/'official_node.py'),'exec'),ns)
C=ns['Collector']
class IngressTests(unittest.TestCase):
 def node(self):
  n=C.__new__(C);n.cache={};n.lock=threading.Lock();n.queue=queue.Queue(32);n.quit=threading.Event();n.failure=None;n.counts=Counter();n.last_inference=None;n.performance={}
  n.cfg={'robot':{'imu_orientation_correction_wxyz':[1,0,0,0]}}
  n.session=NS(recording=True,busy=False,missing=[])
  n.get_logger=lambda:NS(error=lambda m:None)
  n.get_clock=lambda:NS(now=lambda:NS(nanoseconds=int(100*1e9)))
  pose=lambda:NS(received_monotonic=time.monotonic(),stream_mode=1,calibrated=True,fields={'smpl_pose':np.ones(63)})
  n.pico=n.manager=NS(latest=pose,close=lambda:None)
  n.put('state',NS(position=[0.]*31,name=RAW_JOINTS),100.)
  n.put('command',NS(pos=[1.]*31,actuators_name=RAW_JOINTS),100.)
  n.put('imu',NS(orientation=NS(w=1.,x=0.,y=0.,z=0.)),100.)
  n.put('gripper',(np.array([1.,2.]),np.array([3.,4.])),10.)
  for k in CAMERAS:n.put(k,np.zeros((8,8,3),np.uint8),100.)
  return n
 def msg(self,i=1):return NS(data=json.dumps(dict(motion_token_valid=True,model_sha256=MODEL_SHA,inference_sequence=i,stamp={'sec':100,'nanosec':0},motion_token=[.1]*64,policy_status='live_reference')))
 def test_frozen_snapshot_survives_delayed_write(self):
  n=self.node();n.inference(self.msg());n.put('state',NS(position=[9.]*31,name=RAW_JOINTS),105.)
  for k in CAMERAS:n.put(k,np.ones((8,8,3),np.uint8),105.)
  kind,(frame,provenance)=n.queue.get_nowait()
  self.assertTrue(np.all(frame['observation.state'][:29]==0))
  self.assertEqual(provenance['source_stamps']['state'],100.)
  for k in CAMERAS:self.assertTrue(np.all(frame['observation.images.'+k]==0))
  n.inference(self.msg());self.assertTrue(n.queue.empty())
 def test_full_queue_does_not_block_receiving_or_accept_more_tokens(self):
  n=self.node()
  for i in range(32):n.inference(self.msg(i))
  started=time.monotonic();n.inference(self.msg(32))
  self.assertLess(time.monotonic()-started,.1)
  self.assertTrue(n.quit.is_set());self.assertIn('cannot keep up',n.failure['detail'])
  n.inference(self.msg(33));self.assertEqual(n.queue.qsize(),32)
 def test_saving_or_idle_drains_dds_without_filling_writer_queue(self):
  n=self.node()
  for recording,busy in [(False,False),(True,True)]:
   n.session.recording=recording;n.session.busy=busy
   for i in range(500):n.inference(self.msg(i))
   self.assertTrue(n.queue.empty());self.assertIsNone(n.failure)
 def test_overload_preserves_accepted_rows_as_interrupted_not_saved(self):
  n=self.node();n.inference(self.msg());n.failure='synthetic encoder overload';n.quit.set();seen=[]
  n.session.add=lambda f,p:seen.append(('row',p['inference_sequence']))
  n.session.publish_status=lambda:dict(phase='RECORDING',accepted_rows=1,missing=[])
  n.session.data_exporter=None;n.session.fail=lambda e:seen.append(('error',e))
  n.session.handle=lambda cmd:seen.append(('command',cmd));n.session.close=lambda:None
  n.write_loop()
  self.assertEqual(seen,[('row',1),('error','synthetic encoder overload'),('command','interrupt')])
 def test_old_sensor_timestamp_is_preserved_not_30ms_filtered(self):
  n=self.node();n.put('state',NS(position=[0.]*31,name=RAW_JOINTS),99.8);n.inference(self.msg())
  self.assertEqual(n.queue.get()[1][1]['source_stamps']['state'],99.8)
 def test_shutdown_does_not_replay_queued_start_button(self):
  n=self.node();seen=[];n.queue.put(('command',('toggle',1)));n.quit.set()
  n.session.handle=lambda *x:seen.append(x);n.session.close=lambda:None;n.session.data_exporter=None
  n.session.publish_status=lambda:dict(phase='WAITING_FOR_BUTTON',accepted_rows=0,missing=[])
  n.write_loop();self.assertEqual(seen,[])
 def test_camera_loss_interrupts_recording_but_ax_pause_alone_does_not(self):
  n=self.node();n.state_info=('com.bxi.sonic/sonic_teleop',time.monotonic());n.last_health_notice=None;n.last_token_at=None
  n.gate=NS(events={},last_reason='no_edge',last_rejection=None,rejected=0)
  n.monitor();self.assertFalse(n.quit.is_set())
  key=next(iter(CAMERAS));old=n.cache[key];n.cache[key]=(old[0],old[1],time.monotonic()-3.)
  n.monitor();self.assertTrue(n.quit.is_set());self.assertEqual(n.failure['code'],'camera_stream_lost')
if __name__=='__main__':unittest.main()
