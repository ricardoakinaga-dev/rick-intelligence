"""Fail-closed launcher for the externally composed ingestion worker.

The repository provides the worker class and adapters, but deliberately does
not provide a process-level production composition. A deployment supplies a
small, reviewed module whose factory returns either a
``PostgresIngestionWorker`` or an object exposing ``worker``. The factory owns
all database, Redis, object-store, vector, identity, and provider clients.
This launcher never reads or constructs those clients and never prints
environment values.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import os
import re
import sys
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
        check = getattr(worker, "health_check", None)
        if not callable(check):
            _fail("configured worker has no health_check")
        try:
            return 0 if check() is True else 1
        except Exception:
            return 1
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # Keep process logs free of secret-bearing text.
        print(f"worker stopped with {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
