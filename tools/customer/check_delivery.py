#!/usr/bin/env python3
"""Offline file and path checks only. Never imports ROS or hardware modules."""
import hashlib
import json
from pathlib import Path
from delivery_inventory import REPO, files

REQUIRED = [
 'tools/customer/prepare_pico_runtime.sh', 'docs/PYTHON_ENVIRONMENT.md',
 'tools/collection_review/download.py', 'tools/collection_review/review.py',
 'tools/collection_review/export_all.py', 'tools/collection_review/validate_exports.py',
 'tools/camera_clock/build.py', 'tools/camera_clock/vendor/usb_cam-0.8.1/src/usb_cam.cpp',
 'tools/gr00t_dataset/contract.py', 'tools/gr00t_dataset/elf3_native_1d_config.py',
 'tools/gr00t_dataset/elf3_native_1d_abi.json', 'tools/gr00t_dataset/modality.json',
 'tools/gr00t_dataset/export_dataset.py', 'tools/gr00t_dataset/validate_official.py',
 'tools/gr00t_dataset/official_writer.py', 'tools/gr00t_dataset/vendor/sonic_data/exporter.py',
 'tools/gr00t_dataset/vendor/sonic_data/video_writer.py',
 'tools/gr00t_dataset/vendor/sonic_data/UPSTREAM.json',
 'tools/gr00t_dataset/vendor/sonic_data/process_dataset.py',
 'tools/gr00t_dataset/verify_online.py',
 'tools/gr00t_dataset/vendor/sonic_data/LOCAL_CHANGES.patch',
 'tools/gr00t_dataset/vendor/gr00t_stats.py',
 'tools/gr00t_dataset/requirements.txt', 'docs/GR00T_N17_DATA_FORMAT.md',
 'mod.yaml', 'plugin.py', 'state.py', 'policy.py', 'tracking_tap.py',
 'assets/sonic_action_token.onnx', 'assets/stream_reference.npz',
 'pico/gear_sonic/data/human/human_joints_info.npz',
 'pico/manager_launcher.py', 'pico/pose_to_smpl_ref_bridge.py', 'pico/streamed_smpl_ref.py',
 'bxi_gripper_protocol.py', 'bxi_gripper_mm.json',
 'bxi_demo.py', 'bxi_demo_native.so', 'gripper.py', 'collection_telemetry.py',
 'runtime/linux-x86_64/roboticsservice/RoboticsServiceProcess',
 'runtime/linux-x86_64/roboticsservice/SDK/x64/libPXREARobotSDK.so',
 'tools/tracking_eval/evaluation/g1_kin_step28800.onnx',
 'tools/tracking_eval/recording/elf3_reference.urdf',
 'tools/customer/runtime/ros_humble_x86_64/lib/libusb_cam.so',
 'tools/customer/runtime/ros_humble_x86_64/lib/usb_cam/usb_cam_node_exe',
]
R7 = 'tools/pico_collection/sonic_pico_collection_20261019_r7/'
REQUIRED += [R7+p for p in ('listen.sh','start.sh','environment.sh','configure.py','delivery_paths.py',
 'collector/check_config.py','collector/config/left_wrist_usb.yaml','collector/config/right_wrist_usb.yaml',
 'official_node.py','official_session.py','resident_launcher.py','collection_health.py','sonic_collection_vendor/recording_commands.py')]
ACTIVE = [R7+p for p in ('environment.sh','configure.py','delivery_paths.py','resident_launcher.py','official_node.py','official_session.py','collection_health.py')]
ACTIVE += ['tools/collection_review/download.py', 'tools/collection_review/review.py',
           'tools/collection_review/export_all.py', 'tools/collection_review/validate_exports.py',
           'tools/camera_clock/build.py']
ACTIVE += ['tools/customer/environment.sh','tools/customer/record_tracking.sh','tools/tracking_eval/recording/record.py']

def check():
    errors = []
    for name in REQUIRED:
        if not (REPO/name).is_file(): errors.append('missing: '+name)
    for p in files():
        if p.is_symlink():
            try: p.resolve(strict=True).relative_to(REPO)
            except (OSError, ValueError): errors.append('external/broken link: '+str(p.relative_to(REPO)))
    manifest = json.loads((REPO/'tools/customer/DELIVERY_MANIFEST.json').read_text())
    for name, expected in manifest['files'].items():
        p = REPO/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            errors.append('fingerprint mismatch: '+name)
    for name in ACTIVE:
        for private in ('/home/bxi/', '/home/huangchenwei/', '/data/ros2_ws/'):
            if private in (REPO/name).read_text(): errors.append('private active path: '+name)
    library = REPO/'tools/customer/runtime/ros_humble_x86_64/lib/libusb_cam.so'
    if library.is_file() and hashlib.sha256(library.read_bytes()).hexdigest() != '513f7143ccbb376d92350ef28ab084e340e3c2bb840cafdf7c6874283a2e9c76':
        errors.append('clock-corrected usb_cam hash mismatch')
    print(json.dumps(dict(status='FAIL' if errors else 'PASS', checked_files=len(manifest['files']),
                         errors=errors, hardware_commands=0), ensure_ascii=False))
    return errors

if __name__ == '__main__':
    raise SystemExit(bool(check()))
