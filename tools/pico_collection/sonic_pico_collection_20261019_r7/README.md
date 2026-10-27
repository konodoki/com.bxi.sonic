> 当前维护版：v17常驻恢复；见[恢复说明](../RECOVERY_V17.md)与[统一入口](../../customer/README.md)。下文旧版本步骤仅用于追溯。

# ELF3 PICO 数据采集

当前在线版本为v13：直接调用官方SONIC写入器保存MP4和Parquet，不再使用v12的JPEG队列。见[在线采集说明](../../gr00t_dataset/ONLINE_COLLECTION.md)。下文旧JPEG步骤仅用于历史记录；新格式也由同一下载检查/离线训练导出入口读取。

本地源码版本：`20261021-collection-12-latest-received`。离线验证完成后供人工部署；尚无本版真机结果。目录名保留兼容原入口。客户部署与依赖见[客户入口](../../customer/README.md)，训练文件与字段见[官方写入器入口](../../gr00t_dataset/README.md)。

## 按键

| 按键 | 操作 |
|---|---|
| 左握持键+A | 空闲时开始；录制或暂停时保存 |
| 左握持键+B | 弃用当前条，原文件保留并排除训练 |
| A+X | 切出POSE暂停写入；切回后继续同一条 |

握持键是中指侧键，不是控制夹爪的食指扳机。没有Y+A/Y+B采集别名。
开始后等`RECORDING`和`accepted_rows`增长。保存期间显示`SAVING/FINALIZING`，必要写盘和本采集进程收尾完成后回到`WAITING_FOR_BUTTON`；此时可开始下一条。

## 本版复用官方的部分

以NVIDIA `GR00T-WholeBodyControl`提交`e3018c79f1a0c92b254470db312c25d08794806d`为依据：

- `EpisodeState`直接使用随包保留的官方源码，来源在`sonic_collection_vendor/UPSTREAM.json`。
- 按`run_data_exporter.py`的`latest_proprio_msg/latest_image_msg`方式使用最近收到的数据。删除当前模式的30ms因果匹配、目标角严格相等匹配、100ms图像配对门槛；不因这些时间差丢整行。没有首次数据时等待，不编造关节或IMU。
- 对应官方状态订阅的`ZMQ CONFLATE`，ROS状态/指令/IMU各用独立串行回调组和`KEEP_LAST=1`，避免高频旧包排队。推理结果是事件流，用独立回调组和256条队列；每个实际推理结果最多保存一次。
- 机器人保存只等待写入器排空和必要进程收尾，不调用逐张JPEG检查。`launcher_status.json`记录`finalization=PASS`、`readback=NOT_RUN_ON_ROBOT`。工作站下载后仍运行完整`verify_saved.py`。
- 工作站训练导出继续直接调用官方`Gr00tDataExporter/VideoWriter`及统计函数；不另写Parquet/MP4格式。

官方入口接G1/ZMQ的成组数据，ELF3接ROS2独立话题，因此这里保留必要接口适配；不是把整个G1程序原样放到ELF3运行。

## 保存内容与时间

当前模式`capture_profile=sonic50_latest_rgb`，`sample_selection=latest_received_v1`。每个新到达的真实SONIC推理结果对应一行，目标50Hz。状态、最终指令、IMU、夹爪和三路图像使用组装时最近收到的有效值；相机仍30Hz，同一画面可对应多行。

这不等于所有字段物理上同时采样。原始行保留各自源时间、接收时间、组装时间及推理序号；SMPL没有独立墙钟时明确使用接收时间，不借用另一个PICO帧的时间冒充。数据旧了也保留真实年龄供离线查看。缺失的推理结果不复制补齐。格式不合法、首次必需数据未收到、写盘失败等仍明确报错。

A+X暂停区间不写推理行，恢复后仍在同一原始episode；最新图像/状态允许跨恢复边界沿用。`capture_segment`和`pose_pauses`只保留来源。训练导出按官方清理后的语义，把前后段连成同一训练episode，训练窗口允许跨接缝。

训练输入维度保持现有合同：身体29、左右夹爪各1个实际电机角；`observation.state`31维加重力3维，动作motion-token64加双爪2维。夹爪角使用真实电机rad，闭合0°、打开300°，不转为仿真开度；原始诊断行仍可包含头部2维，导出不使用头部。

## 启动和核查

客户按`tools/customer/README.md`配置自身路径与环境；不引用开发工作站目录。test-01更新沿用已有服务和site.json，不改硬件、键盘、SONIC身体或夹爪控制，不自动录制。

机器人：先保存/弃用正在录制的一条，等监听器空闲，再运行提供的更新脚本。版本就绪后测试普通保存、暂停后保存、普通弃用、暂停后弃用各一次。保存时不再等待全量JPEG解码；写盘仍需要时间。

工作站：下载原始数据后执行`verify_saved.py /记录/episode_0000`，弃用数据加`--allow-incomplete`。完整JPEG读回、时间年龄和实际帧率在此检查，不能把机器人写盘成功等同于训练验收。

历史`head30`和v11严格匹配数据仍可读回。新采集路径只使用上述最新值语义。相机/状态机完全失联、低磁盘、写盘失败等仍中断并保留原始数据；不会自动重试，也不发送电机命令。
