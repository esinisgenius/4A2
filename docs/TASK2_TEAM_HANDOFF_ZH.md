# Task 2 → Task 3/4 接入说明

Task 2 负责人已于 2026-10-27 确定以下接口并完成 Publisher 实现。请以
`event_schema.md`、`mqtt_topics.md` 为当前契约；P0 的原始草案已被替换。
本文用于交接，不代表组员已完成接入。

## 接入时必须保持一致

1. 默认 broker 为 `127.0.0.1:1883`，同一台电脑运行本地演示。不同电脑联调时，
   大家改用同一个可访问的 broker 地址；不能各自连自己的 localhost。
2. 先启动 Subscriber，收到订阅成功的 SUBACK 后，再启动 Publisher。
3. 演示 run_id 例如 `team-demo-01`，订阅 `comp5339/a2/runs/team-demo-01/#`，QoS 1。
   新演示用新 run_id；中断后继续原次演示才用 `--resume`。
4. 四类 payload 均含 `station_id`（物理站点）、`charger_id`（A1 配置）、
   `event_time`（UTC）、`event_id`、`dataset_id`、`sequence`、`run_id`。
   `connector_id` 是字符串，编号仅在该 charger 配置内有效。
5. 价格必须按 charger_id 保存，不能把同站点不同配置的价格互相覆盖。
6. 用 `(run_id,event_id)` 去重；会话主键用 `(run_id,session_id)`。
   当前状态及历史指标只统计所选 run，不能把多次演示相加。
7. 同时刻顺序：price_update → meter → session_end → session_start。
   这保证最后一次计量先保存，旧会话先释放连接器，再打开新会话。
8. 消息 retain=false。中途加入不会自动收到过去状态；需要已有持久化状态，
   或从头开启一个新的 run。Broker PUBACK 不等于 DuckDB 已入库。

## Task 3

- 按 station_id 连接 P0 站点经纬度；同一 marker 下列出各配置的价格与占用。
- 按所选 run 的 sequence 顺序应用首次收到的事件，忽略已处理 event_id 的重复包。
- 当前折线图使用所选会话的 meter 事件时间、累计 energy_kwh 或 power_kw。
- session_end 到达才关闭占用；charge_end_time 只是充电结束，不是拔枪时间。
- 弹窗包含名称、地址、插头、运营商、价格，及 Task 4 提供的当前/历史指标。
- 短窗口带有初始化历史，图表注明数据覆盖时间；窗口结束仍活跃的会话保留活跃状态。

## Task 4

- 将收到的事件连到现有 A2 metadata DuckDB 中 stations/chargers 的实际 ID。
- 事件插入和状态/累计指标更新应保持一致，并以 `(run_id,event_id)` 阻止重复计数。
- 按 `(run_id,charger_id,connector_id)` 管理连接器占用；不同 run 的 session_id 可相同。
- 建议反馈一个当前指标（活跃会话数）和一个历史指标（已结束会话数/累计能量）。
- 对比独立接收并持久化的唯一事件数与 `publish_manifest.json`，不要只看网络包数。
- 保留用于最终提交的 subscriber 侧 DuckDB 与 DDL；Publisher 的 checkpoint 不能替代它。

## 本地启动

在仓库根目录安装 `requirements-demo.txt`。完整命令见 `task2_publishing.md`。

```powershell
.\.venv\Scripts\python.exe src/local_broker.py
# 另一个终端先运行你们的 Subscriber，再在第三个终端运行：
.\.venv\Scripts\python.exe src/publisher.py --events data/events/mqtt_demo/events.json --run-id team-demo-01
```

短演示包含 1,091 条实际源数据事件：864 价格、16 开始、210 计量、1 结束；
其中 432 条是初始化后的真实电价变化。包括窗口前的必要初始化，运行约两分钟。
演示窗口为 NEM 00:59–01:02，结束时仍有 15 个活跃会话。

## 可以直接发到群里的摘要

> Task 2 的 Publisher 和消息接口已做好，接口说明在 docs/event_schema.md 和
> docs/mqtt_topics.md。默认用本机 1883，订阅 comp5339/a2/runs/{run_id}/#，
> QoS 1、不 retain。每条消息都有物理 station_id 和配置 charger_id；价格按
> charger_id 保存；用 (run_id,event_id) 去重。请先启动订阅再运行发布。
> 我准备了约两分钟的真实数据回放，包含四类事件和电价变化，具体启动命令及
> Task 3/4 接入注意事项在 docs/TASK2_TEAM_HANDOFF_ZH.md。

上述文字尚未代发。Task 2 通过 `feature/task2-publishing` 分支交付：
https://github.com/esinisgenius/4A2/tree/feature/task2-publishing
该分支基于已完成的 Task 1 分支，包含运行所需的 Task 1 数据。
请先在此分支接入验证，再按团队 PR 流程合并。
