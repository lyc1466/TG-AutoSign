from __future__ import annotations

from typing import Optional


def mask_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    if len(value) <= 12:
        return value[:2] + "****" + value[-2:]
    return value[:4] + "*" * (len(value) - 8) + value[-4:]
