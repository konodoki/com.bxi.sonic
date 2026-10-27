# 维护入口与发布

SONIC本体、夹爪、数采、导出和跟踪工具统一在这一个Git工作树维护。开发工作站继续使用com.bxi.sonic-main目录，但它现在具有Git历史和远端，不再从另一个发布副本手工拼文件。归档包和历史work目录仅用于追溯。

origin为konodoki/com.bxi.sonic；没有上游写权限时，publish为维护者fork，提交分支并向origin/main发PR。PR提交不等于合并，GitHub主分支状态必须另行确认。不强推、不把未提交改动直接覆盖机器人。

更新流程：git status检查现有工作 → fetch核对上游 → 分支修改与适用测试 → 更新SHA256和交付清单 → check_delivery → build_delivery并解压检查 → commit/push/PR → 合并后按正常Git流程同步。新机器人安装仍是独立操作，先确认实际工作区和资源占用。

```bash
python3 tools/customer/refresh_manifest.py
python3 tools/customer/check_delivery.py
python3 tools/customer/build_delivery.py /库外的交付目录
```

refresh_manifest只对已经审阅/测试的改动运行，不能用它掩盖未知文件被替换。完整默认pytest发现含历史角度合同测试，不作为当前毫米发行的验收命令；v17适用测试见RELEASE_20261027_V17.md，旧发行验证见RELEASE_20261026.md。
