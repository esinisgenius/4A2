"""Optional loopback-only MQTT broker for a single-computer group demonstration."""
import argparse
import asyncio
import logging


async def serve(port: int) -> None:
    from amqtt.broker import Broker

    broker = Broker({
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    })
    await broker.start()
    print(f"Local MQTT broker ready at 127.0.0.1:{port}; Ctrl+C to stop", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(serve(args.port))
    except KeyboardInterrupt:
        pass
