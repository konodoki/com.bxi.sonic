# PICO数采维护入口

当前本地源码：`20261026-collection-17-resident-recovery`。v17已完成离线回归；10月27日现场已安装并进入WAITING_FOR_BUTTON，断线恢复和本版新录制仍待验证。BXI夹爪合同仍为0～70mm。

- 左握持键+A：开始/保存；左握持键+B：弃用。
- A+X：原有POSE暂停/恢复，前后仍属同一条；采用既有官方写入/清理逻辑。
- 数采后台常驻；相机设备缺失、占用或子进程退出时显示原因，条件恢复后自动回到等待录制。
- 异常中止保留已有文件和原因，不标成成功保存，不自动重录/续录。

[客户统一入口](../customer/README.md) · [v17中止与恢复说明](RECOVERY_V17.md) · [在线写入逻辑](../gr00t_dataset/ONLINE_COLLECTION.md) · [训练导出](../gr00t_dataset/README.md)

旧r7/v7等目录名是现场兼容路径，版本以`COLLECTOR_RELEASE`及启动日志为准。
