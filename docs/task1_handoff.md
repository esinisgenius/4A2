# Task 1 Handoff

## Current status

P0 is complete. Task 1 synthetic generation has **not** been run. There is no `data/generated/` directory, AEMO cache, generated price data, session data, or meter data in the current handoff.

## Inputs

- Generator input: `data/input/stations.csv`
- Generator-to-metadata mapping: `data/processed/generator_station_mapping.csv`
- Input exclusions: `data/processed/generator_input_exclusions.csv`
- Input summary: `data/processed/generator_input_summary.json`
- Prepared physical stations: `data/processed/stations_prepared.csv`
- Prepared chargers: `data/processed/chargers_prepared.csv`
- Teacher generator: `vendor/data_generator/generate_dataset.py`
- Teacher demo input: `vendor/data_generator/demo_stations.csv`
- Teacher generator notes: `vendor/data_generator/README.md`

`stations.csv` has the confirmed teacher schema:

```text
station_id,name,lat,lon,site_type,connectors,max_kw
```

It contains 432 validated DC configurations and 1,656 connectors. Generator `station_id` is the stable A1 `charger_id`; use the mapping CSV to recover the physical station ID. One DC configuration with an unsupported unitless power rating is excluded and documented.

## Recommended generation command

The agreed start date is `2026-09-15`, duration is one day, output directory is `data/generated/`, and random seed is fixed at `5339`:

```bash
mkdir -p logs
python vendor/data_generator/generate_dataset.py \
  --stations data/input/stations.csv \
  --start 2026-09-15 \
  --days 1 \
  --out data/generated \
  --seed 5339 \
  --sessions-per-connector-day 3 2 \
  2>&1 | tee logs/task1_generation.log
```

Before running, verify that the official AEMO file `PRICE_AND_DEMAND_202609_NSW1.csv` is available and contains all 288 five-minute NSW1 periods needed for 15 September 2026. The earlier availability check was interrupted, so availability is not confirmed in this handoff. If it is incomplete, report the reason and propose another date; do not silently switch dates.

The generator also supports `--region`, `--meter-every`, pricing bounds, elasticity, and `--static-prices`. Keep their defaults unless the team records a deliberate change. Do not use `--static-prices` if the submission is intended to demonstrate AEMO-driven dynamic prices.

## Expected scale

- Hourly prices: exactly `432 × 24 = 10,368` for one complete day.
- Charging sessions: approximately 4,266 from the connector/rate calculation using urban/regional rates `3 2`.
- The session value is an estimate only. Poisson sampling and occupied-connector rejection determine the actual result.

The assignment target is at least 10,000 hourly prices and approximately 4,000 charging sessions; 3,900 sessions is acceptable. Record actual counts after generation and do not alter the prepared input merely to force a target.

## Files to preserve and submit

Generator inputs and provenance:

- `data/input/stations.csv`
- `data/processed/generator_station_mapping.csv`
- Teacher generator and demo files under `vendor/data_generator/`
- Exact command, fixed seed, AEMO source/cache, and generation log

Expected generator outputs under `data/generated/`:

- `stations.csv` with generated base prices
- `prices_hourly.csv`
- `sessions.csv`
- `session_metering.csv`
- `aemo_cache/PRICE_AND_DEMAND_202609_NSW1.csv`

Later tasks must additionally preserve the MQTT JSON event files and Subscriber-side DuckDB, but those are outside Task 1 and have not been implemented.

## Task 1 acceptance checks

1. Confirm AEMO data covers the full requested day before generation.
2. Save the exact command, seed, stdout/stderr log, and all raw generator outputs.
3. Confirm `prices_hourly.csv` has 10,368 rows, unique `(ts, station_id)` pairs, 24 timestamps per input row, and no orphan station IDs.
4. Confirm the actual session count is near 4,000 and report it without changing expected values.
5. Require unique, nonempty `session_id` values and valid station IDs.
6. Require each `connector_id` to be an integer from 1 through that input row's `connectors` value.
7. Require `start_ts <= charge_end_ts <= end_ts`, positive duration/energy, and nonnegative cost and power.
8. Require every meter row to reference an existing session and matching station/connector.
9. Within each session, require meter timestamps and cumulative `energy_kwh` to be nondecreasing and bounded by the session interval/final energy, allowing only documented rounding tolerance.
10. Use `generator_station_mapping.csv` before constructing later MQTT events so physical `station_id` and A1 `charger_id` are not conflated.
11. Do not publish MQTT events or build the Subscriber in Task 1.

## Important identifier note

The generator has only one equipment identifier level. Its `station_id` equals A1 `charger_id` in this adapter, and its `connector_id` is a 1-based local number for that configuration. Later event conversion must use the mapping file to emit both the physical station ID and charger ID defined by the P0 interface contract.
