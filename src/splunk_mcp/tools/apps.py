"""App / add-on tools: list, install (incl. Splunkbase add-ons), enable, delete.

The intent is to lean on *existing* Splunkbase apps and their prebuilt dashboards
(e.g. Cisco Security Cloud, the Cisco Security Cloud Control add-on, Splunk Add-on
for Cisco ISE, Splunk Add-on for Microsoft Windows) rather than hand-building
panels. Splunkbase downloads are auth-gated, so the flow is: download the add-on
.tgz (with splunk.com creds), put it on the Splunk host, then splunk_install_app
it by path (or install directly from a URL Splunk can reach).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps

_SLIM = ("name", "label", "version", "disabled", "visible", "configured", "author")


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_list_apps() -> str:
        """List installed apps/add-ons (name, label, version, enabled, visible)."""
        rows = await client.list_entries("/services/apps/local")
        return dumps([{k: r.get(k) for k in _SLIM} for r in rows])

    @mcp.tool()
    async def splunk_get_app(name: str) -> str:
        """Full detail for one installed app/add-on."""
        rows = client.unwrap_entries(await client.get(f"/services/apps/local/{name}"))
        return dumps(rows[0] if rows else {})

    @mcp.tool()
    async def splunk_install_app(source: str, update: bool = False) -> str:
        """Install an app/add-on from a .tgz/.spl package.

        Args:
            source: a file path on the Splunk host (e.g. '/tmp/splunk-add-on-for-cisco-ise.tgz')
                or a URL Splunk can fetch. For Splunkbase add-ons, download the package
                first (auth-gated) and pass its path here.
            update: set True to upgrade an already-installed app.

        After install, restart Splunk if prompted, then splunk_enable_app if needed.
        """
        body = {"name": source, "filename": "true", "update": "true" if update else "false"}
        return dumps(await client.post("/services/apps/local", data=body))

    @mcp.tool()
    async def splunk_enable_app(name: str) -> str:
        """Enable an installed app/add-on."""
        return dumps(await client.post(f"/services/apps/local/{name}/enable"))

    @mcp.tool()
    async def splunk_disable_app(name: str) -> str:
        """Disable an installed app/add-on."""
        return dumps(await client.post(f"/services/apps/local/{name}/disable"))

    @mcp.tool()
    async def splunk_delete_app(name: str) -> str:
        """Uninstall an app/add-on (removes it from disk)."""
        return dumps(await client.delete(f"/services/apps/local/{name}"))
