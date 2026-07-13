"""User / role tools (access-control): list and manage users and roles."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_list_users() -> str:
        """List Splunk users (name, real name, roles, email, type)."""
        rows = await client.list_entries("/services/authentication/users")
        return dumps([{k: r.get(k) for k in
                       ("name", "realname", "roles", "email", "type", "defaultApp")}
                      for r in rows])

    @mcp.tool()
    async def splunk_list_roles() -> str:
        """List roles and their capabilities / index access."""
        rows = await client.list_entries("/services/authorization/roles")
        return dumps([{"name": r.get("name"),
                       "imported_roles": r.get("imported_roles"),
                       "srchIndexesAllowed": r.get("srchIndexesAllowed"),
                       "capabilities": r.get("capabilities")} for r in rows])

    @mcp.tool()
    async def splunk_create_user(
        name: str,
        password: str,
        roles: str = "user",
        realname: str | None = None,
        email: str | None = None,
    ) -> str:
        """Create a Splunk user.

        Args:
            name: login name.
            password: initial password.
            roles: comma-separated role(s), e.g. 'admin' or 'user,power'.
            realname / email: optional profile fields.
        """
        body: list = [("name", name), ("password", password)]
        for role in [r.strip() for r in roles.split(",") if r.strip()]:
            body.append(("roles", role))
        if realname:
            body.append(("realname", realname))
        if email:
            body.append(("email", email))
        return dumps(await client.post("/services/authentication/users", data=body))

    @mcp.tool()
    async def splunk_delete_user(name: str) -> str:
        """Delete a Splunk user."""
        return dumps(await client.delete(f"/services/authentication/users/{name}"))
