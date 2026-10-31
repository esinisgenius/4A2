# Task 4 查询交接

本文件说明 Task 4 的交付内容和查询用法。未修改 Task 3 的 Subscriber 或 Dashboard，也不代表 T3 已完成接入。

## 交付文件

- `database/charger_analytics.duckdb`：原有五张 metadata 表，加上 T4 的事件和状态数据。
- `database/analytics_schema.sql`：新增四张表、两个视图的 DDL；在 metadata 数据库副本上执行。
- `src/analytics_storage.py`：校验、去重、原子保存事件和更新状态。
- `src/analytics_subscriber.py`：订阅指定 run 的 MQTT 流，处理序号缺口。
- `src/analytics_queries.py`：只查询数据的 Python 接口和命令行入口。
- `docs/README_TASK4.md`：本说明，包含运行方法、查询接口和交接注意事项。

以上六个文件为本次 T4 核心交付。本地辅助测试脚本和验证日志不包含在本次上传清单中，运行以下示例不依赖这些文件。

依赖沿用项目 `requirements-demo.txt`，使用 Python 3.12。下方命令均在仓库根目录执行，`python` 应指向已安装项目依赖的 Python 3.12 环境。

## 已验证的回放

run_id：`task4-mqtt-20261101-01`。数据来自 T2 演示事件，通过本机 Broker 和 T4 Subscriber 实际接收后持久化，不是把 Publisher checkpoint 当成接收数据库。

核对结果：1,091 个唯一事件，包括 864 个价格更新、16 个会话开始、210 个电表读数、1 个会话结束；15 个会话仍活跃，1 个已结束。测试故意制造一次重发，未重复计数。全部已保存 payload 与 Publisher 导出清单逐条一致。该回放是演示数据，不是现实充电站的实时监测结果。

## 直接查看查询结果

先停止写入这个数据库的 Subscriber，再执行：

```bash
python src/analytics_queries.py
python src/analytics_queries.py --run-id task4-mqtt-20261101-01
python src/analytics_queries.py --run-id task4-mqtt-20261101-01 --station-id 实际的station_id
```

第一个命令列出已有 run；第二个查整次回放；第三个查某站点。可加 `--database 路径` 指定其他已初始化数据库。

## Python 调用

以下适用于 Subscriber 已停止或独立的已完成数据库快照。接口返回普通 dict/list，可 JSON 序列化；时间为 UTC 字符串，尚未有值的字段为 None。

```python
from src.analytics_queries import AnalyticsQueries

run_id = "task4-mqtt-20261101-01"
with AnalyticsQueries("database/charger_analytics.duckdb") as queries:
    runs = queries.list_runs()
    metrics = queries.get_run_metrics(run_id)
    sessions = queries.get_sessions(run_id, status="active")
    station_id = sessions[0]["station_id"]
    station_metrics = queries.get_station_metrics(run_id, station_id)
    charger_states = queries.get_charger_states(run_id, station_id)
    session_id = sessions[0]["session_id"]
    meter_rows = queries.get_meter_history(run_id, session_id)
```

实际使用时应先检查 sessions 是否为空，再访问第一个元素。

| 方法 | 参数 | 返回内容 |
|---|---|---|
| `list_runs()` | 无 | run_id、dataset_id、事件数、最大序号、事件时间范围 |
| `get_run_metrics(run_id, station_id=None)` | 回放编号，可选站点 | 活跃/结束会话数、结束会话电量和费用、事件覆盖范围 |
| `get_station_metrics(run_id, station_id)` | 回放编号、物理站点编号 | 上述指标，限定到这个站点 |
| `get_charger_states(run_id, station_id=None)` | 回放编号，可选站点 | 配置编号、站名、最新价格、已观察到的占用数量 |
| `get_sessions(run_id, station_id=None, status=None, limit=1000, offset=0)` | 可选站点、状态和分页 | 会话明细，包括锁定电价、起止时间、最新/最终电量和最终费用 |
| `get_meter_history(run_id, session_id, limit=10000, offset=0)` | 回放编号、会话编号和分页 | 按 sequence 排序的电压、电流、瞬时功率、累计电量、SOC |

limit 最大 100000，offset 从 0 开始；需要更多记录时增加 offset。未知 run/站点/会话抛出 ValueError，避免把编号写错解释成零业务。已知 run 中无会话时指标为 0；合法但该回放未观察到事件的站点也是 0，覆盖时间为 None。已知会话没有 meter 时返回空列表。

`get_run_metrics` 的返回字段：

```text
run_id, station_id,
active_sessions, completed_sessions,
completed_energy_kwh, completed_cost_aud,
event_count, first_event_time, last_event_time
```

## 读写方式

DuckDB 正被 Subscriber 进程写入时，不能让另一个 Dashboard 进程直接打开同一个文件。上述独立文件查询用于停止写入之后或独立快照。

若调用方位于同一写入进程，可传入已有连接，串行执行查询：

```python
with AnalyticsQueries(connection=storage.con) as queries:
    metrics = queries.get_run_metrics(run_id)
```

storage 是现有 AnalyticsStorage 实例。查询对象不会关闭借入的连接。不要跨线程同时使用此连接，也不要在未完成的写入事务中调用。若 Dashboard 采用独立进程，实时读取需由调用方选择同进程查询转发或快照方案；Task 4 此次未实现 HTTP 服务。

## 指标解释

- 所有动态查询限定一个 run，不混合多次演示。
- completed_energy_kwh 只加总已结束会话的最终电量，不累加 meter 的累计读数。
- 会话电价是开始时锁定的电价，最终费用保留 session_end 的源值。
- session_end 是拔枪时刻；charge_end_time 是充电完成时刻，不能据此提前释放接口。
- 缺少价格表示尚未观察到，不显示为免费；占用为 0 不证明现实插座可用。
- first/last_event_time 表示已收到事件的实际范围，包含窗口初始化历史，不代表完整自然日。

## 新的 MQTT 回放

先启动 Broker，再启动 T4 Subscriber，看到 SUBACK 后才启动 Publisher。每次新演示使用新的 run_id。

```bash
python src/local_broker.py
python src/analytics_subscriber.py --run-id 新的run_id
python src/publisher.py --events data/events/mqtt_demo/events.json --run-id 新的run_id
```

以上分别在不同终端运行。Subscriber 使用 QoS 1；保存后才确认接收。缺号超过 30 秒或连接断开会停止并报错，不把不完整的后续状态当作正常结果。结束接收用 Ctrl+C，再查询 DuckDB。未保留的消息不会自动补发，中断后应核对数据库已保存前缀，并进行完整同源重放或用新 run 从头演示。

## 查看随附数据库的结果

Subscriber 停止后执行：

```bash
python src/analytics_queries.py --run-id task4-mqtt-20261101-01
```

随附数据库中该 run 的预期结果为：event_count=1091、active_sessions=15、completed_sessions=1、completed_energy_kwh=44.13、completed_cost_aud=28.24。该命令只读取数据库，不会重新发送事件。
