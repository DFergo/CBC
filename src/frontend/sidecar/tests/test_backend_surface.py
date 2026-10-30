"""Tests for the two sidecar surfaces and the backend-surface signature.

Adapted from HRDDHelper/src/frontend/sidecar/tests/test_backend_surface.py.

Run inside the frontend container (the sidecar writes under /app/data):
    cd /app && python -m unittest sidecar.tests.test_backend_surface -v
"""

import os
import secrets as pysecrets
import time
import unittest

SECRET = "s" * 40
PREVIOUS = "p" * 40
os.environ["CBC_BACKEND_SECRET"] = SECRET
os.environ["CBC_BACKEND_SECRET_PREVIOUS"] = PREVIOUS
os.environ.pop("ALLOW_UNSIGNED_BACKEND_SURFACE", None)
os.environ.pop("BACKEND_SURFACE_AUTH", None)

from fastapi import FastAPI, Form  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sidecar import backend_auth  # noqa: E402
from sidecar.main import app, backend_app  # noqa: E402


def signed_headers(method: str, path_qs: str, body: bytes = b"", secret: str = SECRET,
                   ts: int | None = None, nonce: str | None = None) -> dict[str, str]:
    ts_s = str(int(time.time()) if ts is None else ts)
    nonce = nonce or pysecrets.token_urlsafe(18)
    return {
        "X-HRDD-Timestamp": ts_s,
        "X-HRDD-Nonce": nonce,
        "X-HRDD-Signature": backend_auth.sign(secret, ts_s, nonce, method, path_qs, body),
    }


class SignatureVectorTest(unittest.TestCase):
    """Shared vector — the backend client and every app must produce the same value."""

    def test_vector(self):
        body = b'{"token":"AB12-CD34","status":"not_found","data":null}'
        sig = backend_auth.sign("0123456789abcdef0123456789abcdef", "1767225600", "n-0001", "POST",
                                "/backend/v1/session/AB12-CD34/recovery-data", body)
        self.assertEqual(sig, "v1=c8cfb97d1391eebf7dab6c476c36fd64c7594c11204ef2ef1411b478e23c5a02")


class BackendSurfaceTest(unittest.TestCase):
    def setUp(self):
        # Fresh middleware (nonce cache, start time) for each test.
        backend_app.middleware_stack = None
        self.client = TestClient(backend_app)
        # Build the middleware now so signatures made in the test are not
        # "signed before the process started".
        self.client.get("/backend/v1/health")

    def test_unsigned_rejected(self):
        r = self.client.get("/backend/v1/queue")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"detail": "Unauthorized"})

    def test_signed_get_ok(self):
        r = self.client.get("/backend/v1/queue", headers=signed_headers("GET", "/backend/v1/queue"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("messages", r.json())
        self.assertEqual(r.json()["surface_auth"], "signed")

    def test_signed_with_query_ok(self):
        h = signed_headers("GET", "/backend/v1/config?probe=1")
        self.assertEqual(self.client.get("/backend/v1/config?probe=1", headers=h).status_code, 200)

    def test_query_not_covered_rejected(self):
        h = signed_headers("GET", "/backend/v1/config")
        self.assertEqual(self.client.get("/backend/v1/config?probe=1", headers=h).status_code, 401)

    def test_replay_rejected(self):
        h = signed_headers("GET", "/backend/v1/queue")
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 401)

    def test_stale_timestamp_rejected(self):
        h = signed_headers("GET", "/backend/v1/queue", ts=int(time.time()) - 600)
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 401)

    def test_wrong_secret_rejected(self):
        h = signed_headers("GET", "/backend/v1/queue", secret="x" * 40)
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 401)

    def test_previous_secret_accepted(self):
        h = signed_headers("GET", "/backend/v1/queue", secret=PREVIOUS)
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 200)

    def test_tampered_body_rejected(self):
        body = b'{"event":"token","data":"hi"}'
        h = signed_headers("POST", "/backend/v1/stream/T-1/chunk", body)
        r = self.client.post("/backend/v1/stream/T-1/chunk", content=b'{"event":"token","data":"evil"}',
                             headers={**h, "content-type": "application/json"})
        self.assertEqual(r.status_code, 401)

    def test_signed_json_post_ok(self):
        body = b'{"event":"token","data":"hi"}'
        h = signed_headers("POST", "/backend/v1/stream/T-1/chunk", body)
        r = self.client.post("/backend/v1/stream/T-1/chunk", content=body,
                             headers={**h, "content-type": "application/json"})
        self.assertEqual(r.status_code, 200)

    def test_cancellations_every_second_keeps_nonce_cache_bounded(self):
        # The backend polls /cancellations every second during a stream: one
        # nonce per request, each expiring after 2 × window.
        mw = backend_app.middleware_stack
        while not isinstance(mw, backend_auth.BackendSignatureMiddleware):
            mw = mw.app
        for _ in range(50):
            h = signed_headers("GET", "/backend/v1/cancellations")
            self.assertEqual(self.client.get("/backend/v1/cancellations", headers=h).status_code, 200)
        self.assertEqual(len(mw._nonces), 50)
        now = time.time()
        for n in list(mw._nonces)[:40]:
            mw._nonces[n] = now - 1  # as if 240 s had passed for these
        h = signed_headers("GET", "/backend/v1/cancellations")
        self.client.get("/backend/v1/cancellations", headers=h)
        self.assertEqual(len(mw._nonces), 11)

    def test_signed_multipart_document_push_ok(self):
        # CBC-specific multipart route: the backend pushes a CBA file for a
        # pending sidepanel download. Body is buffered by the middleware and
        # replayed to the multipart parser.
        pub = TestClient(app)
        rid = pub.post("/internal/document-request",
                       json={"scope_key": "fe/acme", "filename": "cba.pdf"}).json()["request_id"]
        boundary = "testboundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"cba.pdf\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n%PDF-1.4 test\r\n--{boundary}--\r\n"
        ).encode()
        path = f"/backend/v1/document/{rid}/result"
        h = signed_headers("POST", path, body)
        r = self.client.post(path, content=body,
                             headers={**h, "content-type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(pub.get(f"/internal/document/{rid}").content, b"%PDF-1.4 test")

    def test_signed_before_start_rejected(self):
        h = signed_headers("GET", "/backend/v1/queue", ts=int(time.time()) - 30)  # inside the window
        self.assertEqual(self.client.get("/backend/v1/queue", headers=h).status_code, 401)


class PublicSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_browser_routes_work(self):
        self.assertEqual(self.client.get("/internal/config").status_code, 200)
        self.assertEqual(self.client.get("/internal/health").status_code, 200)
        self.assertEqual(self.client.get("/internal/companies").status_code, 200)
        self.assertEqual(self.client.get("/internal/guardrails/thresholds").status_code, 200)
        r = self.client.post("/internal/queue", json={
            "session_token": "AB12-CD34", "survey": {}, "language": "en",
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.post("/internal/session/recover", json={"token": "AB12-CD34"}).status_code, 200)

    def test_backend_routes_absent_on_public_app(self):
        for method, path in [
            ("GET", "/internal/queue"), ("GET", "/internal/uploads"), ("GET", "/internal/cancellations"),
            ("POST", "/internal/branding"), ("POST", "/internal/session-settings"),
            ("POST", "/internal/companies"), ("POST", "/internal/guardrails/thresholds"),
            ("POST", "/internal/session/AB12-CD34/recovery-data"),
            ("POST", "/internal/stream/AB12-CD34/chunk"), ("POST", "/internal/auth/AB12-CD34/result"),
            ("POST", "/internal/document/1-1/result"), ("POST", "/internal/document/1-1/error"),
            ("GET", "/internal/upload/AB12-CD34/x.pdf"), ("DELETE", "/internal/upload/AB12-CD34/x.pdf"),
            ("GET", "/backend/v1/queue"), ("GET", "/backend/v1/config"),
        ]:
            r = self.client.request(method, path, json={} if method == "POST" else None)
            self.assertIn(r.status_code, (404, 405), f"{method} {path} -> {r.status_code}")


class ModeTest(unittest.TestCase):
    """Middleware configuration edge cases, on a minimal app."""

    ENV = ("CBC_BACKEND_SECRET", "CBC_BACKEND_SECRET_PREVIOUS", "ALLOW_UNSIGNED_BACKEND_SURFACE", "BACKEND_SURFACE_AUTH")

    def _client(self, **env):
        saved = {k: os.environ.get(k) for k in self.ENV}
        try:
            for k in saved:
                os.environ.pop(k, None)
            os.environ.update(env)
            mini = FastAPI()
            mini.add_middleware(backend_auth.BackendSignatureMiddleware)

            @mini.post("/backend/v1/echo")
            async def echo(x: str = Form("")):
                return {"x": x}

            client = TestClient(mini)
            client.post("/backend/v1/echo")  # build the middleware with this env
            return client
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_no_secret_rejects_even_signed(self):
        c = self._client()
        self.assertEqual(c.post("/backend/v1/echo", headers=signed_headers("POST", "/backend/v1/echo")).status_code, 401)

    def test_short_secret_ignored(self):
        c = self._client(CBC_BACKEND_SECRET="short")
        h = signed_headers("POST", "/backend/v1/echo", secret="short")
        self.assertEqual(c.post("/backend/v1/echo", headers=h).status_code, 401)

    def test_hrdd_variable_names_not_read(self):
        # Shared host: HRDD's secret must not unlock CBC's backend surface.
        c = self._client(HRDD_BACKEND_SECRET=SECRET)
        self.assertEqual(c.post("/backend/v1/echo", headers=signed_headers("POST", "/backend/v1/echo")).status_code, 401)
        os.environ.pop("HRDD_BACKEND_SECRET", None)

    def test_allow_unsigned_alias_not_supported(self):
        c = self._client(ALLOW_UNSIGNED_BACKEND_SURFACE="true")
        self.assertEqual(c.post("/backend/v1/echo", data={"x": "ok"}).status_code, 401)

    def test_trusted_network_mode(self):
        c = self._client(BACKEND_SURFACE_AUTH="trusted-network")
        r = c.post("/backend/v1/echo", data={"x": "ok"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"x": "ok"})

    def test_trusted_network_does_not_need_a_secret(self):
        c = self._client(BACKEND_SURFACE_AUTH="trusted-network", CBC_BACKEND_SECRET="")
        self.assertEqual(c.post("/backend/v1/echo").status_code, 200)

    def test_unknown_mode_falls_back_to_signed(self):
        c = self._client(BACKEND_SURFACE_AUTH="yolo", CBC_BACKEND_SECRET=SECRET)
        self.assertEqual(c.post("/backend/v1/echo").status_code, 401)

    def test_surface_mode_reporting(self):
        for env, expected in (({}, "signed"), ({"BACKEND_SURFACE_AUTH": "trusted-network"}, "trusted-network"),
                              ({"ALLOW_UNSIGNED_BACKEND_SURFACE": "true"}, "signed"),
                              ({"BACKEND_SURFACE_AUTH": "signed"}, "signed")):
            saved = {k: os.environ.pop(k, None) for k in ("BACKEND_SURFACE_AUTH", "ALLOW_UNSIGNED_BACKEND_SURFACE")}
            try:
                os.environ.update(env)
                self.assertEqual(backend_auth.surface_mode(), expected, env)
            finally:
                for k in ("BACKEND_SURFACE_AUTH", "ALLOW_UNSIGNED_BACKEND_SURFACE"):
                    os.environ.pop(k, None)
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
