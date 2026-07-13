"""Dashboard (view) tools: list, read, create, delete Simple XML / dashboard views.

Prefer the dashboards that ship inside installed add-ons (see the apps tools);
use these to inventory them, read their source, or add a custom lab dashboard.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_list_dashboards(app: str | None = None) -> str:
        """List dashboard views (name, app, label). Omit app to list across all apps."""
        path = f"/servicesNS/-/{app}/data/ui/views" if app else "/servicesNS/-/-/data/ui/views"
        rows = await client.list_entries(path)
        slim = []
        for r in rows:
            slim.append({"name": r.get("name"), "app": r.get("app"),
                         "label": r.get("label"), "disabled": r.get("disabled")})
        return dumps(slim)

    @mcp.tool()
    async def splunk_get_dashboard(name: str, app: str = "search") -> str:
        """Get a dashboard view's Simple XML / source definition."""
        rows = client.unwrap_entries(
            await client.get(f"/servicesNS/-/{app}/data/ui/views/{name}"))
        info = rows[0] if rows else {}
        return dumps({"name": info.get("name"), "app": app,
                      "label": info.get("label"), "source": info.get("eai:data")})

    @mcp.tool()
    async def splunk_create_dashboard(name: str, source_xml: str, app: str = "search") -> str:
        """Create a dashboard view from Simple XML source in the given app."""
        body = {"name": name, "eai:data": source_xml}
        path = f"/servicesNS/nobody/{app}/data/ui/views"
        return dumps(await client.post(path, data=body))

    @mcp.tool()
    async def splunk_delete_dashboard(name: str, app: str = "search") -> str:
        """Delete a dashboard view."""
        return dumps(await client.delete(f"/servicesNS/-/{app}/data/ui/views/{name}"))
