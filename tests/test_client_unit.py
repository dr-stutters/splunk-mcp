"""Splunk-free unit tests for the client + config.

No live Splunk needed - httpx.MockTransport supplies canned responses, so these
run anywhere (CI included). Run: `uv run pytest`.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from splunk_mcp.client import (
    SplunkAPIError,
    SplunkClient,
    SplunkConnectionError,
    normalize_search,
)
from splunk_mcp.config import Settings, load_settings


def run(coro):
    return asyncio.run(coro)


def _settings(**kw) -> Settings:
    d = dict(base_url="https://splunk.example.com:8089", username="admin", password="pw",
             hec_url="https://splunk.example.com:8088", hec_token="tok-abc",
             verify_ssl=False, timeout=5, retries=2)
    d.update(kw)
    return Settings(**d)


def _client(handler, **kw) -> SplunkClient:
    c = SplunkClient(_settings(**kw))
    c._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        auth=httpx.BasicAuth("admin", "pw"), follow_redirects=True)
    return c


# --------------------------------------------------------------------------
# config: HEC port derivation (regression - base_url carries :8089, HEC must be :8088)
# --------------------------------------------------------------------------
def _base_env(monkeypatch):
    monkeypatch.setattr("splunk_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("SPLUNK_USERNAME", "admin")
    monkeypatch.setenv("SPLUNK_PASSWORD", "pw")
    monkeypatch.delenv("SPLUNK_HEC_URL", raising=False)
    monkeypatch.delenv("SPLUNK_HEC_TOKEN", raising=False)


def test_hec_url_forces_8088_even_when_base_has_8089(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SPLUNK_URL", "https://splunk.example.com:8089")
    s = load_settings()
    assert s.base_url == "https://splunk.example.com:8089"
    assert s.hec_url == "https://splunk.example.com:8088"  # NOT :8089


def test_url_without_port_defaults_to_8089(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SPLUNK_URL", "splunk.example.com")
    s = load_settings()
    assert s.base_url == "https://splunk.example.com:8089"
    assert s.hec_url == "https://splunk.example.com:8088"


def test_explicit_hec_url_respected(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SPLUNK_URL", "https://splunk.example.com:8089")
    monkeypatch.setenv("SPLUNK_HEC_URL", "https://hec.example.com")
    s = load_settings()
    assert s.hec_url == "https://hec.example.com:8088"


def test_missing_url_raises(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("SPLUNK_URL", raising=False)
    monkeypatch.delenv("SPLUNK_HOST", raising=False)
    with pytest.raises(RuntimeError):
        load_settings()


# --------------------------------------------------------------------------
# normalize_search
# --------------------------------------------------------------------------
def test_normalize_prepends_search_to_bare_filter():
    assert normalize_search("index=main error") == "search index=main error"


def test_normalize_leaves_pipe_and_generating_commands():
    assert normalize_search("| makeresults") == "| makeresults"
    assert normalize_search("search index=x") == "search index=x"
    assert normalize_search("tstats count where index=x") == "tstats count where index=x"


# --------------------------------------------------------------------------
# unwrap_entries: Atom entry[] -> flat dicts
# --------------------------------------------------------------------------
def test_unwrap_entries_flattens_name_and_content():
    data = {"entry": [
        {"name": "idx1", "content": {"totalEventCount": "5"}, "acl": {"app": "search"}},
        {"name": "idx2", "content": {"totalEventCount": "0"}},
    ]}
    rows = SplunkClient.unwrap_entries(data)
    assert rows[0]["name"] == "idx1" and rows[0]["totalEventCount"] == "5" and rows[0]["app"] == "search"
    assert rows[1]["name"] == "idx2" and rows[1]["totalEventCount"] == "0"


# --------------------------------------------------------------------------
# request: adds output_mode=json; error extraction from messages[]
# --------------------------------------------------------------------------
def test_request_adds_output_mode_json():
    def handler(req):
        assert req.url.params.get("output_mode") == "json"
        return httpx.Response(200, json={"entry": []})
    run(_client(handler).get("/services/data/indexes"))


def test_error_extraction_from_messages():
    def handler(_req):
        return httpx.Response(400, json={"messages": [{"type": "ERROR", "text": "index not found"}]})
    with pytest.raises(SplunkAPIError) as ei:
        run(_client(handler).get("/services/data/indexes/nope"))
    assert ei.value.status_code == 400 and "index not found" in str(ei.value)


def test_post_sends_form_body():
    def handler(req):
        assert req.headers.get("content-type", "").startswith("application/x-www-form-urlencoded")
        assert b"name=cisco" in req.content
        return httpx.Response(201, json={"entry": []})
    run(_client(handler).post("/services/data/indexes", data={"name": "cisco"}))


# --------------------------------------------------------------------------
# HEC send: MUST bypass client BasicAuth and send "Authorization: Splunk <token>"
# (regression - client-level BasicAuth otherwise clobbers the header -> "Invalid token")
# --------------------------------------------------------------------------
def test_hec_send_uses_splunk_token_not_basic_auth():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("Authorization")
        seen["body"] = req.content.decode()
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"text": "Success", "code": 0})

    r = run(_client(handler).hec_send([{"event": "hi", "index": "main"}], token="tok-xyz"))
    assert seen["auth"] == "Splunk tok-xyz"          # NOT "Basic ..."
    assert seen["url"].endswith(":8088/services/collector/event")
    assert '"event": "hi"' in seen["body"]
    assert r == {"text": "Success", "code": 0}


def test_hec_send_without_token_raises():
    with pytest.raises(SplunkAPIError):
        run(_client(lambda _r: httpx.Response(200), hec_token="").hec_send([{"event": "x"}]))


# --------------------------------------------------------------------------
# transport-error wrapping + retry
# --------------------------------------------------------------------------
def test_transport_error_wrapped_as_connection_error():
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        raise httpx.ConnectError("connection refused")

    with pytest.raises(SplunkConnectionError) as ei:
        run(_client(handler, retries=0).get("/services/server/info"))
    assert ei.value.status_code == 0 and calls["n"] == 1


def test_transient_transport_error_is_retried():
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("transient")
        return httpx.Response(200, json={"entry": []})

    run(_client(handler, retries=2).get("/services/server/info"))
    assert calls["n"] == 2


# --------------------------------------------------------------------------
# telemetry generator (#23) - pure core + HEC/UDP transports
# --------------------------------------------------------------------------
import json  # noqa: E402
import socket as _socket  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from splunk_mcp.tools import telemetry as tele  # noqa: E402

_FIXED_NOW = 1_700_000_000.0


def _tele_mcp(handler, **kw) -> FastMCP:
    m = FastMCP("t")
    tele.register(m, _client(handler, **kw))
    return m


async def _call(mcp, name, **args):
    res = await mcp.call_tool(name, args)
    return res[1]["result"] if isinstance(res, tuple) else res


def test_telemetry_deterministic_and_windowed():
    a = tele._generate("ios", 20, 60, seed=42, now=_FIXED_NOW)
    b = tele._generate("ios", 20, 60, seed=42, now=_FIXED_NOW)
    assert a == b  # same seed -> byte-identical
    assert tele._generate("ios", 20, 60, seed=43, now=_FIXED_NOW) != a
    ts = [t for t, _h, _x in a]
    assert ts == sorted(ts)  # oldest -> newest
    assert ts[0] >= _FIXED_NOW - 3600 and ts[-1] <= _FIXED_NOW  # inside the span


def test_telemetry_every_profile_shape():
    for prof in ("ios", "ise_auth", "ise_acct", "asa", "windows"):
        evs = tele._generate(prof, 15, 30, seed=1, now=_FIXED_NOW)
        assert len(evs) == 15
        assert all(h.startswith("sim-") for _t, h, _x in evs)
    assert "CISE_" in tele._generate("ise_auth", 5, 30, seed=1)[0][2]
    assert "UserName=" in tele._generate("ise_auth", 5, 30, seed=1)[0][2]
    assert "CISE_RADIUS_Accounting" in tele._generate("ise_acct", 5, 30, seed=1)[0][2]
    assert "EventCode=" in tele._generate("windows", 5, 30, seed=1)[0][2]
    assert "%ASA-" in tele._generate("asa", 5, 30, seed=1)[0][2]


def test_telemetry_unknown_profile_raises():
    with pytest.raises(ValueError):
        tele._generate("nope", 5, 30, seed=1)


def test_telemetry_hec_envelopes_and_token():
    seen = {}

    def handler(req):
        if req.url.host == "splunk.example.com" and req.url.port == 8088:
            seen["auth"] = req.headers.get("authorization")
            seen["body"] = req.content.decode()
            return httpx.Response(200, json={"text": "Success", "code": 0})
        return httpx.Response(404)

    out = run(_call(_tele_mcp(handler),
                    "splunk_generate_telemetry", profile="ios", count=3,
                    span_minutes=10, seed=7, token="tok-xyz"))
    assert seen["auth"] == "Splunk tok-xyz"  # NOT Basic
    lines = [json.loads(x) for x in seen["body"].splitlines()]
    assert len(lines) == 3
    for env in lines:
        assert env["index"] == "cisco" and env["sourcetype"] == "cisco:ios"
        assert env["host"].startswith("sim-") and "time" in env
    assert '"sent": 3' in out and '"transport": "hec"' in out


def test_telemetry_hec_index_override_and_batching():
    posts = {"n": 0, "events": 0}

    def handler(req):
        if req.url.port == 8088:
            posts["n"] += 1
            posts["events"] += len(req.content.decode().splitlines())
            return httpx.Response(200, json={"text": "Success", "code": 0})
        return httpx.Response(404)

    run(_call(_tele_mcp(handler), "splunk_generate_telemetry",
              profile="ise_auth", count=1100, span_minutes=60, seed=1))
    assert posts["events"] == 1100 and posts["n"] == 3  # 500+500+100 batches


def test_telemetry_asa_udp_rejected():
    # asa has no UDP input -> must error toward HEC
    import asyncio as _a
    with pytest.raises(Exception):  # noqa: B017 - MCP wraps ValueError
        _a.run(_tele_mcp(lambda _r: httpx.Response(200)).call_tool(
            "splunk_generate_telemetry",
            {"profile": "asa", "count": 5, "transport": "udp"}))


def test_telemetry_udp_sends_packets(monkeypatch):
    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(1.0)
    port = srv.getsockname()[1]
    # base_url host is splunk.example.com; force target to loopback for the test
    monkeypatch.setattr(tele.socket, "socket", _socket.socket)

    def handler(_r):
        return httpx.Response(200)

    c = _client(handler)
    monkeypatch.setattr(c, "base_url", "https://127.0.0.1:8089", raising=False)
    m = FastMCP("t")
    tele.register(m, c)
    run(m.call_tool("splunk_generate_telemetry",
                    {"profile": "ios", "count": 5, "transport": "udp",
                     "udp_port": port, "seed": 3}))
    got = 0
    try:
        while True:
            srv.recvfrom(65535)
            got += 1
    except _socket.timeout:
        pass
    finally:
        srv.close()
    assert got == 5
