"""Real official MP4/Parquet close on interruption; synthetic data, no ROS."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R),str(R/'collector'),str(R.parents[1]/'gr00t_dataset')]
from official_session import OfficialSession
from collection_health import reason
from contract import CAMERAS, VECTOR_NAMES
import official_writer

class RealWriterRecovery(unittest.TestCase):
    def test_camera_failure_flushes_all_three_videos_and_marks_interrupted(self):
        with tempfile.TemporaryDirectory() as temp,patch('pathlib.Path.home',return_value=Path(temp)):
            cfg={'gripper':{'expected_identities':[]},'dataset':{'tasks':[{'instruction':'SYNTHETIC RECOVERY TEST ONLY'}]}}
            s=OfficialSession(Path(temp)/'runs',Path(temp)/'data',cfg)
            try:
                s.handle('toggle')
                for i in range(12):
                    frame={k:np.zeros(len(v),np.float32) for k,v in VECTOR_NAMES.items()}
                    frame['teleop.smpl_pose']=np.ones(63,np.float32)
                    for name in CAMERAS:frame['observation.images.'+name]=np.full((32,32,3),i*10,np.uint8)
                    s.add(frame,dict(inference_sequence=i))
                writer=s.data_exporter
                s.fail(reason('camera_right_exit','synthetic exit=250'))
                s.handle('interrupt')
                self.assertEqual(official_writer.verify_videos(writer),36)
                info=json.loads((s.output/'lerobot/meta/info.json').read_text())
                self.assertEqual(info['total_frames'],12)
                self.assertEqual(info['discarded_episode_indices'],[0])
                report=json.loads((s.folder/'session_result.json').read_text())
                self.assertEqual(report['outcome'],'interrupted')
                self.assertEqual(report['reason']['code'],'camera_right_exit')
                self.assertFalse(s.recording)
            finally:s.close()
if __name__=='__main__':unittest.main()
