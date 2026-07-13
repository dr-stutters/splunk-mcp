"""System tools: server info, settings, health, messages, licensing."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_server_info() -> str:
        """Server info: version, build, server name/roles, GUID, OS, CPU/RAM as
        Splunk sees them, and licensing state. Good first call."""
        data = await client.get("/services/server/info")
        rows = client.unwrap_entries(data)
        return dumps(rows[0] if rows else data)

    @mcp.tool()
    async def splunk_server_settings() -> str:
        """Server settings: mgmt/web ports, SSL, session timeout, default index paths."""
        rows = client.unwrap_entries(await client.get("/services/server/settings"))
        return dumps(rows[0] if rows else {})

    @mcp.tool()
    async def splunk_health() -> str:
        """Overall splunkd health tree (feature colours: green/yellow/red)."""
        return dumps(client.unwrap_entries(await client.get("/services/server/health/splunkd")))

    @mcp.tool()
    async def splunk_messages() -> str:
        """Server-level messages / banner notifications (warnings, errors, info)."""
        return dumps(client.unwrap_entries(await client.get("/services/messages")))

    @mcp.tool()
    async def splunk_licensing() -> str:
        """Installed licenses (type, quota bytes, expiry) and license stack usage."""
        out = {
            "licenses": client.unwrap_entries(await client.get("/services/licenser/licenses")),
            "usage": client.unwrap_entries(await client.get("/services/licenser/pools")),
        }
        return dumps(out)

    @mcp.tool()
    async def splunk_check() -> str:
        """Probe what answers from here: management REST (8089) and, if a HEC token
        is configured, the HEC endpoint (8088). Handy first reachability check."""
        out = {}
        try:
            rows = client.unwrap_entries(await client.get("/services/server/info"))
            info = rows[0] if rows else {}
            out["management_8089"] = (
                f"reachable - Splunk {info.get('version')} ({info.get('serverName')})")
        except Exception as e:
            out["management_8089"] = f"unreachable: {str(e)[:100]}"
        if client.settings.hec_token:
            try:
                await client.hec_send([{"event": "splunk-mcp reachability probe"}])
                out["hec_8088"] = "reachable (test event accepted)"
            except Exception as e:
                out["hec_8088"] = f"unreachable: {str(e)[:100]}"
        else:
            out["hec_8088"] = "no HEC token configured (SPLUNK_HEC_TOKEN unset)"
        return dumps(out)
