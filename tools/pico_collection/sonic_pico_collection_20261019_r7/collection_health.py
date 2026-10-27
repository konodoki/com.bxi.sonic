"""Collection diagnostics only; no control commands or hardware access."""
import errno

MESSAGES = {
    'camera_unavailable': '腕部相机设备缺失、权限不足或被其他程序占用；等待恢复',
    'camera_left_exit': '左腕相机进程退出；检查连接和相机日志',
    'camera_right_exit': '右腕相机进程退出；检查连接和相机日志',
    'camera_stream_lost': '相机超过2秒没有新画面；当前条中止并收尾',
    'collector_exit': '数采进程异常退出；检查记录器日志',
    'ros_receive_error': 'ROS消息接收异常；当前条中止并收尾',
    'writer_error': '数采写入或视频编码异常；保留已有文件供检查',
    'writer_overload': '数采写入跟不上，接收队列已满；当前条中止',
    'disk_full': '数据盘空间不足；当前条中止，需释放空间',
    'operator_stop': '数采服务被停止；当前条按中断处理',
    'startup_error': '数采启动失败；检查依赖、配置与权限',
}


def reason(code, detail=''):
    return dict(code=code, message=MESSAGES.get(code, code), detail=str(detail))


def exception_reason(exc, default='writer_error'):
    return reason('disk_full' if isinstance(exc, OSError) and exc.errno == errno.ENOSPC else default, exc)


def input_health(cache, manager, now, cameras, *, state_name=None, state_age=None):
    """Report seconds-scale outages, not a frame matching/filtering rule."""
    required = ['state', 'command', 'imu', 'gripper', *cameras]
    missing = [key for key in required if key not in cache]
    stale = [key for key in required if key in cache and now-cache[key][2] > 2.]
    manager_age = None if manager is None else max(0., now-manager.received_monotonic)
    return dict(missing=missing, stale=stale, camera_stalled=[k for k in cameras if k in stale],
                manager_age_s=manager_age, manager_connected=manager_age is not None and manager_age <= 2.,
                robot_state=state_name, robot_state_age_s=state_age)
