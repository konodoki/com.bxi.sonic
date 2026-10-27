"""Offline file transaction checks; never examines real processes or devices."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('install_exit', Path(__file__).with_name('install_exit.py'))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root/'example'
        self.previous = b'# offline previous controller fixture\n'
        self.paths = []
        for folder in m.FOLDERS:
            p = self.base/folder/'bxi_demo.py'
            p.parent.mkdir(parents=True)
            p.write_bytes(self.previous)
            self.paths.append(p)
        self.sha_patch = patch.object(m, 'PREVIOUS_SHA', m.sha(self.previous))
        self.sha_patch.start()
        self.addCleanup(self.sha_patch.stop)
        self.idle = patch.object(m, 'require_idle')
        self.idle.start()
        self.addCleanup(self.idle.stop)

    def test_both_locations_backed_up_and_idempotent(self):
        m.install(m.plan(self.base), self.root)
        for p in self.paths:
            self.assertEqual(m.sha(p.read_bytes()), m.PAYLOAD_SHA)
        backups = list(self.root.glob('gripper_exit_backup_*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0]/'0').read_bytes(), self.previous)
        m.install(m.plan(self.base), self.root)
        self.assertEqual(len(list(self.root.glob('gripper_exit_backup_*'))), 1)

    def test_unknown_file_prevents_any_write(self):
        self.paths[1].write_bytes(b'# local edit')
        with self.assertRaisesRegex(RuntimeError, '拒绝覆盖'):
            m.plan(self.base)
        self.assertEqual(self.paths[0].read_bytes(), self.previous)

    def test_external_symlink_is_rejected(self):
        outside = self.root/'outside.py'
        outside.write_bytes(self.previous)
        self.paths[0].unlink()
        self.paths[0].symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'outside'):
            m.plan(self.base)

    def test_alias_to_source_is_updated_once_without_breaking_link(self):
        self.paths[1].unlink()
        self.paths[1].symlink_to(self.paths[0])
        records = m.plan(self.base)
        self.assertEqual(len(records), 1)
        m.install(records, self.root)
        self.assertTrue(self.paths[1].is_symlink())
        self.assertEqual(m.sha(self.paths[1].read_bytes()), m.PAYLOAD_SHA)

    def test_process_guard_and_concurrent_edit_prevent_writes(self):
        records = m.plan(self.base)
        with patch.object(m, 'require_idle', side_effect=RuntimeError('busy')):
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                m.install(records, self.root)
        self.paths[1].write_bytes(b'# concurrent change')
        with self.assertRaisesRegex(RuntimeError, 'changed after'):
            m.install(records, self.root)
        self.assertEqual(self.paths[0].read_bytes(), self.previous)

    def test_second_write_failure_rolls_back_first(self):
        original = m.atomic_write
        def write(path, data):
            if path == self.paths[1] and data != self.previous:
                raise OSError('offline write failure')
            original(path, data)
        with patch.object(m, 'atomic_write', side_effect=write):
            with self.assertRaises(OSError):
                m.install(m.plan(self.base), self.root)
        self.assertTrue(all(p.read_bytes() == self.previous for p in self.paths))


if __name__ == '__main__':
    unittest.main()
