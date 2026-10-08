"""
Tests for skewproof.serve.

FeatureServer.handle() is tested directly (no socket) for routing/response
logic. build_server()/run_server() are tested by actually starting the server
on an OS-assigned ephemeral port (port=0) in a background thread and making
real HTTP requests against it with urllib - the thin http.server wiring only
gets genuine coverage by going over a real socket.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from skewproof.definition import Aggregation, FeatureRegistry, feature
from skewproof.offline import InMemoryEventSource
from skewproof.online import OnlineStore
from skewproof.serve import FeatureServer, build_server, run_server


def ts(day: int) -> datetime:
    return datetime(2026, 1, day)


@pytest.fixture
def store() -> OnlineStore:
    return OnlineStore()


@pytest.fixture
def registry() -> FeatureRegistry:
    reg = FeatureRegistry()
    feature(
        reg, name="soil_latest", source="s", entity_key="e",
        timestamp_key="t", value_key="v", aggregation=Aggregation.LATEST,
    )
    return reg


class TestHandleRouting:
    def test_healthz(self, store) -> None:
        response = FeatureServer(store).handle("GET", "/healthz")
        assert response.status == 200
        assert json.loads(response.body) == {"status": "ok"}

    def test_unknown_path_is_404(self, store) -> None:
        response = FeatureServer(store).handle("GET", "/nope")
        assert response.status == 404

    def test_non_get_method_is_405(self, store) -> None:
        response = FeatureServer(store).handle("POST", "/healthz")
        assert response.status == 405

    def test_metrics_is_plain_text(self, store) -> None:
        response = FeatureServer(store).handle("GET", "/metrics")
        assert response.status == 200
        assert response.content_type.startswith("text/plain")
        assert "skewproof_requests_total" in response.body.decode()

    def test_metrics_counts_requests_and_errors(self, store) -> None:
        fs = FeatureServer(store)
        fs.handle("GET", "/healthz")
        fs.handle("GET", "/does-not-exist")
        body = fs.handle("GET", "/metrics").body.decode()
        # 3 requests total: healthz, does-not-exist, and this /metrics call itself
        assert "skewproof_requests_total 3" in body
        assert "skewproof_errors_total 1" in body

    def test_internal_error_is_500_and_still_counted(self) -> None:
        class BoomStore:
            def get(self, feature_name, entity_id):
                raise RuntimeError("boom")

            def materialize(self, *a, **k):
                raise NotImplementedError

        fs = FeatureServer(BoomStore())
        response = fs.handle("GET", "/features/x/y")
        assert response.status == 500
        assert fs.errors_total == 1


class TestFeatureEndpoint:
    def test_returns_a_materialized_value(self, store, registry) -> None:
        definition = registry.get("soil_latest")
        source = InMemoryEventSource(data={"f1": [(ts(1), 30.0)]})
        store.materialize(definition, source, ["f1"], ts(6))

        response = FeatureServer(store, registry).handle("GET", "/features/soil_latest/f1")
        assert response.status == 200
        assert json.loads(response.body) == {
            "feature": "soil_latest", "entity_id": "f1", "value": 30.0,
        }

    def test_never_materialized_entity_returns_null_value(self, store, registry) -> None:
        response = FeatureServer(store, registry).handle("GET", "/features/soil_latest/ghost")
        assert response.status == 200
        assert json.loads(response.body)["value"] is None

    def test_unregistered_feature_is_404_when_registry_given(self, store, registry) -> None:
        response = FeatureServer(store, registry).handle("GET", "/features/nope/f1")
        assert response.status == 404

    def test_unregistered_feature_is_allowed_without_a_registry(self, store) -> None:
        # No registry at all - the server can't tell a typo from a real
        # feature, so it just passes the name straight to the store.
        response = FeatureServer(store).handle("GET", "/features/whatever/f1")
        assert response.status == 200
        assert json.loads(response.body)["value"] is None

    def test_trailing_slash_is_accepted(self, store) -> None:
        response = FeatureServer(store).handle("GET", "/features/x/y/")
        assert response.status == 200


class TestServerIntegration:
    def _start(self, store, registry=None):
        httpd = build_server(store, registry, host="127.0.0.1", port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        return httpd, thread, port

    def _stop(self, httpd, thread) -> None:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()

    def test_real_http_request_against_healthz(self, store) -> None:
        httpd, thread, port = self._start(store)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as resp:
                assert resp.status == 200
                assert json.loads(resp.read()) == {"status": "ok"}
        finally:
            self._stop(httpd, thread)

    def test_real_http_request_against_feature_endpoint(self, store, registry) -> None:
        httpd, thread, port = self._start(store, registry)
        try:
            url = f"http://127.0.0.1:{port}/features/soil_latest/f1"
            with urllib.request.urlopen(url, timeout=5) as resp:
                assert resp.status == 200
                assert json.loads(resp.read())["value"] is None
        finally:
            self._stop(httpd, thread)

    def test_real_http_404_raises_httperror(self, store) -> None:
        httpd, thread, port = self._start(store)
        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
            assert exc_info.value.code == 404
        finally:
            self._stop(httpd, thread)

    def test_run_server_stops_cleanly_on_keyboard_interrupt(self, store, monkeypatch) -> None:
        httpd = build_server(store, port=0)

        def raise_interrupt():
            raise KeyboardInterrupt

        monkeypatch.setattr(httpd, "serve_forever", raise_interrupt)
        monkeypatch.setattr("skewproof.serve.build_server", lambda *a, **k: httpd)
        run_server(store, port=0)  # should not raise
