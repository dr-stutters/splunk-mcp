"""KV Store tools: list collections and read their records (lookups backed by KV)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_list_kvstore_collections(app: str = "search") -> str:
        """List KV Store collections defined in an app."""
        rows = await client.list_entries(
            f"/servicesNS/nobody/{app}/storage/collections/config")
        return dumps([{"name": r.get("name"), "app": r.get("app")} for r in rows])

    @mcp.tool()
    async def splunk_kvstore_records(
        collection: str,
        app: str = "search",
        limit: int = 100,
    ) -> str:
        """Read records from a KV Store collection (returns up to `limit` documents)."""
        return dumps(await client.get(
            f"/servicesNS/nobody/{app}/storage/collections/data/{collection}",
            params={"limit": limit}))
