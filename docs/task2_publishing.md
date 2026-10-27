# Task 2 publishing and reproducible verification

Task 2 converts Task 1 data to ordered events, publishes to MQTT, and exports the
broker-confirmed logical event stream. It does not implement the Task 3 dashboard
or Task 4 event database. The historic A1 submission and upstream Task 1 CSVs are
preserved. The shared contract is now documented in `event_schema.md` and
`mqtt_topics.md`.

## Setup and local demonstration (Windows PowerShell, Python 3.12)

From the repository root, install `requirements-demo.txt` into the virtual
environment. This includes runtime requirements and the optional aMQTT broker.
No Mosquitto service or Docker installation is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-demo.txt
```

Terminal 1, leave the broker running:

```powershell
.\.venv\Scripts\python.exe src/local_broker.py
```

Terminal 2, start the Task 3/4 subscriber and wait for its subscription to be ready.
Subscribe to `comp5339/a2/runs/team-demo-01/#` at QoS 1. The local broker is for
programs on the same computer; another computer's localhost is a different broker.

Terminal 3, publish the included short real-data replay:

```powershell
.\.venv\Scripts\python.exe src/publisher.py --events data/events/mqtt_demo/events.json --run-id team-demo-01
```

This replays 00:59–01:02 on the NEM clock with necessary warmup: 1,091 events
(864 prices including 432 initial prices and 432 changes, 16 starts, 210 meters,
1 end). Fifteen sessions remain active at the cutoff. It takes at least 109
seconds of spacing, plus network/disk overhead. Source-time coverage and warmup
must be labelled in the dashboard. It is a short integration/demo selection;
Task 1 still supplies all 10,368 hourly prices and 4,021 sessions for submission.

To reproduce this prepared selection:

```powershell
.\.venv\Scripts\python.exe src/prepare_events.py --start 2026-09-15T00:59:00 --end 2026-09-15T01:02:00 --output-dir data/events/mqtt_demo
```

For a later demo use a **new** run ID, e.g. `team-demo-02`, and update the subscriber
filter. A prepared `manifest.json` intentionally remains `NOT_PUBLISHED`; it is
not mutated by any particular run. Publication evidence is saved separately.

## Resume and connection settings

Ctrl+C writes an interrupted checkpoint and confirmed export. Resume using the
same command plus `--resume`. `--stop-after 50` deliberately pauses after 50 new
acknowledgements; omit that option when resuming to completion.

```powershell
.\.venv\Scripts\python.exe src/publisher.py --events data/events/mqtt_demo/events.json --run-id team-demo-01 --resume
```

Defaults: 0.1-second minimum interval, 10-second connection/ACK timeout, three
additional retries, 1-second retry backoff. `--interval` values below 0.1 are
rejected. `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC_PREFIX` supply optional defaults;
CLI settings take precedence. For a remote broker use its verified TLS endpoint
with `--tls` and, if needed, `--ca-file`. Authentication uses environment variables
`MQTT_USERNAME` and `MQTT_PASSWORD`.

Resume is appropriate while the same receiving state/broker context is retained.
If the local broker or subscriber lost its state, run the whole prepared stream
under a new run ID. The loopback broker is ephemeral and has no durable disk queue.

## Outputs under data/published/<run-id>

| File | Purpose |
|---|---|
| published_events.json | One JSON array of actual broker-confirmed logical payloads, including run_id |
| publish_manifest.json | COMPLETE/PAUSED/FAILED/INTERRUPTED status, counts, input/output hashes and connection namespace |
| checkpoint.json | Durable confirmed prefix; atomically replaced after each PUBACK |
| attempts.jsonl | Diagnostic attempt times, sequence, ACK/error outcome; not the event submission |
| publisher.lock | OS lock handle; automatically released if the process exits |

On an abrupt kill, exported JSON/manifest can lag the checkpoint; resume regenerates
them. A failure between acceptance and checkpoint may duplicate the last event.
Never interpret PUBACK as proof of Task 4 persistence. QoS 1 is at-least-once,
not exactly-once; Task 3/4 must deduplicate `(run_id, event_id)` before analytics.
The exported JSON contains each confirmed logical event once. An unconfirmed tail
may already have reached the broker; this is marked on failed/interrupted runs.

## Automated checks

Recorded local verification on 2026-10-27 passed: 1,091 unique events,
1,092 captured packets including the single injected duplicate, 432 price changes
after initialization, minimum attempt spacing 0.109s, elapsed 120.172s. Evidence:
`data/published/task2-local-verification-20261027/verification.json`.
All 45 unit tests passed; `pip check` reported no broken requirements.
Remote brokers/TLS and the team's actual Task 3/4 integration were not tested.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/verify_mqtt.py --events data/events/mqtt_demo/events.json --run-id verify-new-01 --output-dir data/published/verify-new-01 --inject-ack-loss-at 51
```

`verify_mqtt.py` owns a temporary loopback broker on a free port and a test receiver.
It waits for SUBACK, pauses after event 50, resumes from disk using a new MQTT
transport, then closes its broker/receiver. With fault injection it sends event 51
successfully but simulates loss of ACK knowledge before checkpointing. It verifies
that the retry has the same identity, subsequent events stay ordered, duplicates
can be removed, every attempt is >=0.1s apart, and captured unique payloads equal
both input plus run_id and the published export. This is not a production Task 3
subscriber and it does not write Task 4 DuckDB.

Additional verification outputs are `received_events.json` (wire capture with
topics) and `verification.json` (measurements). Use a fresh output/run for each
verification. The included dated run is evidence only; do not reuse its checkpoint
with the default port, since its broker used an ephemeral port and has stopped.

Unit tests cover source preparation, pause/resume, interrupt, exhausted retries,
payload tampering, changed input/broker, topic/path validation, concurrent run locks,
unchanged prices and same-time connector handoffs. Network faults are bounded;
the program reports failure instead of declaring an incomplete stream successful.

## Final submission selection and limitations

Keep Task 1 stations input and all generated CSVs. Include the prepared JSON for
the chosen replay plus that run's `published_events.json` (and optionally the
test capture as a third JSON event file). Include relevant manifests as metadata.
Full/day and four-hour prepared streams are optional development artifacts;
do not label them as actually published or include every unused replay in the
final ZIP. The optional diagnostic files are not additional event datasets.

Git includes the `mqtt_demo` prepared stream, the dated published/received
evidence, and manifests for the other local preparation checks. The full-day,
four-hour and exploratory smoke JSON arrays are regenerated locally rather than
uploaded. Use the commands in `task2_events.md` for the full/day and four-hour
files. The smoke manifest describes NEM 00:20–00:22 and can be reproduced with
`--start 2026-09-15T00:20:00 --end 2026-09-15T00:22:00 --output-dir data/events/mqtt_smoke`.
Operational lock/checkpoint files and subsequent local runs are ignored by Git;
start a fresh run after cloning instead of resuming the dated evidence run.

The final subscriber-side DuckDB, dashboard screenshot, integrated demo and
report still require Task 3/4 work. Their state must survive or explicitly reset
across runs; current/historical metrics must state replay coverage and not count
retry packets as extra sessions.

The implementation follows the [Paho client API](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html)
and the [aMQTT broker configuration](https://amqtt.readthedocs.io/en/latest/references/broker_config/).
