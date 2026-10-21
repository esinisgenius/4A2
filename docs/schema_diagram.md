# Schema Diagram

The solid metadata relationships exist in the P0 DuckDB. Event entities are **PROPOSED** for Task 4 and are not implemented yet.

```mermaid
erDiagram
    STATIONS ||--o{ CHARGERS : contains
    STATIONS ||--o{ STATION_CONNECTOR_TYPES : has_verified_type
    OPERATOR_ALIASES ||--o{ CHARGERS : standardizes
    STATIONS ||--o{ PRICE_EVENTS_PROPOSED : receives
    CHARGERS ||--o{ SESSIONS_PROPOSED : hosts
    SESSIONS_PROPOSED ||--o{ METER_EVENTS_PROPOSED : emits

    STATIONS {
        string station_id PK
        string station_name
        double latitude
        double longitude
    }
    CHARGERS {
        string charger_id PK
        string station_id FK
        string operator_standard
        double effective_power_kw
    }
    STATION_CONNECTOR_TYPES {
        string station_id FK
        string connector_type
    }
    OPERATOR_ALIASES {
        string operator_original PK
        string operator_standard
    }
    PRICE_EVENTS_PROPOSED {
        string event_id PK
        string station_id FK
        timestamp event_time
        double price_per_kwh
    }
    SESSIONS_PROPOSED {
        string session_id PK
        string charger_id FK
        string connector_id
        timestamp start_time
        timestamp end_time
    }
    METER_EVENTS_PROPOSED {
        string event_id PK
        string session_id FK
        timestamp event_time
        double energy_kwh
    }
```

`connector_id` remains proposed because the A1 source identifies configuration rows and plug counts, not physical connector instances. It must be reconciled with the teacher generator before event tables are finalized.
