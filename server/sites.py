"""Start the app on the network: plain HTTP (always), HTTPS (if on) and the mDNS name.
Shared by the launcher (launcher/backend.py) and `python -m server`."""

import asyncio
import logging

from aiohttp import web

from server import mdns

log = logging.getLogger("cdlivemap.server")
LOOPBACK = "127.0.0.1"


class Sites:
    def __init__(self, runner, mdns_transport):
        self.runner, self.mdns = runner, mdns_transport

    async def stop(self):
        if self.mdns:
            self.mdns.close()
        await self.runner.cleanup()


async def start(app, config, hosts):
    """Listen on every host; raises OSError (naming the port) when a port is taken."""
    runner = web.AppRunner(app)
    await runner.setup()
    lan = [h for h in hosts if h != LOOPBACK]
    port = config.port
    try:
        for host in hosts:
            await web.TCPSite(runner, host, port).start()
        if config.https:
            port = config.https_port
            ctx = await asyncio.get_running_loop().run_in_executor(None, app["tls"].ssl_context, lan)
            for host in hosts:
                await web.TCPSite(runner, host, port, ssl_context=ctx).start()
    except OSError as e:
        await runner.cleanup()
        raise OSError(e.errno, f"Cannot listen on port {port}: {e.strerror or e}") from e
    transport = await mdns.start(lan) if config.mdns else None
    return Sites(runner, transport)
