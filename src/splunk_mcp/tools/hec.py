"""HTTP Event Collector (HEC) tools: global settings, tokens, and sending events.

HEC (port 8088) is the modern, token-authenticated ingest path - ideal for
structured events from scripts, forwarders, or the other lab MCPs.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_hec_settings() -> str:
        """Global HEC settings (whether HEC is enabled, port, SSL)."""
        rows = client.unwrap_entries(await client.get("/services/data/inputs/http/http"))
        return dumps(rows[0] if rows else {})

    @mcp.tool()
    async def splunk_enable_hec(enable_ssl: bool = True, port: int = 8088) -> str:
        """Enable the HEC listener globally (disabled=0). Do this before creating tokens."""
        body = {"disabled": 0, "enableSSL": 1 if enable_ssl else 0, "port": port}
        return dumps(await client.post("/services/data/inputs/http/http", data=body))

    @mcp.tool()
    async def splunk_list_hec_tokens() -> str:
        """List HEC tokens (name, token value, index, sourcetype, disabled)."""
        rows = await client.list_entries("/services/data/inputs/http")
        slim = []
        for r in rows:
            if r.get("name") in ("http", "http://http"):
                continue  # the global settings entry, not a token
            slim.append({k: r.get(k) for k in (
                "name", "token", "index", "indexes", "sourcetype", "disabled")})
        return dumps(slim)

    @mcp.tool()
    async def splunk_create_hec_token(
        name: str,
        index: str = "main",
        sourcetype: str | None = None,
    ) -> str:
        """Create a HEC token input and return its token value.

        Use the returned token as SPLUNK_HEC_TOKEN (or pass to splunk_send_hec_event)
        to POST events to :8088. Enable HEC globally first (splunk_enable_hec).
        """
        body: dict = {"name": name, "index": index}
        if sourcetype:
            body["sourcetype"] = sourcetype
        data = await client.post("/services/data/inputs/http", data=body)
        rows = client.unwrap_entries(data)
        info = rows[0] if rows else data
        token = info.get("token") if isinstance(info, dict) else None
        return dumps({"name": name, "token": token, "detail": info})

    @mcp.tool()
    async def splunk_delete_hec_token(name: str) -> str:
        """Delete a HEC token input."""
        return dumps(await client.delete(f"/services/data/inputs/http/{name}"))

    @mcp.tool()
    async def splunk_send_hec_event(
        event: str,
        index: str | None = None,
        sourcetype: str | None = None,
        source: str | None = None,
        host: str | None = None,
        token: str | None = None,
    ) -> str:
        """Send one event to HEC (:8088). `event` is the raw event text (or JSON string).

        Uses SPLUNK_HEC_TOKEN unless `token` is given. Useful to smoke-test ingest
        or push a synthetic event. Returns HEC's ack response.
        """
        envelope: dict = {"event": event}
        if index:
            envelope["index"] = index
        if sourcetype:
            envelope["sourcetype"] = sourcetype
        if source:
            envelope["source"] = source
        if host:
            envelope["host"] = host
        return dumps(await client.hec_send([envelope], token=token))
