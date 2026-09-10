"""Endpoint-confined HTTP transport for the existing S3 signing adapter.

Uses one connection per streamed response. No redirects, environment proxies,
retries, decompression, or request URL rewriting are performed here.
"""

from __future__ import annotations

import http.client
import math
import threading
from collections.abc import Mapping
from urllib.parse import unquote, urlsplit


class ObjectStoreHttpTransportError(RuntimeError):
    """Sanitized transport failure; excludes URLs, headers and response bodies."""


def _parts(value: str):
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError
    parts = urlsplit(value)
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None or parts.fragment):
        raise ValueError
    port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    if port == 0:
        raise ValueError
    return parts, (parts.scheme, parts.hostname.lower(), port)


def _path(value: str) -> str:
    path = unquote(value, errors="strict") or "/"
    if "\\" in path or any(part in {".", ".."} for part in path.split("/")):
        raise ValueError
    return path


class _Response:
    def __init__(self, owner, connection, response):
        self._owner = owner
        self._connection = connection
        self._response = response
        self.status_code = response.status
        self.headers = {key.lower(): value for key, value in response.getheaders()}
        self._closed = False

    def read(self, size: int = -1) -> bytes:
        # The S3 adapter applies total object/XML limits; this layer bounds each
        # allocation even if another caller accidentally asks for read-all.
        if type(size) is not int or not 0 <= size <= 1024 * 1024:
            raise ObjectStoreHttpTransportError("A bounded response read is required")
        if self._closed:
            raise ObjectStoreHttpTransportError("Object store response is closed")
        try:
            return self._response.read(size)
        except Exception:
            self.close()
            raise ObjectStoreHttpTransportError("Object store response read failed") from None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._response.close()
            finally:
                self._connection.close()
                with self._owner._lock:
                    self._owner._responses.discard(self)


class StdlibS3HttpTransport:
    """Synchronous transport pinned to an explicitly configured endpoint.

    ``timeout_seconds`` is a finite per-socket-operation timeout, not an overall
    request deadline. HTTPS uses Python's default certificate and hostname checks.
    Explicit HTTP is available for local compatible stores via require_https=False.
    """

    def __init__(self, endpoint_url: str, *, timeout_seconds: float = 30.0,
                 require_https: bool = True):
        try:
            endpoint, origin = _parts(endpoint_url)
            if type(require_https) is not bool or endpoint.query or (require_https and endpoint.scheme != "https"):
                raise ValueError
            if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
                raise ValueError
            self._base_path = _path(endpoint.path).rstrip("/")
        except Exception:
            raise ObjectStoreHttpTransportError("Invalid object store transport configuration") from None
        self._origin = origin
        self._timeout = timeout_seconds
        self._closed = False
        self._lock = threading.Lock()
        self._responses: set[_Response] = set()

    def request(self, method: str, url: str, *, headers: Mapping[str, str],
                body: bytes | None = None) -> _Response:
        connection = None
        try:
            with self._lock:
                if self._closed:
                    raise ValueError
            parts, origin = _parts(url)
            path = _path(parts.path)
            if origin != self._origin or (self._base_path and path != self._base_path
                                         and not path.startswith(self._base_path + "/")):
                raise ValueError
            if method not in {"GET", "HEAD", "PUT", "DELETE"}:
                raise ValueError
            if body is not None and not isinstance(body, bytes):
                raise ValueError
            for key, value in headers.items():
                if key.lower() == "host" and value.lower() != parts.netloc.lower():
                    raise ValueError
            scheme, host, port = origin
            factory = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
            connection = factory(host, port, timeout=self._timeout)
            target = parts.path or "/"
            if parts.query:
                target += "?" + parts.query
            connection.request(method, target, body=body, headers=dict(headers))
            response = _Response(self, connection, connection.getresponse())
            with self._lock:
                if self._closed:
                    connection.close()
                    raise ValueError
                self._responses.add(response)
            return response
        except Exception:
            if connection is not None:
                connection.close()
            raise ObjectStoreHttpTransportError("Object store HTTP request failed") from None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            responses = tuple(self._responses)
        for response in responses:
            response.close()
