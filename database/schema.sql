CREATE TABLE stations (
    station_id VARCHAR PRIMARY KEY,
    station_name VARCHAR NOT NULL,
    station_name_original VARCHAR,
    station_name_source VARCHAR NOT NULL,
    address VARCHAR NOT NULL,
    latitude DOUBLE NOT NULL,
    longitude DOUBLE NOT NULL,
    operator_names_original VARCHAR NOT NULL,
    operator_names_standard VARCHAR NOT NULL,
    configuration_count INTEGER NOT NULL,
    dc_configuration_count INTEGER NOT NULL,
    connector_types VARCHAR,
    connector_evidence_source VARCHAR,
    connector_evidence_status VARCHAR NOT NULL
);

CREATE TABLE chargers (
    charger_id VARCHAR PRIMARY KEY,
    station_id VARCHAR NOT NULL REFERENCES stations(station_id),
    operator_original VARCHAR NOT NULL,
    operator_standard VARCHAR NOT NULL,
    charger_type VARCHAR,
    operational_status VARCHAR NOT NULL,
    number_of_plugs INTEGER NOT NULL,
    source_power_kw DOUBLE,
    effective_power_kw DOUBLE,
    power_rule VARCHAR NOT NULL,
    source_power_rating VARCHAR,
    power_parse_status VARCHAR NOT NULL,
    connector_types VARCHAR,
    connector_evidence_status VARCHAR NOT NULL,
    quality_flags VARCHAR
);

CREATE TABLE operator_aliases (
    operator_original VARCHAR PRIMARY KEY,
    operator_standard VARCHAR NOT NULL,
    reason VARCHAR NOT NULL
);

CREATE TABLE station_connector_types (
    station_id VARCHAR NOT NULL REFERENCES stations(station_id),
    connector_type VARCHAR NOT NULL,
    evidence_source VARCHAR NOT NULL,
    PRIMARY KEY (station_id, connector_type)
);

CREATE TABLE source_files (
    file_name VARCHAR PRIMARY KEY,
    sha256 VARCHAR NOT NULL
);

CREATE INDEX idx_chargers_station ON chargers(station_id);
CREATE INDEX idx_chargers_operator ON chargers(operator_standard);
