# 客户部署入口

当前版本：20261027-mm-v17-resident-recovery。BXI demo04 / 数采v17，闭合0mm、打开70mm。当前预编译运行库支持Ubuntu22.04 x86_64 / ROS2 Humble；其他平台须重新构建并验证。

## 外部依赖与站点配置

客户提供example Mod API4宿主、basic_actions、communication ROS消息、ROS2 Humble、系统共享库和Python依赖。头部相机由宿主的bxi_depth_camera启动；数采启动自己拥有的两路腕部相机。库内资源不需要开发者工作区。

在独立库根目录：

```bash
cp tools/customer/site.example.json tools/customer/site.local.json
```

编辑site.local.json：controller_setup指向实际宿主install/setup.bash；robot_hostname、ros_domain_id和DDS配置与控制器一致。确认三路画面和左右角色后设置camera_roles_confirmed。wrist_usb_ports默认左7/右1，主板PCI拓扑变化时还需调整设备路径。runs_root、data_root可指定数据盘；留空使用当前用户家目录。

capture_profile使用sonic50_latest_rgb；training_task可录后填写真实任务，不能把Diagnostic占位文字当正式标注。training_export保持false。夹爪实测/目标均是mm，身体29维为rad，头部自由度不进训练向量。旧rad采集只能使用其冻结合同。

```bash
export SONIC_SITE_CONFIG="$PWD/tools/customer/site.local.json"
source tools/customer/environment.sh
```

设置环境不会启动机器人。SONIC按宿主的Mod流程加载mod.yaml；启动宿主也要使用同一环境，以选中库内XR服务。

## PICO独立Python环境（不使用Conda）

先在库根执行下面的安装。脚本用系统 `/usr/bin/python3` 创建隔离venv，从PyPI安装已现场使用的依赖版本；只验证依赖导入，不启动XR、ROS、相机或电机。

```bash
bash tools/customer/prepare_pico_runtime.sh
```

看到 `PICO_VENV_READY` 后，SONIC会自动选择 `.runtime/<平台>/pico/bin/python`。它也支持 `.venv` 或通过 `SONIC_PICO_PYTHON` 显式指定系统Python创建的venv；不再搜索/调用Conda，也拒绝从Conda Python创建的venv。当前预编译XR扩展要求Python3.10。

不要把已有Conda的site-packages复制进venv。包管理器名称不能改变包的来源或许可证；本项目使用PyPI、官方PyTorch wheel源和随包固定LeRobot源码wheel。完整边界见[Python环境与依赖来源](../../docs/PYTHON_ENVIRONMENT.md)。

## 安装数采依赖与运行

```bash
bash tools/gr00t_dataset/prepare_online_runtime.sh "$PWD/.runtime/collection-writer-v13"
python3 tools/customer/check_delivery.py
bash tools/pico_collection/sonic_pico_collection_20261019_r7/listen.sh \
  --left bxi --right bxi --left-id 1 --right-id 1 --left-bus 5 --right-bus 6
```

r7、v13是兼容目录名，实际采集发行号为v17。依赖安装复用已装版本，LeRobot wheel随包提供，其他Python依赖仍可能需要下载。

左握持+A开始/保存，左握持+B弃用；A+X暂停/恢复同条episode。与扳机键不同。此入口是前台监听，不改systemd服务，不发电机命令。已有监听器时不要重复开。确认RECORDING且accepted_rows持续增长；结束后确认saved/discarded结果。v17在相机/记录器异常后报告原因、收尾当前条，并自动恢复待机。设备缺失/占用时每5秒检查；恢复后先松开按键，再手动开始新一条。不会自动续录中断条。SONIC及A+X控制逻辑不变；详见[中止与恢复说明](../pico_collection/RECOVERY_V17.md)。

[三相机人工检查](../../docs/CAMERA_MANUAL_CHECK.md) · [数采操作](../pico_collection/README.md) · [具体数据字段](../../docs/COLLECTION_DATA_FORMAT.md)

## 下载、检查与训练导出

工作站使用库内[collection_review](../collection_review/README.md)。SSH地址、输出盘和GR00T解释器显式配置；默认不猜旧IP。不需要root、ROS或机器人控制操作。

批量检查导出会保留保存、弃用、中断的区别，生成三路视频页面。检查包不等于训练就绪包。正式训练需人工确认有效示范、补真实任务标签，再按[gr00t_dataset](../gr00t_dataset/README.md)导出保存的数据并用已有ELF3适配的GR00T加载。当前没有模型后训练结果。

## 跟踪评测

机器人上已有SONIC控制运行时：

```bash
bash tools/customer/record_tracking.sh --output "$HOME/sonic_tracking_runs/trial_01" --seconds 120 --mod-root "$PWD"
```

mod-root指向实际加载的SONIC目录。确认trace增长。把记录目录下载到工作站后：

```bash
python3 tools/tracking_eval/recording/analyze.py /实际记录目录
python3 tools/tracking_eval/evaluation/evaluate.py /实际记录目录
```

模型参考重建不是独立真值；不宣称缺失根位姿下的全局跟踪误差已可测。

## 打包

```bash
python3 tools/customer/check_delivery.py
python3 tools/customer/build_delivery.py /库外的交付输出目录
```

包名包含20261027，源码、校验、入口和相对链接一致。资源检查通过不替代客户设备权限/驱动验收。相机补丁构建和现场结果见[相机说明](../camera_clock/README.md)。
