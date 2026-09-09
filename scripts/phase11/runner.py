#!/usr/bin/env python3
"""Run root commands without hiding unavailable dependencies or failures."""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
CVG = ROOT / "cvg-master-rag-v2"
FRONTEND = CVG / "frontend"
PROFESSOR = ROOT / "rick-professor"
LOCKER = ROOT / "modulo-redis-locker"
PYTHON = str((ROOT / ".runtime/venvs/cvg/bin/python") if (ROOT / ".runtime/venvs/cvg/bin/python").is_file() else Path(sys.executable))
NPM = os.environ.get("NPM", "npm")
NODE = os.environ.get("NODE", "node")
GENERATED_COMPONENT_ARTIFACTS = (
    PROFESSOR / "test/artifacts/phase-0.6-provider-contract.json",
    FRONTEND / "next-env.d.ts",
)


def _command_text(command: Sequence[str]) -> str:
    return " ".join(str(part) for part in command)


def run_case(
    label: str,
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    env_updates: dict[str, str] | None = None,
    timeout: int = 600,
) -> bool:
    environment = os.environ.copy()
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


def run_cases(cases: Iterable[tuple[str, Sequence[str], Path, dict[str, str] | None, int]]) -> bool:
    results = []
    for label, command, cwd, env_updates, timeout in cases:
        results.append(run_case(label, command, cwd=cwd, env_updates=env_updates, timeout=timeout))
    return all(results)


def run_preserving_generated_artifacts(
    cases: Iterable[tuple[str, Sequence[str], Path, dict[str, str] | None, int]],
) -> bool:
    """Run preserved suites without leaking their disposable report files into root Git."""

    snapshots: dict[Path, bytes | None] = {}
    for path in GENERATED_COMPONENT_ARTIFACTS:
        try:
            snapshots[path] = path.read_bytes() if path.is_file() else None
        except OSError as exc:
            print(f"Could not snapshot generated artifact {path}: {exc}", file=sys.stderr, flush=True)
            return False

    result = False
    try:
        result = run_cases(cases)
    finally:
        restore_ok = True
        for path, content in snapshots.items():
            try:
                if content is None:
                    if path.is_file():
                        path.unlink()
                else:
                    path.write_bytes(content)
            except OSError as exc:
                restore_ok = False
                print(f"Could not restore generated artifact {path}: {exc}", file=sys.stderr, flush=True)
        result = result and restore_ok
    return result


def cvg_env() -> dict[str, str]:
    return {
        "PYTHONPATH": str(CVG / "src"),
        "OPENAI_API_KEY": "",
        "RERANKING_ENABLED": "false",
        "RAG_SKIP_QDRANT_BOOTSTRAP": "1",
        "SESSION_COOKIE_SECURE": "false",
    }


def npm_case(label: str, component: Path, args: Sequence[str], *, timeout: int = 600):
    return (label, [NPM, *args], component, None, timeout)


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
        ("preserved CVG runtime bootstrap", ["bash", "scripts/phase05/bootstrap-runtime.sh"], ROOT, None, 1200),
        npm_case("CVG frontend lockfile install", FRONTEND, ["ci", "--ignore-scripts", "--no-audit", "--no-fund"], timeout=1200),
        npm_case("Professor lockfile install", PROFESSOR, ["ci", "--ignore-scripts", "--no-audit", "--no-fund"], timeout=1200),
        npm_case("Locker lockfile install", LOCKER, ["ci", "--ignore-scripts", "--no-audit", "--no-fund"], timeout=1200),
        root_check_case(),
    ]
    return 0 if run_preserving_generated_artifacts(cases) else 1


def mode_test_fast() -> int:
    cases = [
        root_check_case(),
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
            "CVG focused contract/security regression",
            [
                "-m",
                "pytest",
                "-q",
                "src/tests/test_phase05_contract.py",
                "src/tests/test_phase05_security.py",
                "src/tests/test_phase06_rbac.py",
                "src/tests/test_p0_closeout.py",
            ],
            cwd=CVG,
            env=cvg_env(),
            timeout=600,
        ),
        npm_case("Professor tests", PROFESSOR, ["test", "--", "--test-force-exit"], timeout=600),
        npm_case("Locker tests", LOCKER, ["test"], timeout=300),
    ]
    return 0 if run_preserving_generated_artifacts(cases) else 1


def mode_test() -> int:
    cases = [
        root_check_case(),
        python_case("CVG complete preserved suite", ["-m", "pytest", "-q"], cwd=CVG, env=cvg_env(), timeout=1200),
        npm_case("Professor complete tests", PROFESSOR, ["test", "--", "--test-force-exit"], timeout=600),
        npm_case("Locker complete tests", LOCKER, ["test"], timeout=300),
        npm_case("CVG frontend lint and browser smoke", FRONTEND, ["test"], timeout=1200),
    ]
    return 0 if run_preserving_generated_artifacts(cases) else 1


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
            ],
            timeout=120,
        ),
        ("Locker JavaScript syntax", [NODE, "--check", "server.js"], LOCKER, None, 120),
        npm_case("CVG frontend lint", FRONTEND, ["run", "lint"], timeout=600),
    ]
    return 0 if run_cases(cases) else 1


def mode_typecheck() -> int:
    cases = [
        npm_case("Professor TypeScript compiler", PROFESSOR, ["run", "build"], timeout=600),
        (
            "CVG frontend TypeScript compiler (compatibility override)",
            [NPM, "exec", "--", "tsc", "--noEmit", "--ignoreDeprecations", "5.0"],
            FRONTEND,
            None,
            600,
        ),
        python_case("CVG Python compilation (no Python type checker configured)", ["-m", "compileall", "-q", "src"], cwd=CVG, env=cvg_env(), timeout=300),
    ]
    return 0 if run_cases(cases) else 1


def mode_build() -> int:
    cases = [
        npm_case("Professor build", PROFESSOR, ["run", "build"], timeout=600),
        npm_case("CVG frontend production build", FRONTEND, ["run", "build"], timeout=1200),
        python_case("CVG Python compilation", ["-m", "compileall", "-q", "src"], cwd=CVG, env=cvg_env(), timeout=300),
    ]
    return 0 if run_preserving_generated_artifacts(cases) else 1


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


def _wait_for_http(url: str, process: subprocess.Popen[bytes] | None = None, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _http_ready(url):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.25)
    return False


def _start_locker() -> tuple[subprocess.Popen[bytes] | None, object | None]:
    log_dir = ROOT / ".runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_handle = (log_dir / "phase11-locker.log").open("ab")
    environment = os.environ.copy()
    environment.update({"PORT": "3317", "REDIS_URL": "redis://127.0.0.1:6380"})
    try:
        process = subprocess.Popen(
            [NPM, "start"],
            cwd=LOCKER,
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    except OSError:
        log_handle.close()
        return None, None
    if not _wait_for_http("http://127.0.0.1:3317/healthz", process):
        process.terminate()
        process.wait(timeout=5)
        log_handle.close()
        return None, None
    return process, log_handle


def _stop_process(process: subprocess.Popen[bytes] | None, log_handle: object | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if log_handle is not None:
        log_handle.close()  # type: ignore[union-attr]


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
    locker_process: subprocess.Popen[bytes] | None = None
    locker_log = None
    locker_was_ready = _http_ready("http://127.0.0.1:3317/healthz")
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
        if not locker_was_ready:
            locker_process, locker_log = _start_locker()
            if locker_process is None:
                print("Locker integration process could not become ready; see .runtime/phase11-locker.log", file=sys.stderr)
                return False
        return run_cases(cases)
    finally:
        _stop_process(locker_process, locker_log)
        for label, pid in services_started.items():
            _stop_pid(label, pid)
            print(f"Stopped only runner-started {label} PID {pid}.", flush=True)


def mode_test_integration() -> int:
    cases = [
        python_case("CVG deterministic integration E2E", ["scripts/phase05/phase05_e2e.py", "--mode", "full"], env=cvg_env(), timeout=600),
        python_case("CVG deterministic restart E2E", ["scripts/phase05/phase05_e2e.py", "--mode", "restart"], env=cvg_env(), timeout=600),
        python_case("CVG non-leakage integration test", ["-m", "pytest", "-q", "src/tests/integration/test_tkt_010_non_leakage.py"], cwd=CVG, env=cvg_env(), timeout=600),
        ("Locker real HTTP integration", [NODE, "scripts/phase05/locker_e2e.mjs"], ROOT, {"LOCKER_URL": "http://127.0.0.1:3317"}, 300),
    ]
    return 0 if _with_local_services(cases) else 1


def mode_eval() -> int:
    cases = [
        python_case("deterministic Phase 0.5 RAG plumbing evaluation", ["scripts/phase05/phase05_e2e.py", "--mode", "full"], env=cvg_env(), timeout=600),
    ]
    return 0 if _with_local_services(cases) else 1


def mode_ci() -> int:
    modes = (mode_validate, mode_test_fast, mode_lint, mode_typecheck, mode_build)
    results = [mode() == 0 for mode in modes]
    return 0 if all(results) else 1


def mode_validate() -> int:
    label, command, cwd, env_updates, timeout = root_check_case()
    return 0 if run_case(label, command, cwd=cwd, env_updates=env_updates, timeout=timeout) else 1


def mode_compose(action: str) -> int:
    configured_file = os.environ.get("RICK_COMPOSE_FILE", "docker-compose.dev.yml").strip()
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
    compose_action = "up" if action == "dev" else action
    command = ["docker", "compose", "-f", str(compose.relative_to(ROOT)), compose_action]
    if action == "up":
        command.append("-d")
    return 0 if run_case(f"root compose {action}", command) else 1


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
