# NSW EV Charging — Streaming, Storage and Interactive Analytics

**COMP5339 Data Engineering · Assignment 2 · 2026 S2**

This project simulates electric-vehicle charging activity across New South Wales (NSW). It extends the **Assignment 1 charging-station database** with synthetic hourly electricity prices, charging sessions and minute-by-minute meter readings. An MQTT publisher replays the generated events in timestamp order; an integrated subscriber validates and persists them in DuckDB; and a Streamlit dashboard displays station status, prices, charging-session curves and historical usage metrics.

**For markers assessing the project, begin with [Quick Start: Live MQTT](#4-quick-start-live-mqtt--three-terminals) to see events flowing through the whole system, then use [Historical Replay](#5-historical-replay--one-terminal-no-broker) to inspect the completed 134,162-event run.** You do not need to regenerate datasets or replay the entire multi-hour stream.

## 1. What this project does

| Component | Responsibility | Main files |
| --- | --- | --- |
| Data preparation | Reuse NSW station/charger records from Assignment 1; prepare the generator inputs | `database/charger_metadata.duckdb`, `data/processed/` |
| Synthetic data generation | Generate hourly prices, charging sessions and minute-level readings | `src/run_task1.py`, `src/validate_task1.py`, `data/generated/` |
| Event preparation | Transform CSV rows into validated, ordered JSON events; omit unchanged prices | `src/prepare_events.py`, `data/events/` |
| MQTT transport | Publish events to a local MQTT broker using QoS 1 and at least 0.1 seconds between messages | `src/publisher.py`, `src/local_broker.py` |
| Subscription and storage | Receive, validate, deduplicate and order messages; transactionally persist events and state to DuckDB | `src/integrated_runtime.py`, `src/analytics_subscriber.py`, `src/analytics_storage.py` |
| Visualisation and analytics | Show the NSW map, station popups, current prices/occupancy, charging curves and historical metrics | `dashboard/app.py`, `src/analytics_queries.py` |

### System architecture

```text
Assignment 1 metadata ───────────┐
                                  │
Synthetic generator              │
  ├── hourly prices CSV          │
  ├── charging sessions CSV      │
  └── meter readings CSV         │
              │                   │
              ▼                   ▼
    Event preparation       Station/charger
    (ordered JSON)          metadata DuckDB
              │                   │
              ▼                   │
       MQTT Publisher            │
       QoS 1 / >= 0.1 s          │
              │                   │
              ▼                   │
     Local MQTT Broker            │
       127.0.0.1:1883             │
              │                   │
              ▼                   │
  Integrated MQTT Subscriber      │
  validate / order / dedupe       │
              └────────┬──────────┘
                       ▼
        charger_analytics.duckdb
        raw events + current state
                       │
                       ▼
          Streamlit Dashboard
        NSW map / live session
         curves / historical KPIs
```

**Important architecture rule:** the Streamlit application runs **one integrated subscriber and one DuckDB writer**. Do **not** start the standalone legacy subscribers simultaneously. In Live mode, MQTT events are accepted and committed before they are displayed. In Historical replay, Streamlit reads already-persisted events directly from DuckDB without connecting to MQTT.

### Dataset and event counts

| Generated dataset | Records |
| --- | ---: |
| Physical charging stations | 414 |
| Charger configurations | 432 |
| Hourly price records | 10,368 |
| Charging sessions | 4,021 |
| Minute-level meter readings | 121,800 |

| Prepared MQTT event | Count |
| --- | ---: |
| `price_update` (initial prices + actual changes) | 4,320 |
| `session_start` | 4,021 |
| `meter` | 121,800 |
| `session_end` | 4,021 |
| **Full stream** | **134,162** |

The published messages include the physical `station_id` and configuration-level `charger_id`, which connect the synthetic records to the Assignment 1 spatial metadata.

## 2. Files supplied in the submission ZIP

```text
README.md                           This guide
requirements.txt                    Python packages
dashboard/
  app.py                            Streamlit map and charts
src/
  run_task1.py                      Generate synthetic source data
  validate_task1.py                 Validate generated data
  prepare_events.py                 Convert source CSVs into MQTT-ready JSON
  publisher.py                      MQTT publisher
  local_broker.py                   Local MQTT broker
  integrated_runtime.py             One MQTT/DuckDB worker for Streamlit
  analytics_subscriber.py           Ordering, validation and deduplication
  analytics_storage.py              DuckDB transactions/state updates
  analytics_queries.py              Queries for dashboard metrics
  task3_state.py                    Event-to-visual-state projection
database/
  charger_metadata.duckdb           Assignment 1 station/charger metadata
  charger_analytics.duckdb          Persisted MQTT events and analytics
  analytics_schema.sql              Schema / DDL
data/
  generated/
    stations.csv
    prices_hourly.csv
    sessions.csv
    session_metering.csv
  processed/                        Metadata mapping and preparation
  events/
    mqtt_demo/events.json           Ready-to-publish short replay: 1,091 events
    full/events.json                Full replay: 134,162 events
    full/manifest.json              Checksums and prepared-stream statistics
  published/                        Run-specific publisher logs/checkpoints
scripts/
  verify_full_stream.py             Event-file and DuckDB reconciliation
  check_submission.py               ZIP deliverable checks
tests/                               Automated tests
docs/                                Detailed implementation documentation
```

**Check the extracted ZIP, not just GitHub.** The large `data/events/full/events.json` file is Git-ignored, and `database/charger_analytics.duckdb` is a local runtime artifact. They must be copied into the submission ZIP if the marker is to inspect the completed full run. Never delete the provided DuckDB file to troubleshoot a lock.

## 3. One-time setup

### Prerequisites

- **Python 3.12** recommended.
- macOS, Linux or Windows; all commands must be run from the **extracted project root**, i.e. the folder containing `README.md` and `requirements.txt`.
- A browser for the local Streamlit interface. Internet access is needed for OpenStreetMap background tiles; MQTT and DuckDB work locally.
- No Docker, hosted MQTT service or separate DuckDB server required.

### macOS / Linux

Open Terminal, change into the extracted folder, then create and activate a virtual environment:

```bash
cd /path/to/extracted/4A2
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Windows PowerShell

```powershell
cd C:\path\to\extracted\4A2
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, use `.\.venv\Scripts\python.exe` in place of `python` in the commands below.

**For each new terminal** in the Live walkthrough, first change into the same project root and activate the same environment. Do not run the scripts from the `src/` or `dashboard/` folders.

## 4. Quick Start: Live MQTT — THREE terminals

This is the recommended **end-to-end live demonstration**. It uses the included **1,091-event replay**, avoiding the long full replay.

### Before starting

Confirm these files exist:

```text
data/events/mqtt_demo/events.json
database/charger_metadata.duckdb
```

Close any old Broker, Streamlit or Publisher processes from earlier attempts. Use a **new Run ID**, e.g. `marker-live-01`; if you already used it, choose `marker-live-02`. Use **exactly the same ID** in the Dashboard and Publisher.

### TERMINAL 1 — Start the MQTT Broker

Open the first terminal, go to the project root, activate the environment and run:

```bash
python src/local_broker.py
```

**Wait for:**

```text
Local MQTT broker ready at 127.0.0.1:1883; Ctrl+C to stop
```

Keep Terminal 1 open. This broker receives the Publisher's events and forwards them to the subscriber.

### TERMINAL 2 — Start the Dashboard + integrated Subscriber

Open a **second terminal**, go to the same project root, activate the environment and run:

```bash
python -m streamlit run dashboard/app.py
```

Open **http://localhost:8501** in the browser. This is a **local URL**: it opens on the computer running Streamlit; it is not a public hosted website.

At the top of the dashboard:

1. Set **View** to **Live demonstration**.
2. Set **Run ID** to **`marker-live-01`** (or your fresh alternative).
3. Leave **Auto-refresh (5s)** enabled so new data appears automatically.
4. Wait for the subscriber to connect. The Streamlit interface should show **`Receiver: SUBSCRIBED`**, and Terminal 2 should print a message similar to:

```text
SUBACK: integrated DuckDB ready for marker-live-01
```

**Do not start the Publisher before SUBACK.** Starting too early can leave the receiver without earlier event sequences.

### TERMINAL 3 — Publish the short MQTT event stream

Only after SUBACK, open a **third terminal**, change into the project root, activate the environment and execute:

```bash
python src/publisher.py --events data/events/mqtt_demo/events.json --run-id marker-live-01
```

**Expected Publisher behaviour:** the terminal prints progress such as `PUBACK 100/1091`, `PUBACK 200/1091`, etc., followed by a final manifest with `status: COMPLETE` and `acknowledged_count: 1091`.

At a minimum of **0.1 seconds per message**, the short stream lasts **at least ~109 seconds**, plus processing overhead. The Dashboard updates every five seconds; no manual browser reload is normally necessary.

### What to test in the Dashboard

| Step | Action | Expected behaviour |
| --- | --- | --- |
| **A. Confirm live ingestion** | Watch the top status line while Publisher runs | **DuckDB committed** increases from 0 towards 1,091; `Receiver: SUBSCRIBED` remains visible |
| **B. Map and price** | Inspect the NSW map and click a station marker | A popup shows station address, operator, connector information, latest price and occupancy |
| **C. Synchronised selection** | Click a map marker | **Station details** changes to the corresponding physical station |
| **D. Charging session** | In Station details, select a station with sessions; inspect **Session status** and **Session with meter readings** | Session options are filtered to the selected station |
| **E. Live charging curve** | Choose a session with meter readings; switch **Cumulative energy (kWh)** / **Power (kW)** | A Plotly time-series curve shows session progress; as further meter events arrive, points appear |
| **F. Final state** | Wait until Publisher finishes, then allow one dashboard refresh | **1,091 committed events**, **15 active sessions**, **1 completed session**, approximately **44.13 kWh completed energy** |

**Why may Active Sessions initially be 0?** The prepared stream starts with price updates and events are published in timestamp order. Sessions only become active after their `session_start` messages arrive; do not expect 15 active sessions immediately. For a meaningful live curve, select a session receiving meter readings during publication. To make interaction easier, temporarily disable Auto-refresh while opening map popups, then enable it again.

**Run ID rule:** A Run ID identifies a particular replay and is used in MQTT topics and DuckDB records. Do not start a second fresh Publisher against a completed Run ID. Publisher output is written under `data/published/<run-id>/`.

### Shutting down

After publication, press **Ctrl+C** in the Publisher terminal if it has not already exited; stop Streamlit with **Ctrl+C** in Terminal 2, then stop the Broker with **Ctrl+C** in Terminal 1. Stop Streamlit before running an independent script that opens the DuckDB file, because the integrated worker holds the connection during Live mode.

## 5. Historical Replay — ONE terminal, NO Broker

This mode demonstrates **persistence and historical analytics** using stored data. It is the fastest way to inspect the full dataset and does **not** republish any messages.

1. Stop the live Streamlit process first, if it is running.
2. Open a terminal in the project root and activate the environment.
3. Launch only Streamlit:

   ```bash
   python -m streamlit run dashboard/app.py
   ```

4. Visit **http://localhost:8501** and set **View = Historical replay**.
5. Enter **Run ID = `integration-full-02`**, provided the included `charger_analytics.duckdb` contains that original completed run.
6. Turn **Auto-refresh (5s) = Off** to navigate the large dataset more comfortably. Use **Refresh now** if needed.

**Expected output for the supplied completed full run:** **134,162 stored events**, **4,021 completed sessions**, **0 active sessions** at the end of the complete replay. The dashboard also shows the completed-energy total calculated from DuckDB.

**Things to click:** choose any map marker → inspect its popup → confirm **Station details** follows the map click → filter **Session status = Completed** → choose a recorded session → inspect the Power/Energy line curve.

**Important distinction:** for the fully completed historical run, **Active Sessions = 0 is correct**. All session-end events have arrived. To demonstrate currently active sessions and the curve updating as new messages arrive, use **Live demonstration** in Section 4.

Historical replay will show no data for an unknown Run ID, and it cannot reconstruct the full run unless the corresponding DuckDB database is included.

## 6. Data integrity and reproducibility

### Validate the prepared full stream (no MQTT required)

With the provided `data/events/full/events.json` and `data/events/full/manifest.json`:

```bash
python scripts/verify_full_stream.py
```

This checks event counts, hashes, sequence ordering and event semantics. It should print `PASS prepared full event stream`. This test **does not itself prove MQTT delivery**.

### Reconcile a fully stored MQTT run

If the full run `integration-full-02` is included in DuckDB, **stop Streamlit first**, then run:

```bash
python scripts/verify_full_stream.py --run-id integration-full-02
```

The script compares the stored DuckDB event count and sequence range against the prepared stream; verifies every stored payload; and checks completed/active session counts. It prints a final `PASS MQTT/DuckDB ...` only if **every check succeeds**. Do not interpret the prepared-stream PASS as the same result.

### Reproduce source data (optional)

Only if the generated source files are missing:

```bash
python src/run_task1.py
python src/validate_task1.py
```

The generator can require the retained AEMO data cache or internet access when the source cache is unavailable. It is **not necessary** for the recommended live demo when the prepared datasets are already supplied.

### Regenerate the event stream (optional)

From existing Task 1 CSVs:

```bash
python src/prepare_events.py
```

This regenerates `data/events/full/events.json` and its manifest. It is **not necessary** if the ZIP already contains the prepared events.

### Full MQTT publication (optional, multi-hour)

The full stream was previously run end-to-end as `integration-full-02`. To publish it **again** from scratch, follow the same three-terminal setup as Section 4 but choose a **fresh** Run ID in both the Dashboard and the command below:

```bash
python src/publisher.py --events data/events/full/events.json --run-id marker-full-new-01
```

This is **not part of the recommended initial marking walkthrough**: 134,162 MQTT events with at least 0.1 seconds between messages take at least about **3 hours 44 minutes**.

### Automated tests

```bash
python -m unittest discover -s tests -v
```

## 7. DuckDB schema and query behaviour

The database starts from the Assignment 1 spatial metadata and is extended by `database/analytics_schema.sql`.

| Table / view | Function |
| --- | --- |
| `mqtt_events` | Persistent original JSON payload, run ID, event identity, sequence and timestamps |
| `charger_current_state` | Most recent configuration-level electricity price |
| `charging_sessions` | Active/completed sessions and final usage metrics |
| `active_connectors` | Connector occupancy for current-state visualisation |
| `meter_history` (view) | Session meter measurements extracted from stored event payloads |
| `run_session_metrics` (view) | Active sessions, completed sessions and total completed energy |

Event and derived state are committed in one DuckDB transaction. `(run_id, event_id)` prevents duplicate event insertion, and `(run_id, sequence)` constrains replay order. An in-memory visual projection converts the stored event history into the map and chart state. Live snapshots read newly committed rows incrementally; historical visualisation can still take longer on very large runs because the projection is rebuilt.

## 8. Assumptions and limitations

- This is a **simulation**, not real-time access to a commercial EV charging network. Source-generation timestamps use fixed NEM/AEST (UTC+10); stored event timestamps are converted to UTC.
- The selected Run ID scopes subscription topics, persisted records and analytics. Historical runs are not mixed with live runs.
- MQTT QoS 1 can redeliver packets. The receiver handles duplicates and sequence gaps; Subscriber ACKs are issued after accepted events are persisted.
- A single integrated worker owns the DuckDB write connection. A separate verification process may encounter a lock while Live Streamlit is running; stop Streamlit before executing it.
- OpenStreetMap map tiles require internet access.
- The system was exercised with the complete 134,162-event replay, but event-count completeness should not be confused with independent payload-level equivalence unless the reconciliation script also passes. Sustained multi-publisher throughput has not been benchmarked.

## 9. Troubleshooting

| Problem | What to do |
| --- | --- |
| Broker fails to bind on port 1883 | Another Broker may already be running. Stop the older Broker; do not start two Brokers on the same port. |
| Dashboard shows CONNECTING / no SUBACK | Start Terminal 1 first. Ensure Broker is on `127.0.0.1:1883`; check the Streamlit terminal for errors. |
| Dashboard shows zero events | Make sure the Publisher is running, SUBACK occurred first and **both interfaces use the same Run ID**. |
| Dashboard shows zero active sessions | At the beginning of Live replay, session starts may not have arrived yet. At the end of the full historical replay, zero active sessions is expected. |
| Session curve is missing | Select a station with a session, then select that session after meter events arrive; switch between Power and Energy views. |
| Map popup closes during refresh | Temporarily disable Auto-refresh, interact with the popup, then enable it again. |
| DuckDB reports a file lock | Stop Streamlit and other DuckDB processes before external verification. Do **not** remove the database. |
| Historical replay shows zero events | Check the stored Run ID and the presence of `database/charger_analytics.duckdb`. |
| Maps have no background tiles | Enable internet access for OpenStreetMap; the data pipeline can still run offline. |

## 10. Submission verification

The submitted ZIP must include **all generated CSV datasets, both prepared event streams (especially the large full JSON), Assignment 1 metadata DB, updated DuckDB analytics DB, schema/DDL, Python source, dependencies and README**. The report (PDF, at most six pages of content excluding title/appendix) and Generative AI Usage Report are separate submissions.

After making the ZIP, check it from the project root:

```bash
python scripts/check_submission.py /path/to/submission.zip
```

This validates the presence and nonempty sizes of required files; it is not a runtime test. Do **not** rely on `git archive` alone: the full JSON and analytics DuckDB may be absent from Git. Exclude `.git/`, `.venv/`, secrets, caches and development SQLite databases.

For implementation details and advanced publisher recovery, see the supplementary documents in `docs/`. The startup flow described in Sections 4–5 is the **only recommended integrated workflow**.
