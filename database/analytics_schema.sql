BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS mqtt_events (
    run_id VARCHAR NOT NULL,
    event_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL CHECK (schema_version = '1.0'),
    sequence BIGINT NOT NULL CHECK (sequence > 0),
    event_type VARCHAR NOT NULL CHECK (event_type IN
        ('price_update', 'session_start', 'meter', 'session_end')),
    event_time TIMESTAMPTZ NOT NULL,
    station_id VARCHAR NOT NULL REFERENCES stations(station_id),
    charger_id VARCHAR NOT NULL REFERENCES chargers(charger_id),
    session_id VARCHAR,
    connector_id VARCHAR,
    payload JSON NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, event_id),
    UNIQUE (run_id, sequence),
    CHECK (event_type = 'price_update' OR
        (session_id IS NOT NULL AND connector_id IS NOT NULL
         AND regexp_full_match(connector_id, '[1-9][0-9]*')))
);

CREATE TABLE IF NOT EXISTS charger_current_state (
    run_id VARCHAR NOT NULL,
    charger_id VARCHAR NOT NULL REFERENCES chargers(charger_id),
    station_id VARCHAR NOT NULL REFERENCES stations(station_id),
    price_per_kwh DOUBLE NOT NULL,
    currency VARCHAR NOT NULL CHECK (currency = 'AUD'),
    price_unit VARCHAR NOT NULL CHECK (price_unit = 'AUD/kWh'),
    event_time TIMESTAMPTZ NOT NULL,
    last_sequence BIGINT NOT NULL CHECK (last_sequence > 0),
    PRIMARY KEY (run_id, charger_id)
);

CREATE TABLE IF NOT EXISTS charging_sessions (
    run_id VARCHAR NOT NULL,
    session_id VARCHAR NOT NULL,
    station_id VARCHAR NOT NULL REFERENCES stations(station_id),
    charger_id VARCHAR NOT NULL REFERENCES chargers(charger_id),
    connector_id VARCHAR NOT NULL CHECK (regexp_full_match(connector_id, '[1-9][0-9]*')),
    vehicle_model VARCHAR NOT NULL,
    site_type VARCHAR NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    charge_end_time TIMESTAMPTZ,
    status VARCHAR NOT NULL CHECK (status IN ('active', 'completed')),
    price_per_kwh DOUBLE NOT NULL, 
    currency VARCHAR NOT NULL CHECK (currency = 'AUD'),
    energy_kwh DOUBLE, 
    charge_minutes DOUBLE,
    avg_kw DOUBLE,
    peak_kw DOUBLE,
    cost_aud DOUBLE, 
    last_sequence BIGINT NOT NULL CHECK (last_sequence > 0),
    PRIMARY KEY (run_id, session_id),
    CHECK ((status = 'active' AND end_time IS NULL) OR
           (status = 'completed' AND end_time IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS active_connectors (
    run_id VARCHAR NOT NULL,
    charger_id VARCHAR NOT NULL REFERENCES chargers(charger_id),
    connector_id VARCHAR NOT NULL CHECK (regexp_full_match(connector_id, '[1-9][0-9]*')),
    session_id VARCHAR NOT NULL,
    last_sequence BIGINT NOT NULL CHECK (last_sequence > 0),
    PRIMARY KEY (run_id, charger_id, connector_id),
    UNIQUE (run_id, session_id)
);

CREATE OR REPLACE VIEW meter_history AS
SELECT run_id, event_id, sequence, event_time, station_id, charger_id,
       session_id, connector_id,
       CAST(json_extract(payload, '$.voltage_v') AS DOUBLE) AS voltage_v,
       CAST(json_extract(payload, '$.current_a') AS DOUBLE) AS current_a,
       CAST(json_extract(payload, '$.power_kw') AS DOUBLE) AS power_kw,
       CAST(json_extract(payload, '$.energy_kwh') AS DOUBLE) AS energy_kwh,
       CAST(json_extract(payload, '$.soc_pct') AS DOUBLE) AS soc_pct
FROM mqtt_events WHERE event_type = 'meter';

CREATE OR REPLACE VIEW run_session_metrics AS
SELECT run_id,
       COUNT(*) FILTER (WHERE status = 'active') AS active_sessions,
       COUNT(*) FILTER (WHERE status = 'completed') AS completed_sessions,
       COALESCE(SUM(energy_kwh) FILTER (WHERE status = 'completed'), 0)
           AS completed_energy_kwh
FROM charging_sessions GROUP BY run_id;

COMMIT;