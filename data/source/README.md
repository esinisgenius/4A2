# Retained A1 Sources

- `ev_charging_locations_nsw_20251216.csv`: official TfNSW December 2025 source snapshot.
- `chargers_clean_a1.csv`: validated A1 configuration-grain metadata without SA4 columns.
- `sites_a1.csv`: conservative A1 physical-site candidates.
- `site_chargers_a1.csv`: one-to-one charger-to-site mapping.
- `power_components_a1.csv`: parsed components for compound power expressions.
- `ocm_matches_a1.csv` and `chargealong_matches_a1.csv`: previously generated A1 matching outcomes used only to retain accepted connector-type evidence.

These files are included so P0 preparation is reproducible without rerunning A1 spatial processing or refreshing external augmentation data. Their SHA-256 hashes are loaded into the `source_files` table of `database/charger_metadata.duckdb`.
