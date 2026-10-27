# Task 2: offline event preparation

Implemented and checked on 2026-10-27. Owner: Xuanhan Guo (Task 2).

`src/prepare_events.py` converts the accepted Task 1 CSVs into a JSON array of
ordered MQTT payloads. It does not connect to a broker, publish messages, or
change upstream data. Every output manifest says `NOT_PUBLISHED`.

The Task 2 owner has finalized contract 1.0 in `event_schema.md` and
`mqtt_topics.md`. The Publisher adds a replay `run_id` to each prepared payload;
see `task2_publishing.md` for live execution and `TASK2_TEAM_HANDOFF_ZH.md` for
the Task 3/4 integration handoff.

## Run from the repository root

Full source dataset, including sessions that finish after midnight:

```powershell
.\.venv\Scripts\python.exe src/prepare_events.py
```

Files: `data/events/full/events.json` and `data/events/full/manifest.json`.

A four-hour example, with source/NEM times rather than UTC CLI arguments:

```powershell
.\.venv\Scripts\python.exe src/prepare_events.py --start 2026-09-15T09:00:00 --end 2026-09-15T13:00:00
```

Files: `data/events/20260915T090000_20260915T130000/events.json` and its
`manifest.json`. Use `--output-dir data/events/my_replay` to select another
destination. Both start and end must be provided together; end is exclusive.
The window must fall within hourly-price coverage. Full mode retains all
cross-day session tails.

Only the Python standard library is needed by this converter. The existing
project environment also supports the P0/Task 1 tests. The separate Publisher
requires Paho MQTT; the optional local broker requires `requirements-demo.txt`.

## What the converter does

1. Reads generated stations, hourly prices, sessions, meters and the P0 mapping.
2. Checks identifiers, price coverage, source duplicates, session/connector
   references, session overlap, meter timing and cumulative values.
3. Converts each configuration's initial price and subsequent changes to
   `price_update`; equal consecutive prices are removed. A later return to an
   older price is a genuine change and is retained.
4. Converts each session into `session_start` and `session_end`, plus its meter
   events. Start payloads contain no future final energy, duration or cost.
5. Applies optional window selection and recovers the required starting state.
6. Sorts events, gives each file contiguous one-based sequence numbers, and
   replays the result internally to check price availability and session state.
7. Writes `events.json`, then a manifest containing source/output hashes,
   counts, window policy and validation results.

This converter checks the properties needed for event preparation. Continue
using `src/validate_task1.py` for the upstream AEMO formula and electrical
consistency checks; this module does not replace that validator.

## Payload and identity

Each item in `events.json` is the prepared payload for one logical event.
Publisher adds `run_id` and determines its topic using `mqtt_topics.md`.
There is no extra `payload` wrapper.

| Common field | Meaning |
|---|---|
| `schema_version` | Finalized project contract `1.0` |
| `dataset_id` | SHA-256 of logically ordered input CSV records; not a replay/run ID |
| `event_id` | SHA-256 of semantic payload before sequence/run_id; dedupe by (run_id,event_id) |
| `sequence` | Position within this particular prepared file, starting at 1 |
| `event_type` | `price_update`, `session_start`, `meter`, `session_end` |
| `event_time` | RFC 3339 UTC with a `Z` suffix |
| `station_id` | Candidate site ID from the P0 mapping |
| `charger_id` | A1 configuration ID; required on every event, including prices |

The generator field named `station_id` equals A1 `charger_id` in this project.
It is translated with `data/processed/generator_station_mapping.csv`.
Session/meter events also contain `session_id` and a **string** `connector_id`,
consistent with the current P0 draft. The connector number is local to a charger;
it is not globally unique or a verified physical device identifier.

Event-specific fields:

- Price: `price_per_kwh`, `currency="AUD"`, `price_unit="AUD/kWh"`.
- Start: vehicle model, site type and the locked start tariff/currency.
- Meter: `voltage_v`, `current_a`, `power_kw`, cumulative `energy_kwh`, `soc_pct`.
- End: final energy, charge duration, average/peak power, start tariff, cost,
  currency and `charge_end_time`.

End event time is the original **end_ts (unplug time)**. It is not charge_end_ts.
Session cost retains the teacher generator's locked start-price interpretation.
Meter energy and session final energy retain their respective source rounding.

Identical source records produce identical dataset/event IDs even if CSV row
order or line endings change. The same event in full and window files has the
same ID and payload except for `sequence`. A change to the source dataset creates
a new dataset identity. Separate executions use distinct run_id values in the
publisher/storage design; dataset_id alone does not distinguish demonstrations.

## Time and ordering

Source timestamps are interpreted as **fixed UTC+10**, never the computer's
local timezone and never daylight-saving-adjusted Sydney time. For example:

```text
2026-09-15T09:00:00 on the NEM clock -> 2026-09-14T23:00:00Z
```

Sort by `event_time`, then the following priority, then `event_id`:

```text
price_update -> meter -> session_end -> session_start
```

The dataset has positive charging durations and the first meter follows the
start by one minute. This priority therefore allows a final meter, an old
session's end, and a new session's start to share a timestamp without falsely
occupying a connector twice. It also sets a new hourly price before a session
starting at that hour. This deliberately corrects the P0 draft's start-before-end
rule; subscriber/storage owners should apply the finalized contract.

## Window boundaries and historical scope

For a window `[start, end)`, select sessions that start before end and end at or
after start. Include their actual start events and all available meter records
before end, including required records before start. Include an end only if its
real end timestamp is before end. Do not fabricate closure at the cutoff.

Price recovery uses the latest actual change at or before the earliest selected
session start (or window start when there are no sessions), then subsequent
changes before end. Original timestamps are preserved, so baseline prices can
precede the requested window by several hours. The complete result is sorted
including these initialization events.

Events before the requested start are **warmup**, counted in the manifest. This
is a selective warmup: sessions that ended before the window are not replayed.
Consequently, historical statistics describe the selected replay, not all earlier
activity in the generated day. The dashboard should distinguish warmup from the
requested viewing window and display the statistics' coverage. Session starts
in the visible window remain distinct from starts sent during warmup.

The 09:00 example correctly restores 115 already-active sessions; it does not
claim those sessions began at 09:00. At the exclusive 13:00 cutoff, 157 sessions
remain active. These are valid current states, not missing synthetic end events.

## Results on the accepted Task 1 data

| Measure | Full source | 09:00–13:00 with warmup |
|---|---:|---:|
| Price messages (including initialization) | 4,320 | 1,296 |
| Start events | 4,021 | 1,269 |
| Meter events | 121,800 | 36,128 |
| End events | 4,021 | 1,112 |
| Total prepared events | 134,162 | 39,805 |
| Events before viewing-window start | 0 | 3,390 |
| Active sessions after final selected event | 0 | 157 |

Of the 10,368 original hourly prices, 6,048 consecutive unchanged observations
are omitted in the full event stream. The window has 1,154 starts inside the
viewing window plus 115 start events in warmup.

At the assignment's minimum 0.1-second publication interval, spacing alone would
take approximately 3 h 44 min for full mode, or 66 min 20 s for this window.
Actual MQTT acknowledgement/retry overhead can add time. Neither file has been
published. A shorter time range can be prepared for live demonstrations; FAQ Q5
does not require full replay.

## Checks and next integration step

Eleven new tests cover per-configuration prices, return-to-old-price changes,
same-time connector handoff, no future-result leakage, unplug semantics, window
warmup/open tails, an empty-session window, deterministic identities, timezones,
invalid mappings, duplicate/missing records, non-finite values and JSON output.
Together with the existing suite, 36 tests passed.

The finalized handoff to Task 3/4 covers:

1. Required charger_id for prices, and configuration-scoped price topics/state.
2. The corrected same-time ordering.
3. New dataset_id/sequence fields and replay/run isolation.
4. Warmup handling and the scope of historical metrics.
5. Broker, QoS, retained-message policy and topic prefix.

`publisher.py` reads the event file, publishes in sequence with
at least 0.1 seconds between messages, and saves acknowledgements/failures. Only
the stream actually published should be labelled as published in the final
submission; a prepared file or passing offline validation is not evidence of
MQTT delivery.
