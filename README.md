# NSW EV Charging — Streaming, Storage and Interactive Dashboard

**COMP5339 Data Engineering · Assignment 2 · 2026 Semester 2**

This project simulates electric-vehicle charging activity across New South Wales (NSW). It builds on the station and charger metadata from Assignment 1, generates hourly electricity prices and charging sessions, publishes an ordered stream of MQTT events, stores them in DuckDB, and visualises live and historical charging activity on an interactive map.

**Start here:** If you are marking or testing this submission for the first time, follow **Section 1 (Quick start)**. The three terminal commands below are all you need for a live demonstration of the included short replay.

## 1. Quick start — run the live demonstration

### 1.1 Prerequisites and project files

- Python **3.12** and an internet connection to install dependencies; no Docker or external MQTT account is required.
- Extract the entire submitted ZIP to a folder. **Keep the folder structure unchanged.**
- Open a terminal **inside the extracted project root** (the folder containing `README.md`, `requirements.txt`, `src/`, `dashboard/` and `database/`).
- The ZIP includes the prepared short event stream `data/events/mqtt_demo/events.json` and the validated metadata database `database/charger_metadata.duckdb`. You do **not** need to regenerate data before running the demo.

**macOS / Linux — one-time environment setup:**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If `python3.12` is unavailable but `python3 --version` reports Python 3.12, replace `python3.12` with `python3` in the first command.

**Windows PowerShell — one-time environment setup:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` instead of `python` for all commands below (no activation required). The following terminal examples use `python` and assume the environment is activated.

### 1.2 Open THREE terminals in this exact order

All three terminals must have the project root as their working directory and use the same Python environment.

| Order | Terminal | Program | Keep it open? |
| --- | --- | --- | --- |
| **1** | A | MQTT Broker | Yes, throughout the live demo |
| **2** | B | Streamlit Dashboard **and built-in Subscriber** | Yes, throughout the live demo |
| **3** | C | MQTT Publisher | Start **only after** Terminal B confirms SUBACK |

**TERMINAL A — Start the local MQTT Broker**

```bash
python src/local_broker.py
```

Expected terminal output includes:

```text
Local MQTT broker ready at 127.0.0.1:1883; Ctrl+C to stop
```

**Leave Terminal A running.** This is a local MQTT server; no cloud service is necessary.

**TERMINAL B — Start the Dashboard and integrated MQTT Subscriber**

In a **new** terminal (do not stop Terminal A):

```bash
python -m streamlit run dashboard/app.py
```

Open **http://localhost:8501** in a browser. The URL works on the **same computer** where Streamlit runs, not on an external computer.

At the top of the dashboard, set:

| Dashboard control (exact UI label) | What to choose |
| --- | --- |
| **View** | `Live demonstration` |
| **Run ID** | Enter **`marker-demo-01`** (or a different fresh, unused ID) |
| **Auto-refresh (5s)** | **On** |

**Important:** the Live Run ID field starts empty. Entering the ID starts the integrated subscriber. Wait until Terminal B prints:

```text
SUBACK: integrated DuckDB ready for marker-demo-01
```

The dashboard should also say **Receiver: SUBSCRIBED**. **Do not start the Publisher before this point.** Use the same Run ID in both places.

**TERMINAL C — Publish the included 1,091-event demonstration stream**

In a **third** terminal, with Terminals A and B still running:

```bash
python src/publisher.py --events data/events/mqtt_demo/events.json --run-id marker-demo-01
```

This publishes **1,091 ordered MQTT events at QoS 1**, with a minimum interval of **0.1 seconds**. The replay requires **at least 109.1 seconds** plus processing overhead. Leave all three terminals running until the Publisher finishes.

### 1.3 What to check in the Dashboard

During the live replay:

1. **Applied events** increases as messages are successfully committed to DuckDB.
2. The **NSW map** displays physical charging stations. Nearby markers may be grouped: zoom in or click a cluster to reveal individual markers.
3. **Click a station marker** to open a popup showing its station/charger details, connector information, latest price and occupancy. The **Station details** selector should follow your marker selection.
4. Under the selected station, use **Session status** (`All`, `Active`, `Completed`) and **Find session** to locate a session with meter readings. Select it in **Session with meter readings**.
5. Switch the **Live meter curve** between **Cumulative energy (kWh)** and **Power (kW)**. With **Auto-refresh (5s)** enabled, additional meter messages extend the time-series chart.

**Important interpretation of the demo:** The first ~864 records are predominantly `price_update` messages. It is **normal for Active sessions to show 0 at the beginning**. Charging sessions appear later when `session_start` events have been applied. You may need to select a station that actually has a session in this short replay; not every station is active.

**Expected counts after successful completion of this specific short replay:**

| Metric | Expected value |
| --- | ---: |
| Applied / committed events | **1,091** |
| Price-update events | 864 |
| Session starts | 16 |
| Meter events | 210 |
| Session ends | 1 |
| Active sessions remaining at the selected replay cutoff | **15** |
| Completed sessions | **1** |
| Completed charging energy | **approximately 44.13 kWh** |

The data represents a **simulated time window**, not real-world charger availability. The short dataset deliberately leaves 15 sessions active at its cutoff. The original event timestamps are retained, while messages are transmitted sequentially at the configured replay pace.

### 1.4 Repeat the live demo

A new live publication must use a **new Run ID** to avoid clashing with old publisher checkpoints and committed database events. For example, change the dashboard Run ID to `marker-demo-02`, wait for its new SUBACK, then run:

```bash
python src/publisher.py --events data/events/mqtt_demo/events.json --run-id marker-demo-02
```

Do not reuse `marker-demo-01` unless explicitly continuing an interrupted publisher run using `--resume` as documented in [publisher details](docs/task2_publishing.md).

### 1.5 Stop the programs

Once you finish the live test, use **Ctrl+C** in Terminal C (if still active), then Terminal B, then Terminal A. **Stop Streamlit before opening the analytics database from an external verification script**, because DuckDB can hold a file lock while the app is running.

---

## 2. Historical replay — run without MQTT

Use this to inspect events already persisted in the supplied DuckDB database. **Only one terminal is needed. No Broker and no Publisher.**

1. Stop any currently running Streamlit instance and MQTT Publisher.
2. Open one terminal in the project root and activate the virtual environment.
3. Run:

   ```bash
   python -m streamlit run dashboard/app.py
   ```

4. Open **http://localhost:8501**.
5. Set **View → Historical replay**.
6. In **Run ID**, **replace the default value** with **`integration-full-02`**, provided this Run ID is present in the submitted `database/charger_analytics.duckdb`.
7. Switch **Auto-refresh (5s)** **Off** for easier interaction with large runs.
8. Look for the caption **Historical DuckDB snapshot**, then inspect the four KPI cards and map. Click a station marker, pick a station-associated session, and select an energy/power curve.

The completed full replay used **134,162 events** with sequence numbers **1 through 134,162**. It contains **4,021 session starts and 4,021 session ends**, so a completed full run should show **0 active and 4,021 completed sessions**. This is **different from the short live replay**, whose cutoff deliberately leaves 15 active sessions.

If `integration-full-02` returns no records, the supplied DuckDB copy may not contain that run; check which Run IDs it includes. Do not assume the default `integration-demo-01` refers to the full dataset. Historical replay needs an existing populated `charger_analytics.duckdb`; it cannot create historical events by itself.

---

## 3. What the project does — architecture and data flow

### 3.1 End-to-end system overview

```text
                      PREPARATION (offline)
┌────────────────────────────┐        ┌──────────────────────────────┐
│ Assignment 1 NSW metadata  │        │ AEMO NSW electricity prices  │
│ stations, chargers, coords  │        │ + supplied synthetic generator│
└──────────────┬─────────────┘        └─────────────┬────────────────┘
               │                                    │
               └────────────────┬───────────────────┘
                                ▼
                 Task 1 generated CSV datasets
                 (prices, sessions, meter readings)
                                │
                                ▼
                      Event preparation
                      src/prepare_events.py
            validation + ordering + price-change filtering
                                │
                                ▼
                 data/events/.../events.json
                 4 event types + sequence numbers

                       LIVE STREAMING
                                │
                                ▼
              MQTT Publisher — src/publisher.py
                   QoS 1; >= 0.1 s/message
                                │
                                ▼
              MQTT Broker — src/local_broker.py
                        127.0.0.1:1883
                                │
                                ▼
        Integrated MQTT Subscriber — src/integrated_runtime.py
            validates, orders, deduplicates messages
                                │
                                ▼
          DuckDB — database/charger_analytics.duckdb
           raw events + current price/occupancy/session state
                                │
                                ▼
                Streamlit — dashboard/app.py
           NSW map, popups, meter curves, run-level KPIs
                                ▲
                                │
             Historical replay reads DuckDB directly
                   (no Broker/Publisher needed)
```

### 3.2 Responsibilities of the components

| Component | Source | Purpose |
| --- | --- | --- |
| Station and charger metadata | `database/charger_metadata.duckdb` | Validated physical NSW sites, operators, coordinates, connector configurations |
| Synthetic dataset generation | `src/run_task1.py` and supplied generator in `vendor/` | Create hourly prices, charging sessions and per-minute meter data |
| Offline preparation | `src/prepare_events.py` | Map generator charger IDs to physical stations, remove unchanged prices, validate and sort JSON events |
| Ordered MQTT Publisher | `src/publisher.py` | Publish one event per message, wait for PUBACK, support checkpoint/retry/resume |
| Local Broker | `src/local_broker.py` | Route published MQTT messages to the subscriber |
| Integrated receiver | `src/integrated_runtime.py`, `src/analytics_subscriber.py` | Subscribe to selected Run ID, check sequence ordering and duplicate identity, manually acknowledge persisted events |
| DuckDB storage and queries | `src/analytics_storage.py`, `src/analytics_queries.py`, `database/analytics_schema.sql` | Persist raw JSON and transactional derived state; query live and historical metrics |
| Dashboard | `dashboard/app.py`, `src/task3_state.py` | Show interactive NSW station map, latest price, occupancy, sessions and meter charts |

**Important architectural decision:** Only **one integrated MQTT Subscriber and one DuckDB writer** operate during the recommended live workflow. The Streamlit process manages this receiver internally. **Do not start a separate `src/subscriber.py` or standalone `src/analytics_subscriber.py` process at the same time.** This avoids inconsistent duplicate processing and DuckDB writer contention.

**Run IDs** separate independent replays. Always use the identical Run ID in the dashboard and Publisher for live mode. Raw and derived records in DuckDB are scoped by Run ID, preventing a short replay from being mixed with the 134,162-event historical run.

### 3.3 Event types and state updates

| Event type | Meaning | Subscriber / analytics update |
| --- | --- | --- |
| `price_update` | Initial or changed electricity price for one charger configuration | Updates current `price_per_kwh` |
| `session_start` | Vehicle starts a charging session on a connector | Creates active session and marks connector occupied |
| `meter` | Minute-level readings including `power_kw` and cumulative `energy_kwh` | Updates progress and supports energy/power curves |
| `session_end` | Vehicle unplugs and the session closes | Completes session, records final measures, releases connector |

The message topic includes the replay ID, physical station ID, charger configuration ID and event type. Events are ordered by simulated event time; ties are deterministically resolved. Source generator times are on a fixed NEM clock (UTC+10), then converted to UTC in MQTT payloads.

The integrated receiver uses MQTT 3.1.1 **QoS 1**, handles duplicate/out-of-order deliveries and acknowledges events after successful database commits. The raw event and derived state changes share a DuckDB transaction; the UI reads committed state. The generated input is **synthetic**, not a live feed from NSW charging providers.

---

## 4. Where the data comes from — scale and expected results

### 4.1 Generated datasets

The supplied synthetic generator uses the validated NSW metadata and AEMO-derived electricity-price inputs. These are the verified project outputs:

| Dataset | File | Count |
| --- | --- | ---: |
| Charger configurations | `data/generated/stations.csv` | **432**, representing 414 physical sites |
| Hourly prices | `data/generated/prices_hourly.csv` | **10,368** |
| Charging sessions | `data/generated/sessions.csv` | **4,021** |
| Minute meter readings | `data/generated/session_metering.csv` | **121,800** |

### 4.2 Prepared MQTT streams

| Event type | Short demo | Full event stream |
| --- | ---: | ---: |
| `price_update` | 864 | 4,320 |
| `session_start` | 16 | 4,021 |
| `meter` | 210 | 121,800 |
| `session_end` | 1 | 4,021 |
| **Total** | **1,091** | **134,162** |

- **Short demonstration:** `data/events/mqtt_demo/events.json` — practical for a live walkthrough; chosen around 15 September 2026, 00:59–01:02 NEM, including the starting state needed to interpret events.
- **Full preparation:** `data/events/full/events.json` — all prepared events, including sessions extending beyond the generation day. The corresponding `manifest.json` records preparation validation and file checksum.
- **Published evidence:** `data/published/<run-id>/` — publisher checkpoint, broker-acknowledged events and publication manifest.
- **Persisted results:** `database/charger_analytics.duckdb` — actual messages ingested into DuckDB for each replay Run ID.

The full stream must be present in the **submitted ZIP even though it may be excluded by Git**. The updated analytics DuckDB must also be included for Historical replay.

### 4.3 Optional: reproduce or verify generated data

Do **not** regenerate data for the basic short live demo or for viewing an already-populated historical database.

To regenerate Task 1 (the AEMO input cache must exist, otherwise the generator may need network access):

```bash
python src/run_task1.py
python src/validate_task1.py
```

To recreate the full ordered events from the Task 1 CSVs:

```bash
python src/prepare_events.py
```

To validate the prepared full JSON, independently of MQTT:

```bash
python scripts/verify_full_stream.py
```

The script distinguishes **prepared-data integrity** from **actual MQTT/DB delivery**. A valid preparation manifest does not itself prove that the events were published.

---

## 5. Database design, dashboard displays and verification

### 5.1 DuckDB design

The integrated analytics database is initialized using the Assignment 1 metadata and the DDL in `database/analytics_schema.sql`. Important structures:

| Object | Description |
| --- | --- |
| `mqtt_events` | Raw JSON events, event time, Run ID, event ID and sequence |
| `charger_current_state` | Latest price for each charger within a Run ID |
| `charging_sessions` | Active/completed sessions and most recent/final charging metrics |
| `active_connectors` | Occupied connector assignments |
| `meter_history` (view) | Time-series readings extracted from raw meter events |
| `run_session_metrics` (view) | Run-specific active sessions, completed sessions, completed energy |

The schema maintains primary/unique constraints to prevent duplicate logical events and conflicting sequence positions. Maintaining separate current-state tables avoids repeatedly recomputing all state from raw events for every analytics query. The meter and metrics objects are **views, not materialized tables**.

### 5.2 Dashboard UI reference

| UI element | What it shows / how to use it |
| --- | --- |
| **Applied events** | Count of valid events applied for the selected Run ID |
| **Active sessions** | Open charging sessions at the current replay cutoff |
| **Completed sessions** | Sessions closed by a `session_end` event |
| **Completed energy (kWh)** | Total final energy from completed sessions |
| **Station map** | NSW physical stations, clustered for readability |
| **Marker popup** | Station details, charger operator, connector/plug information, latest price, occupancy |
| **Station details** | Selected station's charger configurations; follows marker clicks |
| **Session status** / **Find session** | Limit the session list to the chosen station and selected status/search |
| **Session with meter readings** | Select one charging session for time-series plotting |
| **Live meter curve** | Toggle cumulative energy (kWh) or instantaneous power (kW) |

**Pricing/occupancy interpretation:** Values reflect the **currently applied simulated event sequence**. A station cannot display a new price before its `price_update` event arrives; an occupied connector becomes free only after the corresponding `session_end` event.

### 5.3 Verify the already-ingested complete run (optional)

The team completed a full MQTT-to-DuckDB replay with Run ID **`integration-full-02`**: **134,162 persisted events**, with sequence numbers from **1 to 134,162**; the saved run was then inspected through the Historical replay dashboard.

To independently check exact stored payloads against the full prepared JSON, **first stop Streamlit** so the database lock is released, then run:

```bash
python scripts/verify_full_stream.py --run-id integration-full-02
```

**Expected success line if the submitted database contains that run and all records match:**

```text
PASS MQTT/DuckDB run integration-full-02: all 134162 stored payloads match exactly
```

Do not confuse a prior successful **event-count/sequence check** with a successful **payload-by-payload match**. This command performs the stronger comparison; its result should be treated as verified only when it actually prints PASS.

### 5.4 Automated tests

```bash
python -m unittest discover -s tests -v
```

The tests cover input preparation, event ordering, publishing and receiving, state transitions and dashboard-related logic. Use the same Python environment installed from the root `requirements.txt`.

---

## 6. Troubleshooting — practical fixes

| Issue | Check / fix |
| --- | --- |
| **Broker won't start / port 1883 in use** | Another broker may already be running. Stop the earlier broker before rerunning `python src/local_broker.py`. |
| **Dashboard says CONNECTING** | Confirm Terminal A is still running and that Run ID is nonempty. Wait until the subscriber prints **SUBACK**. |
| **Applied events remains 0** | Confirm the Run ID in Terminal C **exactly matches** the Live Run ID. Check Publisher output and wait for SUBACK first. |
| **Active sessions is 0** | Normal at the beginning of the short stream: most of its first events are price updates. Wait for `session_start` events; final short-run expected count is **15**. In the **complete historical run**, final Active sessions is **0** because all sessions have ended. |
| **No charging curve** | Select a station that has sessions, use `All` or `Active` in **Session status**, and pick a session with meter readings. Not every station has an active session in the short replay. |
| **Map marker can't be selected** | Zoom into a cluster and click an individual station marker; turn Auto-refresh Off temporarily while interacting with popups. |
| **Historical replay shows no records** | Historical mode needs a populated `charger_analytics.duckdb`. Enter an **existing stored Run ID**; `integration-full-02` was used for the complete test, while the short replay uses a separate ID. |
| **DuckDB conflicting lock** | Stop Streamlit and other processes reading/writing the analytics database before running external verification. Do **not** delete the database. |
| **Map tiles missing** | OpenStreetMap basemap tiles require an internet connection, even though MQTT and DuckDB operate locally. |
| **Large historical run is slow** | Switch **Auto-refresh (5s)** Off. The dashboard currently reconstructs its visual projection from the selected run's accumulated history, so very large runs may refresh more slowly. |
| **Need to publish again** | Use a **fresh Run ID** in both the dashboard and Publisher. Do not restart with a completed ID unless following the documented checkpoint resume procedure. |

---

## 7. Project layout — key files

```text
README.md                       This document: overview and reproduction instructions
requirements.txt                All Python dependencies for integrated operation
config/                         Generator/operator settings
vendor/                         Provided synthetic generation resources
data/
  source/                       Retained NSW/AEMO source files
  input/                        Generator input
  processed/                    Prepared A1 metadata and charger-to-station mapping
  generated/                    stations.csv, prices_hourly.csv, sessions.csv, session_metering.csv
  events/
    mqtt_demo/events.json       Included 1,091-event example for a quick live replay
    full/events.json            Prepared 134,162-event full stream (required in ZIP)
    full/manifest.json          Full preparation checks and event counts
  published/                    Per-run Publisher checkpoints and exported receipts
database/
  charger_metadata.duckdb       A1 stations and charger configurations
  charger_analytics.duckdb      Real MQTT-ingested events and derived session state
  analytics_schema.sql          Tables, integrity constraints and analytical views
dashboard/
  app.py                        Streamlit application (includes live and historical UI)
src/
  run_task1.py                  Run synthetic dataset generation
  validate_task1.py             Check Task 1 outputs
  prepare_events.py             Validate, filter and order MQTT-ready events
  local_broker.py               Local MQTT server
  publisher.py                  MQTT event publisher and resume checkpoints
  integrated_runtime.py         Single subscriber and DuckDB worker
  analytics_subscriber.py       Sequence validation, buffering, deduplication
  analytics_storage.py          Transactional DuckDB event/state writes
  analytics_queries.py          Current and historical metrics
  task3_state.py                Event-driven dashboard projection
scripts/
  verify_full_stream.py         Prepared events + optional DuckDB payload comparison
  check_submission.py           Check essential files in the final ZIP
tests/                           Unit/integration tests
docs/                            Technical details for generation, events and publishing
```

For more information, refer to [Task 1 results](docs/task1_results.md), [event preparation](docs/task2_events.md), [publisher and recovery](docs/task2_publishing.md), [event schema](docs/event_schema.md) and [MQTT topics](docs/mqtt_topics.md).

---

## 8. Final submission and reproducibility checklist

The Canvas submission requires a **source-code/database ZIP**, **project report (PDF)** and **separate Generative AI Usage Report**. Before submitting, confirm that the ZIP contains:

- The complete project source, `requirements.txt`, `README.md` and `database/analytics_schema.sql`.
- The validated metadata database `database/charger_metadata.duckdb` and **persisted analytics database** `database/charger_analytics.duckdb`.
- All four Task 1 generated datasets in `data/generated/`.
- The full **134,162-event** JSON file `data/events/full/events.json` and its manifest, plus the short `data/events/mqtt_demo/events.json`.
- Any supporting source/config files required by the provided generator.

**Do not rely on `git archive` or a fresh Git clone for the full hand-in**: the full `events.json` and populated analytics database can be Git-ignored/local artifacts.

After creating `submission.zip`:

```bash
python scripts/check_submission.py submission.zip
```

The checker verifies that the essential ZIP members exist and are nonempty, including the full event-stream size. It does not prove the application runs or validate the accuracy of the written report. Exclude `.git/`, `.venv/`, caches and development-only files from the ZIP.

**Runtime assumptions and limits:** local MQTT broker on `127.0.0.1:1883`; a single integrated MQTT subscriber/analytics writer; synthetic data and UTC-normalised event timestamps; OpenStreetMap requires internet; Streamlit/DuckDB run on the assessor's own computer; the full 134,162-event MQTT replay takes **at least ~3 h 44 min** at the required minimum publishing interval and is **not required** to demonstrate the system if the persisted full-run DuckDB is included.
