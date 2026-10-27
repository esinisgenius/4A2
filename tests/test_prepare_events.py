"""Behavioural tests for Task 2 event preparation, including replay boundaries."""
import csv
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from src.prepare_events import market_time, prepare, utc_string, write_outputs


class PrepareEventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="task2-events-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stations = [{"station_id": c, "connectors": "1", "name": c} for c in ("c1", "c2")]
        self.mapping = [{"generator_station_id": c, "physical_station_id": "shared-site", "charger_id": c} for c in ("c1", "c2")]
        self.prices = [{"station_id": c, "ts": f"2026-09-15T0{h}:00:00", "price_per_kwh": price}
                       for c, values in [("c1", ["0.60", "0.70", "0.70", "0.60"]), ("c2", ["0.80", "0.80", "0.90", "0.90"])]
                       for h, price in enumerate(values)]
        self.sessions = [
            self.session("s1", "c1", "00:58:00", "01:00:00", "01:00:00", "0.60"),
            self.session("s2", "c1", "01:00:00", "01:02:00", "01:03:00", "0.70"),
            self.session("s3", "c2", "00:59:00", "01:01:00", "01:01:00", "0.80"),
        ]
        self.meters = []
        for sid, cid, times in [("s1", "c1", ["00:59:00", "01:00:00"]), ("s2", "c1", ["01:01:00", "01:02:00"]), ("s3", "c2", ["01:00:00", "01:01:00"])]:
            for i, time in enumerate(times, 1):
                self.meters.append({"session_id": sid, "station_id": cid, "connector_id": "1", "type": "meter",
                                    "ts": f"2026-09-15T{time}", "voltage_v": "400", "current_a": "75", "power_kw": "30",
                                    "energy_kwh": str(i * 0.5), "soc_pct": str(40 + i)})
        self.save()

    def session(self, sid, cid, start, charge_end, end, price):
        return {"session_id": sid, "station_id": cid, "connector_id": "1", "vehicle_model": "Test EV", "site_type": "urban",
                "start_ts": f"2026-09-15T{start}", "charge_end_ts": f"2026-09-15T{charge_end}", "end_ts": f"2026-09-15T{end}",
                "price_per_kwh": price, "energy_kwh": "1.00", "charge_minutes": "2", "avg_kw": "30", "peak_kw": "30", "cost_aud": price}

    def write(self, name, rows):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def save(self):
        for name, data in [("data/generated/stations.csv", self.stations), ("data/processed/generator_station_mapping.csv", self.mapping),
                           ("data/generated/prices_hourly.csv", self.prices), ("data/generated/sessions.csv", self.sessions),
                           ("data/generated/session_metering.csv", self.meters)]:
            self.write(name, data)

    def test_price_changes_are_per_configuration_and_can_return_to_old_price(self):
        events, manifest = prepare(self.root)
        prices = [e for e in events if e["event_type"] == "price_update"]
        self.assertEqual([p["price_per_kwh"] for p in prices if p["charger_id"] == "c1"], [0.6, 0.7, 0.6])
        self.assertEqual([p["price_per_kwh"] for p in prices if p["charger_id"] == "c2"], [0.8, 0.9])
        self.assertEqual({p["station_id"] for p in prices}, {"shared-site"})
        self.assertEqual(manifest["full_dataset_unchanged_price_rows_removed"], 3)
        self.assertEqual(manifest["event_count"], 17)

    def test_final_meter_precedes_end_and_end_precedes_new_start(self):
        events, manifest = prepare(self.root)
        boundary = [e for e in events if e["charger_id"] == "c1" and e["event_time"] == "2026-09-14T15:00:00Z"]
        self.assertEqual([e["event_type"] for e in boundary], ["price_update", "meter", "session_end", "session_start"])
        self.assertEqual(manifest["stream_checks"]["active_sessions_at_end"], 0)
        self.assertEqual(manifest["stream_checks"]["completed_sessions"], 3)

    def test_start_does_not_leak_final_results_and_end_uses_unplug_time(self):
        events, _ = prepare(self.root)
        start = next(e for e in events if e.get("session_id") == "s2" and e["event_type"] == "session_start")
        self.assertFalse({"energy_kwh", "cost_aud", "charge_end_time", "end_ts", "charge_minutes"} & start.keys())
        end = next(e for e in events if e.get("session_id") == "s2" and e["event_type"] == "session_end")
        self.assertEqual(end["event_time"], "2026-09-14T15:03:00Z")
        self.assertEqual(end["charge_end_time"], "2026-09-14T15:02:00Z")

    def test_window_recovers_existing_sessions_and_leaves_tail_active(self):
        events, manifest = prepare(self.root, market_time("2026-09-15T01:00:00"), market_time("2026-09-15T01:02:00"))
        starts = {e["session_id"] for e in events if e["event_type"] == "session_start"}
        self.assertEqual(starts, {"s1", "s2", "s3"})
        self.assertGreater(manifest["warmup_event_count"], 0)
        self.assertTrue(all(e["event_time"] < "2026-09-14T15:02:00Z" for e in events))
        self.assertEqual(manifest["stream_checks"]["active_sessions_at_end"], 1)
        self.assertFalse(any(e["event_type"] == "session_end" and e["session_id"] == "s2" for e in events))

    def test_window_without_sessions_still_initialises_prices(self):
        events, manifest = prepare(self.root, market_time("2026-09-15T01:04:00"), market_time("2026-09-15T01:30:00"))
        self.assertEqual(manifest["selected_sessions"], 0)
        self.assertEqual(len(events), 2)
        self.assertEqual({e["charger_id"]:e["price_per_kwh"] for e in events}, {"c1": 0.7, "c2": 0.8})

    def test_event_identity_stable_across_windows_and_input_row_order(self):
        full, _ = prepare(self.root)
        self.prices.reverse()
        self.sessions.reverse()
        self.meters.reverse()
        self.mapping.reverse()
        self.save()
        reordered, _ = prepare(self.root)
        self.assertEqual(full, reordered)
        window, _ = prepare(self.root, market_time("2026-09-15T01:00:00"), market_time("2026-09-15T01:02:00"))
        lookup = {e["event_id"]:{k:v for k,v in e.items() if k != "sequence"} for e in full}
        for event in window:
            self.assertEqual(lookup[event["event_id"]], {k:v for k,v in event.items() if k != "sequence"})

    def test_fixed_aest_conversion_and_explicit_window_validation(self):
        self.assertEqual(utc_string(market_time("2026-09-15T09:00:00")), "2026-09-14T23:00:00Z")
        self.assertEqual(utc_string(market_time("2026-10-15T09:00:00")), "2026-10-14T23:00:00Z")
        with self.assertRaisesRegex(ValueError, "offset-free"):
            market_time("2026-09-15T09:00:00Z")
        with self.assertRaisesRegex(ValueError, "both"):
            prepare(self.root, datetime(2026, 9, 15, 1))
        with self.assertRaisesRegex(ValueError, "coverage"):
            prepare(self.root, datetime(2026, 9, 15, 3), datetime(2026, 9, 15, 5))

    def test_unknown_mapping_or_inconsistent_meter_is_rejected(self):
        self.mapping[0]["charger_id"] = "wrong"
        self.save()
        with self.assertRaisesRegex(ValueError, "mapping"):
            prepare(self.root)
        self.mapping[0]["charger_id"] = "c1"
        self.meters[0]["station_id"] = "c2"
        self.save()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            prepare(self.root)

    def test_duplicate_prices_and_meters_are_rejected(self):
        self.prices.append(dict(self.prices[0]))
        self.save()
        with self.assertRaisesRegex(ValueError, "Duplicate price"):
            prepare(self.root)
        self.prices.pop()
        self.meters.append(dict(self.meters[0]))
        self.save()
        with self.assertRaisesRegex(ValueError, "Duplicate meter"):
            prepare(self.root)

    def test_missing_meter_and_nonfinite_values_are_rejected(self):
        removed = self.meters.pop(0)
        self.save()
        with self.assertRaisesRegex(ValueError, "Missing minute"):
            prepare(self.root)
        self.meters.insert(0, removed)
        self.prices[0]["price_per_kwh"] = "NaN"
        self.save()
        with self.assertRaisesRegex(ValueError, "Invalid price"):
            prepare(self.root)

    def test_json_roundtrip_and_prepared_does_not_mean_published(self):
        events, manifest = prepare(self.root)
        result = write_outputs(events, manifest, self.root / "data/events/test", self.root)
        loaded = json.loads((self.root / "data/events/test/events.json").read_text(encoding="utf-8"))
        self.assertEqual(events, loaded)
        self.assertEqual(result["publication_status"], "NOT_PUBLISHED")
        self.assertTrue(all(isinstance(e["connector_id"], str) for e in events if "connector_id" in e))
        with self.assertRaisesRegex(ValueError, "upstream"):
            write_outputs(events, manifest, self.root / "data/generated", self.root)


if __name__ == "__main__":
    unittest.main()
