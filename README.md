# COMP5339 Assignment 2 — EV Charging Data Streaming and Analysis

> **Final integrated workflow:** Use **Integrated deployment** for live MQTT ingestion or **Historical replay** for offline viewing. The root `requirements.txt` includes all required packages. Do not launch legacy subscribers alongside the integrated dashboard.

## Project Status

This repository is an independent A2 copy derived from the validated COMP5339 A1 project. This branch includes **P0 metadata preparation, completed Task 1 generation and Task 2 MQTT publishing**. Task 2 preserves upstream CSVs and the historical A1 submission, maps configuration-level events to physical stations, and supports ordered publishing with durable resume.

The integrated branch includes the original Task 3 map and Task 4 DuckDB modules, plus a single-writer runtime for shared operation. The included test receiver verifies MQTT delivery only; `database/charger_metadata.duckdb` contains P0 metadata, not the final subscriber event database.

## Data Lineage

The official December 2025 TfNSW source snapshot is retained at `data/source/ev_charging_locations_nsw_20251216.csv`. Validated A1 derivatives provide conservative physical-site resolution, charger configuration IDs, parsed power, and previously accepted connector evidence. No A1 source was re-downloaded and no augmentation source was refreshed.

Operator aliases are applied only in A2 outputs. Both `operator_original` and `operator_standard` are retained. Missing station names receive deterministic, clearly marked fallback names. Power uses the explicit A1 kW value where available, the lower component value for compound ratings, or 11 kW only for an AC-only label without a numeric rating.

## Structure

```text
.
├── config/operator_aliases.csv
├── data/
│   ├── source/       # retained A1 source and validated metadata evidence
│   ├── input/        # validated teacher-generator stations.csv
│   ├── processed/    # reproducible P0 station and charger metadata
│   ├── generated/    # Task 1 stations, prices, sessions, metering and AEMO cache
│   ├── events/       # prepared event streams (not proof of publication)
│   └── published/    # per-run acknowledged events, checkpoint and verification
├── database/
│   ├── schema.sql
│   └── charger_metadata.duckdb
├── docs/
│   ├── data_mapping.md
│   ├── event_schema.md
│   ├── mqtt_topics.md
│   ├── generator_audit.md
│   ├── task1_handoff.md
│   ├── task1_results.md
│   ├── task2_events.md
│   ├── task2_publishing.md
│   ├── TASK2_TEAM_HANDOFF_ZH.md
│   ├── schema_diagram.md
│   └── p0_validation.*
├── src/
│   ├── acquire_ev_chargers.py
│   ├── prepare_chargers.py
│   ├── validate_chargers.py
│   ├── prepare_events.py
│   ├── publisher.py
│   └── local_broker.py
├── scripts/verify_mqtt.py
├── tests/
├── requirements.txt
├── requirements-demo.txt
└── README.md
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Python 3.12 is the tested version. On Windows PowerShell, activate with
`.venv\Scripts\Activate.ps1`, or invoke `.venv\Scripts\python.exe` directly.
The local broker and dashboard are included in this root requirements file.

## Integrated deployment — single DuckDB source (recommended)

This branch combines Task 3 visualisation with the Task 4 MQTT/DuckDB state
engine. **Only one MQTT subscriber and one persisted event database are used.**
The subscriber runs as an internal worker of the Streamlit process. It owns
the DuckDB write connection; Streamlit requests consistent snapshots through
a thread-safe queue. No SQLite, duplicate MQTT subscription, HTTP API, or
concurrent cross-process DuckDB reads are needed.

Key files: `src/integrated_runtime.py` (thread and queue owner),
`src/analytics_subscriber.py` (Task 4's ordered receiver),
`src/analytics_storage.py` (atomic event/state persistence),
`src/analytics_queries.py` (stored current/historical metrics),
and `dashboard/app.py` (map, popups and meter charts).

### Setup and run

Use Python 3.12 and **all** requirements:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Do this from the project root using **three** terminals:

```bash
# Terminal A — local MQTT broker
python src/local_broker.py

# Terminal B — start the integrated subscriber + dashboard
python -m streamlit run dashboard/app.py

# Terminal C — after Terminal B shows "SUBACK: integrated DuckDB ready"
python src/publisher.py --events data/events/mqtt_demo/events.json --run-id integration-demo-01
```

Select **Live demonstration** and enter the **Run ID** `integration-demo-01` **before**
running the Publisher. Confirm `SUBACK` in the Streamlit terminal, then
send the events. The MQTT topic filter is
`comp5339/a2/runs/integration-demo-01/#`, QoS 1. Enable the Dashboard's
5-second auto-refresh to see charging curves and updated station state.

**Run a new ID for each fresh replay**; the broker has no retained messages.
On the first start, the runtime creates `database/charger_analytics.duckdb`
from the validated P0 metadata database and applies
`database/analytics_schema.sql` in-place. It will reuse an existing Task 4
analytics database if that file is already present. The original Task 4
branch's prepopulated DB is a separate binary artifact; include the final
verified DuckDB in the assignment ZIP.

### Live MQTT verification: three separate terminals

1. **Broker**: `python src/local_broker.py` (terminal 1).
2. **Dashboard + single DuckDB subscriber**: `python -m streamlit run dashboard/app.py` (terminal 2). Set a new Run ID, e.g. `integration-demo-final-01`; wait for **SUBACK** in terminal 2.
3. **Task 2 Publisher**: `python src/publisher.py --events data/events/mqtt_demo/events.json --run-id integration-demo-final-01` (terminal 3, only after SUBACK).

Watch `PUBACK N/1091` in terminal 3 while Dashboard shows **MQTT packets** and **DuckDB committed** increasing. The latter is the verified persisted prefix, not the Broker PUBACK count. Auto-refresh is enabled by default (5 seconds); disable it temporarily when navigating popups. Do not run the old `src/subscriber.py` or standalone Task 4 `src/analytics_subscriber.py` at the same time. Do not use an old run ID for a new replay; Publisher checkpoints are bound to a run ID. The MQTT Broker must already be running before Dashboard subscribes.

### Final data and packaging checks

The full offline event stream is generated by `python src/prepare_events.py`
and verified by `python scripts/verify_full_stream.py`. Its verified
manifest expects 134,162 prepared events; the provided 1,091-event replay
is a separate MQTT end-to-end test, not the full replay.

**Important:** `data/events/full/events.json` is ignored by Git because it is
large. It must be explicitly included when creating the Canvas submission
ZIP, together with `data/generated/`, `database/charger_analytics.duckdb`,
`database/analytics_schema.sql`, all source scripts, `requirements.txt`,
and this README. Run `python scripts/check_submission.py <zip-file>` to check
the archive before uploading. Do not assume `git archive` automatically
contains ignored local artifacts. The database may contain short replay
results only; describe actual persisted scope accurately.

### Evidence and verification

Expected for the provided short replay, after full publication: 1,091 stored
events, 15 active sessions, 1 completed session, and 44.13 kWh completed
energy (from the Task 4 verification). The 1,091 messages consist of 864
prices, 16 starts, 210 meter events and 1 end. The Dashboard's live metrics
come from DuckDB's `AnalyticsQueries.get_run_metrics`; the map and curves
come from the same database's committed event payloads. Stop Streamlit
**before** running a separate `python src/analytics_queries.py` process;
its direct file open otherwise conflicts with the running DuckDB writer.
No second `src/subscriber.py` or `src/analytics_subscriber.py` process
should be started alongside the integrated dashboard.

Run tests from the repo root:

```bash
python -m unittest discover -s tests -v
```

Do not present the short demo as all generated data. Task 1 has 10,368
hourly prices and 4,021 charging sessions; Task 2 publishes only price
changes and may replay a selected time window.

### Shutdown / recovery and constraints

Stop Streamlit with Ctrl+C to release its DuckDB connection. If the
broker/subscriber disconnects or a sequence gap persists, the worker reports
an error; do not claim completion unless the Dashboard event count matches
the publisher's confirmed manifest. Restart the dashboard (same run for
recovery only with a verified publisher resume; otherwise use a new run).
Do not open the same DuckDB file for writing from another process. MQTT
connection settings use localhost:1883 for the coursework demo; the integrated
runtime is not a publicly deployed authenticated service. It performs
disk-backed atomic commits before MQTT acknowledgements and uses the Task 4
de-duplication and sequence validation logic.

## Historical replay (offline, no broker)

Stop any active live ingestion in this Streamlit app before switching to
**Historical replay**. The dashboard releases its integrated runtime and
opens the DuckDB file in read-only mode. Choose a stored Run ID (e.g.
`integration-final-02`). You do **not** need to start MQTT Broker or Publisher
for this mode. The UI still reads historical event payloads to construct the
station map and meter curves; a 134,162-event run can be slower than the
1,091-event example.

## Full-scale MQTT validation (optional but recommended for stress testing)

The full stream has 134,162 events and the Task 2 publisher enforces at least
0.1 seconds between consecutive publications. This implies at least 3h 43m
37s of publishing time, excluding processing overhead. **Do not reuse the
short-run IDs** already in DuckDB. On a test run, ensure the Broker is started,
launch the integrated Dashboard in Live mode with a new Run ID, and only then
start the Publisher with matching ID:

```bash
python src/publisher.py --events data/events/full/events.json --run-id integration-full-01
```

Wait for the Publisher to finish; verify the Dashboard's committed count
is 134,162. Stop Streamlit before accessing the DuckDB file externally:

```bash
python scripts/verify_full_stream.py --run-id integration-full-01
```

The verifier compares event counts, event types, every stored JSON payload,
completed sessions, and remaining active connectors. A prepared-stream PASS
alone is not evidence of a full MQTT/DuckDB replay. The integrated runtime
avoids repeatedly querying all prior rows from DuckDB, but the current
Streamlit map/state projection still processes all previously committed
records when refreshing; auto-refresh may be turned off for responsiveness.

### Legacy modules

`src/subscriber.py` and the standalone `src/analytics_subscriber.py` CLI are
preserved as earlier individual Task 3/4 implementations. Do not launch
them alongside the integrated Dashboard. The single-process integrated
runtime remains the only recommended run path.

## Task 2 quick start

Run commands from this repository root. In terminal 1:

```powershell
.\.venv\Scripts\python.exe src/local_broker.py
```

Start the team's Subscriber in another terminal and wait for its SUBACK on
`comp5339/a2/runs/team-demo-01/#` at QoS 1. Then publish:

```powershell
.\.venv\Scripts\python.exe src/publisher.py --events data/events/mqtt_demo/events.json --run-id team-demo-01
```

Use a new run ID for each new replay; use the same command plus `--resume` only
to continue an existing run. Both Publisher and Subscriber must use the same
broker, prefix and run ID. The local broker binds `127.0.0.1:1883` and is intended
for one computer. It has no persistent queue. A lost broker/subscriber state
requires a fresh replay, rather than continuing from Publisher's checkpoint.

The included short replay has 1,091 events and takes about two minutes: it includes
432 initial prices, 432 changes, 16 starts, 210 meters and one end. See
[Task 2 instructions](docs/task2_publishing.md) for preparation, other windows,
remote broker settings, failure recovery, output meanings, and submission selection.
The Chinese [team handoff](docs/TASK2_TEAM_HANDOFF_ZH.md) describes Task 3/4 integration.

To verify Task 2 without waiting for the team's dashboard, run this standalone
test (it starts and stops its own broker and test receiver):

```powershell
.\.venv\Scripts\python.exe scripts/verify_mqtt.py --events data/events/mqtt_demo/events.json --run-id verify-new-01 --output-dir data/published/verify-new-01 --inject-ack-loss-at 51
```

Use a fresh verification run/directory each time. Received packet capture and
`verification.json` supplement the `published_events.json` and publication manifest.
The dated included verification is evidence, not a reusable live broker session.
Git includes the short demo JSON and dated MQTT evidence. Full/day, four-hour
and exploratory smoke event arrays are local, reproducible outputs; their
manifests are included. See `docs/task2_events.md` to generate longer replays.

## Reproduce P0

```bash
python src/prepare_chargers.py
python src/validate_chargers.py
python src/prepare_generator_input.py
python src/validate_generator_input.py
python -m unittest discover -s tests
```

`src/acquire_ev_chargers.py` is retained as A1 acquisition provenance. It is not part of normal A2 P0 execution because the validated source snapshot is included and must not be refreshed unintentionally.

## Generator Input

The teacher generator and demo CSV are preserved under `vendor/data_generator/`. The validated input is `data/input/stations.csv`, with 432 usable DC configuration rows and the exact required columns `station_id,name,lat,lon,site_type,connectors,max_kw`.

Task 1 generated 10,368 hourly prices, 4,021 sessions and 121,800 meter rows for
432 DC configurations across 414 physical sites. The source day is 2026-09-15,
using September 2026 AEMO NSW data, seed 5339 and `--sessions-per-connector-day 3 2`.
Generation commands, validated counts and source assumptions are recorded in
`docs/task1_results.md` and `docs/task1_run.json`.

`docs/task1_handoff.md` is the earlier P0-to-Task-1 handoff. Current generation
outputs are under `data/generated/`; do not overwrite them during Publisher tests.

## Interface Status

The generator CSV fields are documented in `docs/generator_audit.md`. Task 2 has
finalized contract 1.0 in `docs/event_schema.md` and `docs/mqtt_topics.md`, replacing
the original P0 proposals. Prices are configuration-scoped; time is UTC converted
from fixed NEM UTC+10; only initial and changed prices are sent. QoS 1 retries are
deduplicated by `(run_id,event_id)` on the receiving side. Window warmup preserves
original times and leaves sessions open at the cutoff. Historical metrics must
describe selected replay coverage. These are project assumptions, not prescribed
teacher field names. Task 3/4 still need to integrate this finalized contract.

## Git Workflow

Clone the repository, update local `main`, and create a feature branch for the assigned task. Recommended branches are `feature/task1-generation`, `feature/task2-publishing`, `feature/task3-dashboard`, and `feature/task4-storage`.

Keep changes within the responsible module where possible. Before changing shared event schemas, charger identifiers, MQTT topics, or database contracts, coordinate with the team. Run the relevant local tests before committing, push the feature branch, and merge through a Pull Request into `main`. Do not force push, rewrite shared history, or allow AI coding tools to modify another member's work or shared interfaces without review.
