#!/usr/bin/env python3
"""Install demo05 exit fix into an idle example workspace; no hardware imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_SHA = '4240522bb5b76b2bbd35363b0d09f40a34d46b3be90d6356c1599e5339ef20bf'
PAYLOAD_SHA = '7491f4740d4b527bfc8a5abee807771a2c3ead14c97c537b48fe74d9699d789a'
FOLDERS = ('src/bxi_example_py_elf3/mods/com.bxi.sonic',
           'install/share/bxi_example_py_elf3/mods/com.bxi.sonic')
ACTIVE = ('[h]ardware_elf3|[b]xi_example_py_elf3_demo|[b]xi_example_demo[.]py|'
          '[p]ico_manager_thread_server[.]py|[p]ose_to_smpl_ref_bridge[.]py|'
          '[g]ripper_backend|[g]ripper_demo[.]py|[t]est_grippers[.]py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require_idle():
    result = subprocess.run(['pgrep', '-af', ACTIVE], capture_output=True, text=True)
    if result.returncode != 1:
        raise RuntimeError('控制/输入/夹爪测试仍运行或检查失败；请正常结束自己的流程。\n'
                           + result.stdout + result.stderr)


def plan(workspace):
    base = workspace.resolve(strict=True)
    payload = (ROOT/'bxi_demo.py').read_bytes()
    if sha(payload) != PAYLOAD_SHA:
        raise RuntimeError('payload fingerprint mismatch')
    compile(payload, 'bxi_demo.py', 'exec')
    records = {}
    for folder in FOLDERS:
        path = (base/folder/'bxi_demo.py').resolve(strict=True)
        if not path.is_relative_to(base):
            raise RuntimeError('module points outside selected workspace: '+str(path))
        before = path.read_bytes()
        if sha(before) not in (PREVIOUS_SHA, PAYLOAD_SHA):
            raise RuntimeError('不是已核对的毫米demo04/demo05，拒绝覆盖：'+str(path))
        records[path] = (before, payload)
    return records


def atomic_write(path, data):
    stat = path.stat()
    fd, temp = tempfile.mkstemp(prefix='.bxi_exit_', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), stat.st_mode & 0o777)
            if os.geteuid() == 0:
                os.fchown(handle.fileno(), stat.st_uid, stat.st_gid)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def install(records, backup_parent):
    require_idle()
    changes = {p: pair for p, pair in records.items() if pair[0] != pair[1]}
    if not changes:
        return
    backup = Path(tempfile.mkdtemp(prefix='gripper_exit_backup_', dir=backup_parent))
    rows = []
    for i, (path, (before, after)) in enumerate(changes.items()):
        (backup/str(i)).write_bytes(before)
        rows.append(dict(path=str(path), backup=str(i), before=sha(before), after=sha(after)))
    (backup/'manifest.json').write_text(json.dumps(rows, indent=2)+'\n')
    print('BACKUP='+str(backup), flush=True)
    require_idle()
    for path, (before, _) in records.items():
        if path.is_symlink() or path.read_bytes() != before:
            raise RuntimeError('file changed after inspection: '+str(path))
    done = []
    try:
        for path, (before, after) in changes.items():
            done.append((path, before))
            atomic_write(path, after)
        if any(p.read_bytes() != after for p, (_, after) in records.items()):
            raise RuntimeError('post-install mismatch')
    except BaseException:
        for path, before in reversed(done):
            atomic_write(path, before)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    records = plan(args.workspace)
    for path, (before, after) in records.items():
        print(('WRITE=' if before != after else 'ALREADY_INSTALLED=')+str(path))
    if not args.apply:
        print('CHECK_PASS: source/install only; no target writes or hardware actions')
        return
    install(records, args.workspace.resolve().parent)
    print('GRIPPER_EXIT_DISABLE_INSTALLED: 20261027-demo-05-exit-disable; NOT_HARDWARE_VALIDATED')
    print('退出SONIC发送失能帧；请手动重启原hw流程。未启停服务、未发CAN、未使能。')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('STOP: '+str(exc))
