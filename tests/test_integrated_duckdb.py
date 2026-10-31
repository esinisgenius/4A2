"""Smoke-test the unified DuckDB state engine without network dependencies."""
import json
import tempfile
import unittest
from pathlib import Path

from src.analytics_storage import AnalyticsStorage
from src.analytics_subscriber import OrderedReceiver, SUFFIX
from src.analytics_queries import AnalyticsQueries
from src.integrated_runtime import ensure_database

ROOT = Path(__file__).resolve().parents[1]


class IntegratedDuckDBTests(unittest.TestCase):
    def test_committed_mqtt_events_feed_current_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "analytics.duckdb"
            ensure_database(db_path)
            with AnalyticsStorage(db_path) as storage:
                receiver = OrderedReceiver(storage, "integration-test")
                prepared = json.loads((ROOT / "data/events/mqtt_demo/events.json").read_text())
                for event in prepared[:30]:
                    event = dict(event, run_id="integration-test")
                    topic = (f"comp5339/a2/runs/integration-test/stations/{event['station_id']}"
                             f"/chargers/{event['charger_id']}/{SUFFIX[event['event_type']]}")
                    raw = json.dumps(event).encode()
                    receipts = receiver.receive(topic, raw, event["sequence"], 1)
                    self.assertEqual(receipts, [(event["sequence"], 1)])
                self.assertEqual(receiver.last_sequence, 30)
                with AnalyticsQueries(connection=storage.con) as q:
                    m = q.get_run_metrics("integration-test")
                    self.assertEqual(m["event_count"], 30)
                    self.assertEqual(m["active_sessions"], 0)
                    self.assertEqual(m["completed_energy_kwh"], 0)
                    rows = q.get_charger_states("integration-test")
                    self.assertEqual(sum(x["price_per_kwh"] is not None for x in rows), 30)
                duplicate = dict(prepared[0], run_id="integration-test")
                topic = (f"comp5339/a2/runs/integration-test/stations/{duplicate['station_id']}"
                         f"/chargers/{duplicate['charger_id']}/prices")
                self.assertEqual(receiver.receive(topic, json.dumps(duplicate).encode(), 1000, 1),
                                 [(1000, 1)])
                self.assertEqual(storage.con.execute(
                    "SELECT COUNT(*) FROM mqtt_events WHERE run_id='integration-test'"
                ).fetchone()[0], 30)
            # Reopen after release: persisted rather than only in memory.
            with AnalyticsQueries(db_path) as q:
                self.assertEqual(q.get_run_metrics("integration-test")["event_count"], 30)


if __name__ == "__main__":
    unittest.main()
