import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from task3_state import connect, insert, load, project

def event(n, kind, **kw):
    e = dict(schema_version="1.0", dataset_id="ds_test", event_id=f"evt_{n}",
             run_id="runA", sequence=n, event_type=kind,
             event_time=f"2026-09-14T00:00:{n:02d}Z",
             station_id="site1", charger_id="charger1")
    e.update(kw)
    return e

class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = connect(Path(self.tmp.name) / "journal.sqlite")
    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()
    def test_dedup_and_restart(self):
        e = event(1,"price_update",price_per_kwh=.55)
        self.assertTrue(insert(self.con,e,"runA"))
        self.assertFalse(insert(self.con,e,"runA"))
        self.assertEqual(len(load(self.con,"runA")),1)
    def test_out_of_order_waits_for_gap(self):
        first = event(1,"price_update",price_per_kwh=.55)
        third = event(3,"meter",session_id="s1",connector_id="1",energy_kwh=.4,power_kw=24)
        second = event(2,"session_start",session_id="s1",connector_id="1",price_per_kwh=.55)
        for e in (third,first):
            insert(self.con,e,"runA")
        self.assertEqual(project(load(self.con,"runA"))["applied"],1)
        insert(self.con,second,"runA")
        state=project(load(self.con,"runA"))
        self.assertEqual(state["applied"],3)
        self.assertEqual(len(state["active"]),1)
        self.assertEqual(len(state["meters"]["s1"]),1)
    def test_ends_on_unplug_and_run_isolation(self):
        for e in (event(1,"session_start",session_id="s",connector_id="1",price_per_kwh=.6),
                  event(2,"session_end",session_id="s",connector_id="1",energy_kwh=3.,cost_aud=1.8)):
            insert(self.con,e,"runA")
        state=project(load(self.con,"runA"))
        self.assertFalse(state["active"])
        self.assertEqual(len(state["completed"]),1)
        self.assertEqual(load(self.con,"runB"),[])
    def test_conflicting_sequence_is_rejected(self):
        insert(self.con,event(1,"price_update",price_per_kwh=.5))
        with self.assertRaises(ValueError):
            insert(self.con,event(1,"price_update",event_id="other",price_per_kwh=.7))

if __name__ == "__main__":
    unittest.main()
