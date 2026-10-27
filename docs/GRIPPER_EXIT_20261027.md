# BXI退出SONIC时失能（demo05）

版本 `20261027-demo-05-exit-disable`。旧demo04按此前要求在退出时仅停止发送位置指令，没有发送失能帧；这不能让仍通电的夹爪释放保持力。此次补丁改为退出时主动失能。

## 行为

- 进入SONIC仍为：使能→获取反馈→打开70mm→PICO扳机控制0～70mm。
- SONIC切到normal、pd_brake、zero_torque或其他状态时，在`on_exit`发送`FF FF FF FF FF FF FF FD`，节点1、CAN FD+BRS，对本次尝试使能过的各侧发送3次，然后释放本会话资源。不等待反馈、不发送闭合/打开动作。
- 尚在打开/等待首帧反馈/故障状态也会执行。未使能的侧不发。单侧发送异常会报告`disable_send_failed`，仍处理另一侧，且不阻断身体状态切换。
- 正常解绑也执行相同释放路径；退出后重复解绑不重复发帧。再次进入新建会话、重新使能打开。
- A+X退出POSE但仍处于SONIC时，不调用SONIC退出钩子，保留现有暂停/续采逻辑。
- 不改变DM、毫米合同、速度、KP/KD、身体策略或数采服务。BXI路径不主动请求身体零力矩。

官方失能定义：[BXI CAN通信说明](https://wiki.bxirobotics.com/actuators/can_communication/)。代码在库根`bxi_demo.py`；同事原C控制/编解码库不需要重新编译。

## 安装

宿主不运行时，在独立库根目录对实际example工作区安装；默认仅核查，`--apply`才写入：

```bash
python3 tools/gripper_native/install_exit.py --workspace /实际/example工作区
sudo python3 tools/gripper_native/install_exit.py --workspace /实际/example工作区 --apply
```

只替换该工作区src和install中的`bxi_demo.py`，仅接受已核对的毫米demo04或此次demo05指纹；未知改动拒绝覆盖。原文件备份在工作区上级`gripper_exit_backup_*`，清单含原路径和哈希。失败回滚；不停止进程、不启停服务、不导入控制模块、不发送CAN。安装后手动重启原hw流程，旧Python进程不会自动重新加载文件。数采监听器不需要为此次补丁重启。

## 验证

离线13项生命周期/安装事务检查、13项真实毫米C库和SONIC父类回归通过。审阅已归档的现场example状态机：完成状态切换的统一入口先调用来源状态`on_exit`，再进入目标状态。暂未做新补丁真机验证。

```bash
python3 -m unittest discover -s tools/gripper_native -p 'test_*.py'
```

现场每项单独验证：

1. 空夹爪进入SONIC，确认版本demo05、打开70mm、左右扳机响应。
2. 依次验证SONIC→normal、重新进入SONIC→pd_brake、重新进入SONIC→zero_torque，确认退出后夹爪不再保持出力。零力矩测试沿用现场原有支撑条件。
3. 每次退出日志应有`exit/action=disable_enabled_sides`和对应CAN的`disable_tx`，数据末字节FD。日志表示ROS发布成功，不代表物理失能回执；以现场夹爪状态验收。失能会释放夹持力，不带物测试。
4. 重新进入SONIC应重新使能、打开70mm并恢复扳机控制；A+X暂停/恢复应不产生`disable_tx`。

本机制依赖Python退出钩子和仍可用的ROS/CAN链路。SIGKILL、断电或链路故障不能保证发送成功；没有修改固件通信超时或增加后台自动重试。
