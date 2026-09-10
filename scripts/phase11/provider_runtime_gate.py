#!/usr/bin/env python3
"""Run a bounded live OpenAI-compatible health/chat/stream/tool/embedding gate.

The gate requires an explicitly configured provider URL and uses the canonical
HTTP client.  It never installs a fake transport, never falls back to the
deterministic provider, and only exposes safe endpoint metadata and assertion
names in its artifact.  Missing runtime authority is ``BLOCKED_EXTERNAL``;
malformed configuration or a live assertion failure is ``FAIL``.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import sys
from urllib.parse import SplitResult, urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-3/provider-runtime-gate.json"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1_536

PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"


class _BlockedExternal(Exception):
    """The requested live provider authority is not available."""


class _InvalidConfiguration(Exception):
    """The supplied provider configuration violates the gate contract."""


@dataclass(frozen=True)
class _Endpoint:
    parsed: SplitResult
    loopback: bool

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
            "host_scope": "loopback" if self.loopback else "nonloopback",
            "port_configured": port is not None,
            "path_configured": bool(self.parsed.path),
        }


@dataclass(frozen=True)
class _Assertion:
    name: str
    result: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        payload = {"name": self.name, "result": self.result}
        if self.detail:
            payload["detail"] = self.detail
        return payload


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _parse_endpoint(value: str, *, allow_nonlocal: bool, require_tls: bool) -> _Endpoint:
    if not isinstance(value, str) or not value.strip():
        raise _BlockedExternal()
    try:
        parsed = urlsplit(value.strip().rstrip("/"))
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
    return _Endpoint(parsed=parsed, loopback=loopback)


def _safe_output(raw: str) -> Path:
    output = (ROOT / raw).resolve()
    try:
        output.relative_to(ROOT.resolve())
    except ValueError:
        raise _InvalidConfiguration() from None
    return output


async def _run_checks(
    provider_url: str,
    *,
    api_key: str | None,
    chat_model: str,
    embedding_model: str,
    embedding_dimensions: int,
    require_tls: bool,
    require_auth: bool,
    allow_nonlocal: bool,
) -> tuple[str, list[_Assertion], bool, dict[str, object]]:
    endpoint = _parse_endpoint(
        provider_url,
        allow_nonlocal=allow_nonlocal,
        require_tls=require_tls,
    )
    if require_auth and not api_key:
        raise _BlockedExternal()
    if not isinstance(chat_model, str) or not chat_model.strip() or len(chat_model.strip()) > 256:
        raise _InvalidConfiguration()
    if not isinstance(embedding_model, str) or not embedding_model.strip() or len(embedding_model.strip()) > 256:
        raise _InvalidConfiguration()
    if type(embedding_dimensions) is not int or not 1 <= embedding_dimensions <= 16_384:
        raise _InvalidConfiguration()

    try:
        from rick_providers.client import OpenAICompatibleClient
        from rick_providers.config import ProviderConfig
        from rick_contracts.providers import ProviderMessage
    except ImportError:
        raise _BlockedExternal() from None

    environment = "production" if require_tls else "local"
    try:
        config = ProviderConfig(
            base_url=provider_url,
            api_key=api_key,
            chat_model=chat_model.strip(),
            embedding_model=embedding_model.strip(),
            embedding_dimensions=embedding_dimensions,
            timeout=5.0,
            max_attempts=1,
            retry_base_delay=0.0,
            max_backoff_delay=0.0,
            environment=environment,
            provider_kind="openai_compatible",
        )
        config.validate()
    except Exception:
        raise _InvalidConfiguration() from None

    client = OpenAICompatibleClient(config)
    assertions: list[_Assertion] = []
    provider_health_ok = False
    chat_ok = False
    embedding_ok = False
    streaming_ok = False
    json_ok = False
    tools_ok = False
    try:
        try:
            provider_health_ok = await client.health_check()
            assertions.append(
                _Assertion(
                    "provider-health-probe",
                    PASS if provider_health_ok else FAIL,
                    "authenticated models probe returned a valid response"
                    if provider_health_ok
                    else "provider health probe did not satisfy the contract",
                )
            )
        except Exception:
            assertions.append(_Assertion("provider-health-probe", FAIL, "live provider health probe failed"))

        try:
            chat = await client.chat_completion(
                messages=[
                    ProviderMessage(
                        role="user",
                        content="Reply with a short health acknowledgement.",
                    )
                ],
                temperature=0,
                correlation_id=f"phase11-provider-chat-{uuid.uuid4().hex[:12]}",
            )
            chat_ok = bool(chat.model == config.chat_model and chat.content.strip())
            assertions.append(
                _Assertion(
                    "chat-completion-contract",
                    PASS if chat_ok else FAIL,
                    "typed chat completion returned"
                    if chat_ok
                    else "typed chat completion did not satisfy the contract",
                )
            )
        except Exception:
            assertions.append(_Assertion("chat-completion-contract", FAIL, "live chat assertion failed"))

        try:
            structured = await client.chat_completion(
                messages=[
                    ProviderMessage(
                        role="user",
                        content="Return a JSON object with status=ok.",
                    )
                ],
                temperature=0,
                response_format={"type": "json_object"},
                correlation_id=f"phase11-provider-json-{uuid.uuid4().hex[:12]}",
            )
            decoded = json.loads(structured.content)
            json_ok = bool(structured.model == config.chat_model and isinstance(decoded, dict))
            assertions.append(
                _Assertion(
                    "json-response-contract",
                    PASS if json_ok else FAIL,
                    "typed JSON response parsed as an object"
                    if json_ok
                    else "typed JSON response did not satisfy the object contract",
                )
            )
        except Exception:
            assertions.append(_Assertion("json-response-contract", FAIL, "live JSON assertion failed"))

        try:
            tool_result = await client.chat_completion(
                messages=[
                    ProviderMessage(
                        role="user",
                        content="Use the report_status function with status=ok.",
                    )
                ],
                temperature=0,
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "report_status",
                            "description": "Report the provider health status.",
                            "parameters": {
                                "type": "object",
                                "properties": {"status": {"type": "string"}},
                                "required": ["status"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
                correlation_id=f"phase11-provider-tool-{uuid.uuid4().hex[:12]}",
            )
            tool_call = (tool_result.tool_calls or [None])[0]
            decoded_arguments = json.loads(tool_call.function.arguments) if tool_call is not None else None
            tools_ok = bool(
                tool_result.model == config.chat_model
                and tool_call is not None
                and tool_call.function.name == "report_status"
                and isinstance(decoded_arguments, dict)
            )
            assertions.append(
                _Assertion(
                    "tool-call-contract",
                    PASS if tools_ok else FAIL,
                    "typed function tool call returned with JSON arguments"
                    if tools_ok
                    else "typed function tool call did not satisfy the contract",
                )
            )
        except Exception:
            assertions.append(_Assertion("tool-call-contract", FAIL, "live tool assertion failed"))

        try:
            deltas: list[str] = []
            finish_reason: str | None = None
            stream = client.chat_completion_stream(
                messages=[
                    ProviderMessage(
                        role="user",
                        content="Reply with a short streaming health acknowledgement.",
                    )
                ],
                temperature=0,
                correlation_id=f"phase11-provider-stream-{uuid.uuid4().hex[:12]}",
            )
            async for chunk in stream:
                if chunk.delta:
                    deltas.append(chunk.delta)
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
            streaming_ok = bool("".join(deltas).strip() and finish_reason in {"stop", "length", "content_filter", "unknown"})
            assertions.append(
                _Assertion(
                    "streaming-contract",
                    PASS if streaming_ok else FAIL,
                    "typed stream emitted deltas and a terminal finish reason"
                    if streaming_ok
                    else "typed stream did not satisfy the terminal contract",
                )
            )
        except Exception:
            assertions.append(_Assertion("streaming-contract", FAIL, "live streaming assertion failed"))

        try:
            embedding = await client.get_embedding(
                "provider runtime health probe",
                correlation_id=f"phase11-provider-embedding-{uuid.uuid4().hex[:12]}",
            )
            embedding_ok = bool(
                embedding.model == config.embedding_model
                and embedding.dimensions == config.embedding_dimensions
                and len(embedding.vector) == config.embedding_dimensions
            )
            assertions.append(
                _Assertion(
                    "embedding-contract",
                    PASS if embedding_ok else FAIL,
                    "typed embedding returned with the configured dimension"
                    if embedding_ok
                    else "typed embedding did not satisfy the configured dimension",
                )
            )
        except Exception:
            assertions.append(_Assertion("embedding-contract", FAIL, "live embedding assertion failed"))

        assertions.append(
            _Assertion(
                "provider-configuration",
                PASS,
                "canonical OpenAI-compatible client is configured",
            )
        )
        status = PASS if provider_health_ok and chat_ok and json_ok and tools_ok and streaming_ok and embedding_ok else FAIL
        production_safe = bool(
            status == PASS
            and config.is_production
            and endpoint.tls
            and bool(api_key)
        )
        assertions.append(
            _Assertion(
                "production-capability",
                PASS if production_safe else "PARTIAL",
                "TLS, authenticated production provider is live"
                if production_safe
                else "live provider semantics passed without production-safe TLS/auth capability",
            )
        )
        return status, assertions, production_safe, endpoint.report()
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-url", default=os.environ.get("RICK_TEST_PROVIDER_URL", ""))
    parser.add_argument(
        "--api-key",
        default=os.environ.get("RICK_TEST_PROVIDER_API_KEY"),
        help="provider credential; it is never written to the artifact",
    )
    parser.add_argument(
        "--chat-model",
        default=os.environ.get("RICK_TEST_PROVIDER_CHAT_MODEL", DEFAULT_CHAT_MODEL),
    )
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("RICK_TEST_PROVIDER_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    )
    parser.add_argument(
        "--embedding-dimensions",
        type=int,
        default=int(os.environ.get("RICK_TEST_PROVIDER_EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS)),
    )
    parser.add_argument("--require-tls", action="store_true")
    parser.add_argument("--require-auth", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        output = _safe_output(args.output)
        if not args.provider_url.strip():
            raise _BlockedExternal()
        status, assertions, production_safe, endpoint = asyncio.run(
            _run_checks(
                args.provider_url,
                api_key=args.api_key,
                chat_model=args.chat_model,
                embedding_model=args.embedding_model,
                embedding_dimensions=args.embedding_dimensions,
                require_tls=args.require_tls,
                require_auth=args.require_auth,
                allow_nonlocal=args.allow_nonlocal,
            )
        )
    except _BlockedExternal:
        status = BLOCKED_EXTERNAL
        assertions = [_Assertion("provider", BLOCKED_EXTERNAL, "explicit provider runtime authority is required")]
        production_safe = False
        endpoint = {}
        output = _safe_output(args.output)
    except _InvalidConfiguration:
        status = FAIL
        assertions = [_Assertion("configuration", FAIL, "provider runtime configuration was rejected")]
        production_safe = False
        endpoint = {}
        output = _safe_output(args.output)
    payload = {
        "schema_version": "phase-3-provider-runtime-gate.v1",
        "status": status,
        "assertions": [item.to_dict() for item in assertions],
        "runtime_claim": status == PASS,
        "production_safe": production_safe,
        "endpoint": endpoint,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "status": status, "production_safe": production_safe}, sort_keys=True))
    return 0 if status == PASS else 2 if status == BLOCKED_EXTERNAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
