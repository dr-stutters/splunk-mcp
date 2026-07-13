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
