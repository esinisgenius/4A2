import argparse
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import re
import sys
from threading import Event
import time

import paho.mqtt.client as mqtt

try:
    from .analytics_storage import AnalyticsStorage, DEFAULT_DATABASE, validate_event
except ImportError:
    from analytics_storage import AnalyticsStorage, DEFAULT_DATABASE, validate_event


SUFFIX = {
    'price_update': 'prices', 'session_start': 'sessions/start',
    'meter': 'sessions/meter', 'session_end': 'sessions/end',
}


class OrderedReceiver:
    """Bounded gap buffer; return packet IDs only after their database commit."""

    def __init__(self, storage, run_id, prefix='comp5339/a2', max_pending=10000):
        self.storage, self.run_id, self.prefix = storage, run_id, prefix
        self.max_pending = max_pending
        self.pending = {}
        self.waiting_since = None
        self.packets = self.duplicates = self.accepted = 0
        self.last_sequence = storage.con.execute(
            'SELECT COALESCE(MAX(sequence),0) FROM mqtt_events WHERE run_id=?',
            [run_id],
        ).fetchone()[0]

    def receive(self, topic, raw, mid, qos, retained=False):
        if retained or qos != 1:
            raise ValueError('Expected non-retained QoS 1 event')
        e = json.loads(raw.decode('utf-8'))
        validate_event(e)
        if e['run_id'] != self.run_id:
            raise ValueError('Payload run_id differs from selected run')
        expected = (f'{self.prefix}/runs/{self.run_id}/stations/{e["station_id"]}'
                    f'/chargers/{e["charger_id"]}/{SUFFIX[e["event_type"]]}')
        if topic != expected:
            raise ValueError('Topic and payload IDs/type disagree')
        self.packets += 1
        seq = e['sequence']
        if seq <= self.last_sequence:
            if self.storage.save_event(e):
                raise RuntimeError('Unexpected insertion behind current sequence')
            self.duplicates += 1
            return [(mid, qos)]
        if seq in self.pending:
            saved, receipts = self.pending[seq]
            if saved != e:
                raise ValueError('Conflicting events for pending sequence')
            if len(receipts) >= self.max_pending:
                raise ValueError('Too many pending duplicate packets')
            receipts.append((mid, qos))
            self.duplicates += 1
        else:
            if len(self.pending) >= self.max_pending:
                raise ValueError('Sequence gap buffer is full')
            self.pending[seq] = (e, [(mid, qos)])
        acknowledged = []
        while self.last_sequence + 1 in self.pending:
            next_seq = self.last_sequence + 1
            event, receipts = self.pending[next_seq]
            if not self.storage.save_event(event):
                raise RuntimeError('Unexpected existing event ahead of current sequence')
            del self.pending[next_seq]
            self.last_sequence = next_seq
            self.accepted += 1
            acknowledged.extend(receipts)
        if not self.pending:
            self.waiting_since = None
        elif self.waiting_since is None or acknowledged:
            self.waiting_since = time.monotonic()
        return acknowledged


def receive_stream(args):
    messages = Queue(maxsize=10000)
    ready, failed = Event(), Event()
    errors = []
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv311, clean_session=True,
        manual_ack=True, reconnect_on_failure=False,
    )

    def fail(message):
        errors.append(message)
        failed.set()

    def connected(client, userdata, flags, reason, properties):
        if reason.is_failure:
            fail(f'Connection rejected: {reason}')
        else:
            result, _ = client.subscribe(f'{args.prefix}/runs/{args.run_id}/#', qos=1)
            if result != mqtt.MQTT_ERR_SUCCESS:
                fail('Subscribe request failed')

    def subscribed(client, userdata, mid, reasons, properties):
        if not reasons or any(r.is_failure or r.value != 1 for r in reasons):
            fail('Broker did not grant QoS 1 subscription')
        else:
            ready.set()
            print(f'SUBACK: ready for run {args.run_id}; start Publisher now.', flush=True)

    def received(client, userdata, message):
        try:
            messages.put_nowait((message.topic, message.payload, message.mid,
                                 message.qos, message.retain))
        except Full:
            fail('Receive queue full; stopped without acknowledging unsaved events')

    def disconnected(client, userdata, flags, reason, properties):
        fail(f'Broker disconnected ({reason}); verify persisted prefix before recovery')

    client.on_connect, client.on_subscribe = connected, subscribed
    client.on_message, client.on_disconnect = received, disconnected
    if os.environ.get('MQTT_USERNAME'):
        client.username_pw_set(os.environ['MQTT_USERNAME'], os.environ.get('MQTT_PASSWORD'))
    if args.tls:
        client.tls_set(ca_certs=args.ca_file)

    with AnalyticsStorage(args.database) as storage:
        receiver = OrderedReceiver(storage, args.run_id, args.prefix)
        try:
            client.connect(args.host, args.port, keepalive=60)
            client.loop_start()
            deadline = time.monotonic() + args.timeout
            while not ready.is_set():
                if failed.is_set():
                    raise RuntimeError(errors[0])
                if time.monotonic() >= deadline:
                    raise TimeoutError('Timed out waiting for SUBACK')
                ready.wait(0.1)
            while True:
                if failed.is_set():
                    raise RuntimeError(errors[0])
                if (receiver.waiting_since is not None and
                        time.monotonic() - receiver.waiting_since > args.gap_timeout):
                    raise TimeoutError(f'Missing sequence {receiver.last_sequence + 1}')
                try:
                    packet = messages.get(timeout=0.5)
                except Empty:
                    continue
                before = receiver.last_sequence
                for mid, qos in receiver.receive(*packet):
                    if client.ack(mid, qos) != mqtt.MQTT_ERR_SUCCESS:
                        raise RuntimeError('Could not acknowledge persisted packet')
                if receiver.last_sequence // 100 > before // 100:
                    print(f'SAVED through sequence {receiver.last_sequence}', flush=True)
                if args.expected_count is not None:
                    if receiver.last_sequence > args.expected_count:
                        raise ValueError('Received more events than expected')
                    if receiver.last_sequence == args.expected_count and not receiver.pending:
                        break
        except KeyboardInterrupt:
            if receiver.pending:
                raise RuntimeError('Stopped with a sequence gap; buffered events are not persisted')
        finally:
            client.disconnect()
            client.loop_stop()
            count = storage.con.execute(
                'SELECT count(*) FROM mqtt_events WHERE run_id=?', [args.run_id]
            ).fetchone()[0]
            print(json.dumps({
                'run_id': args.run_id, 'unique_events_in_database': count,
                'accepted_this_process': receiver.accepted,
                'duplicate_packets': receiver.duplicates,
                'pending_sequences': len(receiver.pending),
            }), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--host', default=os.environ.get('MQTT_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=1883)
    parser.add_argument('--prefix', default='comp5339/a2')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--gap-timeout', type=float, default=30)
    parser.add_argument('--expected-count', type=int,
                        help='Optional known stream size; exit after persisting this prefix')
    parser.add_argument('--tls', action='store_true')
    parser.add_argument('--ca-file')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', args.run_id):
        parser.error('Invalid run_id')
    if not args.prefix or any(c in args.prefix for c in '+#\x00') or args.prefix.endswith('/'):
        parser.error('Invalid topic prefix')
    if not 1 <= args.port <= 65535 or args.timeout <= 0 or args.gap_timeout <= 0:
        parser.error('Invalid port or timeout')
    if args.expected_count is not None and args.expected_count < 1:
        parser.error('expected-count must be positive')
    try:
        receive_stream(args)
    except Exception as exc:
        print(f'Subscriber stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
