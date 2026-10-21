"""Convert validated P0 metadata to the teacher generator's exact station schema."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/input/stations.csv"
MAPPING = ROOT / "data/processed/generator_station_mapping.csv"

# The teacher demo treats Central Coast, Wollongong and Newcastle as urban in
# addition to Greater Sydney. These are existing A1 SA4 labels; no new spatial
# matching is performed for A2.
URBAN_SA4_CODES = {"102", "107", "111", *(str(code) for code in range(115, 129))}
EXPECTED_COLUMNS = ["station_id", "name", "lat", "lon", "site_type", "connectors", "max_kw"]


def prepare() -> dict[str, int | float | str]:
    stations = pd.read_csv(ROOT / "data/processed/stations_prepared.csv", keep_default_na=False)
    chargers = pd.read_csv(ROOT / "data/processed/chargers_prepared.csv", keep_default_na=False)
    a1_sites = pd.read_csv(ROOT / "data/source/sites_a1.csv", keep_default_na=False,
                           dtype={"sa4_code": str})

    station_fields = stations[["station_id", "station_name", "latitude", "longitude"]]
    site_types = a1_sites[["site_id", "sa4_code"]].rename(columns={"site_id": "station_id"})
    joined = (chargers.loc[chargers.charger_type.eq("DC")]
              .merge(station_fields, on="station_id", validate="many_to_one")
              .merge(site_types, on="station_id", validate="many_to_one"))
    joined["effective_power_kw"] = pd.to_numeric(joined.effective_power_kw, errors="coerce")
    joined["number_of_plugs"] = pd.to_numeric(joined.number_of_plugs, errors="raise")

    excluded = joined.loc[joined.effective_power_kw.isna(), [
        "charger_id", "station_id", "source_power_rating", "power_parse_status"
    ]].copy()
    usable = joined.loc[joined.effective_power_kw.notna()].copy()

    generator = pd.DataFrame({
        # The generator has only one identifier level. Configuration-grain
        # charger_id preserves power and connector counts without double counting.
        "station_id": usable.charger_id,
        "name": usable.station_name,
        "lat": pd.to_numeric(usable.latitude, errors="raise"),
        "lon": pd.to_numeric(usable.longitude, errors="raise"),
        "site_type": usable.sa4_code.map(lambda code: "urban" if code in URBAN_SA4_CODES else "regional"),
        "connectors": usable.number_of_plugs.astype(int),
        "max_kw": usable.effective_power_kw.astype(float),
    })
    generator = generator[EXPECTED_COLUMNS].sort_values("station_id").reset_index(drop=True)
    mapping = usable[["charger_id", "station_id"]].rename(columns={
        "charger_id": "generator_station_id",
        "station_id": "physical_station_id",
    }).sort_values("generator_station_id").reset_index(drop=True)
    mapping["charger_id"] = mapping.generator_station_id

    INPUT.parent.mkdir(parents=True, exist_ok=True)
    generator.to_csv(INPUT, index=False)
    mapping.to_csv(MAPPING, index=False)
    excluded.to_csv(ROOT / "data/processed/generator_input_exclusions.csv", index=False)

    urban_connectors = int(generator.loc[generator.site_type.eq("urban"), "connectors"].sum())
    regional_connectors = int(generator.loc[generator.site_type.eq("regional"), "connectors"].sum())
    summary = {
        "generator_input_rows": len(generator),
        "excluded_dc_configurations": len(excluded),
        "urban_rows": int(generator.site_type.eq("urban").sum()),
        "regional_rows": int(generator.site_type.eq("regional").sum()),
        "connectors": int(generator.connectors.sum()),
        "one_day_hourly_price_rows": len(generator) * 24,
        "nominal_sessions_at_3_2_rates": urban_connectors * 3 + regional_connectors * 2,
        "input_path": INPUT.relative_to(ROOT).as_posix(),
        "generator_station_id_semantics": "A1 charger_id; map to physical station with generator_station_mapping.csv",
    }
    (ROOT / "data/processed/generator_input_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
