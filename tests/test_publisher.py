"""Publisher reliability tests: faults, durable resume, isolation and pacing."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from src.prepare_events import canonical
from src.publisher import atomic_json, load_events, publish, run_lock, topic_for


def fixture_events():
    """Small valid stream with all four types; real-data verification is separate."""
    common = {"schema_version": "1.0", "dataset_id": "ds_" + "a" * 64,
              "station_id": "site_example", "charger_id": "evr_example"}
    rows = [
        {"event_type": "price_update", "event_time": "2026-09-14T14:00:00Z", "price_per_kwh": 0.6, "currency": "AUD", "price_unit": "AUD/kWh"},
        {"event_type": "session_start", "event_time": "2026-09-14T14:01:00Z", "price_per_kwh": 0.6, "currency": "AUD", "vehicle_model": "Test EV", "site_type": "urban"},
        {"event_type": "meter", "event_time": "2026-09-14T14:02:00Z", "energy_kwh": 0.5, "power_kw": 30, "voltage_v": 400, "current_a": 75, "soc_pct": 50},
        {"event_type": "session_end", "event_time": "2026-09-14T14:03:00Z", "energy_kwh": 0.5, "price_per_kwh": 0.6, "currency": "AUD", "charge_end_time": "2026-09-14T14:02:00Z", "charge_minutes": 1, "avg_kw": 30, "peak_kw": 30, "cost_aud": 0.3},
    ]
    events = []
    for i, row in enumerate(rows, 1):
        event = {**common, **row}
        if row["event_type"] != "price_update":
            event.update(session_id="session-example", connector_id="1")
        event["event_id"] = "evt_" + hashlib.sha256(canonical(event)).hexdigest()
        event["sequence"] = i
        events.append(event)
    return events


class FakeTransport:
    def __init__(self, faults=None):
        self.calls = []
        self.times = []
        self.faults = faults or {}
        self.closed = 0

    def send(self, topic, payload):
        self.calls.append((topic, payload))
        self.times.append(time.monotonic())
        if len(self.calls) in self.faults:
            raise self.faults[len(self.calls)]

    def close(self):
        self.closed += 1


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="task2-publisher-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / "prepared.json"
        atomic_json(self.input, fixture_events())
        self.output = self.root / "run"

    def run_publish(self, transport, **kwargs):
        return publish(self.input, self.output, "test-run", transport=transport, retry_delay=0, **kwargs)

    def test_complete_export_matches_wire_payload_and_topics(self):
        transport = FakeTransport()
        result = self.run_publish(transport)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["acknowledged_count"], 4)
        exported = json.loads((self.output / "published_events.json").read_text())
        self.assertEqual(exported, [payload for _, payload in transport.calls])
        self.assertTrue(transport.calls[0][0].endswith("/chargers/evr_example/prices"))
        self.assertEqual({e["run_id"] for e in exported}, {"test-run"})
        self.assertTrue(all(b - a >= 0.1 for a, b in zip(transport.times, transport.times[1:])))

    def test_lost_ack_retries_same_identity_before_advancing(self):
        transport = FakeTransport({2: TimeoutError("ACK lost")})
        result = self.run_publish(transport, retries=1)
        self.assertEqual([p["sequence"] for _, p in transport.calls], [1, 2, 2, 3, 4])
        self.assertEqual(transport.calls[1], transport.calls[2])
        self.assertEqual(result["acknowledged_count"], 4)
        self.assertTrue(all(b - a >= 0.1 for a, b in zip(transport.times, transport.times[1:])))

    def test_failure_exports_only_confirmed_prefix_and_resume_completes(self):
        with self.assertRaises(TimeoutError):
            self.run_publish(FakeTransport({2: TimeoutError()}), retries=0)
        manifest = json.loads((self.output / "publish_manifest.json").read_text())
        self.assertEqual((manifest["status"], manifest["acknowledged_count"]), ("FAILED", 1))
        self.assertTrue(manifest["unconfirmed_tail_possible"])
        replacement = FakeTransport()
        result = self.run_publish(replacement, resume=True)
        self.assertEqual([p["sequence"] for _, p in replacement.calls], [2, 3, 4])
        self.assertEqual(result["status"], "COMPLETE")

    def test_pause_resume_and_completed_resume_do_not_republish(self):
        self.assertEqual(self.run_publish(FakeTransport(), stop_after=2)["status"], "PAUSED")
        transport = FakeTransport()
        self.run_publish(transport, resume=True)
        self.assertEqual([p["sequence"] for _, p in transport.calls], [3, 4])
        empty = FakeTransport()
        self.run_publish(empty, resume=True)
        self.assertEqual(empty.calls, [])

    def test_interrupt_leaves_resumable_checkpoint(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_publish(FakeTransport({2: KeyboardInterrupt()}))
        state = json.loads((self.output / "checkpoint.json").read_text())
        self.assertEqual((state["status"], state["acknowledged_count"]), ("INTERRUPTED", 1))

    def test_invalid_pacing_prefix_or_run_id_never_connects(self):
        for kwargs in ({"interval": 0.099}, {"interval": float("nan")}, {"prefix": "a/#"}, {"prefix": "a/"}, {"timeout": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_publish(FakeTransport(), **kwargs)
        with self.assertRaises(ValueError):
            publish(self.input, self.output, "../bad", transport=FakeTransport())

    def test_resume_refuses_changed_input_broker_and_missing_state(self):
        with self.assertRaises(ValueError):
            self.run_publish(FakeTransport(), resume=True)
        self.run_publish(FakeTransport(), stop_after=1)
        with self.assertRaises(ValueError):
            self.run_publish(FakeTransport())
        with self.assertRaises(ValueError):
            self.run_publish(FakeTransport(), resume=True, port=1884)
        self.input.write_bytes(self.input.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            self.run_publish(FakeTransport(), resume=True)

    def test_payload_tampering_and_wrong_order_rejected(self):
        events = fixture_events()
        events[0]["price_per_kwh"] = 9
        atomic_json(self.input, events)
        with self.assertRaises(ValueError):
            load_events(self.input)
        events = fixture_events()
        events[1], events[2] = events[2], events[1]
        atomic_json(self.input, events)
        with self.assertRaises(ValueError):
            load_events(self.input)

    def test_lock_blocks_parallel_publish_and_releases(self):
        with run_lock(self.output):
            with self.assertRaises(ValueError):
                self.run_publish(FakeTransport())
        self.assertEqual(self.run_publish(FakeTransport())["status"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
