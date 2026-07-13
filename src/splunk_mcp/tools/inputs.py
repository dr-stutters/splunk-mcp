"""Data-input tools: TCP/UDP (syslog) and file-monitor inputs for ingest.

These are how Cisco/Windows devices get data into Splunk: point a device's
syslog at a UDP or TCP input here, or monitor a log file. (HEC is separate -
see the hec tools.)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps

_SLIM = ("name", "disabled", "index", "sourcetype", "source", "connection_host", "queue")


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_list_inputs() -> str:
        """List the common data inputs (TCP raw, UDP, file monitors) with their
        index/sourcetype. UDP/TCP are the usual syslog receivers for network gear."""
        out = {}
        for label, path in (
            ("udp", "/services/data/inputs/udp"),
            ("tcp", "/services/data/inputs/tcp/raw"),
            ("monitor", "/services/data/inputs/monitor"),
        ):
            try:
                rows = await client.list_entries(path)
                out[label] = [{k: r.get(k) for k in _SLIM if k in r} for r in rows]
            except Exception as e:
                out[label] = f"error: {str(e)[:80]}"
        return dumps(out)

    @mcp.tool()
    async def splunk_create_udp_input(
        port: int,
        sourcetype: str | None = None,
        index: str = "main",
        connection_host: str = "ip",
    ) -> str:
        """Open a UDP input (classic syslog receiver, e.g. port 514) for network devices.

        Args:
            port: UDP port to listen on (e.g. 514).
            sourcetype: sourcetype to tag events (e.g. 'cisco:ios', 'cisco:asa'); optional.
            index: destination index (default 'main').
            connection_host: how to set the event host - 'ip', 'dns', or 'none'.
        """
        body: dict = {"name": str(port), "index": index, "connection_host": connection_host}
        if sourcetype:
            body["sourcetype"] = sourcetype
        return dumps(await client.post("/services/data/inputs/udp", data=body))

    @mcp.tool()
    async def splunk_create_tcp_input(
        port: int,
        sourcetype: str | None = None,
        index: str = "main",
        connection_host: str = "ip",
    ) -> str:
        """Open a raw TCP input (TCP syslog receiver) on a port."""
        body: dict = {"name": str(port), "index": index, "connection_host": connection_host}
        if sourcetype:
            body["sourcetype"] = sourcetype
        return dumps(await client.post("/services/data/inputs/tcp/raw", data=body))

    @mcp.tool()
    async def splunk_create_monitor_input(
        path: str,
        sourcetype: str | None = None,
        index: str = "main",
    ) -> str:
        """Monitor a file or directory on the Splunk host and ingest new lines."""
        body: dict = {"name": path, "index": index}
        if sourcetype:
            body["sourcetype"] = sourcetype
        return dumps(await client.post("/services/data/inputs/monitor", data=body))

    @mcp.tool()
    async def splunk_delete_input(
        kind: str,
        name: str,
    ) -> str:
        """Delete a data input. kind is one of 'udp', 'tcp', 'monitor'; name is the
        input's name (the port for udp/tcp, the path for monitor)."""
        sub = {"udp": "udp", "tcp": "tcp/raw", "monitor": "monitor"}.get(kind)
        if not sub:
            raise ValueError("kind must be 'udp', 'tcp', or 'monitor'")
        return dumps(await client.delete(f"/services/data/inputs/{sub}/{name}"))
