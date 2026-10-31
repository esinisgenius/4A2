# COMP5339 Assignment 2 — EV Charging Data Streaming and Analysis

## Project Status

This repository is an independent A2 copy derived from the validated COMP5339 A1 project. This branch includes **P0 metadata preparation, completed Task 1 generation and Task 2 MQTT publishing**. Task 2 preserves upstream CSVs and the historical A1 submission, maps configuration-level events to physical stations, and supports ordered publishing with durable resume.

The Task 3 production subscriber/dashboard and Task 4 event storage remain separate team modules. The included test receiver verifies MQTT delivery only; `database/charger_metadata.duckdb` contains P0 metadata, not the final subscriber event database.

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
For the optional local broker and network verification, install
`python -m pip install -r requirements-demo.txt` instead.

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
