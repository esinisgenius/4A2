# A1 to A2 Data Mapping

## Grain and identifiers

| A2 concept | A1 source | Status | Definition |
|---|---|---|---|
| `station_id` | `data/source/sites_a1.csv.site_id` | Retained | Conservative candidate physical site from A1 site resolution. |
| `charger_id` | `data/source/chargers_clean_a1.csv.charger_id` | Retained | Stable A1 source configuration identifier; not a physical connector ID. |
| `connector_id` | None | PROPOSED | Future generator/event identifier. A1 only supplies plug counts and some station-level connector types. |
| `session_id` | Generator output | PROPOSED | Future charging-session identifier; unavailable during P0. |

The generator's column named `station_id` uses A1 `charger_id` in `data/input/stations.csv`. This is a deliberate adapter because the generator has only one equipment level. `data/processed/generator_station_mapping.csv` maps that value back to both the physical station and charger configuration.

Every charger maps to exactly one station through `data/source/site_chargers_a1.csv`. A station may contain one or more charger configurations. No physical connector instances are fabricated in P0.

## Prepared attributes

- Coordinates, addresses, original station names, charger types, plug counts, and source ratings come from validated A1 artifacts.
- `operator_original` preserves A1 text. `operator_standard` applies `config/operator_aliases.csv`.
- Missing station names receive `"<standard operator> Station <station suffix>"` and are marked `a2_deterministic_fallback`.
- `effective_power_kw` uses an explicit A1 kW value first, the lower A1 compound component second, and 11 kW only for an AC-only label with no numeric rating. Unsupported unitless or unknown ratings remain missing.
- Connector types are retained only from A1 matches accepted as verified. OCM `CCS (Type 2)` and ChargeAlong `ccs2` map to `CCS2`; case variants of CHAdeMO map to `CHAdeMO`.

## Included source files

`data/source/` contains the official TfNSW snapshot plus the minimal validated A1 derivatives needed to reproduce P0. The preparation script records SHA-256 hashes for every included source file in `database/charger_metadata.duckdb.source_files`.

ABS SA4 boundaries and spatial outputs were intentionally removed because A2 requires charger locations, not SA4 analysis. Latitude and longitude remain available directly from the A1 charger/site metadata.
