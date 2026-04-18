"""Minimal frontends listing for Sprint 3/3.5 (before real registry).

Sprint 4 replaces this with `frontend_registry.py` (with persistence, health
polling, enable/disable flag). For now we scan `/app/data/campaigns/*/` and
return directory names as frontend IDs. Good enough for populating scope
selectors in Registered Users + Per-frontend notification overrides.
"""
from src.services._paths import CAMPAIGNS_DIR


def list_frontends() -> list[dict[str, str]]:
    if not CAMPAIGNS_DIR.exists():
        return []
    out: list[dict[str, str]] = []
    for entry in sorted(CAMPAIGNS_DIR.iterdir()):
        if entry.is_dir():
            out.append({"id": entry.name, "name": entry.name})
    return out
