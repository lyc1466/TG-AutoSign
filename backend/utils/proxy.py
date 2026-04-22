from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from backend.core.runtime_config import get_proxy_runtime_config


def normalize_proxy_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        return value
    if "://" in value:
        return value
    if "@" in value:
        return f"socks5://{value}"
    parts = value.split(":")
    if len(parts) == 2:
        host, port = parts
        return f"socks5://{host}:{port}"
    if len(parts) == 4:
        host, port, user, password = parts
        return f"socks5://{user}:{password}@{host}:{port}"
    return f"socks5://{value}"


def build_proxy_dict(raw: str) -> Optional[dict]:
    value = normalize_proxy_url(raw)
    if not value:
        return None
    parsed = urlparse(value)
    if not (parsed.scheme and parsed.hostname and parsed.port):
        return None
    proxy = {
        "scheme": parsed.scheme,
        "hostname": parsed.hostname,
        "port": parsed.port,
    }
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


def resolve_proxy_url(
    *, explicit_proxy: Optional[str] = None, account_proxy: Optional[str] = None
) -> Optional[str]:
    runtime = get_proxy_runtime_config()
    for candidate in (explicit_proxy, account_proxy, runtime.global_proxy):
        if not isinstance(candidate, str):
            continue
        value = candidate.strip()
        if value:
            return value
    return None


def resolve_proxy_dict(
    *, explicit_proxy: Optional[str] = None, account_proxy: Optional[str] = None
) -> Optional[dict]:
    value = resolve_proxy_url(
        explicit_proxy=explicit_proxy,
        account_proxy=account_proxy,
    )
    if not value:
        return None
    return build_proxy_dict(value)
