"""PATCH /admin/api/v1/frontends/{id} — URL editing with guardrails.

Covers the reconciler-facing contract: URL change preserves the id (so
campaign config survives), normalises trailing slashes, rejects collisions
(409) and unreachable URLs (400), lets `?verify=false` skip only the
reachability probe, and leaves rename-only edits untouched by the probe.
"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.v1.admin import frontends as fe_mod
from src.api.v1.admin.auth import require_admin
from src.services.frontend_registry import registry

BASE = "/admin/api/v1/frontends"


@pytest.fixture(autouse=True)
def clean_registry():
    registry._frontends.clear()
    yield
    registry._frontends.clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(fe_mod.router)
    app.dependency_overrides[require_admin] = lambda: {"sub": "admin"}
    return TestClient(app)


@pytest.fixture
def probe_ok(monkeypatch):
    """Reachability probe always succeeds."""
    async def _ok(url):  # noqa: ARG001
        return None
    monkeypatch.setattr(fe_mod, "_probe_reachable", _ok)


def test_url_update_preserves_id_and_normalises(client, probe_ok):
    fe = registry.register(url="http://10.0.0.1:8190", name="Packaging EU")
    fid, created = fe["frontend_id"], fe["created_at"]

    r = client.patch(f"{BASE}/{fid}", json={"url": "http://10.0.0.2:8190/"})

    assert r.status_code == 200
    body = r.json()["frontend"]
    assert body["frontend_id"] == fid            # id preserved -> campaign config intact
    assert body["url"] == "http://10.0.0.2:8190"  # trailing slash normalised away
    assert body["created_at"] == created          # untouched fields preserved
    assert registry.get(fid)["url"] == "http://10.0.0.2:8190"


def test_generic_host_accepted(client, probe_ok):
    """No IPv4 assumption: a hostname / MagicDNS / .local name is fine as long
    as it's reachable (which the probe fixture makes true here)."""
    fid = registry.register(url="http://10.0.0.1:8190", name="A")["frontend_id"]
    r = client.patch(f"{BASE}/{fid}", json={"url": "http://cbc-fe.tailnet.ts.net:8190"})
    assert r.status_code == 200
    assert registry.get(fid)["url"] == "http://cbc-fe.tailnet.ts.net:8190"


def test_unreachable_url_rejected_400(client, monkeypatch):
    async def _fail(url):  # noqa: ARG001
        raise HTTPException(400, "not reachable")
    monkeypatch.setattr(fe_mod, "_probe_reachable", _fail)

    fid = registry.register(url="http://10.0.0.1:8190", name="A")["frontend_id"]
    r = client.patch(f"{BASE}/{fid}", json={"url": "http://10.0.0.9:8190"})

    assert r.status_code == 400
    assert registry.get(fid)["url"] == "http://10.0.0.1:8190"  # not persisted


def test_verify_false_skips_reachability(client, monkeypatch):
    called = []

    async def _fail(url):
        called.append(url)
        raise HTTPException(400, "probe should have been skipped")
    monkeypatch.setattr(fe_mod, "_probe_reachable", _fail)

    fid = registry.register(url="http://10.0.0.1:8190", name="A")["frontend_id"]
    r = client.patch(f"{BASE}/{fid}?verify=false", json={"url": "http://host.local:8190"})

    assert r.status_code == 200
    assert called == []                           # probe never invoked
    assert registry.get(fid)["url"] == "http://host.local:8190"


def test_collision_rejected_409(client, probe_ok):
    a = registry.register(url="http://10.0.0.1:8190", name="A")
    registry.register(url="http://10.0.0.2:8190", name="B")

    r = client.patch(f"{BASE}/{a['frontend_id']}", json={"url": "http://10.0.0.2:8190"})

    assert r.status_code == 409
    assert registry.get(a["frontend_id"])["url"] == "http://10.0.0.1:8190"  # unchanged


def test_collision_checked_even_with_verify_false(client, monkeypatch):
    # Probe must never run: collision is checked first AND verify=false skips it.
    async def _boom(url):  # noqa: ARG001
        raise AssertionError("reachability must not run for a colliding URL")
    monkeypatch.setattr(fe_mod, "_probe_reachable", _boom)

    a = registry.register(url="http://10.0.0.1:8190", name="A")
    registry.register(url="http://10.0.0.2:8190", name="B")

    # Trailing slash on the incoming URL proves both sides are normalised
    # before comparison.
    r = client.patch(f"{BASE}/{a['frontend_id']}?verify=false", json={"url": "http://10.0.0.2:8190/"})

    assert r.status_code == 409
    assert registry.get(a["frontend_id"])["url"] == "http://10.0.0.1:8190"


def test_rename_only_does_not_probe(client, monkeypatch):
    called = []

    async def _spy(url):
        called.append(url)
    monkeypatch.setattr(fe_mod, "_probe_reachable", _spy)

    fid = registry.register(url="http://10.0.0.1:8190", name="Old")["frontend_id"]
    r = client.patch(f"{BASE}/{fid}", json={"name": "New name"})

    assert r.status_code == 200
    body = r.json()["frontend"]
    assert body["name"] == "New name"
    assert body["url"] == "http://10.0.0.1:8190"  # untouched
    assert called == []                           # no url in patch -> no probe


def test_missing_frontend_404(client, probe_ok):
    r = client.patch(f"{BASE}/does-not-exist", json={"name": "x"})
    assert r.status_code == 404
