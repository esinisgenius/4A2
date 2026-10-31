"""Real local-broker test and evidence capture; not the Task 3 subscriber.

Starts/stops its own loopback broker, subscribes before publishing, pauses and
resumes, and optionally simulates lost application knowledge of one PUBACK.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import paho.mqtt.client as mqtt
from src.publisher import MQTTTransport, atomic_json, load_events, publish, topic_for


class LostAckTransport(MQTTTransport):
    def __init__(self, *args, fault_sequence=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fault_sequence = fault_sequence
        self.injected = False

    def send(self, topic, payload):
        super().send(topic, payload)
        if payload["sequence"] == self.fault_sequence and not self.injected:
            self.injected = True
            # The broker received it, but imitate an ACK lost before checkpoint.
            raise TimeoutError("Injected loss of PUBACK knowledge")


def verify(events_path, output_dir, run_id, inject_ack_loss_at=None):
    expected, _ = load_events(events_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / "checkpoint.json").exists():
        raise ValueError("Choose a fresh verification run/output directory")
    if inject_ack_loss_at is not None and not 1 <= inject_ack_loss_at <= len(expected):
        raise ValueError("Fault sequence is outside the stream")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    packets, errors = [], []
    ready = threading.Event()
    receiver = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"verify-{port}")

    def connected(client, userdata, flags, reason, properties):
        if reason.is_failure:
            errors.append(str(reason))
        else:
            client.subscribe(f"comp5339/a2/runs/{run_id}/#", qos=1)

    def subscribed(client, userdata, mid, reasons, properties):
        if any(reason.is_failure for reason in reasons):
            errors.append("SUBACK rejected")
        else:
            ready.set()

    def received(client, userdata, message):
        try:
            packets.append({"topic": message.topic, "qos": message.qos, "retain": message.retain,
                            "received_monotonic_seconds": time.monotonic(),
                            "payload": json.loads(message.payload)})
        except Exception as exc:
            errors.append(type(exc).__name__)

    receiver.on_connect, receiver.on_subscribe, receiver.on_message = connected, subscribed, received
    started = time.monotonic()
    with (output_dir / "broker.log").open("w", encoding="utf-8") as log:
        broker = subprocess.Popen([sys.executable, str(ROOT / "src/local_broker.py"), "--port", str(port)],
                                  cwd=ROOT, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            deadline = time.monotonic() + 15
            while True:
                if broker.poll() is not None:
                    raise RuntimeError("Broker failed; inspect broker.log")
                try:
                    receiver.connect("127.0.0.1", port, keepalive=60)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError("Broker did not start")
                    time.sleep(0.1)
            receiver.loop_start()
            if not ready.wait(10):
                raise TimeoutError(f"Subscription not ready: {errors}")
            pause_at = min(50, max(1, len(expected) // 2))
            transport = LostAckTransport("127.0.0.1", port, run_id, fault_sequence=inject_ack_loss_at)
            paused = publish(events_path, output_dir, run_id, port=port, transport=transport,
                             stop_after=pause_at, retry_delay=0.1)
            assert paused["status"] == "PAUSED"
            # New transport uses only the durable checkpoint, not client state.
            replacement = LostAckTransport("127.0.0.1", port, run_id,
                                          fault_sequence=None if transport.injected else inject_ack_loss_at)
            result = publish(events_path, output_dir, run_id, port=port, transport=replacement,
                             resume=True, retry_delay=0.1)
            expected_packets = len(expected) + (inject_ack_loss_at is not None)
            deadline = time.monotonic() + 10
            while len(packets) < expected_packets and time.monotonic() < deadline:
                time.sleep(0.05)
            receiver.disconnect()
            receiver.loop_stop()
            assert not errors, errors
            assert len(packets) == expected_packets, (len(packets), expected_packets)
            unique = {}
            last_sequence = 0
            for packet in packets:
                payload = packet["payload"]
                assert packet["qos"] == 1 and not packet["retain"]
                assert packet["topic"] == topic_for(payload, "comp5339/a2", run_id)
                assert payload["sequence"] >= last_sequence
                last_sequence = payload["sequence"]
                key = payload["run_id"], payload["event_id"]
                assert key not in unique or unique[key] == payload
                unique[key] = payload
            published = json.loads((output_dir / "published_events.json").read_text(encoding="utf-8"))
            assert list(unique.values()) == published == [{**e, "run_id": run_id} for e in expected]
            attempts = [json.loads(line) for line in (output_dir / "attempts.jsonl").read_text().splitlines()]
            intervals = [b["monotonic_seconds"] - a["monotonic_seconds"] for a, b in zip(attempts, attempts[1:])]
            assert all(value >= 0.1 for value in intervals), min(intervals)
            prices = {}
            changed = 0
            for event in published:
                if event["event_type"] == "price_update":
                    changed += event["charger_id"] in prices
                    prices[event["charger_id"]] = event["price_per_kwh"]
            atomic_json(output_dir / "received_events.json", packets)
            report = {"result": "PASS", "run_id": run_id, "broker": "amqtt 0.11.3 (loopback, ephemeral port)",
                      "publisher": "paho-mqtt 2.1.0 / MQTT 3.1.1 / QoS 1 / retain false",
                      "unique_events": len(unique), "received_packets": len(packets),
                      "duplicate_packets": len(packets) - len(unique), "injected_ack_loss_at": inject_ack_loss_at,
                      "event_counts": dict(Counter(e["event_type"] for e in published)),
                      "price_changes_after_initialization": changed,
                      "pause_resume_at_sequence": pause_at, "final_status": result["status"],
                      "minimum_attempt_spacing_seconds": min(intervals) if intervals else None,
                      "elapsed_seconds": time.monotonic() - started,
                      "checks": ["SUBACK before publish", "all four event payloads roundtrip where present",
                                 "topic/payload IDs match", "sequence order preserved including retries",
                                 "captured unique events equal prepared input plus run_id",
                                 "captured unique events equal PUBACK export", "every attempt spacing >= 0.1s",
                                 "pause/resume via durable checkpoint"],
                      "scope": "Task 2 wire-level evidence; no Task 3 dashboard or Task 4 DuckDB integration claimed"}
            atomic_json(output_dir / "verification.json", report)
            print(json.dumps(report, indent=2))
            return report
        finally:
            receiver.disconnect()
            receiver.loop_stop()
            broker.terminate()
            try:
                broker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                broker.kill()
                broker.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--inject-ack-loss-at", type=int)
    args = parser.parse_args()
    verify(args.events.resolve(), args.output_dir.resolve(), args.run_id, args.inject_ack_loss_at)
