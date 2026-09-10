#!/usr/bin/env python3
"""Run bounded live gates for S3-compatible object storage and Qdrant.

The gate only talks to explicitly configured HTTP services.  It creates
UUID-scoped disposable fixtures, bounds every request and response, performs
negative isolation and cleanup assertions, and records only safe summaries.
Missing configuration or an unavailable dependency is ``BLOCKED_EXTERNAL``;
it is never converted into a runtime claim.  A pass covers only the
operations exercised here and is not a production or promotion approval.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
import ipaddress
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-2/object-qdrant-runtime-gate.json"
DEFAULT_TIMEOUT_SECONDS = 5.0
FAULT_TIMEOUT_SECONDS = 0.25
MAX_FIXTURE_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_QDRANT_POINTS = 8
MAX_QDRANT_RESULTS = 8
MAX_POLL_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.05

PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"


class _BlockedExternal(Exception):
    """Configuration or dependency is not safe/available to attempt."""


class _InvalidConfiguration(Exception):
    """Configuration is present but violates the bounded contract."""


class _TransportTimeout(RuntimeError):
    """Internal marker that lets the Qdrant adapter classify a timeout."""


class _TransportFailure(RuntimeError):
    """Internal marker for a transport failure without response content."""


class _ResponseTooLarge(RuntimeError):
    """A live response crossed the gate's hard body limit."""


class _QdrantHttpFailure(RuntimeError):
    """A direct control-plane request returned a non-success status."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("Qdrant control-plane request failed")


class _BoundedFixtureStream(BytesIO):
    """File-like fixture that forces the storage adapter through many reads."""

    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.read_calls = 0

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if size < 0:
            size = 257
        return super().read(min(size, 257))


@dataclass(frozen=True)
class GateResult:
    name: str
    result: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        value = {"name": self.name, "result": self.result}
        if self.detail:
            value["detail"] = self.detail
        return value


@dataclass(frozen=True)
class Endpoint:
    """Validated endpoint kept in memory; reports expose only safe metadata."""

    raw: str
    parsed: SplitResult
    is_loopback: bool

    @property
    def tls(self) -> bool:
        return self.parsed.scheme == "https"

    def report(self) -> dict[str, object]:
        try:
            port = self.parsed.port
        except ValueError:
            port = None
        return {
            "scheme": self.parsed.scheme,
            "host_scope": "loopback" if self.is_loopback else "nonloopback",
            "port_configured": port is not None,
            "path_configured": bool(self.parsed.path),
        }


class _NoRedirect(HTTPRedirectHandler):
    """Do not allow a configured service URL to redirect elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class _UrllibResponse:
    """Small response wrapper implementing the storage transport contract."""

    def __init__(self, response: object) -> None:
        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "code", None)
        if type(status) is not int:
            raise RuntimeError("invalid HTTP response")
        headers = getattr(response, "headers", None)
        items = getattr(headers, "items", None)
        if not callable(items):
            raise RuntimeError("invalid HTTP response headers")
        self.status_code = status
        self.headers = {str(name).lower(): str(value) for name, value in items()}
        self._response = response
        self._closed = False

    def read(self, size: int = -1) -> bytes:
        value = self._response.read(size)
        if not isinstance(value, bytes):
            raise RuntimeError("invalid HTTP response body")
        return value

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._response, "close", None)
        if callable(close):
            close()


class _UrllibTransport:
    """Real bounded HTTP transport for the injected S3 adapter."""

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> _UrllibResponse:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            response = self._opener.open(request, timeout=self._timeout)
        except HTTPError as error:
            return _UrllibResponse(error)
        except (OSError, TimeoutError, URLError) as error:
            if _looks_like_timeout(error):
                raise _TransportTimeout("HTTP transport timed out") from error
            raise _TransportFailure("HTTP transport failed") from error
        return _UrllibResponse(response)

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class _QdrantResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]


class _QdrantTransport:
    """Real Qdrant HTTP transport with bounded bodies and safe observations."""

    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirect())
        self.request_count = 0
        self.status_counts: dict[str, int] = {}
        self.filter_observations: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes,
        timeout: float,
    ) -> _QdrantResponse:
        self.request_count += 1
        self._observe_filter(content)
        request = Request(
            url,
            data=content or None,
            headers=dict(headers),
            method=method,
        )
        response: object | None = None
        try:
            try:
                response = self._opener.open(request, timeout=timeout)
            except HTTPError as error:
                response = error
            status = getattr(response, "status", None)
            if status is None:
                status = getattr(response, "code", None)
            if type(status) is not int:
                raise RuntimeError("invalid Qdrant HTTP response")
            response_headers = getattr(response, "headers", None)
            items = getattr(response_headers, "items", None)
            reader = getattr(response, "read", None)
            if not callable(items) or not callable(reader):
                raise RuntimeError("invalid Qdrant HTTP response")
            body = _read_bounded(reader, MAX_RESPONSE_BYTES)
            normalized_headers = {str(name).lower(): str(value) for name, value in items()}
            self.status_counts[str(status)] = self.status_counts.get(str(status), 0) + 1
            return _QdrantResponse(status, body, normalized_headers)
        except (_TransportTimeout, _TransportFailure):
            raise
        except (OSError, TimeoutError, URLError) as error:
            if _looks_like_timeout(error):
                raise _TransportTimeout("Qdrant HTTP transport timed out") from error
            raise _TransportFailure("Qdrant HTTP transport failed") from error
        except _ResponseTooLarge:
            raise
        except RuntimeError as error:
            raise _TransportFailure("Qdrant HTTP response was invalid") from error
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _observe_filter(self, body: bytes) -> None:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(parsed, Mapping) or not isinstance(parsed.get("filter"), Mapping):
            return
        must = parsed["filter"].get("must")
        if not isinstance(must, list):
            return
        observation: dict[str, object] = {}
        for clause in must:
            if not isinstance(clause, Mapping):
                continue
            field = clause.get("key")
            match = clause.get("match")
            if not isinstance(field, str) or not isinstance(match, Mapping):
                continue
            if "value" in match:
                observation[field] = match["value"]
            elif isinstance(match.get("any"), list):
                observation[field] = list(match["any"])
        self.filter_observations.append(observation)

    def close(self) -> None:
        return None


def _read_bounded(reader: object, limit: int) -> bytes:
    read = reader if callable(reader) else None
    if read is None:
        raise RuntimeError("response reader unavailable")
    chunks: list[bytes] = []
    total = 0
    while True:
        requested = min(16 * 1024, limit - total + 1)
        if requested <= 0:
            raise _ResponseTooLarge("response exceeded bound")
        chunk = read(requested)
        if not isinstance(chunk, bytes):
            raise RuntimeError("response body was not bytes")
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise _ResponseTooLarge("response exceeded bound")
        chunks.append(chunk)
    return b"".join(chunks)


def _looks_like_timeout(error: BaseException) -> bool:
    if isinstance(error, TimeoutError):
        return True
    reason = getattr(error, "reason", None)
    return "timeout" in type(error).__name__.lower() or "timed out" in str(reason).lower()


def _env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _parse_endpoint(
    value: str,
    *,
    allow_nonlocal: bool,
    require_tls: bool,
) -> Endpoint:
    if not isinstance(value, str) or not value.strip():
        raise _BlockedExternal()
    candidate = value.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            raise ValueError
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.query or parsed.fragment:
            raise ValueError
        _ = parsed.port
    except (TypeError, UnicodeError, ValueError):
        raise _InvalidConfiguration() from None
    loopback = _is_loopback(parsed.hostname)
    if not allow_nonlocal and not loopback:
        raise _BlockedExternal()
    if require_tls and parsed.scheme != "https":
        raise _InvalidConfiguration()
    normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    return Endpoint(normalized, urlsplit(normalized), loopback)


def _redacted_auth(*, configured: bool, kind: str) -> dict[str, object]:
    return {"kind": kind, "configured": configured, "secret_values": "omitted"}


def _gate_report(
    status: str,
    results: list[GateResult],
    *,
    endpoint: Endpoint | None = None,
    auth_configured: bool = False,
    auth_kind: str = "none",
    production_safe: bool = False,
    observations: Mapping[str, object] | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "status": status,
        "live": status == PASS,
        "endpoint": endpoint.report() if endpoint is not None else None,
        "authentication": _redacted_auth(configured=auth_configured, kind=auth_kind),
        "results": [result.to_dict() for result in results],
        "production_safe": bool(production_safe),
        "promotable": bool(production_safe),
    }
    if observations:
        report["observations"] = dict(observations)
    return report


def _arg_text(args: argparse.Namespace, name: str) -> str:
    value = getattr(args, name, "")
    return value.strip() if isinstance(value, str) else ""


def _missing_object_configuration(args: argparse.Namespace) -> bool:
    return not all(
        (
            _arg_text(args, "object_endpoint"),
            _arg_text(args, "object_bucket"),
            _arg_text(args, "object_region"),
            _arg_text(args, "object_access_key"),
            _arg_text(args, "object_secret_key"),
        )
    )


def _object_url(endpoint: Endpoint, bucket: str, scope: object, key: str) -> str:
    tenant_id = getattr(scope, "tenant_id")
    workspace_id = getattr(scope, "workspace_id")
    source_id = getattr(scope, "source_id")
    remote_key = (
        f"runtime-gate/tenants/{tenant_id}/workspaces/{workspace_id}/"
        f"sources/{source_id}/objects/{key}"
    )
    raw_path = (
        f"{endpoint.parsed.path.rstrip('/')}/{quote(bucket, safe='-._~')}/"
        f"{quote(remote_key, safe='/-._~')}"
    )
    return urlunsplit(
        (
            endpoint.parsed.scheme,
            endpoint.parsed.netloc,
            quote(raw_path, safe="/%:@-._~"),
            "",
            "",
        )
    )


def _unsigned_object_status(
    transport: _UrllibTransport,
    endpoint: Endpoint,
    bucket: str,
    scope: object,
    key: str,
) -> int | None:
    response = None
    try:
        response = transport.request("HEAD", _object_url(endpoint, bucket, scope, key), headers={})
        return response.status_code
    except (_TransportTimeout, _TransportFailure):
        return None
    finally:
        if response is not None:
            response.close()


def _object_external_error(error: BaseException) -> bool:
    name = type(error).__name__
    if name in {"ObjectStoreTransportError", "ObjectStoreIOError"}:
        return True
    return name == "ObjectStoreRemoteError" and getattr(error, "retryable", False) is True


def _run_object_gate(args: argparse.Namespace, run_id: str) -> dict[str, object]:
    if _missing_object_configuration(args):
        return _gate_report(
            BLOCKED_EXTERNAL,
            [GateResult("configuration", BLOCKED_EXTERNAL, "object-store endpoint, bucket, region, and credentials are required")],
            auth_kind="aws_sigv4",
        )

    try:
        endpoint = _parse_endpoint(
            _arg_text(args, "object_endpoint"),
            allow_nonlocal=bool(getattr(args, "allow_nonlocal", False)),
            require_tls=bool(getattr(args, "require_tls", False)),
        )
    except _BlockedExternal:
        return _gate_report(
            BLOCKED_EXTERNAL,
            [GateResult("endpoint-policy", BLOCKED_EXTERNAL, "non-loopback object-store endpoint requires --allow-nonlocal")],
            auth_kind="aws_sigv4",
        )
    except _InvalidConfiguration:
        return _gate_report(
            FAIL,
            [GateResult("configuration", FAIL, "object-store endpoint or TLS configuration was rejected")],
            auth_kind="aws_sigv4",
        )

    try:
        source_root = ROOT / "packages/storage/src"
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
        from rick_storage import (
            AwsCredentials,
            ObjectNotFoundError,
            ObjectReadLimitExceededError,
            ObjectScope,
            ObjectTooLargeError,
            S3ObjectStore,
        )
    except ImportError:
        return _gate_report(
            BLOCKED_EXTERNAL,
            [GateResult("driver", BLOCKED_EXTERNAL, "storage package is unavailable")],
            endpoint=endpoint,
            auth_configured=True,
            auth_kind="aws_sigv4",
        )

    transport = _UrllibTransport(DEFAULT_TIMEOUT_SECONDS)
    store = None
    results: list[GateResult] = []
    blocked_external = False
    fixture_refs: list[tuple[object, str]] = []
    created_refs: list[tuple[object, str]] = []
    stream_read_calls = 0

    def add(name: str, result: str, detail: str) -> None:
        nonlocal blocked_external
        results.append(GateResult(name, result, detail))
        blocked_external = blocked_external or result == BLOCKED_EXTERNAL

    scope_a = ObjectScope(
        f"runtime-tenant-{run_id}",
        f"runtime-workspace-{run_id}",
        f"runtime-source-{run_id}",
    )
    tenant_scope = ObjectScope(
        f"runtime-tenant-other-{run_id}",
        f"runtime-workspace-{run_id}",
        f"runtime-source-{run_id}",
    )
    workspace_scope = ObjectScope(
        f"runtime-tenant-{run_id}",
        f"runtime-workspace-other-{run_id}",
        f"runtime-source-{run_id}",
    )
    key = "fixture.bin"
    tenant_only_key = "tenant-only.bin"
    workspace_only_key = "workspace-only.bin"
    payload_a = (f"rick-object-runtime:{run_id}:tenant-a:" + "A" * 4097).encode("ascii")
    payload_tenant = (f"rick-object-runtime:{run_id}:tenant-b:" + "B" * 4097).encode("ascii")
    payload_workspace = (f"rick-object-runtime:{run_id}:workspace-b:" + "C" * 4097).encode("ascii")
    fixture_values = (
        (scope_a, key, payload_a),
        (tenant_scope, key, payload_tenant),
        (tenant_scope, tenant_only_key, payload_tenant),
        (workspace_scope, key, payload_workspace),
        (workspace_scope, workspace_only_key, payload_workspace),
    )
    fixture_refs = [(scope, fixture_key) for scope, fixture_key, _payload in fixture_values]

    try:
        try:
            store = S3ObjectStore(
                endpoint.raw,
                _arg_text(args, "object_bucket"),
                _arg_text(args, "object_region"),
                AwsCredentials(
                    _arg_text(args, "object_access_key"),
                    _arg_text(args, "object_secret_key"),
                    _arg_text(args, "object_session_token") or None,
                ),
                transport,
                key_prefix="runtime-gate",
                max_object_bytes=MAX_FIXTURE_BYTES,
                max_read_bytes=MAX_FIXTURE_BYTES,
                max_response_bytes=MAX_RESPONSE_BYTES,
                max_list_items=8,
                require_https=bool(getattr(args, "require_tls", False)),
            )
        except Exception:
            add("configuration", FAIL, "object-store configuration was rejected")
            return _gate_report(
                FAIL,
                results,
                endpoint=endpoint,
                auth_configured=True,
                auth_kind="aws_sigv4",
            )

        if not store.health_check():
            add("health", BLOCKED_EXTERNAL, "object-store health probe could not reach the configured service")
        else:
            add("health", PASS, "bucket health probe succeeded")
            metadata_by_ref: dict[tuple[object, str], object] = {}
            put_failed = False
            for scope, fixture_key, payload in fixture_values:
                fixture_stream = _BoundedFixtureStream(payload)
                try:
                    metadata = store.put(scope, fixture_key, fixture_stream)
                    expected_checksum = hashlib.sha256(payload).hexdigest()
                    stream_read_calls += fixture_stream.read_calls
                    put_ok = (
                        metadata.size == len(payload)
                        and metadata.sha256 == expected_checksum
                        and metadata.tenant_id == scope.tenant_id
                        and metadata.workspace_id == scope.workspace_id
                        and fixture_stream.read_calls >= 2
                    )
                    if put_ok:
                        metadata_by_ref[(scope, fixture_key)] = metadata
                        created_refs.append((scope, fixture_key))
                    else:
                        put_failed = True
                except Exception as error:
                    stream_read_calls += fixture_stream.read_calls
                    put_failed = True
                    if _object_external_error(error):
                        blocked_external = True
            add(
                "put-streaming",
                BLOCKED_EXTERNAL if blocked_external else (FAIL if put_failed else PASS),
                "bounded file-like uploads returned scoped checksum and size metadata"
                if not put_failed and not blocked_external
                else "live object PUT was unavailable"
                if blocked_external
                else "one or more live object PUT assertions failed",
            )

            idempotent_ok = False
            if not put_failed and not blocked_external:
                try:
                    repeated_stream = _BoundedFixtureStream(payload_a)
                    repeated = store.put(scope_a, key, repeated_stream)
                    stream_read_calls += repeated_stream.read_calls
                    idempotent_ok = repeated == metadata_by_ref[(scope_a, key)]
                except Exception as error:
                    blocked_external = blocked_external or _object_external_error(error)
            add(
                "put-idempotent",
                BLOCKED_EXTERNAL if blocked_external and not idempotent_ok else (PASS if idempotent_ok else FAIL),
                "repeating the same scoped upload preserved metadata"
                if idempotent_ok
                else "idempotent upload could not be verified",
            )

            heads_ok = False
            gets_ok = False
            if created_refs and not blocked_external:
                heads_ok = True
                gets_ok = True
                for scope, fixture_key, payload in fixture_values:
                    try:
                        headed = store.head(scope, fixture_key)
                        expected_checksum = hashlib.sha256(payload).hexdigest()
                        heads_ok = heads_ok and headed.size == len(payload) and headed.sha256 == expected_checksum
                        fetched = store.get(scope, fixture_key, max_bytes=MAX_FIXTURE_BYTES)
                        gets_ok = gets_ok and fetched == payload
                    except Exception as error:
                        heads_ok = False
                        gets_ok = False
                        blocked_external = blocked_external or _object_external_error(error)
                        break
            add(
                "head-checksum-content-length",
                BLOCKED_EXTERNAL if blocked_external and not heads_ok else (PASS if heads_ok else FAIL),
                "HEAD verified checksum and content length for every scoped fixture"
                if heads_ok
                else "live HEAD metadata did not satisfy checksum/content-length assertions",
            )
            add(
                "get-streaming-integrity",
                BLOCKED_EXTERNAL if blocked_external and not gets_ok else (PASS if gets_ok else FAIL),
                "GET streamed bounded bodies and matched every fixture"
                if gets_ok
                else "live GET did not match the bounded fixture bytes",
            )

            read_limit_ok = False
            oversize_ok = False
            if (scope_a, key) in created_refs and not blocked_external:
                try:
                    store.get(scope_a, key, max_bytes=len(payload_a) - 1)
                except ObjectReadLimitExceededError:
                    read_limit_ok = True
                except Exception as error:
                    blocked_external = blocked_external or _object_external_error(error)
                try:
                    oversize_stream = _BoundedFixtureStream(b"x" * (MAX_FIXTURE_BYTES + 1))
                    store.put(scope_a, "oversize.bin", oversize_stream)
                    stream_read_calls += oversize_stream.read_calls
                except ObjectTooLargeError:
                    stream_read_calls += oversize_stream.read_calls
                    oversize_ok = True
                except Exception as error:
                    stream_read_calls += oversize_stream.read_calls
                    blocked_external = blocked_external or _object_external_error(error)
            add(
                "streaming-limits",
                BLOCKED_EXTERNAL if blocked_external and not (read_limit_ok and oversize_ok) else (PASS if read_limit_ok and oversize_ok else FAIL),
                "GET and streaming PUT enforced the configured byte ceiling"
                if read_limit_ok and oversize_ok
                else "object read/write limit assertions were not satisfied",
            )

            private_ok = False
            if (scope_a, key) in created_refs and not blocked_external:
                anonymous_status = _unsigned_object_status(
                    transport,
                    endpoint,
                    _arg_text(args, "object_bucket"),
                    scope_a,
                    key,
                )
                private_ok = anonymous_status in {401, 403}
            add(
                "private-access",
                BLOCKED_EXTERNAL if blocked_external and not private_ok else (PASS if private_ok else FAIL),
                "unsigned access to the existing fixture was rejected"
                if private_ok
                else "private object access was not proven by an anonymous HEAD rejection",
            )

            isolation_ok = False
            if not blocked_external and all(ref in created_refs for ref in fixture_refs):
                try:
                    tenant_items = {item.key for item in store.list(tenant_scope, limit=8)}
                    workspace_items = {item.key for item in store.list(workspace_scope, limit=8)}
                    a_private_tenant = False
                    a_private_workspace = False
                    try:
                        store.head(scope_a, tenant_only_key)
                    except ObjectNotFoundError:
                        a_private_tenant = True
                    try:
                        store.head(scope_a, workspace_only_key)
                    except ObjectNotFoundError:
                        a_private_workspace = True
                    isolation_ok = (
                        tenant_items == {key, tenant_only_key}
                        and workspace_items == {key, workspace_only_key}
                        and a_private_tenant
                        and a_private_workspace
                    )
                except Exception as error:
                    blocked_external = blocked_external or _object_external_error(error)
            add(
                "tenant-workspace-isolation",
                BLOCKED_EXTERNAL if blocked_external and not isolation_ok else (PASS if isolation_ok else FAIL),
                "tenant and workspace listings/reads remained in their exact namespaces"
                if isolation_ok
                else "cross-tenant or cross-workspace isolation was not proven",
            )

            delete_ok = False
            delete_idempotent_ok = False
            restore_negative_ok = False
            if created_refs and not blocked_external:
                delete_ok = True
                for scope, fixture_key in created_refs:
                    try:
                        delete_ok = delete_ok and bool(store.delete(scope, fixture_key))
                    except Exception as error:
                        delete_ok = False
                        blocked_external = blocked_external or _object_external_error(error)
                if delete_ok and not blocked_external:
                    delete_idempotent_ok = True
                    restore_negative_ok = True
                    for scope, fixture_key in created_refs:
                        try:
                            delete_idempotent_ok = delete_idempotent_ok and not bool(store.delete(scope, fixture_key))
                            try:
                                store.head(scope, fixture_key)
                            except ObjectNotFoundError:
                                pass
                            else:
                                restore_negative_ok = False
                            try:
                                store.get(scope, fixture_key, max_bytes=MAX_FIXTURE_BYTES)
                            except ObjectNotFoundError:
                                pass
                            else:
                                restore_negative_ok = False
                        except Exception as error:
                            delete_idempotent_ok = False
                            restore_negative_ok = False
                            blocked_external = blocked_external or _object_external_error(error)
            add(
                "delete",
                BLOCKED_EXTERNAL if blocked_external and not delete_ok else (PASS if delete_ok else FAIL),
                "all live fixture objects were deleted" if delete_ok else "fixture DELETE was not acknowledged for every object",
            )
            add(
                "delete-idempotent",
                BLOCKED_EXTERNAL if blocked_external and not delete_idempotent_ok else (PASS if delete_idempotent_ok else FAIL),
                "repeated DELETE returned absence without resurrecting a fixture"
                if delete_idempotent_ok
                else "repeated object DELETE was not idempotent",
            )
            add(
                "restore-negative",
                BLOCKED_EXTERNAL if blocked_external and not restore_negative_ok else (PASS if restore_negative_ok else FAIL),
                "deleted objects remained absent on HEAD and GET; no restore claim was made"
                if restore_negative_ok
                else "deleted object absence could not be verified",
            )
    finally:
        if store is not None:
            cleanup_ok = True
            for scope, fixture_key in fixture_refs:
                try:
                    store.delete(scope, fixture_key)
                except Exception as error:
                    cleanup_ok = False
                    blocked_external = blocked_external or _object_external_error(error)
                try:
                    store.head(scope, fixture_key)
                except ObjectNotFoundError:
                    pass
                except Exception as error:
                    cleanup_ok = False
                    blocked_external = blocked_external or _object_external_error(error)
                else:
                    cleanup_ok = False
            results.append(
                GateResult(
                    "cleanup",
                    BLOCKED_EXTERNAL if blocked_external and not cleanup_ok else (PASS if cleanup_ok else FAIL),
                    "all UUID-scoped object fixtures are absent" if cleanup_ok else "object fixture cleanup could not be verified",
                )
            )
            try:
                store.close()
            except Exception:
                results.append(GateResult("close", FAIL, "object-store transport close failed"))

    status = BLOCKED_EXTERNAL if blocked_external else (PASS if results and all(item.result == PASS for item in results) else FAIL)
    production_safe = bool(status == PASS and getattr(args, "require_tls", False) and endpoint.tls)
    return _gate_report(
        status,
        results,
        endpoint=endpoint,
        auth_configured=True,
        auth_kind="aws_sigv4",
        production_safe=production_safe,
        observations={
            "fixture_count": len(fixture_values),
            "created_fixture_count": len(created_refs),
            "stream_read_calls": stream_read_calls,
            "max_fixture_bytes": MAX_FIXTURE_BYTES,
            "restore_claim": False,
        },
    )


def _qdrant_headers(api_key: str) -> dict[str, str]:
    headers = {"accept": "application/json", "content-type": "application/json"}
    if api_key:
        headers["api-key"] = api_key
    return headers


def _qdrant_json_request(
    transport: _QdrantTransport,
    endpoint: Endpoint,
    path: str,
    api_key: str,
    *,
    method: str = "GET",
    body: Mapping[str, object] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> _QdrantResponse:
    content = b""
    if body is not None:
        try:
            content = json.dumps(body, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            raise _InvalidConfiguration() from None
        if len(content) > MAX_FIXTURE_BYTES:
            raise _InvalidConfiguration() from None
    return transport.request(
        method,
        f"{endpoint.raw}{path}",
        headers=_qdrant_headers(api_key),
        content=content,
        timeout=timeout,
    )


def _qdrant_json_body(response: _QdrantResponse) -> object:
    if not response.content:
        raise RuntimeError("Qdrant response body was empty")
    try:
        return json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Qdrant response body was malformed") from error


def _collection_schema(
    transport: _QdrantTransport,
    endpoint: Endpoint,
    collection: str,
    api_key: str,
) -> tuple[bool, set[str]]:
    response = _qdrant_json_request(
        transport,
        endpoint,
        f"/collections/{quote(collection, safe='')}",
        api_key,
    )
    if response.status_code != 200:
        raise _QdrantHttpFailure(response.status_code)
    parsed = _qdrant_json_body(response)
    if not isinstance(parsed, Mapping) or not isinstance(parsed.get("result"), Mapping):
        raise RuntimeError("Qdrant collection response was malformed")
    result = parsed["result"]
    config = result.get("config")
    params = config.get("params") if isinstance(config, Mapping) else None
    vectors = params.get("vectors") if isinstance(params, Mapping) else None
    vector_config = vectors.get("dense") if isinstance(vectors, Mapping) and "dense" in vectors else vectors
    schema_ok = (
        isinstance(vector_config, Mapping)
        and vector_config.get("size") == 3
        and vector_config.get("distance") == "Cosine"
    )
    payload_schema = result.get("payload_schema")
    indexed_fields: set[str] = set()
    if isinstance(payload_schema, Mapping):
        for field_name, raw_schema in payload_schema.items():
            if not isinstance(field_name, str) or not isinstance(raw_schema, Mapping):
                continue
            data_type = raw_schema.get("data_type")
            if data_type is None and isinstance(raw_schema.get("params"), Mapping):
                data_type = raw_schema["params"].get("type")
            if data_type == "keyword":
                indexed_fields.add(field_name)
    return schema_ok, indexed_fields


def _filter_observation_matches(
    transport: _QdrantTransport,
    tenant: str,
    workspace: str,
    collection_id: str,
) -> bool:
    if not transport.filter_observations:
        return False
    observation = transport.filter_observations[-1]
    allowed = observation.get("collection_id")
    return (
        observation.get("tenant_id") == tenant
        and observation.get("workspace_id") == workspace
        and (allowed == collection_id or isinstance(allowed, list) and collection_id in allowed)
    )


def _query_scoped(
    vector_store: object,
    vector: Sequence[float],
    *,
    tenant: str,
    workspace: str,
    collection_id: str,
    limit: int = MAX_QDRANT_RESULTS,
) -> list[object]:
    from rick_retrieval.qdrant import QdrantStatusError

    try:
        return vector_store.query(
            vector,
            tenant_id=tenant,
            workspace_id=workspace,
            allowed_collection_ids=[collection_id],
            limit=limit,
        )
    except QdrantStatusError as error:
        if error.status_code not in {404, 405}:
            raise
        return vector_store.search(
            vector,
            tenant_id=tenant,
            workspace_id=workspace,
            allowed_collection_ids=[collection_id],
            limit=limit,
        )


def _delete_qdrant_collection(
    endpoint: Endpoint,
    collection: str,
    api_key: str,
) -> str:
    """Delete only the UUID-derived collection created by this run."""

    transport = _QdrantTransport()
    try:
        response = _qdrant_json_request(
            transport,
            endpoint,
            f"/collections/{quote(collection, safe='')}",
            api_key,
            method="DELETE",
        )
        if response.status_code == 404:
            return "absent"
        if response.status_code not in {200, 202, 204}:
            raise _QdrantHttpFailure(response.status_code)
        if response.status_code in {200, 202}:
            parsed = _qdrant_json_body(response)
            if not isinstance(parsed, Mapping) or parsed.get("result") is False or parsed.get("result") is None:
                raise RuntimeError("Qdrant collection delete was not acknowledged")
        return "deleted"
    finally:
        transport.close()


def _delete_qdrant_alias(
    transport: _QdrantTransport,
    endpoint: Endpoint,
    alias: str,
    api_key: str,
) -> str:
    response = _qdrant_json_request(
        transport,
        endpoint,
        "/collections/aliases",
        api_key,
        method="POST",
        body={"actions": [{"action": "delete_alias", "alias_name": alias}]},
    )
    if response.status_code == 404:
        return "absent"
    if response.status_code not in {200, 202}:
        raise _QdrantHttpFailure(response.status_code)
    parsed = _qdrant_json_body(response)
    if not isinstance(parsed, Mapping) or parsed.get("result") is False or parsed.get("result") is None:
        raise RuntimeError("Qdrant alias delete was not acknowledged")
    return "deleted"


def _qdrant_external_error(error: BaseException) -> bool:
    if type(error).__name__ == "_QdrantHttpFailure":
        return int(getattr(error, "status_code", 0)) >= 500
    return type(error).__name__ in {
        "QdrantDependencyError",
        "QdrantTimeoutError",
        "QdrantTransportError",
        "_TransportTimeout",
        "_TransportFailure",
        "_ResponseTooLarge",
    }


def _run_qdrant_failure_policy(
    args: argparse.Namespace,
    endpoint: Endpoint,
    api_key: str,
    run_id: str,
) -> tuple[list[GateResult], bool]:
    """Exercise timeout and retry/circuit policy only through real endpoints."""

    results: list[GateResult] = []
    blocked = False
    fault_raw = _arg_text(args, "qdrant_fault_url")
    timeout_raw = _arg_text(args, "qdrant_timeout_url")
    if not fault_raw:
        results.append(GateResult("retry-circuit", BLOCKED_EXTERNAL, "a disposable real fault endpoint is required for transient failure evidence"))
        blocked = True
    if not timeout_raw:
        results.append(GateResult("timeout", BLOCKED_EXTERNAL, "a disposable real timeout endpoint is required for timeout evidence"))
        blocked = True
    if blocked:
        return results, True

    try:
        fault_endpoint = _parse_endpoint(
            fault_raw,
            allow_nonlocal=bool(getattr(args, "allow_nonlocal", False)),
            require_tls=bool(getattr(args, "require_tls", False)),
        )
        timeout_endpoint = _parse_endpoint(
            timeout_raw,
            allow_nonlocal=bool(getattr(args, "allow_nonlocal", False)),
            require_tls=bool(getattr(args, "require_tls", False)),
        )
    except _BlockedExternal:
        return [GateResult("fault-endpoint-policy", BLOCKED_EXTERNAL, "non-loopback fault endpoints require --allow-nonlocal")], True
    except _InvalidConfiguration:
        return [GateResult("fault-endpoint-configuration", FAIL, "fault endpoint or TLS configuration was rejected")], False

    from rick_retrieval.qdrant import (
        QdrantCircuitOpenError,
        QdrantHttpVectorStore,
        QdrantStatusError,
        QdrantTimeoutError,
        QdrantTransportError,
    )

    fault_transport = _QdrantTransport()
    timeout_transport = _QdrantTransport()
    fault_store = None
    timeout_store = None
    try:
        try:
            fault_store = QdrantHttpVectorStore(
                base_url=fault_endpoint.raw,
                collection=f"runtime_fault_{run_id}",
                api_key=api_key or None,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                transport=fault_transport,
                max_points=1,
                max_query_results=1,
                max_payload_bytes=MAX_FIXTURE_BYTES,
                max_response_bytes=MAX_RESPONSE_BYTES,
                max_attempts=2,
                retry_backoff_seconds=0.01,
                circuit_failure_threshold=1,
                circuit_reset_seconds=1.0,
            )
            first_error = None
            try:
                fault_store.health()
            except (QdrantStatusError, QdrantTimeoutError, QdrantTransportError) as error:
                first_failure = True
                first_error = error
            else:
                first_failure = False
            retry_ok = (
                first_failure
                and fault_transport.request_count >= 2
                and (
                    isinstance(first_error, QdrantTimeoutError)
                    or any(int(status) in {408, 425, 429} or int(status) >= 500 for status in fault_transport.status_counts)
                )
            )
            fault_unavailable = isinstance(first_error, QdrantTransportError) and not fault_transport.status_counts
            circuit_ok = False
            if retry_ok:
                try:
                    fault_store.health()
                except QdrantCircuitOpenError:
                    circuit_ok = True
                except (QdrantStatusError, QdrantTimeoutError, QdrantTransportError):
                    circuit_ok = False
            results.append(
                GateResult(
                    "retry-circuit",
                    BLOCKED_EXTERNAL if fault_unavailable else PASS if retry_ok and circuit_ok else FAIL,
                    "real retryable failure was retried and the circuit then opened"
                    if retry_ok and circuit_ok
                    else "fault endpoint was unavailable"
                    if fault_unavailable
                    else "fault endpoint did not produce bounded retry and circuit-open evidence",
                )
            )
            blocked = blocked or fault_unavailable
        except Exception as error:
            unavailable = _qdrant_external_error(error) and not fault_transport.status_counts
            results.append(
                GateResult(
                    "retry-circuit",
                    BLOCKED_EXTERNAL if unavailable else FAIL,
                    "fault endpoint was unavailable" if unavailable else "retry/circuit probe failed",
                )
            )
            blocked = blocked or unavailable

        try:
            timeout_store = QdrantHttpVectorStore(
                base_url=timeout_endpoint.raw,
                collection=f"runtime_timeout_{run_id}",
                api_key=api_key or None,
                timeout=FAULT_TIMEOUT_SECONDS,
                transport=timeout_transport,
                max_points=1,
                max_query_results=1,
                max_payload_bytes=MAX_FIXTURE_BYTES,
                max_response_bytes=MAX_RESPONSE_BYTES,
                max_attempts=1,
                retry_backoff_seconds=0,
                circuit_failure_threshold=1,
                circuit_reset_seconds=1.0,
            )
            timeout_unavailable = False
            try:
                timeout_store.health()
            except QdrantTimeoutError:
                timeout_ok = True
            except QdrantStatusError:
                timeout_ok = False
            except QdrantTransportError:
                timeout_ok = False
                timeout_unavailable = not timeout_transport.status_counts
            else:
                timeout_ok = False
            results.append(
                GateResult(
                    "timeout",
                    PASS if timeout_ok else BLOCKED_EXTERNAL if timeout_unavailable else FAIL,
                    "real Qdrant timeout was classified fail-closed within the configured bound"
                    if timeout_ok
                    else "timeout endpoint was unavailable"
                    if timeout_unavailable
                    else "timeout endpoint did not produce a typed timeout observation",
                )
            )
            blocked = blocked or timeout_unavailable
        except Exception as error:
            unavailable = _qdrant_external_error(error) and not timeout_transport.status_counts
            results.append(
                GateResult(
                    "timeout",
                    BLOCKED_EXTERNAL if unavailable else FAIL,
                    "timeout endpoint was unavailable" if unavailable else "timeout probe failed",
                )
            )
            blocked = blocked or unavailable
    finally:
        for store in (fault_store, timeout_store):
            if store is not None:
                try:
                    store.close()
                except Exception:
                    results.append(GateResult("fault-close", FAIL, "fault transport close failed"))
    return results, blocked


def _run_vector_gate(args: argparse.Namespace, run_id: str) -> dict[str, object]:
    qdrant_raw = _arg_text(args, "qdrant_url")
    if not qdrant_raw:
        return _gate_report(
            BLOCKED_EXTERNAL,
            [GateResult("configuration", BLOCKED_EXTERNAL, "Qdrant URL is required")],
            auth_kind="qdrant_api_key",
        )

    try:
        endpoint = _parse_endpoint(
            qdrant_raw,
            allow_nonlocal=bool(getattr(args, "allow_nonlocal", False)),
            require_tls=bool(getattr(args, "require_tls", False)),
        )
    except _BlockedExternal:
        return _gate_report(
            BLOCKED_EXTERNAL,
            [GateResult("endpoint-policy", BLOCKED_EXTERNAL, "non-loopback Qdrant endpoint requires --allow-nonlocal")],
            auth_kind="qdrant_api_key",
        )
    except _InvalidConfiguration:
        return _gate_report(
            FAIL,
            [GateResult("configuration", FAIL, "Qdrant URL or TLS configuration was rejected")],
            auth_kind="qdrant_api_key",
        )

    api_key = _arg_text(args, "qdrant_api_key")
    if not endpoint.is_loopback and not api_key:
        return _gate_report(
            BLOCKED_EXTERNAL,
            [GateResult("authentication", BLOCKED_EXTERNAL, "non-loopback Qdrant endpoint requires an API key")],
            endpoint=endpoint,
            auth_kind="qdrant_api_key",
        )

    try:
        source_root = ROOT / "packages/retrieval/src"
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
        from rick_retrieval.qdrant import (
            QdrantDependencyError,
            QdrantHttpVectorStore,
            QdrantStatusError,
        )
    except ImportError:
        return _gate_report(
            BLOCKED_EXTERNAL,
            [GateResult("driver", BLOCKED_EXTERNAL, "retrieval package is unavailable")],
            endpoint=endpoint,
            auth_configured=bool(api_key),
            auth_kind="qdrant_api_key",
        )

    collection_v1 = f"runtime_gate_{run_id}_v1"
    collection_v2 = f"runtime_gate_{run_id}_v2"
    alias = f"runtime_alias_{run_id}"
    logical_a = f"runtime-logical-a-{run_id}"
    logical_b = f"runtime-logical-b-{run_id}"
    tenant_a = f"runtime-tenant-{run_id}"
    tenant_b = f"runtime-tenant-other-{run_id}"
    workspace_a = f"runtime-workspace-{run_id}"
    workspace_b = f"runtime-workspace-other-{run_id}"
    document_a = f"runtime-document-a-{run_id}"
    document_b = f"runtime-document-b-{run_id}"
    document_c = f"runtime-document-c-{run_id}"
    point_a = str(uuid.uuid4())
    point_b = str(uuid.uuid4())
    point_c = str(uuid.uuid4())
    points = [
        {
            "point_id": point_a,
            "vector": [1.0, 0.0, 0.0],
            "payload": {
                "tenant_id": tenant_a,
                "workspace_id": workspace_a,
                "collection_id": logical_a,
                "document_id": document_a,
                "chunk_id": point_a,
                "runtime_gate": True,
            },
        },
        {
            "point_id": point_b,
            "vector": [0.0, 1.0, 0.0],
            "payload": {
                "tenant_id": tenant_a,
                "workspace_id": workspace_b,
                "collection_id": logical_b,
                "document_id": document_b,
                "chunk_id": point_b,
                "runtime_gate": True,
            },
        },
        {
            "point_id": point_c,
            "vector": [0.0, 0.0, 1.0],
            "payload": {
                "tenant_id": tenant_b,
                "workspace_id": workspace_a,
                "collection_id": logical_a,
                "document_id": document_c,
                "chunk_id": point_c,
                "runtime_gate": True,
            },
        },
    ]
    results: list[GateResult] = []
    blocked_external = False
    created_collections: list[str] = []
    alias_created = False
    store_v1 = None
    store_v2 = None
    alias_store = None
    missing_store = None
    transport_v1 = _QdrantTransport()
    transport_v2 = _QdrantTransport()
    transport_alias = _QdrantTransport()
    transport_missing = _QdrantTransport()
    control_transport = _QdrantTransport()

    def add(name: str, result: str, detail: str) -> None:
        nonlocal blocked_external
        results.append(GateResult(name, result, detail))
        blocked_external = blocked_external or result == BLOCKED_EXTERNAL

    def add_exception(name: str, error: BaseException, detail: str) -> None:
        add(name, BLOCKED_EXTERNAL if _qdrant_external_error(error) else FAIL, detail)

    def collection_preflight(store: object) -> bool:
        try:
            store.collection_info()
        except QdrantStatusError as error:
            return error.status_code == 404
        return False

    def create_and_validate(store: object, collection: str, transport: _QdrantTransport) -> bool:
        if not store.create_collection(vector_dimensions=3, distance="Cosine"):
            return False
        created_collections.append(collection)
        for field_name in ("tenant_id", "workspace_id", "collection_id"):
            if not store.create_payload_index(field_name=field_name, field_schema="keyword"):
                return False
        deadline = time.monotonic() + MAX_POLL_SECONDS
        while True:
            schema_ok, indexed_fields = _collection_schema(transport, endpoint, collection, api_key)
            if schema_ok and {"tenant_id", "workspace_id", "collection_id"}.issubset(indexed_fields):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL_INTERVAL_SECONDS)

    try:
        try:
            store_v1 = QdrantHttpVectorStore(
                base_url=endpoint.raw,
                collection=collection_v1,
                api_key=api_key or None,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                transport=transport_v1,
                max_points=MAX_QDRANT_POINTS,
                max_query_results=MAX_QDRANT_RESULTS,
                max_payload_bytes=MAX_FIXTURE_BYTES,
                max_response_bytes=MAX_RESPONSE_BYTES,
                max_attempts=2,
                retry_backoff_seconds=0.05,
                circuit_failure_threshold=3,
                circuit_reset_seconds=5.0,
            )
        except QdrantDependencyError:
            add("driver", BLOCKED_EXTERNAL, "Qdrant HTTP dependency is unavailable")
        except Exception:
            add("configuration", FAIL, "Qdrant client configuration was rejected")

        health_ok = False
        if store_v1 is not None:
            try:
                health_ok = bool(store_v1.health().ok)
                add("health", PASS if health_ok else FAIL, "Qdrant health endpoint responded" if health_ok else "Qdrant health endpoint was not healthy")
            except Exception as error:
                add_exception("health", error, "Qdrant service could not be reached")

        if health_ok and store_v1 is not None:
            preflight_ok = False
            try:
                preflight_ok = collection_preflight(store_v1)
            except Exception as error:
                add_exception("collection-preflight", error, "collection preflight failed")
            add(
                "collection-preflight",
                PASS if preflight_ok else FAIL,
                "unique collection was absent before create" if preflight_ok else "unique collection preflight was not a 404",
            )

            collection_ok = False
            if preflight_ok:
                try:
                    collection_ok = create_and_validate(store_v1, collection_v1, transport_v1)
                except Exception as error:
                    add_exception("collection-schema-index", error, "collection creation/schema/index verification failed")
            add(
                "collection-schema-index",
                PASS if collection_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL),
                "named dense schema and tenant/workspace/collection keyword indexes were observed"
                if collection_ok
                else "collection schema or payload indexes were not verified",
            )

            upsert_ok = False
            if collection_ok:
                try:
                    upsert_ok = store_v1.upsert_points(points) == len(points)
                except Exception as error:
                    add_exception("upsert", error, "live Qdrant upsert failed")
            add("upsert", PASS if upsert_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "three scoped points were acknowledged" if upsert_ok else "bounded point upsert was not acknowledged")

            info_ok = False
            if upsert_ok:
                try:
                    info = store_v1.collection_info()
                    info_ok = info.points_count is not None and info.points_count >= len(points)
                except Exception as error:
                    add_exception("collection-state", error, "collection point count could not be verified")
            add("collection-state", PASS if info_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "collection point count reached the reindex fixture size" if info_ok else "collection state was not verified")

            filter_ok = False
            tenant_filter_ok = False
            workspace_filter_ok = False
            collection_filter_ok = False
            if upsert_ok:
                try:
                    hits_a = _query_scoped(store_v1, [1.0, 0.0, 0.0], tenant=tenant_a, workspace=workspace_a, collection_id=logical_a)
                    hits_b = _query_scoped(store_v1, [0.0, 1.0, 0.0], tenant=tenant_a, workspace=workspace_b, collection_id=logical_b)
                    hits_c = _query_scoped(store_v1, [0.0, 0.0, 1.0], tenant=tenant_b, workspace=workspace_a, collection_id=logical_a)
                    tenant_filter_ok = any(hit.point_id == point_a for hit in hits_a) and any(hit.point_id == point_c for hit in hits_c)
                    workspace_filter_ok = any(hit.point_id == point_b for hit in hits_b)
                    collection_filter_ok = not _query_scoped(
                        store_v1,
                        [1.0, 0.0, 0.0],
                        tenant=tenant_a,
                        workspace=workspace_a,
                        collection_id=logical_b,
                    )
                    filter_ok = (
                        tenant_filter_ok
                        and workspace_filter_ok
                        and collection_filter_ok
                        and _filter_observation_matches(transport_v1, tenant_a, workspace_a, logical_b)
                    )
                except Exception as error:
                    add_exception("tenant-workspace-filter", error, "scoped Qdrant query failed")
            add("tenant-workspace-filter", PASS if filter_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "tenant, workspace, and collection filters were sent and enforced" if filter_ok else "Qdrant filter isolation was not proven")

            negative_filter_ok = False
            if upsert_ok and not blocked_external:
                try:
                    wrong_tenant = _query_scoped(store_v1, [0.0, 0.0, 1.0], tenant=tenant_a, workspace=workspace_a, collection_id=logical_a)
                    wrong_workspace = _query_scoped(store_v1, [0.0, 1.0, 0.0], tenant=tenant_a, workspace=workspace_a, collection_id=logical_b)
                    negative_filter_ok = not wrong_tenant and not wrong_workspace
                except Exception as error:
                    add_exception("cross-scope-negative", error, "negative scoped query failed")
            add("cross-scope-negative", PASS if negative_filter_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "cross-tenant and cross-workspace queries returned no foreign points" if negative_filter_ok else "foreign point visibility was not rejected")

            delete_ok = False
            delete_idempotent_ok = False
            point_restore_negative_ok = False
            if upsert_ok and not blocked_external:
                try:
                    delete_ack = store_v1.delete_by_filter(
                        tenant_id=tenant_a,
                        workspace_id=workspace_a,
                        allowed_collection_ids=[logical_a],
                        document_id=document_a,
                    )
                    delete_ok = bool(delete_ack.acknowledged)
                    remaining = store_v1.count_for_document(
                        document_a,
                        logical_a,
                        tenant_id=tenant_a,
                        workspace_id=workspace_a,
                    )
                    delete_ok = delete_ok and remaining == 0
                    repeated = store_v1.delete_by_filter(
                        tenant_id=tenant_a,
                        workspace_id=workspace_a,
                        allowed_collection_ids=[logical_a],
                        document_id=document_a,
                    )
                    delete_idempotent_ok = bool(repeated.acknowledged)
                    point_restore_negative_ok = not _query_scoped(
                        store_v1,
                        [1.0, 0.0, 0.0],
                        tenant=tenant_a,
                        workspace=workspace_a,
                        collection_id=logical_a,
                    )
                except Exception as error:
                    add_exception("delete", error, "scoped Qdrant delete/count failed")
            add("delete", PASS if delete_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "scoped point deletion reached count zero" if delete_ok else "scoped Qdrant delete was not verified")
            add("delete-idempotent", PASS if delete_idempotent_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "repeated scoped point deletion remained acknowledged and bounded" if delete_idempotent_ok else "repeated Qdrant delete was not verified")
            add("restore-negative", PASS if point_restore_negative_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "deleted projection point stayed absent; no restore authority was claimed" if point_restore_negative_ok else "deleted point absence was not verified")

            try:
                alias_store = QdrantHttpVectorStore(
                    base_url=endpoint.raw,
                    collection=alias,
                    api_key=api_key or None,
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                    transport=transport_alias,
                    max_points=MAX_QDRANT_POINTS,
                    max_query_results=MAX_QDRANT_RESULTS,
                    max_payload_bytes=MAX_FIXTURE_BYTES,
                    max_response_bytes=MAX_RESPONSE_BYTES,
                    max_attempts=2,
                    retry_backoff_seconds=0.05,
                )
                aliases_before = {item.alias_name for item in alias_store.list_aliases()}
                alias_absent = alias not in aliases_before
            except Exception as error:
                alias_absent = False
                add_exception("alias-preflight", error, "Qdrant alias preflight failed")
            add("alias-preflight", PASS if alias_absent else (BLOCKED_EXTERNAL if blocked_external else FAIL), "unique alias was absent before creation" if alias_absent else "unique alias preflight was not clean")

            alias_create_ok = False
            if alias_absent and alias_store is not None:
                try:
                    alias_create_ok = bool(store_v1.replace_alias(alias_name=alias, collection_name=collection_v1))
                    alias_created = alias_create_ok
                    aliases_after = {item.alias_name: item.collection_name for item in alias_store.list_aliases()}
                    alias_create_ok = alias_create_ok and aliases_after.get(alias) == collection_v1
                except Exception as error:
                    add_exception("alias-create", error, "live Qdrant alias creation failed")
            add("alias-create", PASS if alias_create_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "alias pointed to the first projection" if alias_create_ok else "alias creation/snapshot was not verified")

            if alias_create_ok:
                try:
                    alias_hits = _query_scoped(
                        alias_store,
                        [0.0, 1.0, 0.0],
                        tenant=tenant_a,
                        workspace=workspace_b,
                        collection_id=logical_b,
                    )
                    alias_query_ok = any(hit.point_id == point_b for hit in alias_hits)
                except Exception as error:
                    alias_query_ok = False
                    add_exception("alias-read", error, "alias-scoped retrieval failed")
            else:
                alias_query_ok = False
            add("alias-read", PASS if alias_query_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "alias resolved the first projection with its ACL filter" if alias_query_ok else "alias read was not verified")

            try:
                store_v2 = QdrantHttpVectorStore(
                    base_url=endpoint.raw,
                    collection=collection_v2,
                    api_key=api_key or None,
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                    transport=transport_v2,
                    max_points=MAX_QDRANT_POINTS,
                    max_query_results=MAX_QDRANT_RESULTS,
                    max_payload_bytes=MAX_FIXTURE_BYTES,
                    max_response_bytes=MAX_RESPONSE_BYTES,
                    max_attempts=2,
                    retry_backoff_seconds=0.05,
                )
            except Exception as error:
                add_exception("rebuild-configuration", error, "second Qdrant projection configuration failed")

            rebuild_ok = False
            if store_v2 is not None:
                try:
                    v2_preflight = collection_preflight(store_v2)
                    v2_ready = v2_preflight and create_and_validate(store_v2, collection_v2, transport_v2)
                    reindexed = v2_ready and store_v2.upsert_points(points) == len(points)
                    v2_hits = _query_scoped(store_v2, [1.0, 0.0, 0.0], tenant=tenant_a, workspace=workspace_a, collection_id=logical_a) if reindexed else []
                    rebuild_ok = reindexed and any(hit.point_id == point_a for hit in v2_hits)
                except Exception as error:
                    add_exception("rebuild-reindex", error, "fresh Qdrant projection rebuild/reindex failed")
            add("rebuild-reindex", PASS if rebuild_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "fresh collection was indexed and rebuilt from the fixture" if rebuild_ok else "fresh collection rebuild/reindex was not verified")

            swap_ok = False
            if alias_create_ok and rebuild_ok and store_v2 is not None and alias_store is not None:
                try:
                    swap_ok = bool(store_v2.replace_alias(alias_name=alias, collection_name=collection_v2, old_collection_name=collection_v1))
                    aliases_swapped = {item.alias_name: item.collection_name for item in alias_store.list_aliases()}
                    swap_ok = swap_ok and aliases_swapped.get(alias) == collection_v2
                    swapped_hits = _query_scoped(alias_store, [1.0, 0.0, 0.0], tenant=tenant_a, workspace=workspace_a, collection_id=logical_a)
                    swap_ok = swap_ok and any(hit.point_id == point_a for hit in swapped_hits)
                except Exception as error:
                    add_exception("alias-swap", error, "atomic Qdrant alias swap failed")
            add("alias-swap", PASS if swap_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "alias atomically moved to the rebuilt projection" if swap_ok else "alias swap/observation was not verified")

            partial_failure_ok = False
            if rebuild_ok and store_v2 is not None:
                try:
                    missing_store = QdrantHttpVectorStore(
                        base_url=endpoint.raw,
                        collection=f"runtime_missing_{run_id}",
                        api_key=api_key or None,
                        timeout=DEFAULT_TIMEOUT_SECONDS,
                        transport=transport_missing,
                        max_points=1,
                        max_query_results=1,
                        max_payload_bytes=MAX_FIXTURE_BYTES,
                        max_response_bytes=MAX_RESPONSE_BYTES,
                        max_attempts=2,
                        retry_backoff_seconds=0.05,
                    )
                    try:
                        missing_store.collection_info()
                    except QdrantStatusError as error:
                        missing_expected = error.status_code == 404
                    else:
                        missing_expected = False
                    still_live = bool(_query_scoped(store_v2, [1.0, 0.0, 0.0], tenant=tenant_a, workspace=workspace_a, collection_id=logical_a))
                    partial_failure_ok = missing_expected and still_live
                except Exception as error:
                    add_exception("partial-failure", error, "partial Qdrant failure recovery probe failed")
            add("partial-failure", PASS if partial_failure_ok else (BLOCKED_EXTERNAL if blocked_external else FAIL), "a real missing-collection failure did not corrupt the rebuilt projection" if partial_failure_ok else "partial failure was not safely isolated")

            if not blocked_external:
                failure_results, failure_blocked = _run_qdrant_failure_policy(args, endpoint, api_key, run_id)
                results.extend(failure_results)
                blocked_external = blocked_external or failure_blocked
    finally:
        cleanup_ok = True
        cleanup_blocked = False
        if alias_created:
            try:
                alias_status = _delete_qdrant_alias(control_transport, endpoint, alias, api_key)
                if alias_status not in {"deleted", "absent"}:
                    cleanup_ok = False
                if alias_store is not None:
                    aliases_after_cleanup = {item.alias_name for item in alias_store.list_aliases()}
                    cleanup_ok = cleanup_ok and alias not in aliases_after_cleanup
            except Exception as error:
                cleanup_ok = False
                cleanup_blocked = cleanup_blocked or _qdrant_external_error(error)
        for collection in reversed(created_collections):
            try:
                first_status = _delete_qdrant_collection(endpoint, collection, api_key)
                second_status = _delete_qdrant_collection(endpoint, collection, api_key)
                exists_response = _qdrant_json_request(
                    control_transport,
                    endpoint,
                    f"/collections/{quote(collection, safe='')}",
                    api_key,
                )
                absent_after_cleanup = exists_response.status_code == 404
                cleanup_ok = cleanup_ok and first_status in {"deleted", "absent"} and second_status == "absent" and absent_after_cleanup
            except Exception as error:
                cleanup_ok = False
                cleanup_blocked = cleanup_blocked or _qdrant_external_error(error)
        if created_collections:
            results.append(
                GateResult(
                    "collection-cleanup-idempotent",
                    BLOCKED_EXTERNAL if cleanup_blocked else (PASS if cleanup_ok else FAIL),
                    "created collections and alias were deleted, re-delete was absent, and GET returned 404"
                    if cleanup_ok
                    else "Qdrant collection cleanup/idempotence/absence was not verified",
                )
            )
        for store in (missing_store, alias_store, store_v2, store_v1):
            if store is not None:
                try:
                    store.close()
                except Exception:
                    results.append(GateResult("close", FAIL, "Qdrant transport close failed"))
        for transport in (transport_missing, transport_alias, transport_v2, transport_v1, control_transport):
            transport.close()

    status = BLOCKED_EXTERNAL if blocked_external else (PASS if results and all(item.result == PASS for item in results) else FAIL)
    production_safe = bool(status == PASS and getattr(args, "require_tls", False) and endpoint.tls and api_key)
    return _gate_report(
        status,
        results,
        endpoint=endpoint,
        auth_configured=bool(api_key),
        auth_kind="qdrant_api_key",
        production_safe=production_safe,
        observations={
            "physical_collections": 2,
            "fixture_points": len(points),
            "filter_requests_observed": sum(
                len(transport.filter_observations)
                for transport in (transport_v1, transport_v2, transport_alias)
            ),
            "restore_claim": False,
            "fault_endpoints_configured": bool(_arg_text(args, "qdrant_fault_url") and _arg_text(args, "qdrant_timeout_url")),
        },
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qdrant-url",
        default=_env_first("RICK_TEST_QDRANT_URL", "RICK_QDRANT_URL", "QDRANT_URL"),
    )
    parser.add_argument(
        "--qdrant-api-key",
        default=_env_first("RICK_TEST_QDRANT_API_KEY", "RICK_QDRANT_API_KEY", "QDRANT_API_KEY"),
    )
    parser.add_argument(
        "--qdrant-fault-url",
        default=_env_first("RICK_TEST_QDRANT_FAULT_URL", "RICK_QDRANT_FAULT_URL"),
        help="real disposable endpoint that returns a retryable failure for retry/circuit verification",
    )
    parser.add_argument(
        "--qdrant-timeout-url",
        default=_env_first("RICK_TEST_QDRANT_TIMEOUT_URL", "RICK_QDRANT_TIMEOUT_URL"),
        help="real disposable endpoint that intentionally exceeds the bounded timeout",
    )
    parser.add_argument(
        "--object-endpoint",
        default=_env_first(
            "RICK_TEST_OBJECT_STORE_ENDPOINT",
            "RICK_OBJECT_STORE_ENDPOINT",
            "OBJECT_STORAGE_ENDPOINT",
            "S3_ENDPOINT_URL",
        ),
    )
    parser.add_argument(
        "--object-bucket",
        default=_env_first(
            "RICK_TEST_OBJECT_STORE_BUCKET",
            "RICK_OBJECT_STORE_BUCKET",
            "OBJECT_STORAGE_BUCKET",
            "S3_BUCKET",
        ),
    )
    parser.add_argument(
        "--object-region",
        default=_env_first(
            "RICK_TEST_OBJECT_STORE_REGION",
            "RICK_OBJECT_STORE_REGION",
            "OBJECT_STORAGE_REGION",
            "AWS_REGION",
        ),
    )
    parser.add_argument(
        "--object-access-key",
        default=_env_first(
            "RICK_TEST_OBJECT_STORE_ACCESS_KEY_ID",
            "RICK_OBJECT_STORE_ACCESS_KEY_ID",
            "OBJECT_STORAGE_ACCESS_KEY_ID",
            "AWS_ACCESS_KEY_ID",
        ),
    )
    parser.add_argument(
        "--object-secret-key",
        default=_env_first(
            "RICK_TEST_OBJECT_STORE_SECRET_ACCESS_KEY",
            "RICK_OBJECT_STORE_SECRET_ACCESS_KEY",
            "OBJECT_STORAGE_SECRET_ACCESS_KEY",
            "AWS_SECRET_ACCESS_KEY",
        ),
    )
    parser.add_argument(
        "--object-session-token",
        default=_env_first(
            "RICK_TEST_OBJECT_STORE_SESSION_TOKEN",
            "RICK_OBJECT_STORE_SESSION_TOKEN",
            "AWS_SESSION_TOKEN",
        ),
    )
    parser.add_argument(
        "--allow-nonlocal",
        action="store_true",
        help="explicitly permit non-loopback endpoints for this runtime probe",
    )
    parser.add_argument(
        "--require-tls",
        action="store_true",
        help="require HTTPS for all endpoints and allow a production-safety capability claim",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def _overall_status(object_gate: dict[str, object], vector_gate: dict[str, object]) -> str:
    statuses = (object_gate["status"], vector_gate["status"])
    if BLOCKED_EXTERNAL in statuses:
        return BLOCKED_EXTERNAL
    if all(status == PASS for status in statuses):
        return PASS
    return FAIL


def _write_report(path_value: str, report: dict[str, object]) -> Path:
    root = ROOT.resolve()
    path = (ROOT / path_value).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise _InvalidConfiguration() from None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    run_id = uuid.uuid4().hex[:16]

    try:
        object_gate = _run_object_gate(args, run_id)
    except Exception:
        object_gate = _gate_report(
            FAIL,
            [GateResult("runtime", FAIL, "object-store gate encountered an internal failure")],
            auth_kind="aws_sigv4",
        )
    try:
        vector_gate = _run_vector_gate(args, run_id)
    except Exception:
        vector_gate = _gate_report(
            FAIL,
            [GateResult("runtime", FAIL, "Qdrant gate encountered an internal failure")],
            auth_kind="qdrant_api_key",
        )

    status = _overall_status(object_gate, vector_gate)
    production_safe = bool(
        status == PASS
        and bool(getattr(args, "require_tls", False))
        and object_gate.get("production_safe") is True
        and vector_gate.get("production_safe") is True
    )
    report = {
        "schema_version": "phase-3.5-object-qdrant-runtime-gate.v2",
        "status": status,
        "object_gate": object_gate,
        "vector_gate": vector_gate,
        "runtime_claim": status == PASS,
        "production_safe": production_safe,
        "promotable": production_safe,
        "promotion_claim": "EXPLICIT_TLS_AUTH_CONFIGURATION" if production_safe else "NONE",
        "configuration": {
            "allow_nonlocal": bool(getattr(args, "allow_nonlocal", False)),
            "require_tls": bool(getattr(args, "require_tls", False)),
            "fault_policy_endpoints_configured": bool(
                _arg_text(args, "qdrant_fault_url") and _arg_text(args, "qdrant_timeout_url")
            ),
            "run_id": run_id,
        },
        "redaction": {
            "raw_urls": "omitted",
            "access_keys": "omitted",
            "api_keys": "omitted",
            "secret_values": "omitted",
            "backend_exception_text": "omitted",
            "fixture_identifiers": "omitted",
        },
    }

    try:
        output = _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": FAIL, "report": "write_failed"}, sort_keys=True))
        return 1

    print(
        json.dumps(
            {
                "output": str(output.relative_to(ROOT)),
                "status": status,
                "object_status": object_gate["status"],
                "vector_status": vector_gate["status"],
                "production_safe": production_safe,
            },
            sort_keys=True,
        )
    )
    if status == PASS:
        return 0
    if status == BLOCKED_EXTERNAL:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
