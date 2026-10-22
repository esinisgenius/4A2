"""Exercise corrupt handoffs and legitimate rounding/day-boundary cases."""

import csv
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from src import run_task1
from src.validate_task1 import AEMO_NAME, START, validate


class Task1Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="task1-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.out = self.root / "data/generated"
        self.station = {"station_id": "charger-1", "name": "Test station", "lat": "-33.86", "lon": "151.20",
                        "site_type": "urban", "connectors": "1", "max_kw": "50"}
        self.write("data/input/stations.csv", [self.station])
        self.write("data/processed/generator_station_mapping.csv", [
            {"generator_station_id": "charger-1", "physical_station_id": "site-1", "charger_id": "charger-1"}])
        self.write("data/processed/stations_prepared.csv", [{"station_id": "site-1"}])
        self.write("data/processed/chargers_prepared.csv", [{"charger_id": "charger-1", "station_id": "site-1"}])
        self.aemo = [{"REGION": "NSW1", "SETTLEMENTDATE": (START + timedelta(minutes=5*i)).strftime("%Y/%m/%d %H:%M:%S"),
                      "RRP": "100", "PERIODTYPE": "TRADE"} for i in range(1, 289)]
        self.write("data/generated/aemo_cache/" + AEMO_NAME, self.aemo)
        self.write("data/generated/stations.csv", [{**self.station, "base_price": "0.6"}])
        self.prices = [{"ts": (START + timedelta(hours=i)).isoformat(), "station_id": "charger-1",
                        "price_per_kwh": "0.7" if 16 <= i < 21 else "0.6", "wholesale_per_kwh": "0.1"} for i in range(24)]
        self.write("data/generated/prices_hourly.csv", self.prices)
        self.session = {"session_id": "session-1", "station_id": "charger-1", "connector_id": "1", "site_type": "urban",
                        "start_ts": "2026-09-15T01:00:00", "charge_end_ts": "2026-09-15T01:02:00", "end_ts": "2026-09-15T01:03:00",
                        "charge_minutes": "2", "energy_kwh": "0.02", "avg_kw": "0.6", "peak_kw": "0.6",
                        "price_per_kwh": "0.6", "cost_aud": "0.01"}
        self.write("data/generated/sessions.csv", [self.session])
        self.meters = [{"ts": f"2026-09-15T01:0{i}:00", "type": "meter", "station_id": "charger-1", "connector_id": "1",
                        "session_id": "session-1", "voltage_v": "400", "current_a": "1.5", "power_kw": "0.6",
                        "energy_kwh": str(i * 0.01), "soc_pct": str(50+i)} for i in (1, 2)]
        self.write("data/generated/session_metering.csv", self.meters)

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)

class Task1ValidationTests(Task1Fixture):
    def test_complete_dataset_passes(self):
        result = validate(self.root)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["aemo"]["intervals"], 288)
        self.assertEqual(result["hourly_prices"], 24)

    def test_missing_period_ending_at_next_midnight_is_rejected(self):
        self.write("data/generated/aemo_cache/" + AEMO_NAME, self.aemo[:-1])
        with self.assertRaisesRegex(ValueError, "Incomplete AEMO"):
            validate(self.root)

    def test_duplicate_aemo_interval_is_rejected(self):
        self.write("data/generated/aemo_cache/" + AEMO_NAME, self.aemo + [self.aemo[0]])
        with self.assertRaisesRegex(ValueError, "Duplicate AEMO"):
            validate(self.root)

    def test_duplicate_hourly_price_is_rejected(self):
        self.write("data/generated/prices_hourly.csv", self.prices + [self.prices[0]])
        with self.assertRaisesRegex(ValueError, "Duplicate hourly"):
            validate(self.root)

    def test_silent_wholesale_fallback_is_rejected(self):
        self.prices[0]["wholesale_per_kwh"] = "0"
        self.write("data/generated/prices_hourly.csv", self.prices)
        with self.assertRaisesRegex(ValueError, "Wholesale price differs"):
            validate(self.root)

    def test_wrong_physical_station_mapping_is_rejected(self):
        self.write("data/processed/generator_station_mapping.csv", [
            {"generator_station_id": "charger-1", "physical_station_id": "wrong", "charger_id": "charger-1"}])
        with self.assertRaisesRegex(ValueError, "physical station mapping"):
            validate(self.root)

    def test_overlapping_connector_sessions_are_rejected(self):
        self.write("data/generated/sessions.csv", [self.session, {**self.session, "session_id": "session-2"}])
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            validate(self.root)

    def test_wrong_meter_connector_is_rejected(self):
        self.meters[0]["connector_id"] = "2"
        self.write("data/generated/session_metering.csv", self.meters)
        with self.assertRaisesRegex(ValueError, "Meter identity"):
            validate(self.root)

    def test_missing_meter_minute_is_rejected(self):
        self.write("data/generated/session_metering.csv", self.meters[1:])
        with self.assertRaisesRegex(ValueError, "Missing, duplicate or unordered"):
            validate(self.root)

    def test_decreasing_meter_energy_is_rejected(self):
        self.meters[1]["energy_kwh"] = "0.005"
        self.write("data/generated/session_metering.csv", self.meters)
        with self.assertRaisesRegex(ValueError, "Decreasing meter"):
            validate(self.root)

    def test_teacher_rounding_is_accepted_but_large_mismatch_is_rejected(self):
        self.session.update(energy_kwh="1.23", cost_aud="0.74", avg_kw="37.0", peak_kw="37.0")
        for row in self.meters:
            row.update(power_kw="37.02", current_a="92.6")
        self.meters[0]["energy_kwh"] = "0.617"
        self.meters[1]["energy_kwh"] = "1.234"
        self.write("data/generated/sessions.csv", [self.session])
        self.write("data/generated/session_metering.csv", self.meters)
        self.assertEqual(validate(self.root)["result"], "PASS")
        self.meters[1]["energy_kwh"] = "1.25"
        self.write("data/generated/session_metering.csv", self.meters)
        with self.assertRaisesRegex(ValueError, "exceeds final"):
            validate(self.root)

    def test_inconsistent_voltage_current_power_is_rejected(self):
        self.meters[0].update(power_kw="99999", voltage_v="1", current_a="1")
        self.write("data/generated/session_metering.csv", self.meters)
        with self.assertRaisesRegex(ValueError, "power differs from voltage/current"):
            validate(self.root)

    def test_inconsistent_minute_power_and_energy_is_rejected(self):
        self.meters[0].update(power_kw="1.2", current_a="3.0")
        self.write("data/generated/session_metering.csv", self.meters)
        with self.assertRaisesRegex(ValueError, "energy increment differs"):
            validate(self.root)

    def test_incorrect_session_average_power_is_rejected(self):
        self.session["avg_kw"] = "2.0"
        self.write("data/generated/sessions.csv", [self.session])
        with self.assertRaisesRegex(ValueError, "average power mismatch"):
            validate(self.root)

    def test_incorrect_session_peak_power_is_rejected(self):
        self.session["peak_kw"] = "2.0"
        self.write("data/generated/sessions.csv", [self.session])
        with self.assertRaisesRegex(ValueError, "peak power mismatch"):
            validate(self.root)

    def test_sessions_started_in_day_may_finish_next_day(self):
        self.session.update(start_ts="2026-09-15T23:59:00", charge_end_ts="2026-09-16T00:01:00", end_ts="2026-09-16T00:02:00")
        self.meters[0]["ts"] = "2026-09-16T00:00:00"
        self.meters[1]["ts"] = "2026-09-16T00:01:00"
        self.write("data/generated/sessions.csv", [self.session])
        self.write("data/generated/session_metering.csv", self.meters)
        self.assertEqual(validate(self.root)["sessions_ending_after_generation_day"], 1)


class Task1RunnerTests(Task1Fixture):
    def setUp(self):
        super().setUp()
        teacher = self.root / "vendor/data_generator/generate_dataset.py"
        teacher.parent.mkdir(parents=True)
        teacher.write_text("# Protected teacher fixture\n", encoding="utf-8")
        # Keep this test focused on runner state; the validator reads real CSV fixtures.
        self.process = self.enterContext(patch.object(run_task1.subprocess, "run"))
        self.process.return_value = subprocess.CompletedProcess([], 0, "generated\n", "")
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(redirect_stderr(io.StringIO()))
        run_task1.main(self.root)
        self.old_started = self.report("run")["started_utc"]
        for name in ("run", "aemo_validation", "validation"):
            self.assertEqual(self.report(name)["result"], "PASS")

    def report(self, name):
        return json.loads((self.root / f"docs/task1_{name}.json").read_text(encoding="utf-8"))

    def assert_failed_run(self, stage, validation_status, preflight_status):
        run = self.report("run")
        self.assertEqual(run["result"], "FAIL")
        self.assertEqual(run["stage"], stage)
        self.assertEqual(run["validation_result"], validation_status)
        self.assertNotEqual(run["started_utc"], self.old_started)
        self.assertGreaterEqual(run["finished_utc"], run["started_utc"])
        self.assertTrue(run["error"])
        self.assertNotIn("output_sha256", run)
        for name, expected in (("validation", validation_status), ("aemo_validation", preflight_status)):
            report = self.report(name)
            self.assertEqual(report["result"], expected)
            self.assertEqual(report["started_utc"], run["started_utc"])

    def test_success_then_incomplete_aemo_does_not_retain_pass(self):
        self.write("data/generated/aemo_cache/" + AEMO_NAME, self.aemo[:-1])
        with self.assertRaisesRegex(ValueError, "Incomplete AEMO"):
            run_task1.main(self.root)
        self.assert_failed_run("preflight", "NOT_RUN", "FAIL")
        self.assertEqual(self.process.call_count, 1)

    def test_success_then_download_failure_does_not_retain_pass(self):
        (self.out / "aemo_cache" / AEMO_NAME).unlink()
        with patch.object(run_task1.urllib.request, "urlopen", side_effect=OSError("download unavailable")):
            with self.assertRaisesRegex(OSError, "download unavailable"):
                run_task1.main(self.root)
        self.assert_failed_run("preflight", "NOT_RUN", "FAIL")

    def test_success_then_generator_failure_does_not_retain_pass(self):
        def fail_generation(*args, **kwargs):
            self.assertEqual(self.report("run")["result"], "RUNNING")
            self.assertEqual(self.report("validation")["result"], "NOT_RUN")
            return subprocess.CompletedProcess([], 7, "", "generator error")
        self.process.side_effect = fail_generation
        with self.assertRaisesRegex(RuntimeError, "Generator exited with code 7"):
            run_task1.main(self.root)
        self.assert_failed_run("generation", "NOT_RUN", "PASS")
        self.assertEqual(self.report("run")["generator_exit_code"], 7)
        self.assertIn("generator error", (self.root / "logs/task1_generation.log").read_text(encoding="utf-8"))

    def test_success_then_process_launch_failure_does_not_retain_pass(self):
        self.process.side_effect = OSError("cannot launch generator")
        with self.assertRaisesRegex(OSError, "cannot launch generator"):
            run_task1.main(self.root)
        self.assert_failed_run("generation", "NOT_RUN", "PASS")

    def test_success_then_invalid_output_does_not_retain_pass(self):
        self.meters[0].update(power_kw="99999", voltage_v="1", current_a="1")
        self.write("data/generated/session_metering.csv", self.meters)
        with self.assertRaisesRegex(ValueError, "power differs from voltage/current"):
            run_task1.main(self.root)
        self.assert_failed_run("validation", "FAIL", "PASS")
        self.assertEqual(self.report("validation")["error"], self.report("run")["error"])


if __name__ == "__main__":
    unittest.main()
