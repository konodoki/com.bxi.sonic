# 数采中止报告与后台恢复（v17）

版本：20261026-collection-17-resident-recovery。离线验证通过。2026-10-27已在test-01安装，日志确认新版本进入`WAITING_FOR_BUTTON`且`automatic_listener_recovery=true`；尚未取得v17断线重连或新录制的验收结果。

## 现场问题与处理

10月23日数采日志显示右腕相机退出，16:36启动时找不到`/dev/v4l`；旧服务`Restart=no`，之后未恢复。操作者补充当天相机线被扯掉。软件应在设备重连后恢复监听，不应要求操作者重启整个机器人。

新逻辑：后台监听 → 相机/记录器异常 → 记录具体原因并收尾 → 等待设备恢复 → 重新监听。每5秒检查缺失/占用设备；运行中的子进程每秒检查。相机重新枚举后重新解析USB路径，不缓存旧`/dev/videoN`。后台可以在未进入SONIC时等待，进入SONIC后沿用同一监听器；不会自动启动hw、SONIC、PICO或头部相机。

“常开”指按键监听与恢复管理常驻，不是自动录制。异常恢复后先松开按键，再按左握持+A开始新条。掉线之前的条标为`interrupted`，不会混入正常保存条，也不会自动续录。A+X正常暂停不触发中止，仍按原规则保持同一条数据。

## 原因与可见状态

- `camera_left_exit` / `camera_right_exit`：对应腕部相机进程退出，附退出码和该次相机日志目录。不能只凭退出码断言硬件原因。
- `camera_unavailable`：设备路径缺失、无权限或被其他程序占用；附路径/错误，等待恢复。
- `camera_stream_lost`：录制中曾收到的某路相机超过2秒未更新，按中断收尾。使用本机收到图像的时间，不用相机header与token差值判定。
- `ros_receive_error`：ROS接收/回调执行异常。
- `writer_overload` / `writer_error` / `disk_full`：写入队列满、编码/写盘失败或空间不足。
- `operator_stop`：操作者停止数采服务。手动停止服务后不会自行再启动。

原因同时输出到journal、当前`status.json`和会话`failure.json`/`session_result.json`。`listener_status.json`显示恢复状态与监听目录。设备检查失败且尚无录制条时，只生成监听诊断，不伪造session。磁盘满或写盘损坏时不能保证收尾文件完整，已有文件保留，须离线检查，不能宣称已成功保存。

`COLLECTION_HEALTH`及每秒`COLLECTION_STATE.health`包含缺失/停止更新的数据项、PICO消息年龄、机器人状态、token消息年龄、按键接收数与拒绝原因。`missing`表示尚未收到过，`stale`表示超过2秒没有更新；这是运行诊断，没有恢复旧的30ms配对丢行门槛。进入`WAITING_FOR_BUTTON`只证明按键监听在运行，三路画面/数值是否齐全需看health以及录制后的行数增长。

当输入首次缺失时仍保留官方按键与会话逻辑，显示缺项，不捏造画面或数值。PICO切出POSE/短暂停顿不会被新逻辑当作相机掉线。非相机数据缺失报告诊断，不添加自动结束episode的门槛。

## 现场查看（机器人终端）

```bash
systemctl status elf3_pico_collection.service --no-pager
journalctl -u elf3_pico_collection.service -n 60 -f -o cat
cat "$HOME/pico_collection_runs/status.json"
cat "$HOME/pico_collection_runs/listener_status.json"
```

自定义站点将路径替换为site配置的`runs_root`。`COLLECTION_SERVICE`显示后台恢复，`COLLECTION_INTERRUPTED`显示中止原因，`COLLECTION_BUTTON`显示收到的操作；`COLLECTION_FINISHED`才是条目收尾结果。

配置/依赖/库指纹错误属于启动失败，写明确错误；systemd版本用`Restart=on-failure`、5秒间隔恢复后台。前台入口内部恢复相机/记录器，不会反复自动安装依赖。收尾等待只针对本数采创建的子进程，不强杀进程、不删除占用锁、不启停机器人控制服务。

## 验证边界

离线模拟设备缺失→重连、右相机退出、服务停止、队列过载、按键重连；使用真正的官方写入器验证中止后Parquet/三路MP4可读且退出结果是interrupted。仍需现场测试设备断连/重连、SONIC状态下恢复监听和再次保存。
