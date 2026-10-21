# COMP5339 Assignment 2 — EV Charging Data Streaming and Analysis

## Project Status

This repository is an independent A2 copy derived from the validated COMP5339 A1 project. The current scope is **P0 preparation only**: preserve useful A1 charger metadata, fix operator aliases relevant to A2, validate identifiers/coordinates/power attributes, and define proposed interfaces for later streaming work.

Task 1 simulation, MQTT publishing, subscription, dashboarding, and event persistence are not implemented in this P0.

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
│   └── processed/    # reproducible P0 station and charger metadata
├── database/
│   ├── schema.sql
│   └── charger_metadata.duckdb
├── docs/
│   ├── data_mapping.md
│   ├── event_schema.md
│   ├── mqtt_topics.md
│   ├── generator_audit.md
│   ├── task1_handoff.md
│   ├── schema_diagram.md
│   └── p0_validation.*
├── src/
│   ├── acquire_ev_chargers.py
│   ├── prepare_chargers.py
│   └── validate_chargers.py
├── tests/
├── requirements.txt
└── README.md
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

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

The generator has not been executed. For the later Task 1 run, one day yields 10,368 hourly-price rows; `--sessions-per-connector-day 3 2` gives a nominal volume near 4,266 sessions before occupancy effects. The eventual command and actual counts must be recorded when Task 1 is authorized.

The complete handoff for the Task 1 owner is in `docs/task1_handoff.md`. Task 1 has not started in this repository.

## Interface Status

The generator CSV fields documented in `docs/generator_audit.md` are confirmed from its source. Event JSON and MQTT fields in `docs/` remain P0 design proposals where the generator does not prescribe them. No Publisher, Subscriber, dashboard, or event database has been implemented.

## Git Workflow

Clone the repository, update local `main`, and create a feature branch for the assigned task. Recommended branches are `feature/task1-generation`, `feature/task2-publishing`, `feature/task3-dashboard`, and `feature/task4-storage`.

Keep changes within the responsible module where possible. Before changing shared event schemas, charger identifiers, MQTT topics, or database contracts, coordinate with the team. Run the relevant local tests before committing, push the feature branch, and merge through a Pull Request into `main`. Do not force push, rewrite shared history, or allow AI coding tools to modify another member's work or shared interfaces without review.
