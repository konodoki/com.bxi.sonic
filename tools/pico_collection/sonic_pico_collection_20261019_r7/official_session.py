"""File/path and ROS snapshot adapter around NVIDIA recording commands and writer.

One resident process; one actual inference becomes at most one row. No JPEG
writer inheritance, per-episode subprocess, minimum-frame or input-timeout abort.
"""
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'gr00t_dataset'))
import official_writer
from contract import CAMERAS
from configure import COLLECTOR_RELEASE
from collection_health import exception_reason, reason
from session_protocol import atomic_json
from sonic_collection_vendor.episode_state import EpisodeState
from sonic_collection_vendor.recording_commands import RecordingCommands


class OfficialSession(RecordingCommands):
    def __init__(self, runs, data, cfg, *, writer_factory=official_writer.create):
        self.runs, self.data, self.cfg = Path(runs), Path(data), cfg
        self.runs.mkdir(parents=True, exist_ok=True)
        self.data.mkdir(parents=True, exist_ok=True)
        self.writer_factory = writer_factory
        if writer_factory is official_writer.create:
            official_writer.dependencies()  # Load Torch/LeRobot before accepting the first button.
        self._episode_state = EpisodeState()
        self._keyboard_listener = SimpleNamespace(read_msg=lambda: None)
        self.sonic_timing_monitor = SimpleNamespace(reset=lambda: None)
        self.frequency = 50
        self.current_episode_index = 0
        self._manager_toggle_da = self._manager_toggle_dc = False
        self.data_exporter = self.folder = self.source = self.capture_lock = None
        self.last_result = None
        self.rows = 0
        self.pauses = []
        self.pose_mode = None
        self.missing = []
        self.error = None
        self.busy = False
        self.health = {}
        self.failure_reason = None

    def _print_and_say(self, text, **kwargs):
        if text == 'Discarded episode' and self.failure_reason:
            text = '中断条已收尾并保留，不计入正常保存数据'
        print('COLLECTION: ' + text, flush=True)

    @property
    def recording(self):
        return self._episode_state.get_state() == self._episode_state.RECORDING

    def handle(self, command, now=None):
        now = time.monotonic() if now is None else now
        if command in ('pose', 'pause'):
            mode = command == 'pose'
            if self.recording and mode != self.pose_mode:
                self.pauses.append(dict(event='resume' if mode else 'pause', row=self.rows, monotonic=now))
            self.pose_mode = mode
            return
        if command == 'toggle' and not self.recording:
            lock = (Path.home()/'.three_rgb_bxi_trial.lock').open('a')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                print('COLLECTION_BUSY: installer or another recorder owns the capture lock',flush=True)
                return
            self.capture_lock = lock
            self.folder = Path(tempfile.mkdtemp(prefix='session_',dir=self.runs))
            self.output = self.data / self.folder.name / 'episode_0000'
            self.output.mkdir(parents=True)
            self.source = (self.output/'source.jsonl').open('x')
            self.rows, self.pauses, self.error = 0, [], None
            self.failure_reason = None
            atomic_json(self.folder/'capture.json', dict(collector_release=COLLECTOR_RELEASE,
                created_unix=time.time(), expected_grippers=self.cfg['gripper']['expected_identities'],
                storage_backend='nvidia_sonic_lerobot_v2', output=str(self.output)))
            self._manager_toggle_dc = True
            self._check_recording_commands()
        elif self.recording and command in ('toggle', 'discard', 'interrupt'):
            outcome = {'toggle':'saved','discard':'discarded','interrupt':'interrupted'}[command]
            self.busy = True
            self.publish_status()
            try:
                if self.rows:
                    self._manager_toggle_dc = command == 'toggle'
                    self._manager_toggle_da = command != 'toggle'
                    self._check_recording_commands()
                    self._finalize_frame(time.monotonic())
                else:
                    self._episode_state.reset_state()  # No empty episode passed to LeRobot.
                self._finish(outcome)
            finally:
                self.busy = False
        self.publish_status()

    def add(self, frame, provenance):
        if not self.recording:
            return
        if self.data_exporter is None:
            sizes={k:frame['observation.images.'+k].shape for k in CAMERAS}
            self.data_exporter=self.writer_factory(self.output/'lerobot',
                self.cfg['dataset']['tasks'][0]['instruction'],camera_shapes=sizes,online=True,record_smpl=True,
                source_metadata={"gripper_identities":self.cfg["gripper"]["expected_identities"]})
        self.data_exporter.add_frame(frame)
        self.source.write(json.dumps(dict(row=self.rows, **provenance),allow_nan=False)+'\n')
        self.rows += 1

    def _finish(self, outcome):
        if self.data_exporter is not None:
            official_writer.close(self.data_exporter)
            self.data_exporter = None
        self.source.flush()
        os.fsync(self.source.fileno())
        self.source.close()
        self.source = None
        report=dict(schema='official-collection-session-v1',collector_release=COLLECTOR_RELEASE,
            outcome=outcome, num_frames=self.rows, events=self.pauses, error=self.error,
            reason=self.failure_reason,
            lerobot_path=str(self.output/'lerobot') if self.rows else None,
            empty=self.rows == 0, hardware_commands_sent=0)
        atomic_json(self.folder/'session_result.json',report)
        atomic_json(self.folder/'launcher_status.json',dict(exit_code=0 if outcome=='saved' else 2,
            official_session=report, runtime_failure=None))
        self.last_result=report
        self._episode_state.reset_state()
        self.capture_lock.close()
        self.capture_lock=None
        print('COLLECTION_FINISHED='+json.dumps(report),flush=True)

    def fail(self, error):
        self.failure_reason = (error if isinstance(error, dict) else exception_reason(error))
        self.error = self.failure_reason['message'] + ': ' + self.failure_reason['detail']
        print('COLLECTION_INTERRUPTED='+json.dumps(self.failure_reason, ensure_ascii=False), flush=True)
        # Keep evidence, never claim an encoder/write error is a successful save.
        if self.folder is not None and (self.source is not None or self.busy or self.recording):
            atomic_json(self.folder/'failure.json',dict(error=self.error,reason=self.failure_reason,rows=self.rows))
        self.publish_status()

    def publish_status(self):
        state = self._episode_state.get_state()
        phase = ('ERROR' if self.error else 'SAVING' if self.busy else
                 'WAITING_FOR_BUTTON' if state == self._episode_state.IDLE else
                 'PAUSED' if self.pose_mode is False else 'RECORDING')
        value=dict(phase=phase,session=str(self.folder) if self.folder else None,
            accepted_rows=self.rows, missing=self.missing, last_result=self.last_result,
            updated_unix=time.time(),listener_pid=int(os.environ.get('COLLECTION_LISTENER_PID',os.getpid())),
            collector_release=COLLECTOR_RELEASE, storage_backend='nvidia_sonic_lerobot_v2',
            shortcuts={'left_grip+A':'start / save','left_grip+B':'discard','A+X':'pause / resume same episode'},
            controller_modified=False,automatic_retry=False,error=self.error,
            reason=self.failure_reason, health=self.health, automatic_listener_recovery=True,
            automatic_recording=False)
        atomic_json(self.runs/'status.json',value,durable=False)
        return value

    def close(self):
        if self.recording and not self.error:
            self.fail(reason('operator_stop'))
            self.handle('interrupt')
        if self.data_exporter is not None:
            official_writer.close(self.data_exporter)
        if self.source is not None:
            self.source.close()
        if self.capture_lock is not None:
            self.capture_lock.close()
