# MQTT contract 1.0

Finalized by the Task 2 owner on 2026-10-27. Defaults: MQTT 3.1.1 TCP,
`127.0.0.1:1883`, prefix `comp5339/a2`, QoS **1**, retain **false**.
The optional local broker binds loopback only, with anonymous local access.
For a shared remote broker set `--host`, `--port`, and optionally `--prefix`,
`--tls`, `--ca-file`; credentials come from `MQTT_USERNAME`/`MQTT_PASSWORD`.
Never commit credentials. All teammates must use the same broker/prefix/run_id.

```text
{prefix}/runs/{run_id}/stations/{station_id}/chargers/{charger_id}/prices
{prefix}/runs/{run_id}/stations/{station_id}/chargers/{charger_id}/sessions/start
{prefix}/runs/{run_id}/stations/{station_id}/chargers/{charger_id}/sessions/meter
{prefix}/runs/{run_id}/stations/{station_id}/chargers/{charger_id}/sessions/end
```

Subscriptions for a selected run:

```text
comp5339/a2/runs/{run_id}/#
comp5339/a2/runs/{run_id}/stations/+/chargers/+/prices
comp5339/a2/runs/{run_id}/stations/+/chargers/+/sessions/+
```

Replace `{run_id}` with the literal ID, e.g. `team-demo-01`. Subscribe at QoS 1
and wait for SUBACK before starting Publisher. Validate topic IDs against JSON
IDs. A station-specific view can replace the station wildcard with its site ID.
To use an isolated group prefix, every component must set the same prefix.

Publisher has one event in flight. It waits for PUBACK, saves a checkpoint, and
waits at least 0.1 seconds before its next attempt. Connection/ACK failures retry
the same event (default three additional attempts), then fail with a nonzero exit
code and preserve the last confirmed prefix. Retries are also rate limited.
`--resume` verifies the same input hash, broker, topic prefix and run_id. It does
not silently skip a failed event. Separate outputs with the same run_id must not
be used concurrently; the default output directory is locked per run.

The broker's arrival time is not event time. Task 3/4 should process one selected
run in sequence order and apply idempotency before updating current/historical
metrics. The simulated clock advances per event; 0.1s is wall-clock pacing, not a
claim to replay actual elapsed source-time gaps at real-time speed.
