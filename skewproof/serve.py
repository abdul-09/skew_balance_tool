"""
A minimal HTTP layer for serving materialized feature values, with the
observability the rest of the library has been missing: a health check,
request/error counters, and structured per-request logging.

Endpoints:
  GET /healthz                        liveness check - the process is up
  GET /metrics                        Prometheus text-exposition counters
  GET /features/<name>/<entity_id>    the materialized value, or null

This is deliberately small: stdlib http.server, no request framework, no
metrics library. FeatureServer (the routing and response logic) is fully
unit-testable without opening a socket; the tiny amount of code that actually
binds it to http.server is exercised separately with a real ephemeral-port
integration test - see tests/test_serve.py.

Single-threaded (http.server.HTTPServer, not ThreadingHTTPServer): requests
are handled one at a time. That's the right tradeoff for local use, a demo, or
a small internal deployment; it is not meant for high-throughput production
serving - RedisOnlineStore behind a real application server is the answer
there, with this module's routing logic reusable in front of it.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import cast

from .definition import FeatureRegistry
from .redis_store import OnlineStoreProtocol

logger = logging.getLogger(__name__)

_FEATURE_PATH = re.compile(r"^/features/(?P<name>[^/]+)/(?P<entity_id>[^/]+)/?$")


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    content_type: str = "application/json"


def _json(status: int, payload: dict) -> HttpResponse:
    return HttpResponse(status, json.dumps(payload).encode("utf-8"))


@dataclass
class FeatureServer:
    """Routes a (method, path) to a response. No sockets here - see
    build_server()/run_server() for the part that actually listens.

    registry is optional: without one, any feature name is served as-is
    (store.get() returning None just means null); with one, a name that
    isn't registered gets a 404 instead of a null, since that's almost
    always a typo rather than a genuinely-unmaterialized feature.
    """

    store: OnlineStoreProtocol
    registry: FeatureRegistry | None = None
    requests_total: int = field(default=0, init=False)
    errors_total: int = field(default=0, init=False)
    started_at: float = field(default_factory=time.time, init=False)

    def handle(self, method: str, path: str) -> HttpResponse:
        self.requests_total += 1
        start = time.time()
        try:
            response = self._route(method, path)
        except Exception:
            logger.exception("unhandled error handling %s %s", method, path)
            response = _json(500, {"error": "internal server error"})
        if response.status >= 400:
            self.errors_total += 1
        logger.info(
            "%s %s -> %d (%.1fms)", method, path, response.status,
            (time.time() - start) * 1000,
        )
        return response

    def _route(self, method: str, path: str) -> HttpResponse:
        if method != "GET":
            return _json(405, {"error": "method not allowed"})
        if path == "/healthz":
            return _json(200, {"status": "ok"})
        if path == "/metrics":
            body = self._render_metrics().encode("utf-8")
            return HttpResponse(200, body, "text/plain; version=0.0.4")
        match = _FEATURE_PATH.match(path)
        if match:
            return self._handle_feature(match.group("name"), match.group("entity_id"))
        return _json(404, {"error": "not found"})

    def _handle_feature(self, name: str, entity_id: str) -> HttpResponse:
        if self.registry is not None:
            try:
                self.registry.get(name)
            except KeyError:
                return _json(404, {"error": f"unknown feature {name!r}"})
        value = self.store.get(name, entity_id)
        return _json(200, {"feature": name, "entity_id": entity_id, "value": value})

    def _render_metrics(self) -> str:
        uptime = time.time() - self.started_at
        return (
            "# HELP skewproof_requests_total Total HTTP requests served.\n"
            "# TYPE skewproof_requests_total counter\n"
            f"skewproof_requests_total {self.requests_total}\n"
            "# HELP skewproof_errors_total Total HTTP requests with a 4xx/5xx response.\n"
            "# TYPE skewproof_errors_total counter\n"
            f"skewproof_errors_total {self.errors_total}\n"
            "# HELP skewproof_uptime_seconds Seconds since the server started.\n"
            "# TYPE skewproof_uptime_seconds gauge\n"
            f"skewproof_uptime_seconds {uptime:.2f}\n"
        )


class _FeatureHTTPServer(HTTPServer):
    def __init__(
        self, address: tuple[str, int], handler: type, feature_server: FeatureServer
    ) -> None:
        super().__init__(address, handler)
        self.feature_server = feature_server


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
        self._respond("GET")

    def _respond(self, method: str) -> None:
        server = cast(_FeatureHTTPServer, self.server)
        response = server.feature_server.handle(method, self.path)
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        # FeatureServer.handle() already logs every request; suppress
        # BaseHTTPRequestHandler's default write straight to stderr.
        pass


def build_server(
    store: OnlineStoreProtocol,
    registry: FeatureRegistry | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> HTTPServer:
    """Build the server without starting it. Split out from run_server() so
    callers (tests, or an app embedding this differently) can control the
    serve_forever()/shutdown() lifecycle directly - see tests/test_serve.py
    for driving a real request against an OS-assigned ephemeral port."""
    feature_server = FeatureServer(store, registry)
    return _FeatureHTTPServer((host, port), _Handler, feature_server)


def run_server(
    store: OnlineStoreProtocol,
    registry: FeatureRegistry | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Serve features over HTTP until interrupted (Ctrl+C). See the module
    docstring for the endpoints and the single-threaded caveat."""
    httpd = build_server(store, registry, host, port)
    address, actual_port = httpd.server_address[0], httpd.server_address[1]
    logger.info("serving on http://%s:%d", address, actual_port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        httpd.server_close()
