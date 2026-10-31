"""Publish prepared Task 2 events sequentially, with QoS 1 and durable resume."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

import paho.mqtt.client as mqtt

try:
    from .prepare_events import ROOT, canonical, require, validate_stream
except ImportError:
    from prepare_events import ROOT, canonical, require, validate_stream

SUFFIX = {"price_update": "prices", "session_start": "sessions/start",
          "meter": "sessions/meter", "session_end": "sessions/end"}


def segment(value: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value) is not None,
            f"Invalid topic/identifier segment: {value!r}")
    return value


def topic_for(event: dict, prefix: str, run_id: str) -> str:
    return (f"{prefix}/runs/{segment(run_id)}/stations/{segment(event['station_id'])}"
            f"/chargers/{segment(event['charger_id'])}/{SUFFIX[event['event_type']]}")


def atomic_json(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


@contextmanager
def run_lock(directory: Path):
    """OS-released lock: a killed publisher cannot leave a stale lock ownership."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "publisher.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another publisher is using this run directory") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def load_events(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    events = json.loads(raw)
    require(isinstance(events, list) and bool(events), "Input must be a nonempty event JSON array")
    datasets = set()
    for e in events:
        require(isinstance(e, dict) and "run_id" not in e, "Use prepared events, not a previous published export")
        require(e["schema_version"] == "1.0", "Unsupported schema version")
        require(re.fullmatch(r"ds_[0-9a-f]{64}", e["dataset_id"]) is not None, "Invalid dataset ID")
        datasets.add(e["dataset_id"])
        datetime.strptime(e["event_time"], "%Y-%m-%dT%H:%M:%SZ")
        topic_for(e, "validation", "validation")
        semantic = {k: v for k, v in e.items() if k not in {"event_id", "sequence"}}
        require(e["event_id"] == "evt_" + hashlib.sha256(canonical(semantic)).hexdigest(), "Payload/event ID hash mismatch")
        if e["event_type"] != "price_update":
            require(isinstance(e["connector_id"], str) and e["connector_id"].isdigit() and int(e["connector_id"]) > 0,
                    "connector_id must be a positive integer encoded as a string")
    require(len(datasets) == 1, "Mixed datasets are not supported")
    validate_stream(events)
    return events, hashlib.sha256(raw).hexdigest()


class MQTTTransport:
    """One in-flight packet; explicit retries own reconnect and pacing.

    A fresh client on reconnect prevents Paho from independently retransmitting
    outstanding messages outside the publisher's rate limiter.
    """
    def __init__(self, host: str, port: int, run_id: str, timeout: float = 10,
                 tls: bool = False, ca_file: str | None = None):
        self.host, self.port, self.timeout = host, port, timeout
        self.tls, self.ca_file = tls, ca_file
        self.client_id = "a2pub-" + hashlib.sha256(run_id.encode()).hexdigest()[:16]
        self.client = None

    def _loop_until(self, predicate):
        deadline = time.monotonic() + self.timeout
        while not predicate():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MQTT acknowledgement timeout")
            rc = self.client.loop(timeout=min(0.1, remaining))
            if rc != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError(f"MQTT network loop failed: {mqtt.error_string(rc)}")

    def connect(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id,
                                  clean_session=True, protocol=mqtt.MQTTv311, reconnect_on_failure=False)
        self.client.connect_timeout = self.timeout
        self.client.max_inflight_messages_set(1)
        username = os.environ.get("MQTT_USERNAME")
        if username:
            self.client.username_pw_set(username, os.environ.get("MQTT_PASSWORD"))
        if self.tls:
            self.client.tls_set(ca_certs=self.ca_file)
        result = []
        self.client.on_connect = lambda client, userdata, flags, reason, properties: result.append(reason)
        self.client.connect(self.host, self.port, keepalive=60)
        self._loop_until(lambda: bool(result))
        if result[0].is_failure:
            raise ConnectionError(f"Broker rejected connection: {result[0]}")

    def send(self, topic: str, payload: dict):
        if self.client is None:
            self.connect()
        message = self.client.publish(topic, canonical(payload), qos=1, retain=False)
        if message.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT publish failed: {mqtt.error_string(message.rc)}")
        self._loop_until(message.is_published)

    def close(self):
        if self.client is not None:
            try:
                self.client.disconnect()
            except OSError:
                pass
            finally:
                self.client = None


def publish(events_path: Path, output_dir: Path, run_id: str, *, host="127.0.0.1", port=1883,
            prefix="comp5339/a2", interval=0.1, timeout=10.0, retries=3,
            retry_delay=1.0, resume=False, stop_after=None, tls=False, ca_file=None,
            transport=None) -> dict:
    segment(run_id)
    for part in prefix.split("/"):
        segment(part)
    require(math.isfinite(interval) and interval >= 0.1, "Publish interval must be at least 0.1 seconds")
    require(math.isfinite(timeout) and timeout > 0, "Timeout must be positive and finite")
    require(math.isfinite(retry_delay) and retry_delay >= 0 and retries >= 0, "Invalid retry settings")
    require(1 <= port <= 65535 and bool(host), "Invalid broker address")
    require(stop_after is None or stop_after > 0, "--stop-after must be positive")
    require(ca_file is None or tls, "--ca-file requires --tls")
    events, digest = load_events(events_path)
    directory = output_dir.resolve()
    protected = [ROOT / p for p in ("data/source", "data/input", "data/processed", "data/generated", "data/events", "database", "vendor")]
    require(not any(directory.is_relative_to(p.resolve()) for p in protected), "Output must not overwrite source/prepared/database directories")
    require(not events_path.resolve().is_relative_to(directory), "Output directory must not contain the input event file")
    binding = {"input_sha256": digest, "dataset_id": events[0]["dataset_id"], "run_id": run_id,
               "host": host, "port": port, "topic_prefix": prefix, "tls": tls, "qos": 1, "retain": False,
               "expected_events": len(events)}
    transport = transport or MQTTTransport(host, port, run_id, timeout, tls, ca_file)
    with run_lock(directory):
        checkpoint = directory / "checkpoint.json"
        if checkpoint.exists():
            require(resume, "Run already exists; use --resume or a new run ID/directory")
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            require(state["binding"] == binding, "Resume input, run ID or broker/topic settings changed")
        else:
            require(not resume, "No checkpoint exists for --resume")
            require(not any((directory / n).exists() for n in ("published_events.json", "publish_manifest.json", "attempts.jsonl")),
                    "Output contains a previous run without its checkpoint")
            state = {"binding": binding, "acknowledged_count": 0, "status": "READY"}
            atomic_json(checkpoint, state)
        acknowledged = state["acknowledged_count"]
        require(type(acknowledged) is int and 0 <= acknowledged <= len(events), "Invalid checkpoint offset")
        initial = acknowledged
        state["status"] = "RUNNING"
        # Also delay the first message after a resumed process (conservative pacing).
        next_allowed = time.monotonic() + interval
        failure = None
        with (directory / "attempts.jsonl").open("a", encoding="utf-8", newline="\n") as log:
            try:
                for event in events[acknowledged:]:
                    payload = {**event, "run_id": run_id}
                    topic = topic_for(event, prefix, run_id)
                    for attempt in range(retries + 1):
                        while (remaining := next_allowed - time.monotonic()) > 0:
                            time.sleep(remaining)
                        record = {"sequence": event["sequence"], "event_id": event["event_id"], "attempt": attempt + 1,
                                  "attempt_time_utc": datetime.now(timezone.utc).isoformat(), "monotonic_seconds": time.monotonic()}
                        try:
                            transport.send(topic, payload)
                            record["result"] = "PUBACK"
                            break
                        except OSError as exc:
                            record["result"] = "UNCONFIRMED"
                            record["error_type"] = type(exc).__name__
                            transport.close()
                            if attempt == retries:
                                raise
                            time.sleep(retry_delay)
                        finally:
                            next_allowed = time.monotonic() + interval
                            log.write(json.dumps(record, separators=(",", ":")) + "\n")
                            log.flush()
                    state["acknowledged_count"] += 1
                    atomic_json(checkpoint, state)
                    if state["acknowledged_count"] % 100 == 0:
                        print(f"PUBACK {state['acknowledged_count']}/{len(events)}", flush=True)
                    if stop_after is not None and state["acknowledged_count"] - initial >= stop_after:
                        break
                state["status"] = "COMPLETE" if state["acknowledged_count"] == len(events) else "PAUSED"
            except KeyboardInterrupt as exc:
                state["status"] = "INTERRUPTED"
                failure = exc
            except Exception as exc:
                state["status"] = "FAILED"
                failure = exc
            finally:
                transport.close()
                atomic_json(checkpoint, state)
                exported = [{**e, "run_id": run_id} for e in events[:state["acknowledged_count"]]]
                atomic_json(directory / "published_events.json", exported)
                manifest = {**binding, "status": state["status"], "acknowledged_count": len(exported),
                            "event_counts": dict(Counter(e["event_type"] for e in exported)),
                            "interval_seconds_this_invocation": interval,
                            "published_events_sha256": hashlib.sha256((directory / "published_events.json").read_bytes()).hexdigest(),
                            "delivery_semantics": "Broker-PUBACK-confirmed unique logical prefix; QoS 1 retries may duplicate packets. Subscriber receipt/storage requires separate verification.",
                            "unconfirmed_tail_possible": state["status"] in {"FAILED", "INTERRUPTED"}}
                atomic_json(directory / "publish_manifest.json", manifest)
        if failure is not None:
            raise failure
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--run-id", required=True, help="Unique replay ID; reuse only with --resume")
    parser.add_argument("--output-dir", type=Path, help="Default data/published/<run-id>")
    parser.add_argument("--host", default=os.environ.get("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    parser.add_argument("--prefix", default=os.environ.get("MQTT_TOPIC_PREFIX", "comp5339/a2"))
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--retries", type=int, default=3, help="Additional attempts per event")
    parser.add_argument("--retry-delay", type=float, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", type=int, help="Pause after this many new acknowledgements")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--ca-file")
    args = parser.parse_args()
    options = vars(args).copy()
    events_path = options.pop("events")
    output = options.pop("output_dir") or ROOT / "data/published" / args.run_id
    try:
        result = publish(events_path, output, **options)
    except KeyboardInterrupt:
        parser.exit(130, "Interrupted; use the same command with --resume.\n")
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Publication failed ({type(exc).__name__}): {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
