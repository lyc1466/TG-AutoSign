from __future__ import annotations

from typing import Optional


def mask_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    return value[:4] + "*" * (len(value) - 8) + value[-4:] if len(value) > 8 else "****"
