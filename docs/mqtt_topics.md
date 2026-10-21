# Proposed MQTT Topics

The topic design is **PROPOSED** and may change after inspecting the teacher generator.

```text
comp5339/a2/stations/{station_id}/prices
comp5339/a2/stations/{station_id}/chargers/{charger_id}/sessions/start
comp5339/a2/stations/{station_id}/chargers/{charger_id}/sessions/meter
comp5339/a2/stations/{station_id}/chargers/{charger_id}/sessions/end
```

Recommended subscriptions:

- `comp5339/a2/#` receives every event.
- `comp5339/a2/stations/+/prices` receives all price updates.
- `comp5339/a2/stations/+/chargers/+/sessions/+` receives all session lifecycle events.
- A station-specific dashboard can replace the first `+` with one `station_id`.

Payloads carry the identifiers as well as the topic path so Subscriber validation can reject mismatches. MQTT delivery time is not event time; storage and replay order must use the payload `event_time`. QoS, retained-message behavior, broker settings, and any connector-level topic segment remain to be decided during Task 2 implementation.
