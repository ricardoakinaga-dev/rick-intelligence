#!/usr/bin/env python3
"""Run bounded live gates for S3-compatible object storage and Qdrant.

The gate is deliberately fail-closed.  It requires explicit object-store
configuration and an explicit Qdrant URL, accepts only loopback endpoints by
default, uses per-run fixtures, and never emits credentials, API keys, raw
URLs, or backend exception text.  A runtime PASS proves only the operations
performed by this script; it is not a production or promotion approval.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-2/object-qdrant-runtime-gate.json"
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_FIXTURE_BYTES = 4 * 1024
MAX_RESPONSE_BYTES = 64 * 1024

PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"


class _BlockedExternal(Exception):
    """Configuration or dependency is not safe/available to attempt."""


class _InvalidConfiguration(Exception):
    """Configuration is present but violates the gate's bounded contract."""


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
        self.headers = {str(name): str(value) for name, value in items()}
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
        request = Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            response = self._opener.open(request, timeout=self._timeout)
        except HTTPError as error:
            # HTTPError is also a response and lets the adapter classify 401,
            # 403, 404, and other remote statuses without exposing its body.
            return _UrllibResponse(error)
        except (OSError, TimeoutError, URLError) as error:
            raise RuntimeError("HTTP transport failed") from error
        return _UrllibResponse(response)

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class _QdrantResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]


class _QdrantTransport:
    """Real Qdrant transport with a bounded response body."""

    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirect())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout: float,
    ) -> _QdrantResponse:
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
            body = reader(MAX_RESPONSE_BYTES + 1)
            if not isinstance(body, bytes):
                raise RuntimeError("invalid Qdrant HTTP response body")
            return _QdrantResponse(
                status,
                body,
                {str(name): str(value) for name, value in items()},
            )
        except (OSError, TimeoutError, URLError, RuntimeError) as error:
            raise RuntimeError("Qdrant HTTP transport failed") from error
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def close(self) -> None:
        return None


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
    if not value.strip():
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
    return Endpoint(normalized, parsed, loopback)


def _redacted_auth(*, configured: bool, kind: str) -> dict[str, object]:
    return {
        "kind": kind,
        "configured": configured,
        "secret_values": "omitted",
    }


def _gate_report(
    status: str,
    results: list[GateResult],
    *,
    endpoint: Endpoint | None = None,
    auth_configured: bool = False,
    auth_kind: str = "none",
    production_safe: bool = False,
) -> dict[str, object]:
    return {
        "status": status,
        "live": status == PASS,
        "endpoint": endpoint.report() if endpoint is not None else None,
        "authentication": _redacted_auth(configured=auth_configured, kind=auth_kind),
        "results": [result.to_dict() for result in results],
        "production_safe": bool(production_safe),
        "promotable": bool(production_safe),
    }


def _missing_object_configuration(args: argparse.Namespace) -> bool:
    return not all(
        (
            args.object_endpoint.strip(),
            args.object_bucket.strip(),
            args.object_region.strip(),
            args.object_access_key.strip(),
            args.object_secret_key.strip(),
        )
    )


def _run_object_gate(args: argparse.Namespace, run_id: str) -> dict[str, object]:
    if _missing_object_configuration(args):
        return _gate_report(
            BLOCKED_EXTERNAL,
            [
                GateResult(
                    "configuration",
                    BLOCKED_EXTERNAL,
                    "object-store endpoint, bucket, region, and credentials are required",
                )
            ],
            auth_kind="aws_sigv4",
        )

    try:
        endpoint = _parse_endpoint(
            args.object_endpoint,
            allow_nonlocal=args.allow_nonlocal,
            require_tls=args.require_tls,
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
        from rick_storage import AwsCredentials, ObjectNotFoundError, ObjectScope, S3ObjectStore
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
    scope = ObjectScope(
        f"runtime-tenant-{run_id}",
        f"runtime-workspace-{run_id}",
        f"runtime-source-{run_id}",
    )
    key = f"runtime-fixture-{run_id}.bin"
    payload = f"rick-object-qdrant-runtime-gate:{run_id}".encode("ascii")
    results: list[GateResult] = []
    put_attempted = False
    put_ok = False
    delete_ok = False

    try:
        try:
            store = S3ObjectStore(
                endpoint.raw,
                args.object_bucket,
                args.object_region,
                AwsCredentials(
                    args.object_access_key,
                    args.object_secret_key,
                    args.object_session_token or None,
                ),
                transport,
                key_prefix="runtime-gate",
                max_object_bytes=MAX_FIXTURE_BYTES,
                max_read_bytes=MAX_FIXTURE_BYTES,
                max_response_bytes=MAX_RESPONSE_BYTES,
                max_list_items=4,
                require_https=args.require_tls,
            )
        except Exception:
            results.append(GateResult("configuration", FAIL, "object-store configuration was rejected"))
            return _gate_report(
                FAIL,
                results,
                endpoint=endpoint,
                auth_configured=True,
                auth_kind="aws_sigv4",
            )

        put_attempted = True
        try:
            metadata = store.put(scope, key, payload)
            put_ok = bool(metadata.size == len(payload) and metadata.sha256)
            results.append(
                GateResult(
                    "put",
                    PASS if put_ok else FAIL,
                    "bounded object written and checksum metadata returned" if put_ok else "object metadata did not match the fixture",
                )
            )
        except Exception:
            results.append(GateResult("put", FAIL, "live object PUT failed"))

        if put_ok:
            try:
                headed = store.head(scope, key)
                head_ok = headed.size == len(payload) and headed.sha256 == metadata.sha256
                results.append(
                    GateResult(
                        "head",
                        PASS if head_ok else FAIL,
                        "remote metadata matched the fixture" if head_ok else "remote metadata did not match the fixture",
                    )
                )
            except Exception:
                results.append(GateResult("head", FAIL, "live object HEAD failed"))

            try:
                fetched = store.get(scope, key, max_bytes=MAX_FIXTURE_BYTES)
                get_ok = fetched == payload
                results.append(
                    GateResult(
                        "get",
                        PASS if get_ok else FAIL,
                        "bounded object bytes matched the fixture" if get_ok else "downloaded bytes did not match the fixture",
                    )
                )
            except Exception:
                results.append(GateResult("get", FAIL, "live object GET failed"))

            try:
                delete_ok = bool(store.delete(scope, key))
                results.append(
                    GateResult(
                        "delete",
                        PASS if delete_ok else FAIL,
                        "fixture object deleted" if delete_ok else "fixture object was not reported as deleted",
                    )
                )
            except Exception:
                results.append(GateResult("delete", FAIL, "live object DELETE failed"))
    finally:
        if store is not None and put_attempted and not delete_ok:
            try:
                cleanup_deleted = bool(store.delete(scope, key))
                if cleanup_deleted:
                    delete_ok = True
                results.append(
                    GateResult(
                        "cleanup-delete",
                        PASS if cleanup_deleted or not put_ok else FAIL,
                        "fixture cleanup attempted" if cleanup_deleted or not put_ok else "fixture cleanup did not delete the object",
                    )
                )
            except Exception:
                results.append(GateResult("cleanup-delete", FAIL, "object fixture cleanup failed"))

        if store is not None and put_attempted:
            try:
                store.head(scope, key)
            except ObjectNotFoundError:
                results.append(GateResult("cleanup", PASS, "fixture object is absent after cleanup"))
            except Exception:
                results.append(GateResult("cleanup", FAIL, "object fixture absence could not be verified"))
            else:
                results.append(GateResult("cleanup", FAIL, "fixture object remained after cleanup"))

        if store is not None:
            try:
                store.close()
            except Exception:
                results.append(GateResult("close", FAIL, "object-store transport close failed"))

    status = PASS if results and all(item.result == PASS for item in results) else FAIL
    production_safe = bool(status == PASS and args.require_tls and endpoint.tls)
    return _gate_report(
        status,
        results,
        endpoint=endpoint,
        auth_configured=True,
        auth_kind="aws_sigv4",
        production_safe=production_safe,
    )


def _delete_qdrant_collection(
    endpoint: Endpoint,
    collection: str,
    api_key: str,
) -> str:
    """Delete only the UUID-derived collection created by this run."""

    url = f"{endpoint.raw}/collections/{quote(collection, safe='')}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["api-key"] = api_key
    request = Request(url, headers=headers, method="DELETE")
    opener = build_opener(_NoRedirect())
    response: object | None = None
    try:
        try:
            response = opener.open(request, timeout=DEFAULT_TIMEOUT_SECONDS)
        except HTTPError as error:
            response = error
        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "code", None)
        if status == 404:
            return "absent"
        if status not in {200, 202, 204}:
            raise RuntimeError("collection DELETE returned a non-success status")
        return "deleted"
    except (OSError, TimeoutError, URLError, RuntimeError) as error:
        raise RuntimeError("collection cleanup failed") from error
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _run_vector_gate(args: argparse.Namespace, run_id: str) -> dict[str, object]:
    if not args.qdrant_url.strip():
        return _gate_report(
            BLOCKED_EXTERNAL,
            [GateResult("configuration", BLOCKED_EXTERNAL, "Qdrant URL is required")],
            auth_kind="qdrant_api_key",
        )

    try:
        endpoint = _parse_endpoint(
            args.qdrant_url,
            allow_nonlocal=args.allow_nonlocal,
            require_tls=args.require_tls,
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

    api_key = args.qdrant_api_key.strip()
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

    collection = f"runtime_gate_{run_id}"
    tenant = f"runtime-tenant-{run_id}"
    workspace = f"runtime-workspace-{run_id}"
    document = f"runtime-document-{run_id}"
    point_id = f"runtime-point-{run_id}"
    point = {
        "point_id": point_id,
        "vector": [1.0, 0.0, 0.0],
        "payload": {
            "tenant_id": tenant,
            "workspace_id": workspace,
            "collection_id": collection,
            "document_id": document,
            "chunk_id": point_id,
            "runtime_gate": True,
        },
    }
    results: list[GateResult] = []
    vector_store = None
    collection_preexisting = False
    create_attempted = False
    collection_created = False

    try:
        try:
            vector_store = QdrantHttpVectorStore(
                base_url=endpoint.raw,
                collection=collection,
                api_key=api_key or None,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                transport=_QdrantTransport(),
                max_points=1,
                max_query_results=4,
                max_payload_bytes=MAX_FIXTURE_BYTES,
                max_response_bytes=MAX_RESPONSE_BYTES,
                max_attempts=2,
                retry_backoff_seconds=0.05,
            )
        except QdrantDependencyError:
            results.append(GateResult("driver", BLOCKED_EXTERNAL, "Qdrant HTTP dependency is unavailable"))
            return _gate_report(
                BLOCKED_EXTERNAL,
                results,
                endpoint=endpoint,
                auth_configured=bool(api_key),
                auth_kind="qdrant_api_key",
            )
        except Exception:
            results.append(GateResult("configuration", FAIL, "Qdrant client configuration was rejected"))
            return _gate_report(
                FAIL,
                results,
                endpoint=endpoint,
                auth_configured=bool(api_key),
                auth_kind="qdrant_api_key",
            )

        health_ok = False
        try:
            health = vector_store.health()
            health_ok = bool(health.ok)
            results.append(GateResult("health", PASS if health_ok else FAIL, "Qdrant health endpoint responded" if health_ok else "Qdrant health endpoint was not healthy"))
        except Exception:
            results.append(GateResult("health", FAIL, "live Qdrant health probe failed"))

        if health_ok:
            preflight_ok = False
            try:
                vector_store.collection_info()
            except QdrantStatusError as error:
                if error.status_code == 404:
                    preflight_ok = True
                    results.append(GateResult("collection-preflight", PASS, "unique collection name was absent before create"))
                else:
                    results.append(GateResult("collection-preflight", FAIL, "collection preflight returned an unexpected status"))
            except Exception:
                results.append(GateResult("collection-preflight", FAIL, "collection preflight failed"))
            else:
                collection_preexisting = True
                results.append(GateResult("collection-preflight", FAIL, "unique collection name already exists"))

            if preflight_ok:
                create_attempted = True
                try:
                    collection_created = bool(vector_store.create_collection(vector_dimensions=3, distance="Cosine"))
                    results.append(GateResult("collection-create", PASS if collection_created else FAIL, "unique collection created" if collection_created else "collection creation was not acknowledged"))
                except Exception:
                    results.append(GateResult("collection-create", FAIL, "live Qdrant collection create failed"))

            if collection_created:
                upsert_ok = False
                try:
                    upserted = vector_store.upsert_points([point])
                    upsert_ok = upserted == 1
                    results.append(GateResult("upsert", PASS if upsert_ok else FAIL, "one bounded point was acknowledged" if upsert_ok else "Qdrant acknowledged an unexpected point count"))
                except Exception:
                    results.append(GateResult("upsert", FAIL, "live Qdrant upsert failed"))

                if upsert_ok:
                    query_ok = False
                    try:
                        hits = vector_store.query(
                            point["vector"],
                            tenant_id=tenant,
                            workspace_id=workspace,
                            allowed_collection_ids=[collection],
                            limit=1,
                        )
                        query_ok = any(hit.point_id == point_id for hit in hits)
                        results.append(GateResult("query", PASS if query_ok else FAIL, "scoped query returned the fixture point" if query_ok else "scoped query did not return the fixture point"))
                    except QdrantStatusError as error:
                        if error.status_code in {404, 405}:
                            try:
                                hits = vector_store.search(
                                    point["vector"],
                                    tenant_id=tenant,
                                    workspace_id=workspace,
                                    allowed_collection_ids=[collection],
                                    limit=1,
                                )
                                query_ok = any(hit.point_id == point_id for hit in hits)
                                results.append(GateResult("query", PASS if query_ok else FAIL, "compatibility search returned the fixture point" if query_ok else "compatibility search did not return the fixture point"))
                            except Exception:
                                results.append(GateResult("query", FAIL, "Qdrant query and compatibility search failed"))
                        else:
                            results.append(GateResult("query", FAIL, "live Qdrant query returned an unexpected status"))
                    except Exception:
                        results.append(GateResult("query", FAIL, "live Qdrant query failed"))

                    try:
                        deleted = vector_store.delete_by_filter(
                            tenant_id=tenant,
                            workspace_id=workspace,
                            allowed_collection_ids=[collection],
                            document_id=document,
                        )
                        delete_ok = bool(deleted.acknowledged)
                        results.append(GateResult("delete", PASS if delete_ok else FAIL, "fixture point deletion was acknowledged" if delete_ok else "fixture point deletion was not acknowledged"))
                        if delete_ok:
                            try:
                                remaining = vector_store.count_for_document(
                                    document,
                                    collection,
                                    tenant_id=tenant,
                                    workspace_id=workspace,
                                )
                                results.append(GateResult("point-cleanup", PASS if remaining == 0 else FAIL, "fixture point count is zero" if remaining == 0 else "fixture point remained after delete"))
                            except Exception:
                                results.append(GateResult("point-cleanup", FAIL, "fixture point absence could not be verified"))
                    except Exception:
                        results.append(GateResult("delete", FAIL, "live Qdrant delete failed"))
    finally:
        if vector_store is not None and create_attempted and not collection_preexisting:
            try:
                cleanup_status = _delete_qdrant_collection(endpoint, collection, api_key)
                results.append(
                    GateResult(
                        "collection-cleanup",
                        PASS,
                        "unique collection deleted" if cleanup_status == "deleted" else "unique collection was already absent",
                    )
                )
            except Exception:
                results.append(GateResult("collection-cleanup", FAIL, "unique Qdrant collection cleanup failed"))
        if vector_store is not None:
            try:
                vector_store.close()
            except Exception:
                results.append(GateResult("close", FAIL, "Qdrant transport close failed"))

    status = PASS if results and all(item.result == PASS for item in results) else FAIL
    production_safe = bool(status == PASS and args.require_tls and endpoint.tls and api_key)
    return _gate_report(
        status,
        results,
        endpoint=endpoint,
        auth_configured=bool(api_key),
        auth_kind="qdrant_api_key",
        production_safe=production_safe,
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
        help="require HTTPS for both endpoints and allow a production-safety capability claim",
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
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
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
        and args.require_tls
        and object_gate.get("production_safe") is True
        and vector_gate.get("production_safe") is True
    )
    report = {
        "schema_version": "phase-2-object-qdrant-runtime-gate.v1",
        "status": status,
        "object_gate": object_gate,
        "vector_gate": vector_gate,
        "runtime_claim": status == PASS,
        "production_safe": production_safe,
        "promotable": production_safe,
        "promotion_claim": "EXPLICIT_TLS_AUTH_CONFIGURATION" if production_safe else "NONE",
        "configuration": {
            "allow_nonlocal": bool(args.allow_nonlocal),
            "require_tls": bool(args.require_tls),
            "run_id": run_id,
        },
        "redaction": {
            "raw_urls": "omitted",
            "access_keys": "omitted",
            "api_keys": "omitted",
            "secret_values": "omitted",
            "backend_exception_text": "omitted",
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
