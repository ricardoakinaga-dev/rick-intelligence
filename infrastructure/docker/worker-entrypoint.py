"""Fail-closed launcher for the externally composed ingestion worker.

The repository provides the canonical ``WorkerRuntime`` and adapters, but a
deployment still supplies a small, reviewed module whose factory returns the
runtime or an object exposing ``worker``. The factory owns all database,
Redis, object-store, vector, identity, and provider clients. This launcher
never reads or constructs those clients and never prints environment values.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import os
import re
import signal
import sys
import time
from typing import NoReturn


COMPOSITION_ENV = "RICK_WORKER_COMPOSITION"
_COMPOSITION = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
EXIT_CONFIGURATION = 78


def _fail(message: str) -> NoReturn:
    print(f"worker launcher unavailable: {message}", file=sys.stderr)
    raise SystemExit(EXIT_CONFIGURATION)


def _resolve_composition(specification: str) -> object:
    if not _COMPOSITION.fullmatch(specification):
        _fail(f"{COMPOSITION_ENV} must be module:factory")
    module_name, factory_name = specification.split(":", 1)
    try:
        module = importlib.import_module(module_name)
        factory = getattr(module, factory_name)
    except (ImportError, AttributeError):
        _fail("configured composition could not be imported")
    if not callable(factory):
        _fail("configured composition is not callable")
    try:
        value = factory()
        if inspect.isawaitable(value):
            value = asyncio.run(value)
    except Exception as exc:  # Do not expose provider/secret-bearing details.
        _fail(f"configured composition failed with {type(exc).__name__}")
    return value


def _worker_from_composition(value: object) -> object:
    worker = getattr(value, "worker", value)
    if not callable(getattr(worker, "run_forever", None)):
        _fail("composition did not return a worker with run_forever")
    return worker


def _health_value(value: object) -> bool:
    observed = getattr(value, "ok", value)
    return observed is True


def _call_startup(worker: object) -> None:
    startup = getattr(worker, "startup", None)
    if not callable(startup):
        startup = getattr(worker, "start", None)
    if not callable(startup):
        return
    result = startup()
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    if result is False:
        _fail("configured worker startup is not ready")


def _shutdown_worker(worker: object, *, timeout: float = 30.0) -> None:
    shutdown = getattr(worker, "shutdown", None)
    if not callable(shutdown):
        shutdown = getattr(worker, "close", None)
    if not callable(shutdown):
        return
    try:
        parameters = inspect.signature(shutdown).parameters.values()
        names = {parameter.name for parameter in parameters}
    except (TypeError, ValueError):
        names = set()
    kwargs = {}
    if "wait" in names:
        kwargs["wait"] = True
    if "timeout" in names:
        kwargs["timeout"] = timeout
    result = shutdown(**kwargs)
    if inspect.isawaitable(result):
        asyncio.run(result)


def _install_stop_handlers(worker: object) -> tuple[object, object] | None:
    stopper = getattr(worker, "request_stop", None)
    if not callable(stopper):
        stopper = getattr(worker, "stop", None)
    if not callable(stopper):
        stopper = getattr(worker, "shutdown", None)
    if not callable(stopper):
        return None

    def request_stop(_signum: int, _frame: object) -> None:
        try:
            stopper()
        except Exception:
            return

    try:
        previous_int = signal.signal(signal.SIGINT, request_stop)
        try:
            previous_term = signal.signal(signal.SIGTERM, request_stop)
        except (ValueError, OSError):
            signal.signal(signal.SIGINT, previous_int)
            return None
    except (ValueError, OSError):
        return None
    return previous_int, previous_term


def _restore_stop_handlers(previous: tuple[object, object] | None) -> None:
    if previous is None:
        return
    try:
        signal.signal(signal.SIGINT, previous[0])
        signal.signal(signal.SIGTERM, previous[1])
    except (ValueError, OSError):
        return


def _load_worker() -> object:
    specification = os.environ.get(COMPOSITION_ENV, "").strip()
    if not specification:
        _fail(f"{COMPOSITION_ENV} is required")
    return _worker_from_composition(_resolve_composition(specification))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="load the injected composition and call worker.health_check()",
    )
    args = parser.parse_args(argv)
    worker = _load_worker()
    if args.health_check:
        try:
            _call_startup(worker)
        except SystemExit:
            raise
        except Exception:
            return 1
        check = getattr(worker, "readiness_check", None)
        if not callable(check):
            check = getattr(worker, "health_check", None)
        if not callable(check):
            _fail("configured worker has no readiness or health check")
        try:
            result = check()
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            return 0 if _health_value(result) else 1
        except Exception:
            return 1
    try:
        _call_startup(worker)
    except SystemExit:
        raise
    except Exception as exc:
        _fail(f"configured worker startup failed with {type(exc).__name__}")
    previous_handlers = _install_stop_handlers(worker)
    started_at = time.monotonic()
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # Keep process logs free of secret-bearing text.
        print(f"worker stopped with {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        _restore_stop_handlers(previous_handlers)
        _shutdown_worker(worker, timeout=max(1.0, 30.0 - (time.monotonic() - started_at)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
