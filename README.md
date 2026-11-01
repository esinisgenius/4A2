# COMP5339 Assignment 2 — NSW EV Charging Data Streaming and Analysis

This repository contains an integrated solution for **synthetic EV charging data generation, ordered MQTT publishing, event subscription, DuckDB storage, and an interactive NSW charging-station dashboard**. The workflow reuses validated station and charger metadata from Assignment 1.

> **Use the integrated workflow below.** The Streamlit app contains the **only active MQTT subscriber and DuckDB writer**. Do not launch `src/subscriber.py` or the standalone `src/analytics_subscriber.py` alongside it.

## 1. Project overview

| Assignment component | Implementation | Output |
| --- | --- | --- |
| Task 1 — Synthetic dataset | Teacher-provided generator with prepared NSW chargers and AEMO prices | Hourly prices, sessions, minute meter readings |
| Task 2 — Event publishing | `src/prepare_events.py`, `src/publisher.py` | Validated ordered JSON events, MQTT QoS 1 messages |
| Task 3 — Live visualisation | `dashboard/app.py`, `src/integrated_runtime.py` | NSW map, marker details, live charging curves |
| Task 4 — Stateful analytics | `src/analytics_storage.py`, `src/analytics_queries.py`, `database/analytics_schema.sql` | Persistent events, live occupancy, historical session metrics |

### Architecture

```text
Assignment 1 metadata ───────────┐
                                 │
Task 1 generated CSVs            │
          │                      │
          ▼                      ▼
Task 2 event preparation     DuckDB station/charger metadata
          │                      │
          ▼                      │
Ordered MQTT Publisher           │
          │                      │
          ▼                      │
Local MQTT Broker                │
          │                      │
          ▼                      │
Streamlit-integrated subscriber  │
          └──────────┬───────────┘
                     ▼
            charger_analytics.duckdb
                     │
                     ▼
        Streamlit NSW map and analytics
```

**Data ownership:** the integrated subscriber writes every accepted event and its derived state atomically to DuckDB. Dashboard metrics come from DuckDB; historical viewing also reads the persisted event payloads. Legacy SQLite files are not part of the integrated runtime.

## 2. Repository structure

```text
config/                         Operator aliases and settings
data/
  source/                       Retained A1 source data
  input/                        Prepared generator input
  processed/                    A1/P0 prepared metadata
  generated/                    Task 1 generated CSV outputs
  events/mqtt_demo/events.json  Small 1,091-event integration replay
  events/full/events.json       Full 134,162-event stream (local; Git-ignored)
  events/full/manifest.json     Full-stream preparation manifest
  published/                    Per-run publisher checkpoints and evidence
database/
  charger_metadata.duckdb       Validated stations and charger configurations
  charger_analytics.duckdb      MQTT-ingested events and derived analytics (local artifact)
  analytics_schema.sql          Task 4 tables and views
dashboard/app.py                 Streamlit/Folium/Plotly user interface
src/
  run_task1.py                  Reproduce Task 1
  validate_task1.py             Validate generated Task 1 data
  prepare_events.py             Generate validated event stream
  publisher.py                  Ordered MQTT publisher
  local_broker.py               Local MQTT broker
  integrated_runtime.py         Single subscriber/DuckDB writer and snapshots
  analytics_storage.py          Event transactions and derived-state updates
  analytics_subscriber.py       Ordered receiver logic; standalone CLI is legacy
  analytics_queries.py          Current and historical DuckDB queries
  task3_state.py                Deterministic projection utility (legacy SQLite helpers unused)
scripts/
  verify_full_stream.py         Full event integrity and DuckDB reconciliation
  check_submission.py           Submission ZIP content checker
tests/                           Automated unit and integration tests
docs/                            Task-specific data, schema and publisher documentation
requirements.txt                 Integrated runtime and testing dependencies
README.md
```

`data/events/full/events.json` and `database/charger_analytics.duckdb` are **not guaranteed to be present in a Git clone**. They are local deliverable artifacts and **must be included in the final submission ZIP**. If the full JSON is absent, regenerate it from the supplied Task 1 outputs using the instructions below.

## 3. Environment setup

Tested with **Python 3.12**. Run commands from the repository root.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate using `.venv\Scripts\Activate.ps1`. The root requirements file includes the local aMQTT broker, Paho MQTT, DuckDB, Streamlit, Folium and Plotly.

No external MQTT service, Docker installation or cloud database is required. The broker uses **127.0.0.1:1883**. Map tiles from OpenStreetMap require internet access; local MQTT ingestion and database processing do not.

## 4. Run the complete system — live MQTT

Open **three terminals**, activate the same environment, and run each command from the repository root.

**Terminal A — start the broker**

```bash
python src/local_broker.py
```

**Terminal B — start the integrated dashboard and subscriber**

```bash
python -m streamlit run dashboard/app.py
```

Open **http://localhost:8501**. Select **Live demonstration** and enter a **new Run ID**, for example `integration-demo-new-01`. Wait for `SUBACK: integrated DuckDB ready for integration-demo-new-01` in Terminal B before publishing.

**Terminal C — publish the provided short stream**

```bash
python src/publisher.py --events data/events/mqtt_demo/events.json --run-id integration-demo-new-01
```

The Run ID must match the dashboard exactly. Keep the broker and dashboard running during publication. Observe the committed event count and charging-session progress as messages arrive.

**Expected short-replay result:** 1,091 committed events (864 price updates, 16 session starts, 210 meter events, one session end), 15 active sessions at the replay cutoff, one completed session and approximately 44.13 kWh completed energy.

**Run isolation:** use a fresh Run ID for a fresh publication. A previously completed Run ID must not be reused for a new dataset. Publisher checkpoints, receipts and recovery options are documented in [Task 2 publishing](docs/task2_publishing.md).

## 5. Historical replay — without MQTT

Previously ingested events remain in `database/charger_analytics.duckdb` after a restart.

1. Stop any active publisher and the previous Streamlit process.
2. Start **only** the dashboard: `python -m streamlit run dashboard/app.py`.
3. Select **Historical replay**.
4. Enter a stored Run ID, such as `integration-full-02` **if the supplied DuckDB contains that run**.
5. Turn off **Auto-refresh (5s)** when exploring large historical runs.

**No broker or Publisher is required** for Historical replay. The map supports marker selection → Station details → station-filtered session selection → meter chart. Search/status filters help navigate large session lists.

Historical mode requires the supplied analytics database to contain the selected Run ID. A fresh metadata-only database has no historical events.

## 6. Data generation and event preparation

The verified Task 1 output contains:

| Source dataset | Records |
| --- | ---: |
| Physical stations / DC charger configurations | 414 / 432 |
| Hourly price records | 10,368 |
| Charging sessions | 4,021 |
| Meter readings | 121,800 |

The full prepared MQTT stream contains:

| MQTT event type | Events |
| --- | ---: |
| `price_update` (initial prices and actual changes only) | 4,320 |
| `session_start` | 4,021 |
| `meter` | 121,800 |
| `session_end` | 4,021 |
| **Total** | **134,162** |

Reproduce the Task 1 outputs (only if necessary):

```bash
python src/run_task1.py
python src/validate_task1.py
```

Task 1 may need its retained AEMO cache or network access if the required source cache is absent. See [Task 1 results](docs/task1_results.md).

Prepare the complete event JSON from existing generated CSVs and check its integrity:

```bash
python src/prepare_events.py
python scripts/verify_full_stream.py
```

The latter checks the entire prepared stream, including file SHA-256, event counts and ordering. **This offline PASS is not proof that MQTT delivered the stream.** The manifest deliberately retains `publication_status: NOT_PUBLISHED`; actual publication evidence belongs to the individual Publisher Run.

See [event contract](docs/event_schema.md), [topics](docs/mqtt_topics.md), and [Task 2 preparation](docs/task2_events.md) for field semantics, timestamp handling and windowed replays.

## 7. Full-stream MQTT/DuckDB verification

The complete 134,162-event sequence was observed in the local DuckDB under **`integration-full-02`**, with sequences **1 through 134,162**. The full-stream preparation manifest passed its integrity validation. **Run the payload-level reconciliation below to independently confirm byte-content equivalence and final session state**; do not claim that stronger result until the checker prints PASS.

To run a **new** full publication (only if necessary), start Broker and Dashboard as in Section 4, select a fresh Run ID (e.g. `integration-full-new-01`), wait for SUBACK, and execute:

```bash
python src/publisher.py --events data/events/full/events.json --run-id integration-full-new-01
```

The assignment requires at least **0.1 seconds between MQTT messages**. The full run therefore takes at least approximately **3 hours 44 minutes**, excluding processing overhead. Do not reuse `integration-full-02` for a new publication.

To verify the **already ingested** full run, first **stop Streamlit** so DuckDB releases its file lock, then run:

```bash
python scripts/verify_full_stream.py --run-id integration-full-02
```

The final line should read:

```text
PASS MQTT/DuckDB run integration-full-02: all 134162 stored payloads match exactly
```

This command compares record counts, sequence continuity, event-type totals, every stored JSON payload, completed sessions and remaining active connectors. If it reports zero events for the given Run ID, inspect stored Run IDs before replaying; the data might simply be under another Run ID.

## 8. DuckDB schema and analysis

`database/analytics_schema.sql` extends the validated Assignment 1 station and charger metadata with:

- `mqtt_events`: raw received JSON, run ID, sequence, type and event time.
- `charger_current_state`: latest price per charger and run.
- `charging_sessions`: active/completed session lifecycle and results.
- `active_connectors`: current connector occupancy.
- `meter_history`: view of time-series meter readings.
- `run_session_metrics`: view of active sessions, completed sessions and completed energy.

The dashboard uses these records for current-state KPIs and historical session metrics; station mapping is linked to validated metadata rather than inferred from marker location. Raw payloads and derived state are written within the same transaction.

## 9. Testing and troubleshooting

Run automated tests:

```bash
python -m unittest discover -s tests -v
```

| Symptom | Resolution |
| --- | --- |
| `No events received` | Confirm the dashboard and publisher use the same **new** Run ID, and wait for SUBACK before starting publication. |
| DuckDB `Conflicting lock` | Stop Streamlit and other Python processes opening `charger_analytics.duckdb` before running the external verifier. Never delete the database to resolve a lock. |
| Historical Run ID returns no records | Query the stored runs; the completed full run is `integration-full-02` in the tested local database. |
| Historical mode is slow | Disable five-second Auto-refresh. The UI still reconstructs the selected run's historical projection. |
| Markers appear without basemap | OpenStreetMap tile downloads need internet; MQTT/DuckDB can work locally without it. |
| Session selector is hard to navigate | Select a marker/station, filter Active/Completed or search by session number. |
| No meter curve | Select a session that has received meter events; a completed session stops gaining readings. |

**Known limitation:** incremental live DuckDB queries avoid rescanning all stored rows, but the dashboard's in-memory projection still rebuilds from all events for the selected run. Full-run historical rendering may be slower than the short replay.

## 10. Submission checklist

The Canvas **source-code/database ZIP** must contain the source scripts, the complete Task 1 generated datasets, full Task 2 event stream and manifest, `database/charger_analytics.duckdb`, the schema/DDL script, `requirements.txt` and this README. The **project report (maximum six pages of content)** and the **Generative AI Usage Report** are separate required submissions.

**Do not create the ZIP using `git archive` alone:** the 134,162-event JSON is Git-ignored and the full DuckDB may exist only locally.

After creating the ZIP, run:

```bash
python scripts/check_submission.py path/to/submission.zip
```

This checks archive presence/structure and essential artifacts; it does not replace test execution or the DuckDB full-stream verifier. Do not include `.venv/`, `.git/`, local secrets, logs or SQLite development journals.

Additional technical records are in `docs/`; historical Task 3 and Task 4 standalone modules remain in `src/` as provenance but are **not** part of the recommended integrated startup procedure.
