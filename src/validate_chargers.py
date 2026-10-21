"""Validate the A2 P0 station and charger metadata outputs."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def validate() -> dict:
    stations = pd.read_csv(ROOT / "data/processed/stations_prepared.csv", keep_default_na=False)
    chargers = pd.read_csv(ROOT / "data/processed/chargers_prepared.csv", keep_default_na=False)
    checks: list[dict[str, object]] = []

    def check(name: str, condition: bool, observed: object) -> None:
        checks.append({"check": name, "status": "PASS" if condition else "FAIL", "observed": observed})

    check("station_id_unique", stations.station_id.is_unique and stations.station_id.ne("").all(), stations.station_id.nunique())
    check("charger_id_unique", chargers.charger_id.is_unique and chargers.charger_id.ne("").all(), chargers.charger_id.nunique())
    check("charger_station_fk", set(chargers.station_id).issubset(set(stations.station_id)), chargers.station_id.nunique())
    check("all_stations_referenced", set(stations.station_id) == set(chargers.station_id), stations.station_id.nunique())
    lat = pd.to_numeric(stations.latitude, errors="coerce")
    lon = pd.to_numeric(stations.longitude, errors="coerce")
    valid_coords = lat.between(-44, -10) & lon.between(110, 160)
    check("coordinates_valid", valid_coords.all(), int(valid_coords.sum()))
    check("station_names_present", stations.station_name.str.strip().ne("").all(), int(stations.station_name.eq("").sum()))
    check("addresses_present", stations.address.str.strip().ne("").all(), int(stations.address.eq("").sum()))
    check("operators_present", chargers.operator_standard.str.strip().ne("").all(), int(chargers.operator_standard.eq("").sum()))
    plugs = pd.to_numeric(chargers.number_of_plugs, errors="coerce")
    check("plug_counts_positive", plugs.notna().all() and plugs.gt(0).all(), int(plugs.isna().sum() + plugs.le(0).sum()))
    power = pd.to_numeric(chargers.effective_power_kw, errors="coerce")
    valid_power = power.isna() | power.between(1, 1000)
    check("effective_power_reasonable", valid_power.all(), int((~valid_power).sum()))
    check("connector_types_only_verified", chargers.loc[chargers.connector_types.ne(""), "connector_evidence_status"].eq("verified_a1_match").all(), int(chargers.connector_types.ne("").sum()))

    con = duckdb.connect(str(ROOT / "database/charger_metadata.duckdb"), read_only=True)
    try:
        db_counts = {
            "stations": con.execute("SELECT COUNT(*) FROM stations").fetchone()[0],
            "chargers": con.execute("SELECT COUNT(*) FROM chargers").fetchone()[0],
            "connector_types": con.execute("SELECT COUNT(*) FROM station_connector_types").fetchone()[0],
        }
    finally:
        con.close()
    check("database_counts_match_csv", db_counts["stations"] == len(stations) and db_counts["chargers"] == len(chargers), db_counts)

    failures = [item for item in checks if item["status"] == "FAIL"]
    result = {
        "result": "PASS" if not failures else "FAIL",
        "stations": len(stations),
        "chargers": len(chargers),
        "dc_chargers": int(chargers.charger_type.eq("DC").sum()),
        "missing_effective_power": int(power.isna().sum()),
        "stations_with_verified_connectors": int(stations.connector_types.ne("").sum()),
        "checks": checks,
    }
    output = ROOT / "docs/p0_validation.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise AssertionError(json.dumps(failures, indent=2))
    return result


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
