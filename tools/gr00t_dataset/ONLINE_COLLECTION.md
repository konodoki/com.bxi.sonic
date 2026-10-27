> 数采维护版v17增加异常原因与恢复待机，官方写入器、毫米合同与A+X清理逻辑不变。见[维护说明](../pico_collection/RECOVERY_V17.md)。

> 2026-10-22当前版本：BXI demo04 / 数采v16，夹爪开口0～70mm；旧角度参数和v15验证记录仅供历史追溯。使用[毫米协议与合同说明](../../docs/GRIPPER_MM_PROTOCOL_20261022.md)。新版本尚未真机验证。

# 在线采集 v15

版本：`20261021-collection-15-nonblocking-ingress`。这是本地离线验证版，安装成功和真机验收需要分别确认。

入口仍是 `tools/pico_collection/sonic_pico_collection_20261019_r7/listen.sh`（目录名保留兼容已有服务）。它启动常驻 ROS 观察进程和两路腕部相机；头部相机由原硬件流程提供。只拥有自己的相机/观察进程，不启动或停止机器人控制。

| 操作 | 行为 |
|---|---|
| 左握持键＋A | 开始；再次按下保存 |
| 左握持键＋B | 弃用，原始数据保留，官方 discarded 标记排除训练 |
| A＋X 切出/切回 POSE | 同一条任务；暂停后继续，最后只生成一个 episode |

这里是握持键，不是扳机。没有 Y+A/Y+B 采集别名。开始可以先于输入就绪；等待至少收到一份身体、指令、IMU、双爪和三路图像后写行。非空就能保存，录后可补任务文字。相机/状态不更新会保留最近值和时间信息，不自行因30ms/1s/2s阈值把用户的保存改成中断。

## 实际调用链

`listen.sh → resident_launcher.py → official_node.py → official_session.py → NVIDIA RecordingCommands / EpisodeState / Gr00tDataExporter / VideoWriter`。

`RecordingCommands` 的开始/保存/弃用与保存收尾方法从官方 `run_data_exporter.py` 原样摘取，测试核对AST相同。每条任务不再拉起相机或新数采进程。原 `button_supervisor.py / session_node.py / RealEpisodeRecorder` 只供历史兼容，不在这条生产调用链中。

v15将1kHz状态/IMU回调缩为保存最新消息引用；实际推理行才转换所需数值。ROS适配层在收到真实推理结果时固定状态、IMU、夹爪和图像快照，再交给官方写入器。每个真实推理最多一行；不补造token。不同传感器的源时间/接收年龄保存在 `source.jsonl`，不做“超过30ms就丢整行”的筛选。NVIDIA G1 的ZMQ接口不能代替ELF3的ROS消息解析，这部分保留为适配。

当前SONIC控制器在保持/暂停时不会发布新的有效推理token。因此没有推理时不造行；有真实推理但POSE失效时，按官方方式将该行SMPL记零，离线调用官方 `process_dataset.py` 清除零帧及其前面的冻结帧。暂停前后仍是一个episode，40步窗口可跨接缝。

## 文件

每条数据在配置的 `data_root/session_*/episode_0000/`：

- `lerobot/data/chunk-000/episode_000000.parquet`：实际数值，训练前再清理/标注。
- `lerobot/videos/chunk-000/observation.images.{ego_view,left_wrist,right_wrist}/episode_000000.mp4`：三路视频，保留原分辨率，每实际数值行对应一帧最新相机画面。
- `lerobot/meta/`：官方 info、modality、episodes、tasks、episodes_stats。
- `source.jsonl`：每行推理序号、时间和数据接收年龄。没有第二套大份训练向量副本。

会话结果在 `runs_root/session_*/session_result.json`，含明确 `saved/discarded/interrupted`、帧数和暂停/恢复边界。权威数值与弃用标记在官方LeRobot文件中。没有相机/控制数据时保存为空记录，不冒充成功数据。

保存阶段只完成官方写盘和视频收尾，不在机器人上逐帧重解码验收。工作站用 `verify_online.py` 检查；`export_dataset.py` 完成任务标注、官方清理/合并、统计。未删帧的视频直接复制；有删帧才重新编码，不提前统一缩成640×480。

## 安装与依赖

客户在库根目录配置 `tools/customer/README.md` 说明的 site JSON、外部 ROS/example 环境。安装隔离写入依赖：

```bash
bash tools/gr00t_dataset/prepare_online_runtime.sh "$PWD/.runtime/collection-writer-v13"
export SONIC_SITE_CONFIG=/实际站点/site.json
bash tools/pico_collection/sonic_pico_collection_20261019_r7/listen.sh \
  --left bxi --right bxi --left-id 1 --right-id 1 --left-bus 5 --right-bus 6
```

依赖目录名v13沿用已经安装的环境，与采集发行号v15无关。test-01使用配套v15升级脚本保留原systemd入口，仅重启空闲采集服务。请先完成当前任务的保存/弃用；脚本不停止hw、keyboard、SONIC或夹爪。

依赖安装默认直连，忽略继承的代理及 pip/git 配置，避免机器人继承 `127.0.0.1:17897` 这类工作站代理。仅作用于安装子进程，不修改系统设置；需要代理时，在运行 `prepare_online_runtime.sh` 的机器上设置 `SONIC_INSTALL_PROXY` 为该机器实际可访问的代理地址。下载失败时保留已安装依赖，下次重试继续安装；全部依赖检查通过后才进行部署。

LeRobot 固定提交的 wheel 已随 `bootstrap/` 提供，安装时核对 SHA256，从本地安装，不再在机器人上执行 GitHub clone。来源提交、源码归档和 wheel 指纹见 `bootstrap/lerobot_source.json`；官方 Python 源码未修改。已安装且版本匹配的 Torch 和其余写入依赖直接复用。新机器首次安装仍需下载其余 Python 依赖，不将此包称为全量离线环境。

## v15性能与故障可见性

官方写入仍在独立线程执行，ROS使用单线程短回调，避免8个Python回调线程争抢；1080p头部编码4线程、腕部各1线程，避免不受限占满机器人CPU。分辨率、帧率、数据合同均不变。

32条接收队列不再阻塞ROS回调。若后端仍持续跟不上，明确报告`collection writer cannot keep up`，停止本记录器接收，排空已冻结的行并以`interrupted`保留，服务不自动重试。不向硬件发命令，不影响模型状态。这个故障处理不能替代性能达标；现场出现该报错请保留日志。

空闲/官方保存收尾时仍排空推理订阅，但不向写入队列塞不属于录制的数据；保存期间的额外开始按键明确提示忙。没有重新加入30ms传感器筛选。

`source.jsonl`新增`inference_receipt_delay_s`（token头时间到ROS接收的差，ROS时钟）和`writer_queue_age_s`（冻结到写入的排队，monotonic）。`COLLECTION_STATE`中`performance`显示最新一行时间，`encoders`显示各相机累计编码均值/最大值、队列和等待时长。数值不是模型推理耗时，也不是PICO无线网络延迟。取原始逐行统计判断积压；不能用相邻间隔中位数倒数代替整段吞吐。

v14已确认2保存/3弃用，但第一条有秒级错位。v15本地验证详情见[性能报告](PERFORMANCE_V15.md)；未获得v15真机验收，旧数据不会被自动修复。
