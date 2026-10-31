import json
import math
import re
from datetime import datetime
from pathlib import Path

import duckdb


DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / 'database/charger_analytics.duckdb'


def _utc(value):
    if not isinstance(value, str) or not re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value
    ):
        raise ValueError('Expected UTC timestamp YYYY-MM-DDTHH:MM:SSZ')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


def validate_event(e):
    """Validate required fields before making any database changes."""
    if not isinstance(e, dict):
        raise ValueError('Event must be a JSON object')
    for field in ('run_id', 'event_id', 'dataset_id', 'schema_version',
                  'event_type', 'event_time', 'station_id', 'charger_id'):
        if not isinstance(e.get(field), str) or not e[field]:
            raise ValueError(f'Missing or invalid string: {field}')
    if e['schema_version'] != '1.0':
        raise ValueError('Unsupported schema_version')
    if type(e.get('sequence')) is not int or e['sequence'] < 1:
        raise ValueError('sequence must be a positive integer')
    _utc(e['event_time'])
    numeric = {
        'price_update': ('price_per_kwh',),
        'session_start': ('price_per_kwh',),
        'meter': ('voltage_v', 'current_a', 'power_kw', 'energy_kwh', 'soc_pct'),
        'session_end': ('energy_kwh', 'charge_minutes', 'avg_kw', 'peak_kw',
                        'price_per_kwh', 'cost_aud'),
    }
    kind = e['event_type']
    if kind not in numeric:
        raise ValueError('Unknown event_type')
    for field in numeric[kind]:
        value = e.get(field)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'Missing or invalid number: {field}')
    if kind != 'meter' and e.get('currency') != 'AUD':
        raise ValueError('currency must be AUD')
    if kind == 'price_update':
        if e.get('price_unit') != 'AUD/kWh':
            raise ValueError('price_unit must be AUD/kWh')
    else:
        if not isinstance(e.get('session_id'), str) or not e['session_id']:
            raise ValueError('Missing session_id')
        if not isinstance(e.get('connector_id'), str) or not re.fullmatch(
            r'[1-9][0-9]*', e['connector_id']
        ):
            raise ValueError('Invalid connector_id')
    if kind == 'session_start':
        for field in ('vehicle_model', 'site_type'):
            if not isinstance(e.get(field), str):
                raise ValueError(f'Missing or invalid {field}')
    if kind == 'session_end':
        if _utc(e.get('charge_end_time')) > _utc(e['event_time']):
            raise ValueError('Charging completion cannot follow unplug time')


class AnalyticsStorage:
    """Persist events and derived state atomically; False means exact duplicate."""

    def __init__(self, database=DEFAULT_DATABASE):
        path = Path(database)
        if not path.is_file():
            raise FileNotFoundError(f'Initialize database and schema first: {path}')
        self.con = duckdb.connect(str(path))
        self.con.execute("SET TimeZone='UTC'")

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def save_event(self, event):
        validate_event(event)
        payload = json.dumps(event, sort_keys=True, allow_nan=False)
        e = json.loads(payload)
        run, seq = e['run_id'], e['sequence']
        db = self.con
        db.execute('BEGIN TRANSACTION')
        try:
            old = db.execute(
                'SELECT payload FROM mqtt_events WHERE run_id=? AND event_id=?',
                [run, e['event_id']],
            ).fetchone()
            if old:
                if json.loads(old[0]) != e:
                    raise ValueError('Existing event_id has conflicting payload')
                db.execute('COMMIT')
                return False
            previous = db.execute(
                'SELECT COALESCE(MAX(sequence),0), MIN(dataset_id) '
                'FROM mqtt_events WHERE run_id=?', [run]
            ).fetchone()
            if seq != previous[0] + 1:
                raise ValueError(f'Expected sequence {previous[0] + 1}, received {seq}')
            if previous[1] is not None and previous[1] != e['dataset_id']:
                raise ValueError('A run cannot mix datasets')
            pairing = db.execute(
                'SELECT station_id FROM chargers WHERE charger_id=?', [e['charger_id']]
            ).fetchone()
            if not pairing or pairing[0] != e['station_id']:
                raise ValueError('Unknown charger or incorrect station/charger pairing')
            fields = ('run_id', 'event_id', 'dataset_id', 'schema_version', 'sequence',
                      'event_type', 'event_time', 'station_id', 'charger_id',
                      'session_id', 'connector_id')
            db.execute(
                f"INSERT INTO mqtt_events ({','.join(fields)},payload) "
                f"VALUES ({','.join(['?'] * 12)})",
                [e.get(f) for f in fields] + [payload],
            )
            self._update_state(e)
            db.execute('COMMIT')
            return True
        except Exception:
            db.execute('ROLLBACK')
            raise

    def _update_state(self, e):
        db = self.con
        run, charger, seq = e['run_id'], e['charger_id'], e['sequence']
        kind = e['event_type']
        if kind == 'price_update':
            db.execute(
                'INSERT INTO charger_current_state VALUES (?,?,?,?,?,?,?,?) '
                'ON CONFLICT (run_id,charger_id) DO UPDATE SET '
                'price_per_kwh=excluded.price_per_kwh, '
                'event_time=excluded.event_time, last_sequence=excluded.last_sequence',
                [run, charger, e['station_id'], e['price_per_kwh'], e['currency'],
                 e['price_unit'], e['event_time'], seq],
            )
            return
        session, connector = e['session_id'], e['connector_id']
        if kind == 'session_start':
            db.execute(
                'INSERT INTO charging_sessions '
                '(run_id,session_id,station_id,charger_id,connector_id,vehicle_model,'
                'site_type,start_time,status,price_per_kwh,currency,last_sequence) '
                "VALUES (?,?,?,?,?,?,?,?,'active',?,?,?)",
                [run, session, e['station_id'], charger, connector, e['vehicle_model'],
                 e['site_type'], e['event_time'], e['price_per_kwh'], e['currency'], seq],
            )
            db.execute('INSERT INTO active_connectors VALUES (?,?,?,?,?)',
                       [run, charger, connector, session, seq])
            return
        existing = db.execute(
            "SELECT charger_id,connector_id,status,price_per_kwh,"
            "strftime(start_time, '%Y-%m-%dT%H:%M:%SZ') "
            'FROM charging_sessions WHERE run_id=? AND session_id=?', [run, session]
        ).fetchone()
        if not existing or existing[:3] != (charger, connector, 'active'):
            raise ValueError('Meter/end requires a matching active session')
        if _utc(e['event_time']) < _utc(existing[4]):
            raise ValueError('Session event predates start')
        occupied = db.execute(
            'SELECT session_id FROM active_connectors '
            'WHERE run_id=? AND charger_id=? AND connector_id=?',
            [run, charger, connector],
        ).fetchone()
        if occupied != (session,):
            raise ValueError('Active connector does not match session')
        if kind == 'meter':
            db.execute('UPDATE charging_sessions SET energy_kwh=?,last_sequence=? '
                       'WHERE run_id=? AND session_id=?',
                       [e['energy_kwh'], seq, run, session])
            db.execute('UPDATE active_connectors SET last_sequence=? '
                       'WHERE run_id=? AND charger_id=? AND connector_id=?',
                       [seq, run, charger, connector])
        else:
            if e['price_per_kwh'] != existing[3]:
                raise ValueError('End tariff differs from locked start tariff')
            if _utc(e['charge_end_time']) < _utc(existing[4]):
                raise ValueError('Charging completion predates start')
            db.execute(
                "UPDATE charging_sessions SET status='completed',end_time=?,"
                'charge_end_time=?,energy_kwh=?,charge_minutes=?,avg_kw=?,peak_kw=?,'
                'cost_aud=?,last_sequence=? WHERE run_id=? AND session_id=?',
                [e['event_time'], e['charge_end_time'], e['energy_kwh'],
                 e['charge_minutes'], e['avg_kw'], e['peak_kw'], e['cost_aud'],
                 seq, run, session],
            )
            db.execute('DELETE FROM active_connectors WHERE run_id=? AND charger_id=? '
                       'AND connector_id=? AND session_id=?',
                       [run, charger, connector, session])
