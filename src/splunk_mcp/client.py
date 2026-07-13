"""Async HTTP client for the Splunk Enterprise REST API.

Two surfaces, both on the Splunk box:
  - Management/REST : https://<splunk>:8089/services/...   (HTTP Basic auth)
        Config + search + introspection. POST/PUT take *form-encoded* bodies
        (not JSON); responses come back as JSON when ?output_mode=json is set.
        List endpoints return an Atom-style {"entry": [{"name", "content"}...]}.
  - HEC            : https://<splunk>:8088/services/collector/...  (token auth)
        HTTP Event Collector - send events with an "Authorization: Splunk <token>"
        header and a JSON body.

Splunk error bodies look like {"messages": [{"type": "ERROR", "text": "..."}]}.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .config import Settings

_GENERATING = ("search", "|", "search ", "from ", "tstats", "makeresults", "inputlookup")


class SplunkAPIError(Exception):
    def __init__(self, status_code: int, method: str, url: str, detail: str):
        self.status_code = status_code
        super().__init__(f"Splunk API error {status_code} on {method} {url}: {detail}")


class SplunkConnectionError(SplunkAPIError):
    """Splunk was unreachable at the transport layer (timeout, refused, reset).
    status_code is 0."""

    def __init__(self, method: str, url: str, detail: str):
        super().__init__(0, method, url, detail)


def normalize_search(query: str) -> str:
    """Splunk /search/jobs needs the SPL to start with a generating command or
    'search'. Prepend 'search ' if the user gave a bare filter."""
    q = query.strip()
    low = q.lower()
    if low.startswith("|") or any(low.startswith(g) for g in _GENERATING):
        return q
    return f"search {q}"


class SplunkClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.base_url
        self.hec_url = settings.hec_url
        self._http = httpx.AsyncClient(
            verify=settings.verify_ssl,
            timeout=settings.timeout,
            auth=httpx.BasicAuth(settings.username, settings.password),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _send(self, method, url, *, headers=None, params=None, data=None,
                    json_body=None, auth=None) -> httpx.Response:
        """Issue the request, retrying transient transport failures and wrapping
        any httpx transport error in a clean SplunkConnectionError."""
        attempts = max(1, self.settings.retries + 1)
        for attempt in range(attempts):
            try:
                return await self._http.request(
                    method, url, headers=headers, params=params or None,
                    data=data, json=json_body,
                    auth=auth if auth is not None else httpx.USE_CLIENT_DEFAULT)
            except httpx.TransportError as e:
                retryable = not isinstance(e, httpx.ProtocolError)
                if retryable and attempt < attempts - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise SplunkConnectionError(
                    method.upper(), url,
                    f"{type(e).__name__}: {e or 'unreachable'}") from e

    @staticmethod
    def _extract_error(resp: httpx.Response) -> str:
        detail = resp.text[:1500]
        try:
            err = resp.json()
            if isinstance(err, dict) and err.get("messages"):
                msgs = err["messages"]
                if isinstance(msgs, list) and msgs:
                    detail = "; ".join(
                        m.get("text", "") for m in msgs if isinstance(m, dict)) or detail
        except Exception:
            pass
        return detail

    # ------------------------------------------------------------------
    # Management / REST API (port 8089)
    # ------------------------------------------------------------------
    async def request(self, method: str, path: str, *, params=None, data=None,
                      raw_text: bool = False) -> Any:
        """Call a Splunk management endpoint. `data` is a form body (dict or list
        of (key, value) tuples). Adds output_mode=json unless raw_text."""
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        p = {k: v for k, v in (params or {}).items() if v is not None}
        if not raw_text:
            p.setdefault("output_mode", "json")
        resp = await self._send(method, url, params=p, data=data)
        if resp.status_code >= 400:
            raise SplunkAPIError(resp.status_code, method.upper(), url,
                                 self._extract_error(resp))
        if raw_text:
            return resp.text
        if resp.status_code == 204 or not resp.content:
            return None
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            return resp.json()
        return resp.text

    async def get(self, path: str, params=None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, data=None, params=None) -> Any:
        return await self.request("POST", path, data=data, params=params)

    async def delete(self, path: str, params=None) -> Any:
        return await self.request("DELETE", path, params=params)

    @staticmethod
    def unwrap_entries(data: Any) -> list[dict]:
        """Flatten a {"entry": [{"name","content",...}]} listing into a list of
        dicts, hoisting each entry's name + content to the top level."""
        if not isinstance(data, dict):
            return data if isinstance(data, list) else [data]
        out = []
        for e in data.get("entry", []) or []:
            row: dict[str, Any] = {}
            if "name" in e:
                row["name"] = e["name"]
            if isinstance(e.get("id"), str):
                row["id"] = e["id"]
            acl = e.get("acl") or {}
            if acl.get("app"):
                row["app"] = acl["app"]
            content = e.get("content")
            if isinstance(content, dict):
                row.update(content)
            out.append(row)
        return out

    async def list_entries(self, path: str, params=None) -> list[dict]:
        """GET a listing endpoint (count=0 -> all entries) and unwrap it."""
        p = {"count": 0}
        p.update(params or {})
        return self.unwrap_entries(await self.get(path, params=p))

    # ------------------------------------------------------------------
    # Search helpers
    # ------------------------------------------------------------------
    async def search_oneshot(self, query: str, *, earliest="-24h", latest="now",
                             count: int = 100, params=None) -> Any:
        """Run a blocking one-shot search and return the JSON results directly.
        Best for quick lookups; use create_search_job for long/large searches."""
        body = {
            "search": normalize_search(query),
            "exec_mode": "oneshot",
            "output_mode": "json",
            "count": count,
        }
        if earliest:
            body["earliest_time"] = earliest
        if latest:
            body["latest_time"] = latest
        if params:
            body.update(params)
        return await self.request("POST", "/services/search/jobs", data=body, raw_text=False)

    # ------------------------------------------------------------------
    # HTTP Event Collector (port 8088)
    # ------------------------------------------------------------------
    async def hec_send(self, events: list[dict], *, token: str | None = None) -> Any:
        """POST one or more HEC event envelopes to /services/collector/event.
        Each envelope is a dict like {"event": ..., "sourcetype": ..., "index": ...}."""
        tok = token or self.settings.hec_token
        if not tok:
            raise SplunkAPIError(0, "POST", f"{self.hec_url}/services/collector",
                                 "No HEC token set (SPLUNK_HEC_TOKEN or pass token=).")
        url = f"{self.hec_url}/services/collector/event"
        # HEC accepts concatenated JSON objects (one per event), not a JSON array.
        payload = "\n".join(json.dumps(e) for e in events)
        # auth=None bypasses the client-level BasicAuth so it can't clobber the
        # "Authorization: Splunk <token>" header HEC requires.
        resp = await self._http.post(
            url, headers={"Authorization": f"Splunk {tok}"}, content=payload, auth=None)
        if resp.status_code >= 400:
            raise SplunkAPIError(resp.status_code, "POST", url, self._extract_error(resp))
        return resp.json() if resp.content else None
