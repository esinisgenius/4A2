# Event contract 1.0

Finalized by the Task 2 owner on 2026-10-27 for Task 3/4 integration. This replaces
the P0 proposal; it does not assert that teammates have already integrated it.
Examples are in `task2_event_examples.json`; the publisher adds `run_id` to every
prepared payload. Each MQTT payload is one flat UTF-8 JSON object, not a wrapper.

## Common fields (required for all four event types)

| Field | JSON type | Meaning |
|---|---|---|
| schema_version | string | `1.0` |
| dataset_id | string | `ds_` plus SHA-256 of canonical source records |
| event_id | string | `evt_` plus SHA-256 of semantic event, excluding sequence/run_id |
| run_id | string | Replay namespace supplied by Publisher; unique for each new demo |
| sequence | integer | One-based position in this prepared stream; preserved on retry/resume |
| event_type | string | `price_update`, `session_start`, `meter`, `session_end` |
| event_time | string | UTC timestamp, `YYYY-MM-DDTHH:MM:SSZ` |
| station_id | string | Physical site ID; joins `stations.station_id` |
| charger_id | string | A1 configuration ID; joins `chargers.charger_id`; required for prices too |

All three session event types additionally require `session_id` (string) and
`connector_id` (positive integer encoded as a string, local to charger_id).
Generator `station_id` is mapped to A1 `charger_id` through
`data/processed/generator_station_mapping.csv`. A charger is a configuration,
not necessarily a single physical socket. P0 connector-type evidence remains
station-level; simulated connector numbers do not identify real sockets.

## Type-specific fields (required)

| Type | Fields |
|---|---|
| price_update | `price_per_kwh` number, `currency="AUD"`, `price_unit="AUD/kWh"` |
| session_start | `price_per_kwh` number (locked start tariff), `currency="AUD"`, `vehicle_model` string, `site_type` string |
| meter | `voltage_v`, `current_a`, `power_kw`, `energy_kwh`, `soc_pct` (all numbers) |
| session_end | `energy_kwh`, `charge_minutes`, `avg_kw`, `peak_kw`, `price_per_kwh`, `cost_aud` (numbers), `currency="AUD"`, `charge_end_time` (UTC string) |

Meter energy is cumulative within the session; power is instantaneous. The end
event occurs at unplug time (`end_ts`), while `charge_end_time` indicates charging
completion. Charging minutes exclude idle time before unplugging. Session cost
uses the generator's start tariff; do not recalculate it from later price updates.
Source rounding is preserved. Start messages contain no future final results.

## Ordering, identity and replay

Source times are NEM fixed AEST (UTC+10), including months when Sydney observes
daylight saving. Events are sorted by UTC time, then
`price_update < meter < session_end < session_start`, then event_id. In this data
the first meter is one minute after start; this rule handles a final meter, old
session end and replacement session start at the same timestamp correctly.

The first known price initializes each configuration; only subsequent actual
changes are emitted. A return to an earlier price is a new change. Never dedupe
prices across different configurations at one physical site.

Deduplicate incoming messages by **(run_id, event_id)** before updating any counts
or state. Session keys are **(run_id, session_id)** and active connector keys are
**(run_id, charger_id, connector_id)**. Latest-price keys are **(run_id, charger_id)**.
Event IDs are stable across windows but sequence numbers can change. Each new
replay needs a new run_id; a resume reuses its original run_id. Do not mix runs
into one dashboard state or sum their sessions as if they were different days.

The publisher uses QoS 1. A broker acknowledgement proves broker acceptance,
not subscriber persistence. Duplicate packets are possible after lost ACKs or a
crash before checkpointing. A restarted subscriber needs its persisted state or
a fresh full replay under a new run_id; messages are not retained.

Window initialization preserves original timestamps and includes earlier starts,
meters and prices needed for state. Historical metrics cover the selected replay,
not all activity before its viewing window. Open sessions at the exclusive end
stay open. See `task2_events.md` and the selected preparation manifest.
