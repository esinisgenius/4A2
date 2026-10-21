# Teacher Generator Audit

## Confirmed input contract

`vendor/data_generator/generate_dataset.py` reads a CSV with exactly these fields:

| Field | Parsed type | Constraint used by generator |
|---|---|---|
| `station_id` | string | Used in every output and session ID |
| `name` | string | Passed through to generated stations output |
| `lat` | float | Passed through |
| `lon` | float | Passed through |
| `site_type` | string | Exact `urban` uses urban rate/profile; every other value is treated as regional |
| `connectors` | integer | Creates connector IDs `1..connectors` |
| `max_kw` | float | Limits charging power and selects base-price range |

## Confirmed CLI

Important options are `--stations`, `--start`, `--days`, `--region`, `--out`, `--seed`, `--sessions-per-connector-day URBAN REGIONAL`, `--meter-every`, and `--static-prices`. The generator uses Python's standard library only.

Without `--static-prices`, it downloads monthly AEMO `PRICE_AND_DEMAND` CSV files for the requested region and caches them below the output directory. This network dependency belongs to Task 1 and was not invoked during P0.

## Confirmed outputs

- `stations.csv`: input fields plus generated `base_price`.
- `prices_hourly.csv`: `ts,station_id,price_per_kwh,wholesale_per_kwh`.
- `sessions.csv`: session identity, station/connector, vehicle, timing, energy, power, price, and cost.
- `session_metering.csv`: ordered minute-level voltage, current, power, cumulative energy, and state of charge.

## Prepared A2 input

`data/input/stations.csv` contains 432 DC configuration rows. Its `station_id` is the stable A1 `charger_id`; `data/processed/generator_station_mapping.csv` maps it to the physical station. One unsupported unitless DC rating is excluded and documented.

For one day the input yields exactly 10,368 hourly-price rows. With `--sessions-per-connector-day 3 2`, the connector-rate product is 4,266 sessions before stochastic variation and occupied-connector rejection. No simulation was run during P0.
