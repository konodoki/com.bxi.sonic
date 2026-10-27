"""Confirmed USB topology. No writes to deployed controller/camera configuration."""
from pathlib import Path
import os
import re
import yaml
from real_robot_collection.gripper_identity import identities
from delivery_paths import data_root, site

COLLECTOR_RELEASE = "20261026-collection-17-resident-recovery"

ROOT = Path(__file__).resolve().parent
PORTS = site()['wrist_usb_ports']
FIXED_CAMERA_SHA256 = '513f7143ccbb376d92350ef28ab084e340e3c2bb840cafdf7c6874283a2e9c76'


def add_gripper_arguments(parser):
    parser.add_argument('--left', choices=('dm', 'bxi'), default='dm')
    parser.add_argument('--right', choices=('dm', 'bxi'), default='dm')
    parser.add_argument('--left-id', type=int)
    parser.add_argument('--right-id', type=int)
    parser.add_argument('--left-bus', type=int, choices=(5, 6), default=5)
    parser.add_argument('--right-bus', type=int, choices=(5, 6), default=6)


def configuration(left='dm', right='dm', left_id=None, right_id=None, *, left_bus=5, right_bus=6):
    expected = identities(left, right, left_id, right_id, left_bus=left_bus, right_bus=right_bus)
    profile = site().get('capture_profile', 'head30')
    if profile not in ('head30', 'sonic50_latest_rgb'):
        raise ValueError('capture_profile must be head30 or sonic50_latest_rgb')
    cfg = yaml.safe_load((ROOT/'collector/config/real_collection.yaml').read_text())
    cfg['dataset'].update(embodiment='elf3_three_rgb_gripper_diagnostic',
        output_root=str(data_root()), fps=50 if profile == 'sonic50_latest_rgb' else 30, min_episode_frames=1,
        jpeg_quality=90, queue_capacity=16, default_task_id='three_rgb_gripper_trial',
        tasks=[dict(id='three_rgb_gripper_trial', instruction=f'Diagnostic trial: three RGB cameras, left {left} / right {right} PICO teleoperation.')])
    cfg['sequence']['history_size'] = 2048
    cfg['gripper'] = dict(enabled=True, sample_topic='/sonic/gripper_sample',
        state_joint_names=['left_gripper','right_gripper'], command_joint_names=['left_gripper','right_gripper'],
        mapping={'verified':False}, expected_identities=expected)
    cfg['requirements'].update(formal_collection=False, diagnostic_three_rgb_gripper=True,
                               require_pico_calibrated=True)
    cfg['robot']['odom_topic'] = ''
    cfg['robot']['touch_topic'] = ''
    cfg['cameras']['history_size'] = 24
    cfg['cameras']['max_delta_ms'] = 25.
    cfg['cameras']['head_depth'] = dict(enabled=False)
    cfg['cameras']['head_rgb'].update(enabled=True, width=1920, height=1080, fps=30,
        topic='/hardware/head_depth_camera/color/image_raw', message_type='raw',
        serial='existing_head_driver_serial_not_probed', calibration_file='not_verified')
    for side, port in PORTS.items():
        cfg['cameras'][side+'_wrist_rgb'].update(enabled=True, width=640, height=480, fps=30,
            topic=f'/bxi_trial/{side}/image_raw', camera_info_topic=f'/bxi_trial/{side}/camera_info',
            message_type='raw', serial=f'/dev/v4l/by-path/pci-0000:00:14.0-usb-0:{port}:1.0-video-index0',
            frame_id=f'{side}_wrist_camera_optical_frame', calibration_file='not_verified')
    cfg['metadata'] = dict(robot_serial=site()['robot_hostname'], operator_id='diagnostic_operator',
        site='three_rgb_gripper_trial', camera_calibration_status='not_verified',
        gripper_identities=expected,
        collector_release=COLLECTOR_RELEASE, capture_profile=profile,
        storage_backend='nvidia_sonic_lerobot_v1' if profile == 'sonic50_latest_rgb' else 'legacy_jpeg',
        sample_selection='latest_received_v1' if profile == 'sonic50_latest_rgb' else 'legacy_source_match',
        camera_left_right_verified=site()['camera_roles_confirmed'], physical_ports=dict(PORTS),
        camera_role_evidence=site()['camera_role_evidence'],
        notes='Raw source with explicit DM/BXI identity and BXI gripper opening mm (DM remains radians in its own contract); offline training export validates complete saved data.')
    task = site().get('training_task', '').strip()
    if task:
        cfg['dataset']['tasks'][0]['instruction'] = task
    cfg['metadata']['training_export_profile'] = 'elf3_native_1d'
    return cfg


def resolve_devices(cfg):
    resolved = {}
    for side in PORTS:
        path = Path(cfg['cameras'][side+'_wrist_rgb']['serial']).resolve(strict=True)
        if not re.fullmatch(r'/dev/video[0-9]+', str(path)) or not path.is_char_device():
            raise RuntimeError('not a canonical V4L2 camera: '+str(path))
        if not os.access(path, os.R_OK | os.W_OK):
            raise RuntimeError('camera access denied: '+str(path))
        resolved[side] = str(path)
    if len(set(resolved.values())) != 2:
        raise RuntimeError('both camera ports resolve to the same device')
    return resolved


def camera_command(side, device):
    if side not in PORTS or not re.fullmatch(r'/dev/video[0-9]+', device):
        raise ValueError('requires left/right and resolved /dev/videoN')
    return ['ros2','run','usb_cam','usb_cam_node_exe','--ros-args','--params-file',
        str(ROOT/'collector/config'/f'{side}_wrist_usb.yaml'),
        '-r',f'__node:={side}_bxi_trial_camera','-r',f'__ns:=/bxi_trial/{side}',
        '-p',f'video_device:={device}','-p','image_width:=640','-p','image_height:=480',
        '-p','framerate:=30.0','-p',f'camera_name:={side}_wrist_camera',
        '-p',f'frame_id:={side}_wrist_camera_optical_frame']
