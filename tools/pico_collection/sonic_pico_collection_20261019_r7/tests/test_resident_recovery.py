"""Offline disconnect/reconnect and interrupted-session regressions; no ROS/device I/O."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch, Mock

R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R),str(R/'collector'),str(R.parents[1]/'gr00t_dataset')]
from collection_health import reason, input_health
from official_session import OfficialSession
from resident_launcher import Supervisor
from session_protocol import ButtonGate
from test_button_recording import manager


class Writer:
    def __init__(self):
        self.video_writers={};self.episode_buffer={'size':1};self.saved=0;self.discarded=0
    def save_episode(self):self.saved+=1
    def save_episode_as_discarded(self):self.discarded+=1


class RecoveryTests(unittest.TestCase):
    def test_reconnect_re_resolves_ports_and_stops_only_owned_children(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'listener';folder.mkdir()
            spawned=[];stopped=[]
            def spawn(*a,**kw):
                p=Mock(pid=100+len(spawned));p.poll.return_value=None;spawned.append((p,a,kw));return p
            with patch('resident_launcher.resolve_devices',side_effect=[FileNotFoundError('/dev/v4l'),{'left':'/dev/video8','right':'/dev/video0'}]) as resolve, \
                 patch('resident_launcher.output',return_value=NS(returncode=1,stderr='')), \
                 patch('resident_launcher.python',return_value='/usr/bin/python3'), \
                 patch('resident_launcher.stop',side_effect=lambda p:stopped.append(p)):
                s=Supervisor({},folder,spawn=spawn)
                self.assertFalse(s.start());self.assertEqual(s.failure['code'],'camera_unavailable')
                s.status('WAITING_FOR_RECOVERY',s.failure)
                self.assertEqual(json.loads((folder.parent/'status.json').read_text())['phase'],'WAITING_FOR_RECOVERY')
                self.assertFalse(spawned)
                self.assertTrue(s.start());self.assertEqual(resolve.call_count,2)
                self.assertEqual(len(spawned),3)
                spawned[1][0].poll.return_value=250
                cause=s.exited();self.assertEqual(cause['code'],'camera_right_exit')
                s.cleanup(cause)
                self.assertEqual(stopped,[spawned[2][0],spawned[1][0],spawned[0][0]])
                self.assertEqual(json.loads(s.stop_reason.read_text())['code'],'camera_right_exit')
                self.assertFalse(s.children)

    def test_supervisor_waits_and_recovers_without_recording_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'listener';p.mkdir()
            sleeps=[]
            def sleep(t):
                sleeps.append(t)
                if len(sleeps)==3:raise KeyboardInterrupt
            s=Supervisor({},p,sleep=sleep)
            s.start=Mock(side_effect=[False,True])
            s.exited=Mock(return_value=None)
            s.run()
            self.assertEqual(s.start.call_count,2)
            self.assertEqual(sleeps,[5.,1.,1.])
            status=json.loads((p.parent/'status.json').read_text())
            self.assertFalse(status['automatic_recording'])
            self.assertEqual(status['phase'],'LISTENER_STOPPED')

    def test_interrupt_keeps_official_writer_and_real_reason_and_rearms_idle(self):
        with tempfile.TemporaryDirectory() as temp, patch('pathlib.Path.home',return_value=Path(temp)):
            cfg={'gripper':{'expected_identities':[]}}
            s=OfficialSession(Path(temp)/'runs',Path(temp)/'data',cfg,writer_factory=lambda *a,**kw:None)
            s.handle('toggle');s.rows=3;s.data_exporter=writer=Writer()
            s.source.write('{"row":0}\n')
            failure=reason('camera_right_exit','exit_code=250')
            s.fail(failure);s.handle('interrupt')
            report=json.loads((s.folder/'session_result.json').read_text())
            self.assertEqual(report['outcome'],'interrupted')
            self.assertEqual(report['reason'],failure)
            self.assertEqual(report['num_frames'],3)
            self.assertTrue((s.output/'source.jsonl').is_file())
            self.assertEqual(writer.discarded,1);self.assertEqual(writer.saved,0)
            self.assertFalse(s.recording);self.assertIsNone(s.capture_lock)
            s.handle('toggle');self.assertTrue(s.recording);self.assertIsNone(s.failure_reason)
            s.close()

    def test_save_discard_and_ax_still_use_one_episode(self):
        for command,outcome in [('toggle','saved'),('discard','discarded')]:
            with self.subTest(command=command),tempfile.TemporaryDirectory() as temp,patch('pathlib.Path.home',return_value=Path(temp)):
                s=OfficialSession(Path(temp)/'runs',Path(temp)/'data',{'gripper':{'expected_identities':[]}},writer_factory=lambda *a:None)
                s.handle('toggle');original=s.folder;s.rows=4;s.data_exporter=w=Writer()
                s.handle('pose',1);s.handle('pause',2);s.handle('pose',7)
                self.assertTrue(s.recording);self.assertEqual(s.folder,original)
                s.handle(command)
                self.assertEqual(s.last_result['outcome'],outcome)
                self.assertIsNone(s.last_result['reason'])
                self.assertEqual(w.saved,int(command=='toggle'))
                self.assertEqual(w.discarded,int(command=='discard'))
                result=(s.folder/'session_result.json').read_bytes()
                s.fail(reason('operator_stop'))  # Stopping idle service must not alter a finished episode.
                self.assertFalse((s.folder/'failure.json').exists())
                self.assertEqual((s.folder/'session_result.json').read_bytes(),result)
                s.close()

    def test_reconnected_held_button_cannot_start_episode(self):
        gate=ButtonGate(source_clock=False)
        self.assertIsNone(gate.accept(manager(1,toggle=True),1,1))
        self.assertIsNone(gate.accept(manager(1.1),1.1,1.1))
        self.assertEqual(gate.accept(manager(1.2,toggle=True),1.2,1.2),'toggle')
        self.assertIsNone(gate.accept(manager(5,toggle=True),5,5))

    def test_health_uses_receipt_age_not_camera_timestamp_offset_or_ax_mode(self):
        fields=['state','command','imu','gripper','ego_view','left_wrist','right_wrist']
        cache={key:(None,1.,9.9) for key in fields}
        h=input_health(cache,NS(received_monotonic=9.9,stream_mode=2),10.,fields[-3:])
        self.assertEqual(h['stale'],[]);self.assertTrue(h['manager_connected'])
        h=input_health(cache,None,12.1,fields[-3:])
        self.assertEqual(h['camera_stalled'],fields[-3:]);self.assertFalse(h['manager_connected'])

if __name__=='__main__':unittest.main()
