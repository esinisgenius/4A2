"""Single-process DuckDB owner for MQTT ingestion and dashboard queries.

All DuckDB reads/writes occur on one worker thread. Streamlit communicates
through a bounded request queue; no cross-process database file contention.
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import duckdb
import paho.mqtt.client as mqtt

from analytics_storage import AnalyticsStorage, DEFAULT_DATABASE
from analytics_subscriber import OrderedReceiver
from analytics_queries import AnalyticsQueries

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "database/analytics_schema.sql"
METADATA = ROOT / "database/charger_metadata.duckdb"


def ensure_database(path):
    """Initialize a fresh analysis database from immutable P0 metadata."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(METADATA, path)
    with duckdb.connect(str(path)) as con:
        con.execute(SCHEMA.read_text())


class DashboardRuntime:
    def __init__(self, run_id, database=DEFAULT_DATABASE, host="127.0.0.1", port=1883,
                 prefix="comp5339/a2"):
        self.run_id = run_id
        self.database = Path(database)
        self.host, self.port, self.prefix = host, port, prefix
        self.requests = queue.Queue(maxsize=32)
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.error = None
        self.publisher = None
        self.publisher_log = None
        self.received_packets = 0
        self.saved_events = 0
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name=f"duckdb-{run_id}")
        self.thread.start()

    def snapshot(self, timeout=15):
        """Return consistent, committed event data and DuckDB-derived metrics."""
        if self.error:
            raise RuntimeError(self.error)
        if self.stopped.is_set():
            raise RuntimeError(self.error or "MQTT ingestion thread stopped")
        reply = queue.Queue(maxsize=1)
        self.requests.put(("snapshot", reply), timeout=timeout)
        try:
            ok, value = reply.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("DuckDB worker did not return a snapshot") from exc
        if not ok:
            raise RuntimeError(value)
        return value

    def start_demo_replay(self):
        """Launch the actual Task 2 publisher after MQTT SUBACK; never overwrite a run."""
        if self.error or self.stopped.is_set() or not self.ready.is_set():
            raise RuntimeError("Subscriber is not ready; check SUBACK and DuckDB lock.")
        if self.publisher is not None:
            raise RuntimeError("Publisher already launched for this run.")
        output_dir = ROOT / "data/published" / self.run_id
        if output_dir.exists():
            raise RuntimeError(
                f"Publisher checkpoint already exists for {self.run_id}; "
                "choose a NEW run ID to start a fresh test."
            )
        if self.saved_events:
            raise RuntimeError("This run has stored events; choose a fresh run ID.")
        log_path = ROOT / "logs" / f"integrated-{self.run_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.publisher_log = log_path.open("w", encoding="utf-8")
        try:
            self.publisher = subprocess.Popen(
                [sys.executable, str(ROOT / "src/publisher.py"),
                 "--events", str(ROOT / "data/events/mqtt_demo/events.json"),
                 "--run-id", self.run_id],
                cwd=str(ROOT), stdout=self.publisher_log, stderr=subprocess.STDOUT,
            )
        except Exception:
            self.publisher_log.close()
            self.publisher_log = None
            raise
        return str(log_path)

    def publication_status(self):
        if self.publisher is None:
            return "Not started from dashboard"
        status = self.publisher.poll()
        if status is None:
            return "Publisher running"
        return "Publisher completed" if status == 0 else f"Publisher exited with code {status}"

    def _run(self):
        client = None
        try:
            ensure_database(self.database)
            with AnalyticsStorage(self.database) as storage:
                receiver = OrderedReceiver(storage, self.run_id, self.prefix)
                incoming = queue.Queue(maxsize=10000)
                errors = queue.Queue()
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                    protocol=mqtt.MQTTv311, clean_session=True,
                                    manual_ack=True, reconnect_on_failure=False)
                if os.environ.get("MQTT_USERNAME"):
                    client.username_pw_set(os.environ["MQTT_USERNAME"],
                                           os.environ.get("MQTT_PASSWORD"))

                def on_connect(c, userdata, flags, reason, properties):
                    if reason.is_failure:
                        errors.put(f"Broker rejected connection: {reason}")
                    else:
                        code, _ = c.subscribe(f"{self.prefix}/runs/{self.run_id}/#", qos=1)
                        if code != mqtt.MQTT_ERR_SUCCESS:
                            errors.put("MQTT subscribe failed")

                def on_subscribe(c, userdata, mid, reasons, properties):
                    if not reasons or any(r.is_failure or r.value != 1 for r in reasons):
                        errors.put("Broker did not grant QoS 1")
                    else:
                        self.ready.set()
                        print(f"SUBACK: integrated DuckDB ready for {self.run_id}", flush=True)

                def on_message(c, userdata, msg):
                    try:
                        incoming.put_nowait((msg.topic, msg.payload, msg.mid, msg.qos, msg.retain))
                    except queue.Full:
                        errors.put("MQTT input queue full")

                def on_disconnect(c, userdata, flags, reason, properties):
                    if not self.stopped.is_set():
                        errors.put(f"MQTT disconnected: {reason}")

                client.on_connect = on_connect
                client.on_subscribe = on_subscribe
                client.on_message = on_message
                client.on_disconnect = on_disconnect
                client.connect(self.host, self.port, 60)
                client.loop_start()
                with AnalyticsQueries(connection=storage.con) as queries:
                    while not self.stopped.is_set():
                        if not errors.empty():
                            raise RuntimeError(errors.get_nowait())
                        if receiver.waiting_since and time.monotonic()-receiver.waiting_since > 30:
                            raise TimeoutError(f"Missing MQTT sequence {receiver.last_sequence+1}")
                        # Interleave writes and queries; the connection stays on this thread.
                        for _ in range(100):
                            try:
                                packet = incoming.get_nowait()
                            except queue.Empty:
                                break
                            self.received_packets += 1
                            for mid, qos in receiver.receive(*packet):
                                if client.ack(mid, qos) != mqtt.MQTT_ERR_SUCCESS:
                                    raise RuntimeError("MQTT ACK failed")
                        self.saved_events = receiver.last_sequence
                        try:
                            kind, reply = self.requests.get(timeout=0.05)
                        except queue.Empty:
                            continue
                        try:
                            if kind != "snapshot":
                                raise ValueError("Unknown worker request")
                            rows = storage.con.execute(
                                "SELECT payload FROM mqtt_events WHERE run_id=? ORDER BY sequence",
                                [self.run_id],
                            ).fetchall()
                            events = [json.loads(r[0]) for r in rows]
                            metrics = queries.get_run_metrics(self.run_id) if events else None
                            reply.put((True, {"events": events, "metrics": metrics,
                                              "ready": self.ready.is_set(),
                                              "pending": len(receiver.pending),
                                              "received_packets": self.received_packets,
                                              "saved_events": receiver.last_sequence}))
                        except Exception as exc:
                            reply.put((False, str(exc)))
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            print(f"Integrated DuckDB runtime stopped: {self.error}", flush=True)
        finally:
            self.stopped.set()
            if client is not None:
                try:
                    client.disconnect()
                    client.loop_stop()
                except Exception:
                    pass

    def close(self):
        self.stopped.set()
        if self.thread.is_alive():
            self.thread.join(timeout=3)
