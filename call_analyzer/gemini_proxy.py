# -*- coding: utf-8 -*-
"""
Прокси только для запросов к Gemini API — та же логика приоритетов, что в
okpd-2-procurement-guide (src/server/geminiProxy.ts), без изменения глобального
сетевого стека процесса: URL передаётся в отдельный httpx.Client для google-genai.

Порядок:
- GEMINI_PROXY_URL — полный URL, например http://user:pass@host:port
- HTTPS_PROXY / HTTP_PROXY — стандартные переменные (читаются только здесь и
  попадают только в клиент Gemini; чтобы не затронуть остальной трафик, лучше
  использовать GEMINI_PROXY_URL / GEMINI_PROXY и не задавать HTTPS_PROXY в .env)
- GEMINI_PROXY — строка host:port:user:pass (для IPv4: a.b.c.d:port:user:pass)
"""
from __future__ import annotations

import os
import re
from typing import Mapping
from urllib.parse import quote


def ensure_http_scheme(url: str) -> str:
    u = url.strip()
    if re.match(r"^https?://", u, re.I):
        return u
    return f"http://{u}"


def _parse_colon_separated_proxy(raw: str) -> str:
    s = raw.strip()
    ipv4 = re.match(
        r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5}):([^:]+):(.+)$",
        s,
    )
    if ipv4:
        host, port, user, password = ipv4.groups()
        u = quote(user, safe="")
        p = quote(password, safe="")
        return f"http://{u}:{p}@{host}:{port}"

    parts = s.split(":")
    if len(parts) < 4:
        raise ValueError(
            "GEMINI_PROXY: ожидается host:port:user:pass "
            "(для IPv4: a.b.c.d:port:user:pass или задайте GEMINI_PROXY_URL)"
        )
    password = parts.pop()
    user = parts.pop()
    port = parts.pop()
    host = ":".join(parts)
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        raise ValueError("GEMINI_PROXY: неверный порт")
    u = quote(user, safe="")
    p = quote(password, safe="")
    return f"http://{u}:{p}@{host}:{port}"


def resolve_gemini_proxy_url(env: Mapping[str, str] | None = None) -> str | None:
    """
    Возвращает URL прокси для Gemini или None.
    env по умолчанию — os.environ.
    """
    e = env if env is not None else os.environ

    direct = (
        (e.get("GEMINI_PROXY_URL") or "").strip()
        or (e.get("HTTPS_PROXY") or "").strip()
        or (e.get("HTTP_PROXY") or "").strip()
    )
    if direct:
        return ensure_http_scheme(direct)

    raw = (e.get("GEMINI_PROXY") or "").strip()
    if not raw:
        return None
    return _parse_colon_separated_proxy(raw)


def mask_proxy_for_log(proxy_url: str) -> str:
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(proxy_url)
        if parts.username or parts.password:
            netloc = parts.hostname or ""
            if parts.port:
                netloc = f"{netloc}:{parts.port}"
            auth = "***:***@" if parts.username else ""
            new_netloc = f"{auth}{netloc}"
            return urlunsplit(
                (parts.scheme, new_netloc, parts.path, parts.query, parts.fragment)
            )
        return proxy_url
    except Exception:
        return "[proxy]"
