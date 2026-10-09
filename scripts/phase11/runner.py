#!/usr/bin/env python3
"""Run root commands without hiding unavailable dependencies or failures."""

from __future__ import annotations

import json
import os
from hashlib import sha256
import signal
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[2]

try:
    from scripts.state_of_art.json_boundary import loads_json
except ModuleNotFoundError:  # Direct execution from the scripts/phase11 directory.
    sys.path.insert(0, str(ROOT))
    from scripts.state_of_art.json_boundary import loads_json

WEB = ROOT / "apps" / "web"
API = ROOT / "apps" / "api"
WORKER = ROOT / "apps" / "worker"
NPM = os.environ.get("NPM", "npm")
NODE = os.environ.get("NODE", "node")
try:
    from scripts.state_of_art.phase3_runtime_adapter import redact_runtime_value
    from scripts.state_of_art.release_integrity import capture_checkout
    from scripts.state_of_art.runtime_preflight import (
        DEFAULT_PATH as PREFLIGHT_PATH,
        ENDPOINT_CONTRACT,
        REQUIRED_SERVICES,
        build_preflight,
        canonical_compose_project,
        sha256_path,
        validate_preflight,
        write_preflight,
    )
except ModuleNotFoundError:  # Direct execution from the scripts/phase11 directory.
    sys.path.insert(0, str(ROOT))
    from scripts.state_of_art.phase3_runtime_adapter import redact_runtime_value
    from scripts.state_of_art.release_integrity import capture_checkout
    from scripts.state_of_art.runtime_preflight import (
        DEFAULT_PATH as PREFLIGHT_PATH,
        ENDPOINT_CONTRACT,
        REQUIRED_SERVICES,
        build_preflight,
        canonical_compose_project,
        sha256_path,
        validate_preflight,
        write_preflight,
    )
try:
    from scripts.phase13.pyenv import interpreter as _canonical_interpreter
    from scripts.phase13.pyenv import pythonpath as _canonical_pythonpath
except ModuleNotFoundError:  # Direct execution from the scripts/phase11 directory.
    sys.path.insert(0, str(ROOT))
    from scripts.phase13.pyenv import interpreter as _canonical_interpreter
    from scripts.phase13.pyenv import pythonpath as _canonical_pythonpath


def canonical_env() -> dict[str, str]:
    """PYTHONPATH for canonical suites: apps/*/src + packages/*/src, no exports needed."""
    return {"PYTHONPATH": _canonical_pythonpath()}


def worker_suite_env() -> dict[str, str]:
    """Worker suite import path: ``worker.tests.*`` needs ``apps`` itself.

    ``apps/worker`` is already a source root, but the shared worker tests
    import each other as ``worker.tests.<module>``, which resolves from the
    parent directory. Only this lane pays for it, so the canonical PYTHONPATH
    contract for every other suite stays untouched.
    """

    env = canonical_env()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "apps"), env["PYTHONPATH"]])
    return env


PYTHON = _canonical_interpreter()
LOCAL_DOCKER_HOST = "unix:///var/run/docker.sock"
COMPOSE_WAIT_TIMEOUT_DEFAULT = 180
COMPOSE_RUNTIME_DIR = ROOT / ".runtime/phase-3/compose"
COMPOSE_ENV_REMOVE = (
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "DOCKER_API_VERSION",
    "COMPOSE_FILE",
    "COMPOSE_PROJECT_NAME",
)
COMPOSE_PROJECTS = {
    "docker-compose.dev.yml": "rick-intelligence-dev",
    "docker-compose.staging.yml": "rick-intelligence-staging",
}
COMPOSE_REQUIRED_SERVICES = frozenset(REQUIRED_SERVICES)
COMPOSE_ENV_EXAMPLES = {
    "docker-compose.dev.yml": "infrastructure/compose/.env.dev.example",
    "docker-compose.staging.yml": "infrastructure/compose/.env.staging.example",
}


def _command_text(command: Sequence[str]) -> str:
    return " ".join(str(part) for part in command)


def run_case(
    label: str,
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    env_updates: dict[str, str] | None = None,
    env_remove: Iterable[str] = (),
    timeout: int = 600,
) -> bool:
    environment = os.environ.copy()
    for name in env_remove:
        environment.pop(name, None)
    if env_updates:
        environment.update(env_updates)
    print(f"==> {label}: {_command_text(command)}", flush=True)
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=environment,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        print(f"<== {label}: NOT AVAILABLE (missing executable)", file=sys.stderr, flush=True)
        return False
    except subprocess.TimeoutExpired:
        print(f"<== {label}: TIMEOUT after {timeout}s", file=sys.stderr, flush=True)
        return False
    print(f"<== {label}: exit {completed.returncode}", flush=True)
    return completed.returncode == 0


def _compose_project(compose: Path) -> str:
    relative = compose.relative_to(ROOT).as_posix()
    # The project name is stable for this checkout path but cannot collide
    # with another worktree/user that runs the same topology concurrently.
    return canonical_compose_project(ROOT, relative)


def _compose_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    for name in COMPOSE_ENV_REMOVE:
        environment.pop(name, None)
    environment["COMPOSE_INTERACTIVE_NO_CLI"] = "1"
    environment["COMPOSE_MENU"] = "0"
    return environment


def _compose_command(
    compose: Path,
    *arguments: str,
    env_file: Path | None = None,
) -> list[str]:
    """Build a local-only command scoped to the selected Compose project."""

    relative = compose.relative_to(ROOT).as_posix()
    command = [
        "docker",
        "--host",
        LOCAL_DOCKER_HOST,
        "compose",
        "--project-name",
        _compose_project(compose),
    ]
    if env_file is not None:
        command.extend(("--env-file", env_file.relative_to(ROOT).as_posix()))
    command.extend(("--file", relative, *arguments))
    return command


def _compose_fallback_env_file(compose: Path) -> Path | None:
    relative = compose.relative_to(ROOT).as_posix()
    raw_path = COMPOSE_ENV_EXAMPLES.get(relative)
    if raw_path is None:
        return None
    path = ROOT / raw_path
    return path if path.is_file() else None


def _compose_capture(
    label: str,
    command: Sequence[str],
    *,
    timeout: int = 120,
) -> tuple[bool, str]:
    """Run a diagnostic/config command without echoing potentially sensitive output."""

    environment = _compose_environment()
    print(f"==> {label}: {_command_text(command)}", flush=True)
    try:
        completed = subprocess.run(
            list(command),
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        print(f"<== {label}: NOT AVAILABLE (missing executable)", file=sys.stderr, flush=True)
        return False, ""
    except subprocess.TimeoutExpired:
        print(f"<== {label}: TIMEOUT after {timeout}s", file=sys.stderr, flush=True)
        return False, ""
    print(f"<== {label}: exit {completed.returncode}", flush=True)
    return completed.returncode == 0, completed.stdout or ""


def _compose_wait_timeout() -> int:
    raw = os.environ.get("RICK_COMPOSE_WAIT_TIMEOUT", str(COMPOSE_WAIT_TIMEOUT_DEFAULT)).strip()
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise ValueError("RICK_COMPOSE_WAIT_TIMEOUT must be an integer number of seconds") from exc
    if not 1 <= timeout <= 1800:
        raise ValueError("RICK_COMPOSE_WAIT_TIMEOUT must be between 1 and 1800 seconds")
    return timeout


def _validate_compose_before_start(compose: Path) -> bool:
    if not run_case(
        "root compose config validation",
        _compose_command(compose, "config", "--quiet"),
        env_remove=COMPOSE_ENV_REMOVE,
        timeout=120,
    ):
        return False
    ok, output = _compose_capture(
        "root compose service inventory",
        _compose_command(compose, "config", "--services"),
    )
    if not ok:
        return False
    services = {line.strip() for line in output.splitlines() if line.strip()}
    missing = sorted(COMPOSE_REQUIRED_SERVICES - services)
    if missing:
        print(
            "<== root compose service inventory: missing required services: "
            + ", ".join(missing),
            file=sys.stderr,
            flush=True,
        )
        return False
    return True


def _redact_diagnostic_output(value: str) -> str:
    redacted = value
    for name in (
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "QDRANT_API_KEY",
        "MINIO_ROOT_PASSWORD",
        "LLM_API_KEY",
        "RICK_QDRANT_API_KEY",
        "OBJECT_STORE_ACCESS_KEY_ID",
        "OBJECT_STORE_SECRET_ACCESS_KEY",
        "RICK_OBJECT_STORE_SECRET_ACCESS_KEY",
    ):
        secret = os.environ.get(name, "")
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    sanitized = redact_runtime_value(redacted)
    return sanitized if isinstance(sanitized, str) else str(sanitized)


def _phase3_preflight_path() -> str | None:
    """Return the only allowed relative path for the shared attestation."""

    raw = os.environ.get("RICK_PHASE3_PREFLIGHT", PREFLIGHT_PATH).strip()
    candidate = Path(raw)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    normalized = candidate.as_posix()
    if normalized != raw.replace("\\", "/") or normalized != PREFLIGHT_PATH:
        return None
    return normalized


def _invalidate_phase3_preflight() -> None:
    """Remove only the selected attestation so a new run cannot reuse it."""

    relative = _phase3_preflight_path()
    if relative is None:
        return
    target = ROOT / relative
    try:
        if target.is_file() or target.is_symlink():
            target.unlink()
    except OSError as exc:
        print(f"Could not invalidate Phase 3 preflight: {exc}", file=sys.stderr, flush=True)


def _compose_config_sha256(compose: Path) -> str | None:
    """Hash a redacted rendered Compose config without persisting its contents."""

    ok, output = _compose_capture(
        "root compose rendered configuration fingerprint",
        _compose_command(compose, "config", "--format", "json"),
        timeout=120,
    )
    if not ok or not output.strip():
        return None
    redacted = _redact_diagnostic_output(output)
    return sha256(redacted.encode("utf-8")).hexdigest()


def _parse_compose_json_records(output: str) -> list[dict[str, object]]:
    try:
        decoded = loads_json(output)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        return [decoded]
    if isinstance(decoded, list) and all(isinstance(item, dict) for item in decoded):
        return [dict(item) for item in decoded]
    records: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            item = loads_json(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _compose_health_records(compose: Path) -> tuple[list[dict[str, object]], list[str]]:
    ok, output = _compose_capture(
        "root compose service health/readiness inventory",
        _compose_command(compose, "ps", "--all", "--format", "json"),
        timeout=120,
    )
    if not ok:
        return [], ["docker compose ps did not return a service inventory"]
    records = _parse_compose_json_records(output)
    errors: list[str] = []
    observations: list[dict[str, object]] = []
    project = _compose_project(compose)
    for item in records:
        service_name = item.get("Service", item.get("service"))
        if not isinstance(service_name, str) or not service_name.strip():
            errors.append("Compose service inventory contains a record without Service")
        elif service_name not in COMPOSE_REQUIRED_SERVICES:
            errors.append(f"Compose service inventory contains unexpected service {service_name}")
    for service in sorted(COMPOSE_REQUIRED_SERVICES):
        matches = [
            item for item in records
            if item.get("Service", item.get("service")) == service
        ]
        if len(matches) != 1:
            errors.append(f"service {service} has {len(matches)} Compose records")
            continue
        item = matches[0]
        declared_project = item.get("Project", item.get("project"))
        if declared_project != project:
            errors.append(f"service {service} belongs to the wrong Compose project")
        state = str(item.get("State", item.get("state", ""))).strip().lower()
        health = str(item.get("Health", item.get("health", ""))).strip().lower()
        ready = state == "running" and health == "healthy"
        if not ready:
            errors.append(f"service {service} is not running and healthy")
        observations.append(
            {
                "name": service,
                "state": state,
                "health": health,
                "ready": ready,
            }
        )
    return observations, errors


def _phase3_endpoint_timeout() -> float:
    raw = os.environ.get("RICK_PHASE3_ENDPOINT_TIMEOUT", "5").strip()
    try:
        timeout = float(raw)
    except ValueError:
        return 5.0
    return min(max(timeout, 0.5), 30.0)


def _probe_phase3_endpoint(name: str, url: str) -> dict[str, object]:
    verified_at = datetime.now(timezone.utc).isoformat()
    try:
        parsed = urlsplit(url)
    except ValueError:
        parsed = None
    expected_path, expected_port = ENDPOINT_CONTRACT.get(name, (None, None))
    try:
        actual_port = parsed.port if parsed is not None else None
    except ValueError:
        actual_port = None
    if (
        parsed is None
        or expected_path is None
        or expected_port is None
        or parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != expected_path
        or actual_port != expected_port
    ):
        return {
            "name": name,
            "url": url,
            "status": "FAIL",
            "reachable": False,
            "http_status": 0,
            "verified_at": verified_at,
        }
    try:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args: object, **_kwargs: object):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(urllib.request.Request(url, method="GET"), timeout=_phase3_endpoint_timeout()) as response:
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
    except (urllib.error.URLError, OSError, ValueError):
        status_code = 0
    return {
        "name": name,
        "url": url,
        "status": "PASS" if status_code == 200 else "FAIL",
        "reachable": status_code == 200,
        "http_status": status_code,
        "verified_at": verified_at,
    }


def _write_phase3_preflight(compose: Path, run_id: str) -> bool:
    relative_preflight = _phase3_preflight_path()
    if relative_preflight is None:
        print("NOT_READY: RICK_PHASE3_PREFLIGHT must be a normalized repository-relative path.", file=sys.stderr)
        return False
    config_hash = _compose_config_sha256(compose)
    compose_relative = compose.relative_to(ROOT).as_posix()
    source_hash = sha256_path(ROOT, compose_relative)
    services, service_errors = _compose_health_records(compose)
    endpoints = [
        _probe_phase3_endpoint(
            "api-readiness",
            os.environ.get("RICK_PHASE3_API_URL", "http://127.0.0.1:18000/health/ready"),
        ),
        _probe_phase3_endpoint(
            "web-readiness",
            os.environ.get("RICK_PHASE3_WEB_URL", "http://127.0.0.1:13000/login"),
        ),
    ]
    endpoint_errors = [
        f"endpoint {item['name']} did not pass its local readiness probe"
        for item in endpoints
        if item.get("status") != "PASS"
    ]
    checkout = capture_checkout(ROOT)
    if config_hash is None or source_hash is None:
        print("NOT_READY: rendered Compose configuration could not be fingerprinted.", file=sys.stderr)
        return False
    payload = build_preflight(
        run_id=run_id,
        target_id=f"phase3-compose:{_compose_project(compose)}:{compose_relative}",
        compose_file=compose_relative,
        compose_project=_compose_project(compose),
        compose_config_sha256=config_hash,
        compose_source_sha256=source_hash,
        required_services=services,
        required_service_names=REQUIRED_SERVICES,
        endpoints=endpoints,
        checkout=checkout,
    )
    errors = validate_preflight(
        payload,
        root=ROOT,
        expected_checkout=checkout,
        expected_compose_file=compose_relative,
        expected_compose_project=_compose_project(compose),
        expected_config_sha256=config_hash,
    )
    errors.extend(service_errors)
    errors.extend(endpoint_errors)
    if errors:
        print("NOT_READY: shared Phase 3 preflight rejected: " + "; ".join(errors), file=sys.stderr, flush=True)
        return False
    try:
        digest = write_preflight(ROOT, relative_preflight, payload)
    except (OSError, ValueError) as exc:
        print(f"NOT_READY: could not persist shared Phase 3 preflight: {exc}", file=sys.stderr, flush=True)
        return False
    print(
        f"<== shared Phase 3 preflight: PASS run_id={run_id} sha256={digest}",
        flush=True,
    )
    return True


def _collect_compose_diagnostics(compose: Path, *, phase: str = "failure") -> Path | None:
    """Persist bounded redacted Compose diagnostics before state can disappear."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    directory = COMPOSE_RUNTIME_DIR / stamp
    try:
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "metadata.txt").write_text(
            "compose=" + compose.relative_to(ROOT).as_posix() + "\n"
            + "project=" + _compose_project(compose) + "\n"
            + "phase=" + phase + "\n"
            + "captured_at=" + datetime.now(timezone.utc).isoformat() + "\n",
            encoding="utf-8",
        )
        for name, arguments in (
            ("ps.txt", ("ps", "--all")),
            ("logs.txt", ("logs", "--no-color", "--timestamps", "--tail", "200")),
        ):
            environment = _compose_environment()
            try:
                completed = subprocess.run(
                    _compose_command(compose, *arguments),
                    cwd=ROOT,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    timeout=30,
                )
                content = _redact_diagnostic_output(completed.stdout or "")
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                content = f"diagnostic unavailable: {type(exc).__name__}\n"
            target = directory / name
            target.write_text(content, encoding="utf-8")
            target.chmod(0o600)
        return directory.relative_to(ROOT)
    except OSError as exc:
        print(f"Could not collect local Compose diagnostics: {exc}", file=sys.stderr, flush=True)
        return None


def run_cases(cases: Iterable[tuple[str, Sequence[str], Path, dict[str, str] | None, int]]) -> bool:
    results = []
    for label, command, cwd, env_updates, timeout in cases:
        results.append(run_case(label, command, cwd=cwd, env_updates=env_updates, timeout=timeout))
    return all(results)


def npm_case(
    label: str,
    component: Path,
    args: Sequence[str],
    *,
    timeout: int = 600,
    env: dict[str, str] | None = None,
):
    return (label, [NPM, *args], component, env, timeout)


def python_case(label: str, args: Sequence[str], *, cwd: Path = ROOT, env=None, timeout: int = 600):
    return (label, [PYTHON, *args], cwd, env, timeout)


def root_check_case():
    # The implemented root tree is beyond the Phase 1.1 placeholder stage.
    # Keep the historical skeleton validator available for its own regression
    # tests, but make the public root validation target enforce current
    # boundary/preservation rules.
    return python_case("current root boundary validator", ["scripts/phase15/check_boundaries.py"], timeout=120)


def mode_bootstrap() -> int:
    cases = [
        ("runtime bootstrap from hash-locked requirements",
         ["bash", "scripts/phase05/bootstrap-runtime.sh"], ROOT, None, 1200),
        npm_case("canonical web lockfile install", WEB,
                 ["ci", "--ignore-scripts", "--no-audit", "--no-fund"], timeout=1200),
        root_check_case(),
    ]
    return 0 if run_cases(cases) else 1


def mode_test_fast() -> int:
    cases = [
        root_check_case(),
        python_case(
            "evidence store regression (AUD07-18)",
            ["-m", "unittest", "scripts/phase11/test_evidence_store.py"],
            timeout=180,
        ),
        python_case(
            "worktree hygiene / gitignore coverage (AUD07-19)",
            ["-m", "unittest", "scripts/phase11/test_untracked_hygiene.py"],
            timeout=120,
        ),
        python_case(
            "Phase 1.1 boundary validator regression",
            ["-m", "unittest", "scripts/phase11/test_check_skeleton.py"],
            timeout=120,
        ),
        python_case(
            "Phase 1.5 boundary validator regression",
            ["-m", "unittest", "scripts/phase15/test_check_boundaries.py"],
            timeout=120,
        ),
        python_case(
            "Phase 1.5 benchmark contract regression",
            ["-m", "unittest", "scripts/phase15/test_phase15_benchmark.py"],
            timeout=120,
        ),
        python_case(
            "legacy differential reference regression",
            ["-m", "unittest", "scripts/phase15/test_legacy_reference.py"],
            timeout=180,
        ),
        python_case(
            "canonical route/security contract regression",
            [str(ROOT / "scripts" / "phase13" / "phase13.py"), "security"],
            env=canonical_env(),
            timeout=600,
        ),
        python_case(
            "canonical retrieval ACL regression",
            [str(ROOT / "scripts" / "phase13" / "phase14.py"), "acl"],
            env=canonical_env(),
            timeout=600,
        ),
        python_case(
            "CI runner and workflow-validator regressions",
            ["-m", "pytest", "-q", "-p", "no:cacheprovider",
             str(ROOT / "scripts" / "phase11" / "test_check_workflow_actions.py"),
             str(ROOT / "scripts" / "phase11" / "test_check_docs.py"),
             str(ROOT / "scripts" / "phase11" / "test_pytest_discovery.py"),
             str(ROOT / "scripts" / "phase11" / "test_compose_lifecycle.py")],
            env=canonical_env(),
            timeout=600,
        ),
    ]
    return 0 if run_cases(cases) else 1


def mode_test() -> int:
    cases = [
        root_check_case(),
        python_case(
            "canonical Python suites (packages, API, differential)",
            [str(ROOT / "scripts" / "phase13" / "phase14.py"), "full"],
            env=canonical_env(),
            timeout=3600,
        ),
        python_case(
            "canonical worker suite",
            ["-m", "pytest", "-q", str(ROOT / "apps" / "worker" / "tests")],
            env=worker_suite_env(),
            timeout=900,
        ),
        python_case(
            "validator and CI-runner regression suites",
            ["-m", "pytest", "-q", "-p", "no:cacheprovider",
             str(ROOT / "scripts" / "phase11"), str(ROOT / "scripts" / "phase15")],
            env=canonical_env(),
            timeout=1800,
        ),
    ]
    return 0 if run_cases(cases) else 1


def mode_lint() -> int:
    cases = [
        root_check_case(),
        python_case(
            "Phase 1.1 Python syntax",
            [
                "-m",
                "py_compile",
                "scripts/phase11/check_skeleton.py",
                "scripts/phase11/runner.py",
                "scripts/phase11/test_check_skeleton.py",
                "scripts/phase15/check_boundaries.py",
                "scripts/phase15/test_check_boundaries.py",
                "scripts/phase15/legacy_reference.py",
                "scripts/phase13/pyenv.py",
                "scripts/phase13/pyexec.py",
                "scripts/phase13/phase13.py",
                "scripts/phase13/phase131.py",
                "scripts/phase13/phase14.py",
            ],
            timeout=120,
        ),
        python_case(
            "canonical API/worker Python syntax",
            ["-m", "compileall", "-q", "apps/api/src", "apps/worker"],
            timeout=300,
        ),
        npm_case("canonical web lint", WEB, ["run", "lint"], timeout=600),
    ]
    return 0 if run_cases(cases) else 1


def mode_typecheck() -> int:
    cases = [
        npm_case("canonical web TypeScript compiler", WEB, ["run", "typecheck"], timeout=600),
        python_case(
            "canonical scripts/packages Python compilation",
            ["-m", "compileall", "-q", "scripts", "packages"],
            timeout=600,
        ),
        python_case(
            "canonical Python gradual type check (mypy baseline)",
            [str(ROOT / "scripts" / "phase11" / "typecheck_baseline.py")],
            timeout=900,
        ),
    ]
    return 0 if run_cases(cases) else 1


def mode_build() -> int:
    cases = [
        npm_case(
            "canonical web production build",
            WEB,
            ["run", "build"],
            timeout=1200,
            env={"RICK_API_INTERNAL_URL": "http://127.0.0.1:8001"},
        ),
    ]
    return 0 if run_cases(cases) else 1


def _http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def _redis_ready() -> bool:
    redis_cli = shutil.which("redis-cli")
    if not redis_cli:
        return False
    try:
        completed = subprocess.run(
            [redis_cli, "-h", "127.0.0.1", "-p", "6380", "ping"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and completed.stdout.strip() == "PONG"


def _read_pid(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(value) if value.isdigit() else None


def _stop_pid(label: str, pid: int) -> None:
    """Stop only a PID captured as newly created by this runner invocation."""

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as exc:
        print(f"Could not stop runner-started {label} PID {pid}: {exc}", file=sys.stderr, flush=True)
        return

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except OSError:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def _with_local_services(cases: list[tuple[str, Sequence[str], Path, dict[str, str] | None, int]]) -> bool:
    qdrant_was_ready = _http_ready("http://127.0.0.1:6337/readyz")
    redis_was_ready = _redis_ready()
    service_pid_paths = {
        "Qdrant": ROOT / ".runtime/qdrant.pid",
        "Redis": ROOT / ".runtime/redis.pid",
    }
    service_was_ready = {"Qdrant": qdrant_was_ready, "Redis": redis_was_ready}
    service_pids_before = {label: _read_pid(path) for label, path in service_pid_paths.items()}
    services_started: dict[str, int] = {}
    try:
        if not (qdrant_was_ready and redis_was_ready):
            started_ok = run_case("start isolated Qdrant/Redis", ["bash", "scripts/phase05/start-local-services.sh"])
            for label, path in service_pid_paths.items():
                if service_was_ready[label]:
                    continue
                pid = _read_pid(path)
                if pid is not None and pid != service_pids_before[label]:
                    services_started[label] = pid
            if not started_ok:
                return False
        return run_cases(cases)
    finally:
        for label, pid in services_started.items():
            _stop_pid(label, pid)
            print(f"Stopped only runner-started {label} PID {pid}.", flush=True)


def mode_test_integration() -> int:
    """Canonical suites executed with the loopback Qdrant/Redis stack running."""
    cases = [
        python_case("canonical worker suite against local services",
                    ["-m", "pytest", "-q", str(WORKER / "tests")],
                    env=canonical_env(), timeout=900),
        python_case("canonical storage suite against local services",
                    ["-m", "pytest", "-q", str(ROOT / "packages" / "storage" / "tests")],
                    env=canonical_env(), timeout=900),
        python_case("canonical health/readiness suite against local services",
                    ["-m", "pytest", "-q", str(API / "tests" / "test_phase16_health.py")],
                    env=canonical_env(), timeout=900),
    ]
    return 0 if _with_local_services(cases) else 1


def mode_eval() -> int:
    """Offline retrieval/ACL/provenance evaluation against a versioned fixture."""
    env = canonical_env()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env["PYTHONPATH"]])
    cases = [
        python_case(
            "deterministic retrieval/ACL/provenance evaluation",
            ["scripts/state_of_art/evaluate_retrieval.py",
             "--fixture", "scripts/state_of_art/tests/fixtures/retrieval_fixture.json",
             "--pretty"],
            env=env,
            timeout=600,
        ),
    ]
    return 0 if run_cases(cases) else 1


def mode_ci() -> int:
    modes = (mode_validate, mode_test_fast, mode_lint, mode_typecheck, mode_build)
    results = [mode() == 0 for mode in modes]
    return 0 if all(results) else 1


def mode_validate() -> int:
    cases = [
        root_check_case(),
        python_case("portable documentation links (AUD07-24)",
                    ["scripts/phase11/check_docs.py"], timeout=120),
        python_case(
            "evidence store policy (AUD07-18)",
            ["scripts/phase11/evidence_store.py", "check"],
            timeout=180,
        ),
    ]
    return 0 if run_cases(cases) else 1


def mode_compose(action: str) -> int:
    configured_file = os.environ.get("RICK_COMPOSE_FILE", "docker-compose.dev.yml").strip()
    if configured_file not in COMPOSE_PROJECTS:
        print(
            "NOT_READY: RICK_COMPOSE_FILE must select docker-compose.dev.yml or docker-compose.staging.yml.",
            file=sys.stderr,
        )
        return 2
    compose = (ROOT / configured_file).resolve()
    try:
        compose.relative_to(ROOT)
    except ValueError:
        print("NOT_READY: RICK_COMPOSE_FILE must remain inside the repository root.", file=sys.stderr)
        return 2
    if action == "down" and not compose.is_file():
        print("NOT_APPLICABLE: no canonical root compose stack is configured; no external state changed.")
        return 0
    if not compose.is_file():
        print(f"NOT_READY: {compose.name} is unavailable; no external state changed.", file=sys.stderr)
        return 2
    if not shutil.which("docker"):
        print("NOT_AVAILABLE: Docker is required for the root compose lifecycle.", file=sys.stderr)
        return 2
    if action in {"dev", "up"}:
        try:
            wait_timeout = _compose_wait_timeout()
        except ValueError as error:
            print(f"NOT_READY: {error}", file=sys.stderr)
            return 2
        _invalidate_phase3_preflight()
        if not _validate_compose_before_start(compose):
            print("NOT_READY: Compose configuration is not ready; no services were started.", file=sys.stderr)
            return 1
        command = _compose_command(
            compose,
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            str(wait_timeout),
            "--remove-orphans",
        )
        started = run_case(
            f"root compose {action}",
            command,
            env_remove=COMPOSE_ENV_REMOVE,
            timeout=wait_timeout + 120,
        )
        if started:
            run_id = os.environ.get("RICK_PHASE3_RUN_ID", "").strip() or uuid.uuid4().hex
            if _write_phase3_preflight(compose, run_id):
                snapshot = _collect_compose_diagnostics(compose, phase="ready")
                if snapshot:
                    print(f"<== bounded Compose readiness snapshot: {snapshot}", flush=True)
                return 0
            diagnostics = _collect_compose_diagnostics(compose)
            suffix = f" Diagnostics: {diagnostics}." if diagnostics else ""
            print(
                "NOT_READY: Compose services started, but the shared Phase 3 preflight did not pass."
                + suffix,
                file=sys.stderr,
            )
            return 1
        diagnostics = _collect_compose_diagnostics(compose)
        suffix = f" Diagnostics: {diagnostics}." if diagnostics else ""
        print(
            "NOT_READY: required Compose services did not reach running/healthy state."
            + suffix,
            file=sys.stderr,
        )
        return 1
    if action == "down":
        snapshot = _collect_compose_diagnostics(compose, phase="pre-teardown")
        if snapshot:
            print(f"<== bounded Compose pre-teardown snapshot: {snapshot}", flush=True)
        _invalidate_phase3_preflight()
        command = _compose_command(
            compose,
            "down",
            "--remove-orphans",
            "--timeout",
            "30",
            env_file=_compose_fallback_env_file(compose),
        )
    else:
        command = _compose_command(
            compose,
            "logs",
            "--no-color",
            "--timestamps",
            "--tail",
            "200",
            env_file=_compose_fallback_env_file(compose),
        )
    return 0 if run_case(
        f"root compose {action}",
        command,
        env_remove=COMPOSE_ENV_REMOVE,
        timeout=120,
    ) else 1


MODES = {
    "bootstrap": mode_bootstrap,
    "validate": mode_validate,
    "test-fast": mode_test_fast,
    "test": mode_test,
    "test-integration": mode_test_integration,
    "lint": mode_lint,
    "typecheck": mode_typecheck,
    "build": mode_build,
    "ci": mode_ci,
    "eval": mode_eval,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: runner.py <bootstrap|validate|test-fast|test|test-integration|lint|typecheck|build|ci|eval|dev|up|down|logs>", file=sys.stderr)
        return 2
    mode = argv[1]
    if mode in {"dev", "up", "down", "logs"}:
        return mode_compose(mode)
    handler = MODES.get(mode)
    if handler is None:
        print(f"unknown root command: {mode}", file=sys.stderr)
        return 2
    return handler()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
