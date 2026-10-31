# Task 2 report material and evidence

The following draft describes implemented work, not a complete group report.
The team should check it against the final integrated system and page limit.

## MQTT publishing draft

We transformed the Task 1 CSVs into four JSON event types: price updates, session
starts, meter readings and session ends. Generator station IDs identify A1 charger
configurations; the P0 mapping provides the corresponding physical station ID.
Both identifiers are included in every message. Pricing is tracked per charger
configuration, avoiding collisions where one physical site offers multiple tariffs.
The first price initializes each configuration and subsequent equal prices are
suppressed. This reduces 10,368 hourly source prices to 4,320 full-day price events.

Source timestamps use fixed NEM time (UTC+10) and are converted to UTC. Events are
ordered by event time, then price, meter, end and start priority, with stable event
IDs breaking remaining ties. This handles simultaneous final-meter readings,
connector release and the next session start. Meter values remain cumulative;
end events occur at unplugging, and session cost retains the generator's start tariff.

The Publisher uses MQTT 3.1.1 with QoS 1 and non-retained messages. It waits for
each PUBACK and enforces at least 0.1 seconds between attempts, including retries.
An atomic checkpoint records the confirmed prefix; resume verifies the input hash,
broker and topic namespace before continuing. Topics identify the run, physical
station, charger configuration and event type. Stable event IDs support receiver
deduplication by `(run_id,event_id)`, while separate run IDs prevent demonstrations
from being counted as independent charging activity. Broker acknowledgement alone
does not prove subscriber storage, so received events were also captured independently.

For a manageable local test, we selected NEM 00:59–01:02 on 15 September 2026,
including earlier prices and session/meter history needed to initialize state.
The resulting 1,091 logical events comprised 864 prices, 16 starts, 210 meters and
one end. The 864 prices included 432 initial values and 432 actual changes.
A real local broker and independent test receiver confirmed all payloads and order.
Pausing after 50 events and resuming succeeded. Simulated loss of ACK knowledge
for event 51 produced one expected duplicate; its stable ID allowed deduplication.
Minimum measured attempt spacing was 0.109 seconds and the run took 120.172 seconds.
All 45 unit tests passed. These tests verify Task 2; the final dashboard and DuckDB
integration require separate group validation.

## Challenges and limitations

- NEM timestamps cannot simply have a `Z` appended or be interpreted with Sydney
  daylight saving. Fixed UTC+10 conversion avoids shifting event times.
- A short replay needs state initialization. Earlier real events are replayed
  without fabricating starts or ends; statistics cover the selected replay only.
- QoS 1 can duplicate messages. Stable IDs, ordered retries and receiver-side
  idempotency are needed; exactly-once delivery is not claimed.
- Windows sleep can return slightly early. The rate limiter checks the monotonic
  clock repeatedly until its deadline, rather than trusting one sleep call.
- The local broker has no disk-backed queue and binds loopback. A lost receiving
  state requires a new full replay; remote broker authentication/TLS still needs
  environment-specific testing.

## Evidence to retain

- `docs/task2_validation.json`: unit-test, lineage and integration summary.
- `data/events/mqtt_demo/manifest.json`: source hashes, selection and expected counts.
- `data/published/task2-local-verification-20261027/published_events.json`: confirmed payloads.
- Same directory: `received_events.json`, `verification.json`, `publish_manifest.json`.
- `docs/event_schema.md`, `docs/mqtt_topics.md`: finalized contract and topic design.

Use a screenshot from the running integrated Task 3 dashboard in the final report;
console output and this test receiver do not satisfy the dashboard screenshot requirement.
