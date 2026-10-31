
import argparse
import json
from pathlib import Path

import duckdb

try:
    from .analytics_storage import DEFAULT_DATABASE
except ImportError:
    from analytics_storage import DEFAULT_DATABASE


class AnalyticsQueries:
    def __init__(self, database=DEFAULT_DATABASE, *, connection=None):
        self._owns_connection = connection is None
        if connection is None:
            path = Path(database)
            if not path.is_file():
                raise FileNotFoundError(path)
            self.con = duckdb.connect(str(path), read_only=True)
        else:
            self.con = connection
        self.con.execute("SET TimeZone='UTC'")

    def close(self):
        if self._owns_connection:
            self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _rows(self, sql, parameters=()):
        result = self.con.execute(sql, parameters)
        names = [column[0] for column in result.description]
        return [dict(zip(names, row)) for row in result.fetchall()]

    def _require_run(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ValueError('run_id must be a nonempty string')
        if not self.con.execute(
            'SELECT 1 FROM mqtt_events WHERE run_id=? LIMIT 1', [run_id]
        ).fetchone():
            raise ValueError(f'No received events for run_id: {run_id}')

    def _require_station(self, station_id):
        if not self.con.execute(
            'SELECT 1 FROM stations WHERE station_id=?', [station_id]
        ).fetchone():
            raise ValueError(f'Unknown station_id: {station_id}')

    @staticmethod
    def _page(limit, offset):
        if type(limit) is not int or not 1 <= limit <= 100000:
            raise ValueError('limit must be an integer between 1 and 100000')
        if type(offset) is not int or offset < 0:
            raise ValueError('offset must be a nonnegative integer')

    def list_runs(self):
        """Received runs and their actual event coverage, including initialization."""
        return self._rows("""
            SELECT run_id, MIN(dataset_id) AS dataset_id, COUNT(*) AS event_count,
                   MAX(sequence) AS last_sequence,
                   strftime(MIN(event_time), '%Y-%m-%dT%H:%M:%SZ') AS first_event_time,
                   strftime(MAX(event_time), '%Y-%m-%dT%H:%M:%SZ') AS last_event_time
            FROM mqtt_events GROUP BY run_id ORDER BY run_id
        """)

    def get_run_metrics(self, run_id, station_id=None):
        """Session counts and completed-session energy/cost for one run or site.

        Unknown runs/sites raise ValueError. A known site with no sessions returns
        zero metrics; this does not establish its real-world availability.
        """
        self._require_run(run_id)
        where, params = 'run_id=?', [run_id]
        if station_id is not None:
            self._require_station(station_id)
            where += ' AND station_id=?'
            params.append(station_id)
        metrics = self._rows(f"""
            SELECT COUNT(*) FILTER (WHERE status='active') AS active_sessions,
                   COUNT(*) FILTER (WHERE status='completed') AS completed_sessions,
                   COALESCE(SUM(energy_kwh) FILTER (WHERE status='completed'),0)
                       AS completed_energy_kwh,
                   COALESCE(SUM(cost_aud) FILTER (WHERE status='completed'),0)
                       AS completed_cost_aud
            FROM charging_sessions WHERE {where}
        """, params)[0]
        coverage = self._rows(f"""
            SELECT COUNT(*) AS event_count,
                   strftime(MIN(event_time), '%Y-%m-%dT%H:%M:%SZ') AS first_event_time,
                   strftime(MAX(event_time), '%Y-%m-%dT%H:%M:%SZ') AS last_event_time
            FROM mqtt_events WHERE {where}
        """, params)[0]
        return dict(run_id=run_id, station_id=station_id, **metrics, **coverage)

    def get_station_metrics(self, run_id, station_id):
        return self.get_run_metrics(run_id, station_id)

    def get_charger_states(self, run_id, station_id=None):
        """Metadata plus observed price/occupancy, one row per configuration.

        Missing price is None. active_connectors counts observed occupied
        connectors, not total physical sockets or guaranteed available sockets.
        """
        self._require_run(run_id)
        where, params = '', [run_id, run_id]
        if station_id is not None:
            self._require_station(station_id)
            where = 'WHERE c.station_id=?'
            params.append(station_id)
        return self._rows(f"""
            SELECT c.station_id, c.charger_id, s.station_name,
                   p.price_per_kwh, p.currency, p.price_unit,
                   strftime(p.event_time, '%Y-%m-%dT%H:%M:%SZ') AS price_event_time,
                   COALESCE(a.active_connectors,0) AS active_connectors
            FROM chargers c JOIN stations s ON s.station_id=c.station_id
            LEFT JOIN charger_current_state p ON p.charger_id=c.charger_id AND p.run_id=?
            LEFT JOIN (
                SELECT charger_id, COUNT(*) AS active_connectors
                FROM active_connectors WHERE run_id=? GROUP BY charger_id
            ) a ON a.charger_id=c.charger_id
            {where} ORDER BY c.station_id,c.charger_id
        """, params)

    def get_sessions(self, run_id, station_id=None, status=None, *, limit=1000, offset=0):
        self._require_run(run_id)
        self._page(limit, offset)
        where, params = 'run_id=?', [run_id]
        if station_id is not None:
            self._require_station(station_id)
            where += ' AND station_id=?'
            params.append(station_id)
        if status is not None:
            if status not in ('active', 'completed'):
                raise ValueError('status must be active or completed')
            where += ' AND status=?'
            params.append(status)
        return self._rows(f"""
            SELECT run_id,session_id,station_id,charger_id,connector_id,
                   vehicle_model,site_type,status,price_per_kwh,currency,
                   energy_kwh,charge_minutes,avg_kw,peak_kw,cost_aud,last_sequence,
                   strftime(start_time,'%Y-%m-%dT%H:%M:%SZ') AS start_time,
                   strftime(end_time,'%Y-%m-%dT%H:%M:%SZ') AS end_time,
                   strftime(charge_end_time,'%Y-%m-%dT%H:%M:%SZ') AS charge_end_time
            FROM charging_sessions WHERE {where}
            ORDER BY start_time,session_id LIMIT ? OFFSET ?
        """, params + [limit, offset])

    def get_meter_history(self, run_id, session_id, *, limit=10000, offset=0):
        self._require_run(run_id)
        self._page(limit, offset)
        if not self.con.execute(
            'SELECT 1 FROM charging_sessions WHERE run_id=? AND session_id=?',
            [run_id, session_id],
        ).fetchone():
            raise ValueError('Unknown session in selected run')
        return self._rows("""
            SELECT run_id,session_id,event_id,sequence,station_id,charger_id,connector_id,
                   strftime(event_time,'%Y-%m-%dT%H:%M:%SZ') AS event_time,
                   voltage_v,current_a,power_kw,energy_kwh,soc_pct
            FROM meter_history WHERE run_id=? AND session_id=?
            ORDER BY sequence LIMIT ? OFFSET ?
        """, [run_id, session_id, limit, offset])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--run-id', help='Omit to list received runs')
    parser.add_argument('--station-id')
    args = parser.parse_args()
    if args.station_id and not args.run_id:
        parser.error('--station-id requires --run-id')
    try:
        with AnalyticsQueries(args.database) as queries:
            result = queries.get_run_metrics(args.run_id, args.station_id) if args.run_id else queries.list_runs()
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, duckdb.Error) as exc:
        parser.exit(1, f'Query failed: {exc}\n')


if __name__ == '__main__':
    main()
