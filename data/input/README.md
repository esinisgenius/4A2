# Generator Input

`stations.csv` is the validated input for the teacher-provided `generate_dataset.py`.

Its exact columns are:

```text
station_id,name,lat,lon,site_type,connectors,max_kw
```

The generator exposes only one station identifier, so this file uses the A1 configuration-grain `charger_id` as `station_id`. This preserves each configuration's own power rating and plug count. Use `data/processed/generator_station_mapping.csv` to recover both the physical A2 `station_id` and `charger_id` after generation.

The file contains 432 usable DC configurations. One DC configuration with the unitless rating `50` is excluded rather than assuming kW; see `data/processed/generator_input_exclusions.csv`.
