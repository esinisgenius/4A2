"""Task 3 MQTT subscriber. Run this before Task 2 publisher."""
import argparse
import json
import logging
import os
import sys

import paho.mqtt.client as mqtt
from task3_state import connect, insert

LOG = logging.getLogger("task3.subscriber")

def main():
    parser = argparse.ArgumentParser(description="MQTT -> durable Task 3 event journal")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--prefix", default=os.getenv("MQTT_TOPIC_PREFIX", "comp5339/a2"))
    parser.add_argument("--db", default="database/task3_events.sqlite")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--ca-file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = connect(args.db)
    prefix = args.prefix.strip("/")
    topic = f"{prefix}/runs/{args.run_id}/#"

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            LOG.error("MQTT connection rejected: %s", reason_code)
            return
        result, mid = client.subscribe(topic, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            LOG.error("Subscribe failed: %s", result)

    def on_subscribe(client, userdata, mid, reason_code_list, properties):
        LOG.info("SUBACK: subscribed to %s QoS 1; safe to start publisher", topic)

    def on_message(client, userdata, msg):
        try:
            e = json.loads(msg.payload.decode("utf-8"))
            suffix = {"price_update": "prices", "session_start": "sessions/start",
                      "meter": "sessions/meter", "session_end": "sessions/end"}[e["event_type"]]
            expected = f"{prefix}/runs/{args.run_id}/stations/{e['station_id']}/chargers/{e['charger_id']}/{suffix}"
            if msg.topic != expected:
                raise ValueError("Topic/payload mismatch")
            stored = insert(conn, e, args.run_id)
            if stored:
                LOG.info("saved #%s %s %s", e["sequence"], e["event_type"], e["station_id"])
        except (ValueError, KeyError, UnicodeError, json.JSONDecodeError) as exc:
            LOG.warning("Rejected message on %s: %s", msg.topic, exc)
        except Exception:
            LOG.exception("Event persistence failed; stopping subscriber")
            client.disconnect()
            sys.exit(1)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    username = os.getenv("MQTT_USERNAME")
    if username:
        client.username_pw_set(username, os.getenv("MQTT_PASSWORD"))
    if args.tls:
        client.tls_set(ca_certs=args.ca_file)
    client.connect(args.host, args.port, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        LOG.info("Subscriber stopped")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
