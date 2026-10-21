# Proposed Event Contract

This is a P0 event design, not a claim about a teacher-mandated JSON schema. The generator CSV fields are now confirmed, but the four MQTT JSON envelopes remain **PROPOSED** because the generator does not define MQTT messages.

## Common envelope

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `event_type` | string enum | yes | `price_update`, `session_start`, `meter`, or `session_end` |
| `event_id` | string | yes | Unique idempotency key for the published event |
| `event_time` | RFC 3339 UTC string | yes | Time represented by the synthetic dataset |
| `station_id` | string | yes | Joins to prepared station metadata |
| `charger_id` | string | conditional | Joins to prepared charger metadata |
| `connector_id` | string | conditional | PROPOSED connector identifier once generator grain is known |
| `session_id` | string | conditional | Required for session and meter events |
| `schema_version` | string | yes | Proposed contract version, initially `1.0` |

## `price_update`

PROPOSED payload: `price_per_kwh` (number, required), `currency` (string, required), and optional tariff metadata. The Publisher should suppress consecutive unchanged prices at the same pricing scope.

## `session_start`

PROPOSED payload: `session_id`, `charger_id`, `connector_id`, and optional starting meter value. It opens one active session. A connector must not have two active sessions simultaneously.

## `meter`

PROPOSED payload: `session_id`, `energy_kwh` (number, required) and optional instantaneous `power_kw`. Cumulative energy must not decrease within a session.

## `session_end`

PROPOSED payload: `session_id`, final `energy_kwh`, and optional duration/cost fields. It closes the active session.

## Ordering

Events are ordered by `event_time`. For equal timestamps the proposed precedence is `price_update`, `session_start`, `meter`, then `session_end`; ties within one type use `event_id`. The final rule must be reconciled with generator output. Subscriber persistence should still use `event_id` idempotently and tolerate duplicate delivery.

## Metadata joins

The generator emits its input `station_id`, which equals A1 `charger_id` in the prepared adapter. The Publisher must use `generator_station_mapping.csv` to emit the physical `station_id` and `charger_id`. Generator `connector_id` is a 1-based integer within that charger configuration. Connector-type evidence in P0 remains station-level and must not be presented as a physical connector inventory.

## DuckDB direction

Task 4 should retain immutable historical events in an append-oriented event table and maintain derived current-state tables or views for latest price, active sessions, connector occupancy, and latest meter reading. Historical views can calculate hourly average price, session counts, energy, and duration. This is design only; event tables are not created in P0.
