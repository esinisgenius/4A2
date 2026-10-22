# Task 1: generated data and validation

Task 1 is complete on `feature/task1-generation`, based on P0 commit
`d05d69e2bab20c0e569a0220f6ba4f4b15eb0fda`. This document records the completed
run; the original README and P0 handoff remain unchanged historical documents.
All existing P0 files, including the teacher generator, prepared inputs,
metadata database, event schema and MQTT topic proposals, are unchanged.

## Actual results

| Measure | Observed |
|---|---:|
| Generator input DC configurations | 432 |
| Candidate physical stations represented | 414 |
| Simulated connectors from input plug counts | 1,656 |
| Complete AEMO five-minute intervals | 288 |
| Hourly prices | 10,368 |
| Charging sessions | 4,021 |
| Urban / regional sessions | 2,718 / 1,303 |
| Minute meter readings | 121,800 |
| Sessions ending after the generation day | 29 |
| Minimum / maximum retail price (AUD/kWh) | 0.40 / 0.92 |

The actual 4,021 sessions are reported unchanged. The handoff's 4,266 figure is
a nominal connector/rate calculation before stochastic variation, price response
and occupancy effects, not an exact acceptance count. The last unplug event is
`2026-09-16T01:15:41` in the generator's raw time representation.

## Run and reproduce

Use the repository's existing `requirements.txt` for the complete test suite.
The Task 1 runner, validator and teacher generator use only the Python standard
library. This run used CPython 3.12.7 on Windows.

From the repository root, with the project environment activated:

```powershell
python -m pip install -r requirements.txt
python src/run_task1.py
python src/validate_task1.py
python -m unittest discover -s tests -v
```

`run_task1.py` verifies the AEMO cache before invoking the unchanged teacher
script. It downloads the source only if the cache is absent, and stops if the
required day is incomplete. It sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`
for consistent handling of the teacher's default text-file encoding on Windows.
Re-running it regenerates only Task 1 outputs and run/validation records.

Each run replaces previous report statuses before checking inputs. The run report
records `RUNNING`, `PASS` or `FAIL`, together with the stage and UTC timestamps.
On failure, it records the error; output validation is `NOT_RUN` if generation
was not completed, or `FAIL` if the output check failed. All three reports share
the current `started_utc`, so a successful preflight belongs to this run even if
a later step fails. A failed run exits nonzero and must not be used for handoff.

The generator invocation is exactly the handoff's date, duration, seed and rates:

```text
python vendor/data_generator/generate_dataset.py --stations data/input/stations.csv --start 2026-09-15 --days 1 --out data/generated --seed 5339 --sessions-per-connector-day 3 2
```

All other generator options retain their defaults, including dynamic pricing,
`NSW1`, and one-minute meter readings. Static prices were not used. An independent
second execution, using a separate output folder and the same AEMO bytes, produced
identical SHA-256 hashes for all four output CSVs; see `task1_reproducibility.json`.

## Preserved outputs and provenance

| File | Purpose |
|---|---|
| `data/generated/stations.csv` | Unmodified generator output with assigned base prices |
| `data/generated/prices_hourly.csv` | All hourly prices, including consecutive equal prices |
| `data/generated/sessions.csv` | Complete sessions, including those ending next day |
| `data/generated/session_metering.csv` | Raw time-ordered meter telemetry |
| `data/generated/aemo_cache/PRICE_AND_DEMAND_202609_NSW1.csv` | Original downloaded monthly AEMO bytes |
| `logs/task1_generation.log` | Exact command, stdout and stderr |
| `docs/task1_run.json` | Parameters, runtime, timestamps and input/output/log hashes |
| `docs/task1_aemo_validation.json` | Pre-generation source coverage check |
| `docs/task1_validation.json` | Complete output validation, counts and hashes |
| `docs/task1_reproducibility.json` | Independent second-run comparison |

The source was retrieved from the official [AEMO September 2026 NSW1 CSV](https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_202609_NSW1.csv).
It contains 8,640 monthly rows. The source SHA-256 is
`85af3e1f68823c3eef87fcc98e5fa605c609b568ec64d6ef36b96722f8db8cd0`.

The inherited `.gitignore` excludes logs and the download cache. The specific
Task 1 log and source CSV are intentionally included with `git add -f`; the
shared ignore rules are unchanged. A new, narrowly scoped `.gitattributes`
preserves the exact bytes of Task 1 data and its log when checking out on another
platform, so Git line-ending conversion cannot invalidate their recorded hashes.

## Validation performed

- All 288 distinct NSW1 `TRADE` intervals are present, from period end
  `2026-09-15 00:05` through `2026-09-16 00:00`, inclusive. Hourly wholesale prices
  use the average of the twelve five-minute intervals after shifting the
  period-ending timestamps back by five minutes.
- Every generator input maps to the expected A1 charger and a valid prepared
  physical station. Generated station attributes match the supplied input.
- There are exactly 24 unique hourly prices per configuration. Every wholesale
  price matches AEMO and every retail price matches the teacher's default dynamic
  formula, evening adjustment, bounds and rounding.
- Session IDs are nonempty and unique. Station/connector references are valid;
  a connector has no overlapping sessions. Durations, energy, power, start tariff
  and cost are checked, with explicit tolerance for rounded energy and cost.
- Every meter references the correct session, charger and connector. Each session
  has one reading per charging minute, ordered without gaps or duplicates.
  Energy and state of charge are nondecreasing; timestamps lie within charging
  intervals; the final reading matches charging duration and session energy.
- Meter energy is rounded to three decimal places, while session energy is rounded
  to two. The maximum allowed discrepancy is 0.0055 kWh plus numerical epsilon.
- Meter power is checked against voltage times current, and each minute's energy
  increment against power divided by 60. Session mean and peak power are checked
  against energy/duration and the maximum meter power. Tolerances account for the
  teacher's rounding of V/I to 0.1, power to 0.01, and session mean/peak to 0.1.

The four inherited tests and twenty-one Task 1 tests all pass (25 total). The
tests include missing/duplicate AEMO intervals, duplicate prices, incorrect
wholesale values, bad ID mappings, overlapping sessions, incorrect meter
identities, missing meter minutes and decreasing energy. Valid rounding and
sessions crossing midnight are accepted. Five tests exercise successful runs
followed by download, preflight, generator exit, process launch or output-validation
failures. Four additional negative cases check the electrical and power/energy
relationships. A full post-fix run produced the same four CSV files byte for byte;
metadata database and generator-input checks also passed. See
`task1_fix_verification.json` for the post-fix evidence and `task1_review.md` for the
plain-language review. The older `task1_review_evidence.json` records the original,
pre-fix findings. `task1_final_check.json` records the subsequent full review,
including isolated regeneration and independent SQL checks with zero errors.
These checks validate the generated
handoff; they do not establish that synthetic behaviour reflects real chargers.

## Notes for the Task 2 owner

1. Generator `station_id` is the A1 configuration-level `charger_id`, not the
   physical site ID. Join through `data/processed/generator_station_mapping.csv`.
   Its 432 configurations represent 414 physical stations. Keep tariffs scoped
   to their configuration until a station-level display rule is agreed.
2. Raw timestamps are naive strings on the NEM market clock. Interpret them as
   AEST (UTC+10), not UTC. AEMO identifies NEM time as AEST without daylight
   saving in its [official time convention](https://www.aemo.com.au/-/media/files/electricity/nem/planning_and_forecasting/nem_esoo/2019/2019-electricity-statement-of-opportunities.pdf).
   On this September date, this also matches Sydney local time. If emitting UTC,
   attach the UTC+10 offset before conversion; do not simply append `Z`.
3. Price and session CSVs are not one globally ordered stream. Merge prices,
   starts, meters and ends by event time when implementing the Publisher, then
   suppress consecutive unchanged prices at the agreed pricing scope.
4. `charge_end_ts` is when charging finishes; `end_ts` is unplug time, including
   an idle tail. The teacher's session cost uses the price at session start.
   Preserve all 29 cross-midnight sessions and their final events when replaying.
5. Connector IDs are local 1-based numbers within each configuration. They are
   synthetic instances based on reported plug counts, not verified physical
   equipment IDs. The P0 connector-type evidence remains station-level.

The original teacher outputs are preserved as CSVs. MQTT conversion and publishing,
Subscriber behaviour, the dashboard and event persistence remain later tasks.
