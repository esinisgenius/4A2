"""Prepare validated A1 charger metadata for A2 without generating events."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/source"
PROCESSED = ROOT / "data/processed"
DATABASE = ROOT / "database/charger_metadata.duckdb"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def normalise_connectors(value: object) -> list[str]:
    aliases = {
        "ccs (type 2)": "CCS2",
        "ccs2": "CCS2",
        "chademo": "CHAdeMO",
    }
    result = []
    for item in text(value).replace("; ", ";").split(";"):
        if item.strip():
            result.append(aliases.get(item.strip().casefold(), item.strip()))
    return sorted(set(result))


def connector_evidence(ocm: pd.DataFrame, chargealong: pd.DataFrame) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for frame, source in ((ocm, "Open Charge Map"), (chargealong, "ChargeAlong")):
        for row in frame.itertuples(index=False):
            if text(row.status) != "matched":
                continue
            connectors = normalise_connectors(row.connector_types)
            if connectors:
                evidence[row.site_id] = {
                    "connector_types": "|".join(connectors),
                    "connector_evidence_source": source,
                    "connector_evidence_status": "verified_a1_match",
                }
    return evidence


def prepare() -> dict[str, int | float | str]:
    chargers = pd.read_csv(SOURCE / "chargers_clean_a1.csv", keep_default_na=False)
    sites = pd.read_csv(SOURCE / "sites_a1.csv", keep_default_na=False)
    mapping = pd.read_csv(SOURCE / "site_chargers_a1.csv", keep_default_na=False)
    components = pd.read_csv(SOURCE / "power_components_a1.csv", keep_default_na=False)
    ocm = pd.read_csv(SOURCE / "ocm_matches_a1.csv", keep_default_na=False)
    chargealong = pd.read_csv(SOURCE / "chargealong_matches_a1.csv", keep_default_na=False)
    aliases = pd.read_csv(ROOT / "config/operator_aliases.csv", keep_default_na=False)

    if not chargers.charger_id.is_unique or not sites.site_id.is_unique:
        raise ValueError("A1 charger_id and site_id values must be unique")
    if not mapping.charger_id.is_unique or set(mapping.charger_id) != set(chargers.charger_id):
        raise ValueError("Every charger must map to exactly one site")
    if not set(mapping.site_id).issubset(set(sites.site_id)):
        raise ValueError("Charger mapping refers to an unknown site")

    alias_lookup = dict(zip(aliases.operator_original, aliases.operator_standard))
    chargers["operator_original"] = chargers.operator_name.map(text)
    chargers["operator_standard"] = chargers.operator_original.map(lambda value: alias_lookup.get(value, value))
    chargers = chargers.merge(mapping, on="charger_id", validate="one_to_one")

    component_min = (components.assign(component_power_kw=pd.to_numeric(components.component_power_kw))
                     .groupby("charger_id").component_power_kw.min().to_dict())

    effective_power = []
    power_rule = []
    for row in chargers.itertuples(index=False):
        source_power = pd.to_numeric(row.power_kw, errors="coerce")
        if pd.notna(source_power) and source_power > 0:
            effective_power.append(float(source_power))
            power_rule.append("a1_single_explicit_kw")
        elif row.charger_id in component_min:
            effective_power.append(float(component_min[row.charger_id]))
            power_rule.append("a1_compound_lower_bound_kw")
        elif text(row.charger_type) == "AC" and text(row.power_parse_status) == "type_label_only":
            effective_power.append(11.0)
            power_rule.append("a2_ac_label_default_11kw")
        else:
            effective_power.append(pd.NA)
            power_rule.append("unresolved_no_supported_power")
    chargers["effective_power_kw"] = pd.array(effective_power, dtype="Float64")
    chargers["power_rule"] = power_rule

    evidence = connector_evidence(ocm, chargealong)
    station_operators = (chargers.groupby("site_id").agg(
        operator_names_original=("operator_original", lambda values: "|".join(sorted(set(filter(None, values))))),
        operator_names_standard=("operator_standard", lambda values: "|".join(sorted(set(filter(None, values))))),
    ).reset_index())
    sites = sites.merge(station_operators, on="site_id", how="left", validate="one_to_one")
    sites["station_id"] = sites.site_id
    sites["station_name_original"] = sites.station_name.map(text)
    sites["station_name"] = sites.station_name_original
    missing_names = sites.station_name.eq("")
    primary_operator = sites.operator_names_standard.fillna("").str.split("|").str[0].replace("", "NSW EV")
    sites.loc[missing_names, "station_name"] = (
        primary_operator[missing_names] + " Station " + sites.loc[missing_names, "station_id"].str[-8:]
    )
    sites["station_name_source"] = "a1_source"
    sites.loc[missing_names, "station_name_source"] = "a2_deterministic_fallback"
    sites["connector_types"] = sites.site_id.map(lambda value: evidence.get(value, {}).get("connector_types", ""))
    sites["connector_evidence_source"] = sites.site_id.map(
        lambda value: evidence.get(value, {}).get("connector_evidence_source", "")
    )
    sites["connector_evidence_status"] = sites.site_id.map(
        lambda value: evidence.get(value, {}).get("connector_evidence_status", "not_verified_in_a1")
    )

    connector_lookup = sites.set_index("site_id")[
        ["connector_types", "connector_evidence_status"]
    ].to_dict("index")
    chargers["connector_types"] = chargers.site_id.map(lambda value: connector_lookup[value]["connector_types"])
    chargers["connector_evidence_status"] = chargers.site_id.map(
        lambda value: connector_lookup[value]["connector_evidence_status"]
    )

    stations_out = sites[[
        "station_id", "station_name", "station_name_original", "station_name_source",
        "station_address", "latitude", "longitude", "operator_names_original",
        "operator_names_standard", "configuration_count", "dc_configuration_count",
        "connector_types", "connector_evidence_source", "connector_evidence_status",
    ]].rename(columns={"station_address": "address"})
    chargers_out = chargers[[
        "charger_id", "site_id", "operator_original", "operator_standard", "charger_type",
        "operational_status", "number_of_plugs", "power_kw", "effective_power_kw", "power_rule",
        "raw_Charger_rating", "power_parse_status", "connector_types",
        "connector_evidence_status", "quality_flags",
    ]].rename(columns={"site_id": "station_id", "power_kw": "source_power_kw",
                       "raw_Charger_rating": "source_power_rating"})
    for column in ("latitude", "longitude", "configuration_count", "dc_configuration_count"):
        stations_out[column] = pd.to_numeric(stations_out[column], errors="raise")
    chargers_out["number_of_plugs"] = pd.to_numeric(chargers_out.number_of_plugs, errors="raise")
    chargers_out["source_power_kw"] = pd.to_numeric(chargers_out.source_power_kw, errors="coerce")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    stations_path = PROCESSED / "stations_prepared.csv"
    chargers_path = PROCESSED / "chargers_prepared.csv"
    stations_out.to_csv(stations_path, index=False)
    chargers_out.to_csv(chargers_path, index=False)

    if DATABASE.exists():
        DATABASE.unlink()
    con = duckdb.connect(str(DATABASE))
    try:
        con.execute((ROOT / "database/schema.sql").read_text(encoding="utf-8"))
        con.register("stations_df", stations_out)
        con.register("chargers_df", chargers_out)
        con.register("aliases_df", aliases)
        con.execute("INSERT INTO stations SELECT * FROM stations_df")
        con.execute("INSERT INTO chargers SELECT * FROM chargers_df")
        con.execute("INSERT INTO operator_aliases SELECT * FROM aliases_df")
        connector_rows = []
        for row in stations_out.itertuples(index=False):
            for connector in text(row.connector_types).split("|"):
                if connector:
                    connector_rows.append((row.station_id, connector, row.connector_evidence_source))
        if connector_rows:
            con.executemany("INSERT INTO station_connector_types VALUES (?, ?, ?)", connector_rows)
        source_rows = [(path.name, sha256(path)) for path in sorted(SOURCE.glob("*")) if path.is_file()]
        con.executemany("INSERT INTO source_files VALUES (?, ?)", source_rows)
        con.execute("CHECKPOINT")
    finally:
        con.close()

    stats = {
        "stations": len(stations_out),
        "chargers": len(chargers_out),
        "dc_chargers": int(chargers_out.charger_type.eq("DC").sum()),
        "synthetic_station_names": int(missing_names.sum()),
        "operator_alias_rows_changed": int((chargers.operator_original != chargers.operator_standard).sum()),
        "chargers_with_effective_power": int(chargers_out.effective_power_kw.notna().sum()),
        "chargers_without_effective_power": int(chargers_out.effective_power_kw.isna().sum()),
        "stations_with_verified_connector_types": int(stations_out.connector_types.ne("").sum()),
        "database": DATABASE.relative_to(ROOT).as_posix(),
    }
    (PROCESSED / "preparation_summary.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
