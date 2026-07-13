"""Configuration for the Splunk MCP server, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    base_url: str          # management/REST API, includes :8089
    username: str
    password: str
    hec_url: str           # HTTP Event Collector, :8088
    hec_token: str
    verify_ssl: bool
    timeout: float
    retries: int = 2


def _with_port(host: str, default_port: int) -> str:
    """Ensure host has a scheme and an explicit port."""
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    host = host.rstrip("/")
    parts = urlsplit(host)
    if parts.port is None:
        host = f"{parts.scheme}://{parts.hostname}:{default_port}"
    return host


def load_settings() -> Settings:
    """Build settings from SPLUNK_* environment variables.

    A local .env is honored - both next to this project and in the current
    working directory (so the server works standalone and when launched from a
    parent project like cml-mcp via `uv run --directory`).
    """
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    load_dotenv()

    host = os.environ.get("SPLUNK_URL") or os.environ.get("SPLUNK_HOST", "")
    if not host:
        raise RuntimeError(
            "SPLUNK_URL is not set. Set SPLUNK_URL (e.g. https://192.0.2.50:8089), "
            "SPLUNK_USERNAME and SPLUNK_PASSWORD in the environment or a .env file."
        )
    base_url = _with_port(host, 8089)

    username = os.environ.get("SPLUNK_USERNAME", "")
    password = os.environ.get("SPLUNK_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("SPLUNK_USERNAME and SPLUNK_PASSWORD must be set.")

    # HEC defaults to the same host on :8088 unless overridden. Derive from the
    # base host explicitly (base_url already carries :8089, which must not leak
    # into the HEC URL).
    hec_host = os.environ.get("SPLUNK_HEC_URL", "")
    if hec_host:
        hec_url = _with_port(hec_host, 8088)
    else:
        bp = urlsplit(base_url)
        hec_url = f"{bp.scheme}://{bp.hostname}:8088"
    hec_token = os.environ.get("SPLUNK_HEC_TOKEN", "")

    verify = os.environ.get("SPLUNK_VERIFY_SSL", "false").strip().lower() in ("1", "true", "yes")
    timeout = float(os.environ.get("SPLUNK_TIMEOUT", "60"))
    retries = int(os.environ.get("SPLUNK_RETRIES", "2"))

    return Settings(
        base_url=base_url,
        username=username,
        password=password,
        hec_url=hec_url,
        hec_token=hec_token,
        verify_ssl=verify,
        timeout=timeout,
        retries=retries,
    )
