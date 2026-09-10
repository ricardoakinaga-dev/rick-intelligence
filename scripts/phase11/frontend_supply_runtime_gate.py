#!/usr/bin/env python3
"""Run the Phase 3 frontend, accessibility and supply-chain gate.

The browser lane deliberately exercises the canonical web application through
its public HTTP boundary.  It does not install dependencies, intercept
requests, seed browser responses, or reuse the repository's fixture-only
visual tests as runtime evidence.  A managed local run uses the real Next.js
process and the real ``apps/api`` process in test mode; an external run may be
pointed at an approved environment with ``--web-url`` and ``--api-url``.

The command is a diagnostic/release gate, not a claim that a missing tool was
successful.  Exit codes are stable: 0 is PASS, 1 is an observed failure, and
2 is BLOCKED_EXTERNAL/NOT_RUN.  Every persisted payload is redacted before it
is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
VIEWPORTS: tuple[dict[str, int], ...] = (
    {"name": "mobile", "width": 375, "height": 812},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "desktop", "width": 1440, "height": 1000},
)
NODE_COMPONENTS = (
    "apps/web",
    "modulo-redis-locker",
    "rick-professor",
    "cvg-master-rag-v2/frontend",
)
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2
STATUSES = {"PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_RUN", "WARN"}


_SECRET_VALUE = re.compile(
    r"(?:redis|rediss|postgres(?:ql)?|mysql|amqp|https?)://[^\s\"']+|bearer\s+[^\s\"']+",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_-])([\"']?[A-Za-z0-9_-]*(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|credential|dsn|url|bearer)[A-Za-z0-9_-]*[\"']?)"
    r"(\s*[:=]\s*)(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\[REDACTED\]|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_SECRET_ARGUMENT = re.compile(
    r"(?<![A-Za-z0-9_-])([/-]{0,2}[A-Za-z0-9_-]*(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|credential|dsn|url|bearer)[A-Za-z0-9_-]*)"
    r"(\s+)(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\[REDACTED\]|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_HIGH_SIGNAL_SECRETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("github_token", re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9_]{30,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
)
_DIGEST_REF = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_NETWORK_FAILURE = re.compile(
    r"(?:eai_again|enetwork|enetunreach|econnreset|econnrefused|network|fetch failed|timed out|timeout|registry)",
    re.IGNORECASE,
)


def _redact_text(value: str) -> str:
    value = _SECRET_VALUE.sub("[REDACTED]", value)
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)
    return _SECRET_ARGUMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)


def redact(value: Any, *, key: str = "") -> Any:
    """Return a JSON-safe value with secret-shaped fields and values removed."""

    if re.search(
        r"(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|credential|dsn)",
        key,
        re.IGNORECASE,
    ):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(name): redact(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _safe_path(root: Path, raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise ValueError("output/evidence path must remain inside the repository root") from None
    return path


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return "[EXTERNAL_ARTIFACT]"


def _check(
    name: str,
    status: str,
    detail: str,
    *,
    evidence: Sequence[str] = (),
    required: bool = True,
    tool: str | None = None,
    observations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"unsupported check status: {status}")
    result: dict[str, Any] = {
        "name": name,
        "status": status,
        "result": status,
        "required": required,
        "detail": _redact_text(detail),
        "evidence": list(evidence),
    }
    if tool:
        result["tool"] = tool
    if observations:
        result["observations"] = redact(dict(observations))
    return result


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(redact(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    """Run a bounded command without shell expansion or inherited secrets in output."""
    try:
        return subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=dict(env) if env is not None else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            list(argv),
            124,
            stdout=exc.stdout or "",
            stderr="command timed out",
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(list(argv), 127, stdout="", stderr="command unavailable")


def _command_tail(result: subprocess.CompletedProcess[str], *, limit: int = 8) -> str:
    output = "\n".join((result.stdout or "").splitlines()[-limit:] + (result.stderr or "").splitlines()[-limit:])
    return _redact_text(output)[:2_000]


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _git_files(root: Path) -> list[Path]:
    git = _tool("git")
    if git:
        try:
            result = _run_command([git, "-C", str(root), "ls-files", "-z"], cwd=root, timeout=20)
            if result.returncode == 0:
                return [root / item for item in result.stdout.split("\0") if item]
        except (OSError, subprocess.SubprocessError):
            pass
    excluded = {".git", ".next", "node_modules", ".runtime", "test-results", "__pycache__", ".pytest_cache"}
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in excluded for part in path.relative_to(root).parts)
    ]


def _validate_url(value: str, *, field: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{field} must be an HTTP(S) URL without embedded credentials")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _http_observation(url: str, *, timeout: float = 5.0) -> tuple[bool, int | None, str]:
    try:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "rick-phase3-gate/1"})
        with urlopen(request, timeout=timeout) as response:
            return True, int(response.status), "HTTP endpoint responded"
    except HTTPError as exc:
        return False, int(exc.code), f"HTTP endpoint returned status {exc.code}"
    except (OSError, URLError, ValueError) as exc:
        return False, None, f"HTTP endpoint unavailable ({type(exc).__name__})"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tail_file(path: Path, *, limit: int = 12) -> str:
    try:
        return _redact_text("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]))[:2_000]
    except OSError:
        return "runtime log unavailable"


def _terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            process.terminate()
        except OSError:
            return
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            pass


class _ManagedRuntime:
    """Own only the two loopback processes created for this gate."""

    def __init__(self, root: Path, *, timeout: float, production: bool = False) -> None:
        self.root = root
        self.timeout = timeout
        self.production = production
        self.api_port = _free_port()
        self.web_port = _free_port()
        self.api: subprocess.Popen[str] | None = None
        self.web: subprocess.Popen[str] | None = None
        self._tmp = tempfile.TemporaryDirectory(prefix="rick-phase3-frontend-")
        self.api_log = Path(self._tmp.name) / "api.log"
        self.web_log = Path(self._tmp.name) / "web.log"

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def web_url(self) -> str:
        return f"http://127.0.0.1:{self.web_port}"

    def _pythonpath(self) -> str:
        paths = (
            self.root / "apps/api/src",
            self.root / "apps/worker",
            self.root / "packages/jobs/src",
            self.root / "packages/contracts/src",
            self.root / "packages/authorization/src",
            self.root / "packages/identity/src",
            self.root / "packages/observability/src",
            self.root / "packages/knowledge/src",
            self.root / "packages/ingestion/src",
            self.root / "packages/retrieval/src",
            self.root / "packages/providers/src",
            self.root / "packages/locking/src",
            self.root / "packages/professor/src",
            self.root / "packages/evidence/src",
            self.root / "packages/decision/src",
            self.root / "packages/storage/src",
        )
        return os.pathsep.join(str(path) for path in paths)

    def _start(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], log: Path) -> subprocess.Popen[str]:
        stream = log.open("w", encoding="utf-8")
        try:
            return subprocess.Popen(
                list(argv),
                cwd=str(cwd),
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except BaseException:
            stream.close()
            raise

    def _wait(self, url: str, process: subprocess.Popen[str], label: str) -> None:
        deadline = time.monotonic() + self.timeout
        last_detail = "no response"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"{label} exited before readiness: {_tail_file(self.api_log if label == 'API' else self.web_log)}")
            ok, status, detail = _http_observation(url, timeout=2.0)
            last_detail = f"{detail}; status={status}"
            if ok and status is not None and 200 <= status < 300:
                return
            time.sleep(0.25)
        raise RuntimeError(f"{label} readiness timed out ({last_detail})")

    def __enter__(self) -> "_ManagedRuntime":
        api_env = os.environ.copy()
        api_env.update(
            {
                "RICK_ENV": "test",
                "RICK_IDENTITY_MODE": "test",
                "RICK_API_USE_LEGACY": "0",
                "RICK_API_CHAT_BACKEND": "stub",
                "RICK_API_PORT": str(self.api_port),
                "LOGIN_RATE_LIMIT_PER_MIN": "100",
                "CHAT_RATE_LIMIT_PER_MIN": "100",
                "RECOVERY_RATE_LIMIT_PER_MIN": "100",
                "CORS_ALLOWED_ORIGINS": f"{self.web_url},http://localhost:{self.web_port}",
                "PYTHONPATH": self._pythonpath(),
            }
        )
        self.api = self._start(
            [sys.executable, "-m", "main"],
            cwd=self.root / "apps/api",
            env=api_env,
            log=self.api_log,
        )
        try:
            self._wait(f"{self.api_url}/health/live", self.api, "API")
            web_env = os.environ.copy()
            web_env.pop("NEXT_PUBLIC_API_BASE_URL", None)
            requested_dev = os.getenv("RICK_FRONTEND_SUPPLY_DEV", "").strip() == "1"
            if self.production and requested_dev:
                raise RuntimeError("production runtime cannot be combined with RICK_FRONTEND_SUPPLY_DEV=1")
            web_env.update(
                {
                    "RICK_API_INTERNAL_URL": self.api_url,
                    "NEXT_TELEMETRY_DISABLED": "1",
                    "NODE_ENV": "production" if self.production else "development",
                }
            )
            npm = _tool("npm")
            if npm is None:
                raise RuntimeError("npm is unavailable")
            if self.production:
                build = _run_command(
                    [npm, "run", "build"],
                    cwd=self.root / "apps/web",
                    env=web_env,
                    timeout=max(120.0, self.timeout * 4),
                )
                if build.returncode != 0:
                    raise RuntimeError(f"web production build failed: {_command_tail(build)}")
            self.web = self._start(
                [
                    npm,
                    "run",
                    "start" if self.production else "dev",
                    "--",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(self.web_port),
                ],
                cwd=self.root / "apps/web",
                env=web_env,
                log=self.web_log,
            )
            self._wait(f"{self.web_url}/login", self.web, "web")
            return self
        except BaseException:
            _terminate_process(self.web)
            _terminate_process(self.api)
            self._tmp.cleanup()
            raise

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        _terminate_process(self.web)
        _terminate_process(self.api)
        self._tmp.cleanup()


def _find_playwright_module(root: Path) -> Path | None:
    override = os.getenv("RICK_FRONTEND_PLAYWRIGHT_MODULE", "").strip()
    candidates = [Path(override)] if override else []
    candidates.extend(
        [
            root / "apps/web/node_modules/playwright",
            root / "apps/web/node_modules/@playwright/test",
        ]
    )
    return next((candidate.resolve() for candidate in candidates if candidate.is_dir()), None)


def _find_axe(root: Path) -> Path | None:
    override = os.getenv("RICK_FRONTEND_AXE_PATH", "").strip()
    candidates = [Path(override)] if override else []
    candidates.append(root / "apps/web/node_modules/axe-core/axe.min.js")
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def _find_browser(node: str, module: Path, requested: str | None) -> str | None:
    candidates: list[str] = []
    if requested:
        candidates.append(requested)
    env_value = os.getenv("RICK_BROWSER_EXECUTABLE", "").strip()
    if env_value:
        candidates.append(env_value)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = _tool(name)
        if found:
            candidates.append(found)
    try:
        result = _run_command(
            [node, "-e", "const p=require(process.argv[1]).chromium; process.stdout.write(p.executablePath());", str(module)],
            cwd=ROOT,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            candidates.append(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


_BROWSER_PROBE = r'''"use strict";

const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const { chromium } = require(process.env.RICK_FRONTEND_PLAYWRIGHT_MODULE);

const webBase = process.env.RICK_FRONTEND_WEB_URL.replace(/\/$/, "");
const apiBase = process.env.RICK_FRONTEND_API_URL.replace(/\/$/, "");
const axePath = process.env.RICK_FRONTEND_AXE_PATH;
const evidencePath = process.env.RICK_FRONTEND_EVIDENCE;
const screenshotDir = process.env.RICK_FRONTEND_SCREENSHOT_DIR;
const email = process.env.RICK_FRONTEND_LOGIN_EMAIL;
const password = process.env.RICK_FRONTEND_LOGIN_PASSWORD;
const tenant = process.env.RICK_FRONTEND_LOGIN_TENANT || "default";
const viewports = JSON.parse(process.env.RICK_FRONTEND_VIEWPORTS);
const browserExecutable = process.env.RICK_FRONTEND_BROWSER_EXECUTABLE || undefined;

function safeError(error) {
  return String(error && error.message ? error.message : error)
    .replace(/(?:redis|rediss|postgres(?:ql)?|mysql|amqp|https?):\/\/[^\s"']+/gi, "[REDACTED]")
    .replace(/(?:password|passphrase|secret|token|api[_-]?key|authorization)\s*[:=]\s*[^\s,}]+/gi, "$1=[REDACTED]");
}

function isApi(url) { return /\/api\//.test(url); }
function visible(element) {
  const style = getComputedStyle(element);
  const box = element.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0 && box.width > 0 && box.height > 0;
}
function parseColor(value) {
  const match = value.match(/rgba?\(([^)]+)\)/i);
  if (!match) return null;
  const parts = match[1].split(",").map((part) => Number.parseFloat(part.trim()));
  if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return null;
  const alpha = parts.length > 3 && Number.isFinite(parts[3]) ? parts[3] : 1;
  return { r: parts[0], g: parts[1], b: parts[2], a: alpha };
}
function channel(value) {
  const normalized = value / 255;
  return normalized <= 0.03928 ? normalized / 12.92 : Math.pow((normalized + 0.055) / 1.055, 2.4);
}
function luminance(color) { return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b); }
function contrastRatio(foreground, background) {
  const light = Math.max(luminance(foreground), luminance(background));
  const dark = Math.min(luminance(foreground), luminance(background));
  return (light + 0.05) / (dark + 0.05);
}
function opaqueBackground(element) {
  let current = element;
  while (current && current.nodeType === Node.ELEMENT_NODE) {
    const color = parseColor(getComputedStyle(current).backgroundColor);
    if (color && color.a >= 0.99) return color;
    current = current.parentElement;
  }
  return null;
}

async function waitVisible(locator, timeout = 15000) {
  await locator.waitFor({ state: "visible", timeout });
}
async function waitFor(predicate, timeout = 8000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return false;
}
async function sha256(file) {
  return crypto.createHash("sha256").update(await fs.promises.readFile(file)).digest("hex");
}

async function contrastAudit(page) {
  return page.evaluate(() => {
    function parseColor(value) {
      const match = value.match(/rgba?\(([^)]+)\)/i);
      if (!match) return null;
      const parts = match[1].split(",").map((part) => Number.parseFloat(part.trim()));
      if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return null;
      const alpha = parts.length > 3 && Number.isFinite(parts[3]) ? parts[3] : 1;
      return { r: parts[0], g: parts[1], b: parts[2], a: alpha };
    }
    function visible(element) {
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0 && box.width > 0 && box.height > 0;
    }
    function channel(value) {
      const normalized = value / 255;
      return normalized <= 0.03928 ? normalized / 12.92 : Math.pow((normalized + 0.055) / 1.055, 2.4);
    }
    function luminance(color) { return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b); }
    function contrastRatio(foreground, background) {
      const light = Math.max(luminance(foreground), luminance(background));
      const dark = Math.min(luminance(foreground), luminance(background));
      return (light + 0.05) / (dark + 0.05);
    }
    function opaqueBackground(element) {
      let current = element;
      while (current && current.nodeType === Node.ELEMENT_NODE) {
        const color = parseColor(getComputedStyle(current).backgroundColor);
        if (color && color.a >= 0.99) return color;
        current = current.parentElement;
      }
      return null;
    }
    const candidates = Array.from(document.querySelectorAll("body *")).filter((element) => {
      if (!visible(element)) return false;
      const text = (element.textContent || "").replace(/\s+/g, " ").trim();
      const role = element.getAttribute("role");
      return Boolean(text) || ["A", "BUTTON", "INPUT", "TEXTAREA", "SELECT"].includes(element.tagName) || role === "button";
    });
    const findings = [];
    for (const element of candidates.slice(0, 160)) {
      const style = getComputedStyle(element);
      const foreground = parseColor(style.color);
      const background = opaqueBackground(element);
      if (!foreground || !background) {
        findings.push({ selector: element.tagName.toLowerCase(), ratio: null, status: "UNKNOWN" });
        continue;
      }
      const ratio = contrastRatio(foreground, background);
      const size = Number.parseFloat(style.fontSize || "16");
      const bold = Number.parseInt(style.fontWeight || "400", 10) >= 700;
      const large = size >= 18 || (bold && size >= 14);
      const threshold = large ? 3 : 4.5;
      if (ratio < threshold) findings.push({ selector: element.tagName.toLowerCase(), ratio: Number(ratio.toFixed(2)), threshold, status: "FAIL" });
    }
    return { checked: candidates.length, failures: findings.filter((item) => item.status === "FAIL"), unknown: findings.filter((item) => item.status === "UNKNOWN"), sample: findings.slice(0, 24) };
  });
}

async function touchAudit(page) {
  return page.evaluate(() => {
    function visible(element) {
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0 && box.width > 0 && box.height > 0;
    }
    const controls = Array.from(document.querySelectorAll("a[href], button, input, textarea, select, [role='button']")).filter(visible);
    const belowMinimum = controls.map((element) => {
      const box = element.getBoundingClientRect();
      return { tag: element.tagName.toLowerCase(), name: element.getAttribute("aria-label") || (element.textContent || "").trim().slice(0, 80), width: Number(box.width.toFixed(1)), height: Number(box.height.toFixed(1)) };
    }).filter((item) => item.width < 24 || item.height < 24);
    return { touch_points: navigator.maxTouchPoints, checked: controls.length, minimum_css_px: 24, below_minimum: belowMinimum.slice(0, 24) };
  });
}

async function focusAudit(page) {
  const skip = page.locator(".skip-link");
  await page.evaluate(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); });
  await page.keyboard.press("Tab");
  const first = await page.evaluate(() => ({ href: document.activeElement && document.activeElement.getAttribute("href"), className: document.activeElement && document.activeElement.className, tag: document.activeElement && document.activeElement.tagName }));
  await skip.focus();
  const ring = await page.evaluate(() => {
    const element = document.activeElement;
    if (!element) return { visible: false };
    const style = getComputedStyle(element);
    const outline = Number.parseFloat(style.outlineWidth || "0");
    return { visible: outline > 0 || style.outlineStyle !== "none" || style.boxShadow !== "none", outline: style.outline, boxShadow: style.boxShadow };
  });
  let mobileMenu = null;
  if ((page.viewportSize() || {}).width <= 900) {
    const menu = page.getByRole("button", { name: "Abrir navegação" });
    await waitVisible(menu);
    await menu.focus();
    await page.keyboard.press("Enter");
    const close = page.getByRole("button", { name: "Fechar navegação" });
    await waitVisible(close);
    const opened = await menu.getAttribute("aria-expanded");
    const closeFocused = await close.evaluate((element) => document.activeElement === element);
    await page.keyboard.press("Escape");
    const closed = await menu.getAttribute("aria-expanded");
    const restored = await menu.evaluate((element) => document.activeElement === element);
    mobileMenu = { opened: opened === "true", close_focused: closeFocused, closed: closed === "false", focus_restored: restored };
  }
  return { first_tab: first, skip_link_focus_ring: ring, first_tab_is_skip_link: first.href === "#main-content", mobile_menu: mobileMenu };
}

async function axeAudit(page) {
  await page.addScriptTag({ path: axePath });
  return page.evaluate(async () => {
    if (!window.axe || typeof window.axe.run !== "function") throw new Error("axe did not load");
    const result = await window.axe.run(document, { resultTypes: ["violations", "incomplete", "passes"] });
    const project = (item) => ({ id: item.id, impact: item.impact, nodes: item.nodes.map((node) => ({ target: node.target, failureSummary: node.failureSummary || null })) });
    return { violations: result.violations.map(project), incomplete: result.incomplete.map(project), passes: result.passes.map((item) => item.id), engine: result.testEngine && result.testEngine.version };
  });
}

async function runViewport(browser, viewport, index) {
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: 1, hasTouch: viewport.width <= 375, reducedMotion: "reduce" });
  const page = await context.newPage();
  const apiResponses = [];
  const consoleErrors = [];
  const requestFailures = [];
  page.on("response", (response) => { if (isApi(response.url())) apiResponses.push({ path: new URL(response.url()).pathname, status: response.status(), method: response.request().method() }); });
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(safeError(message.text())); });
  page.on("pageerror", (error) => consoleErrors.push(safeError(error)));
  page.on("requestfailed", (request) => { if (isApi(request.url())) requestFailures.push({ path: new URL(request.url()).pathname, error: safeError(request.failure() && request.failure().errorText) }); });
  const result = { name: viewport.name, viewport, states: {}, checks: {}, screenshots: [], api_responses: [], console_errors: [], request_failures: [] };
  try {
    await page.goto(`${webBase}/login?next=%2Fapp`, { waitUntil: "domcontentloaded" });
    await waitVisible(page.getByRole("heading", { name: "Entre para continuar." }));
    result.states.login = { observed: true, url: new URL(page.url()).pathname };
    const loginAxe = await axeAudit(page);
    const loginContrast = await contrastAudit(page);
    const loginScreenshot = path.join(screenshotDir, `login-${viewport.name}.png`);
    await page.screenshot({ path: loginScreenshot, fullPage: true });
    result.screenshots.push({ state: "login", path: loginScreenshot, sha256: await sha256(loginScreenshot) });
    result.checks.axe_login = loginAxe;
    result.checks.contrast_login = loginContrast;

    if (index === 0) {
      const failedPassword = `${password}-invalid`;
      await page.getByLabel("E-mail").fill(email);
      await page.getByLabel("Senha").fill(failedPassword);
      await page.getByRole("button", { name: "Entrar", exact: true }).click();
      await waitVisible(page.getByRole("alert"));
      result.states.login_error = { observed: true, stayed_on_login: new URL(page.url()).pathname === "/login" };
    }

    await page.getByLabel("E-mail").fill(email);
    await page.getByLabel("Senha").fill(password);
    const loginResponse = page.waitForResponse((response) => response.url().includes("/api/v1/auth/login"), { timeout: 15000 });
    await page.getByRole("button", { name: "Entrar", exact: true }).click();
    const loginObserved = await loginResponse;
    if (loginObserved.status() !== 200) throw new Error(`real API login returned ${loginObserved.status()}`);
    await page.waitForURL((url) => url.pathname === "/app", { timeout: 15000 });
    await waitVisible(page.getByRole("heading", { name: "Seu espaço de evidências." }));
    result.states.authenticated = { observed: true, url: new URL(page.url()).pathname };
    const appAxe = await axeAudit(page);
    const appContrast = await contrastAudit(page);
    const focus = await focusAudit(page);
    const reduced = await page.evaluate(() => ({ preference: window.matchMedia("(prefers-reduced-motion: reduce)").matches, animations: document.getAnimations().map((animation) => ({ playState: animation.playState, duration: animation.effect && animation.effect.getComputedTiming().duration })).filter((item) => item.playState === "running") }));
    const appScreenshot = path.join(screenshotDir, `workbench-${viewport.name}.png`);
    await page.screenshot({ path: appScreenshot, fullPage: true });
    result.screenshots.push({ state: "authenticated", path: appScreenshot, sha256: await sha256(appScreenshot) });
    result.checks.axe_authenticated = appAxe;
    result.checks.contrast_authenticated = appContrast;
    result.checks.focus = focus;
    result.checks.reduced_motion = reduced;

    await page.goto(`${webBase}/app/chat`, { waitUntil: "domcontentloaded" });
    await waitVisible(page.getByLabel("Pergunta"));
    await page.getByLabel("Pergunta").fill("Quais documentos estão disponíveis?");
    const chatResponse = page.waitForResponse((response) => response.url().includes("/api/v1/chat"), { timeout: 20000 });
    await page.getByRole("button", { name: "Consultar", exact: true }).click();
    const chatObserved = await chatResponse;
    if (chatObserved.status() < 200 || chatObserved.status() >= 300) throw new Error(`real API chat returned ${chatObserved.status()}`);
    await waitVisible(page.getByRole("heading", { name: "Leitura do resultado" }), 20000);
    result.states.chat = { observed: true, api_status: chatObserved.status() };
    result.checks.axe_chat = await axeAudit(page);
    result.checks.contrast_chat = await contrastAudit(page);
    result.checks.touch = await touchAudit(page);
    result.checks.viewport = await page.evaluate((expected) => ({ inner_width: window.innerWidth, inner_height: window.innerHeight, expected_width: expected.width, expected_height: expected.height, matches: window.innerWidth === expected.width && window.innerHeight === expected.height, touch_points: navigator.maxTouchPoints }), viewport);
    const chatScreenshot = path.join(screenshotDir, `chat-${viewport.name}.png`);
    await page.screenshot({ path: chatScreenshot, fullPage: true });
    result.screenshots.push({ state: "chat", path: chatScreenshot, sha256: await sha256(chatScreenshot) });
    result.api_responses = apiResponses;
    result.console_errors = consoleErrors;
    result.request_failures = requestFailures;
    result.unexpected_console_errors = consoleErrors.filter((item) => !/Failed to load resource: the server responded with a status of (401|404) \(/.test(item));
    result.unexpected_request_failures = requestFailures.filter((item) => item.error !== "net::ERR_ABORTED");
    result.checks.api_backed = { login_200: apiResponses.some((item) => item.path.endsWith("/auth/login") && item.status === 200), session_200: apiResponses.some((item) => item.path.endsWith("/auth/me") && item.status === 200), chat_2xx: apiResponses.some((item) => item.path.endsWith("/chat") && item.status >= 200 && item.status < 300), no_interception: true };
    result.checks.unexpected_runtime_errors = { console: result.unexpected_console_errors.length, request_failures: result.unexpected_request_failures.length, passed: result.unexpected_console_errors.length === 0 && result.unexpected_request_failures.length === 0 };
    await context.close();
    return result;
  } catch (error) {
    result.error = safeError(error);
    result.api_responses = apiResponses;
    result.console_errors = consoleErrors;
    result.request_failures = requestFailures;
    await context.close().catch(() => {});
    throw Object.assign(new Error(result.error), { viewportResult: result });
  }
}

async function main() {
  const report = { schema_version: "rick-frontend-browser-evidence.v1", real_runtime: true, fixture_interception: false, runtime_mode: process.env.RICK_FRONTEND_RUNTIME_MODE || "unknown", web_url: new URL(webBase).origin, api_url: new URL(apiBase).origin, viewports: [], checks: {}, screenshots: [], limitations: ["This is a local/API-backed browser observation; it is not a production or independent visual approval."] };
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: browserExecutable });
    for (let index = 0; index < viewports.length; index += 1) {
      try {
        const item = await runViewport(browser, viewports[index], index);
        report.viewports.push(item);
      } catch (error) {
        if (error.viewportResult) report.viewports.push(error.viewportResult);
        throw error;
      }
    }
    report.screenshots = report.viewports.flatMap((item) => item.screenshots || []);
    const all = report.viewports;
    const axe = all.flatMap((item) => Object.entries(item.checks).filter(([key]) => key.startsWith("axe_")).map(([, value]) => value));
    const contrast = all.flatMap((item) => Object.entries(item.checks).filter(([key]) => key.startsWith("contrast_")).map(([, value]) => value));
    report.checks = {
      browser_api_backed_states: all.every((item) => item.states && item.states.authenticated && item.states.chat),
      viewport_matrix: all.length === 3 && all.every((item, index) => item.viewport.width === viewports[index].width && item.checks.viewport && item.checks.viewport.matches),
      keyboard: all.every((item) => item.checks.focus && item.checks.focus.first_tab_is_skip_link && (!item.checks.focus.mobile_menu || (item.checks.focus.mobile_menu.opened && item.checks.focus.mobile_menu.close_focused && item.checks.focus.mobile_menu.closed && item.checks.focus.mobile_menu.focus_restored))),
      focus: all.every((item) => item.checks.focus && item.checks.focus.skip_link_focus_ring.visible),
      axe: axe.every((item) => item.violations && item.violations.length === 0 && item.incomplete && item.incomplete.length === 0),
      reduced_motion: all.every((item) => item.checks.reduced_motion && item.checks.reduced_motion.preference && item.checks.reduced_motion.animations.every((animation) => animation.playState !== "running" || animation.duration <= 1)),
      contrast: contrast.every((item) => item.failures && item.failures.length === 0 && item.unknown && item.unknown.length === 0),
      touch: all.filter((item) => item.viewport.width <= 375).every((item) => item.checks.touch && item.checks.touch.touch_points > 0 && item.checks.touch.below_minimum.length === 0),
      no_console_or_request_failures: all.every((item) => item.checks.unexpected_runtime_errors && item.checks.unexpected_runtime_errors.passed),
    };
    report.status = Object.values(report.checks).every(Boolean) ? "PASS" : "FAIL";
    report.runtime_claim = report.status === "PASS" && report.real_runtime && report.fixture_interception === false;
  } catch (error) {
    report.status = "FAIL";
    report.runtime_claim = false;
    report.error = safeError(error);
    if (error && error.code === "ENOENT") report.status = "BLOCKED_EXTERNAL";
  } finally {
    if (browser) await browser.close().catch(() => {});
    fs.mkdirSync(path.dirname(evidencePath), { recursive: true });
    fs.writeFileSync(evidencePath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  }
  process.exitCode = report.status === "PASS" ? 0 : report.status === "BLOCKED_EXTERNAL" ? 2 : 1;
}

main().catch((error) => { process.exitCode = 1; console.error(safeError(error)); });
'''


def _browser_status_from_report(report: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    raw_status = report.get("status")
    if raw_status == "PASS" and report.get("runtime_claim") is True and report.get("fixture_interception") is False:
        return "PASS", "real browser/API-backed probe passed", dict(report)
    if raw_status in {"BLOCKED_EXTERNAL", "NOT_RUN"}:
        return "BLOCKED_EXTERNAL", "browser probe was unavailable; no runtime claim is made", dict(report)
    return "FAIL", "real browser/API-backed probe observed a failure", dict(report)


def _blocked_browser_checks(detail: str, *, evidence: Sequence[str] = ()) -> list[dict[str, Any]]:
    return [
        _check(name, "NOT_RUN", detail, evidence=evidence, tool="unavailable")
        for name in (
            "browser-api-backed-states",
            "viewport-matrix",
            "keyboard",
            "focus",
            "axe",
            "reduced-motion",
            "contrast",
            "touch",
        )
    ]


def _browser_checks_from_report(root: Path, report: Mapping[str, Any], report_path: Path) -> list[dict[str, Any]]:
    evidence = [_relative(root, report_path)]
    status, detail, _ = _browser_status_from_report(report)
    checks = report.get("checks") if isinstance(report.get("checks"), Mapping) else {}
    names = {
        "browser_api_backed_states": "browser-api-backed-states",
        "viewport_matrix": "viewport-matrix",
        "keyboard": "keyboard",
        "focus": "focus",
        "axe": "axe",
        "reduced_motion": "reduced-motion",
        "contrast": "contrast",
        "touch": "touch",
    }
    result = []
    for key, name in names.items():
        value = checks.get(key)
        if status == "BLOCKED_EXTERNAL":
            item_status = "NOT_RUN"
        else:
            item_status = "PASS" if value is True else "FAIL" if value is False else "NOT_RUN"
        result.append(_check(name, item_status, detail, evidence=evidence, tool="Playwright/axe", observations={"value": value}))
    if status == "FAIL":
        result.insert(
            0,
            _check(
                "browser-runtime-probe",
                "FAIL",
                detail,
                evidence=evidence,
                tool="Playwright/axe",
                observations={"report_status": report.get("status"), "error": report.get("error")},
            ),
        )
    return result


def _run_browser_probe(
    root: Path,
    *,
    web_url: str | None,
    api_url: str | None,
    browser_executable: str | None,
    managed_runtime: bool,
    production_runtime: bool,
    timeout: float,
    evidence_dir: Path,
) -> tuple[list[dict[str, Any]], bool, dict[str, Any]]:
    node = _tool("node")
    module = _find_playwright_module(root)
    axe = _find_axe(root)
    if not node or module is None or axe is None:
        missing = [name for name, value in (("node", node), ("Playwright", module), ("axe-core", axe)) if not value]
        detail = f"required browser tool(s) unavailable: {', '.join(missing)}"
        return _blocked_browser_checks(detail), False, {"status": "BLOCKED_EXTERNAL", "runtime_claim": False, "missing_tools": missing}
    browser = _find_browser(node, module, browser_executable)
    if browser is None:
        detail = "no executable browser or installed Playwright browser was available"
        return _blocked_browser_checks(detail), False, {"status": "BLOCKED_EXTERNAL", "runtime_claim": False, "missing_tools": ["browser"]}

    managed: _ManagedRuntime | None = None
    runtime_url = web_url
    runtime_api = api_url
    try:
        if runtime_url is None:
            if not managed_runtime:
                detail = "no web runtime URL was supplied and managed runtime was disabled"
                return _blocked_browser_checks(detail), False, {"status": "BLOCKED_EXTERNAL", "runtime_claim": False}
            try:
                managed = _ManagedRuntime(root, timeout=timeout, production=production_runtime).__enter__()
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                detail = f"managed web/API runtime unavailable ({type(exc).__name__})"
                return _blocked_browser_checks(detail), False, {"status": "BLOCKED_EXTERNAL", "runtime_claim": False, "detail": detail}
            runtime_url, runtime_api = managed.web_url, managed.api_url
        else:
            runtime_url = _validate_url(runtime_url, field="web-url")
            if runtime_api is None:
                runtime_api = runtime_url
            runtime_api = _validate_url(runtime_api, field="api-url")
            ok_web, web_status, web_detail = _http_observation(f"{runtime_url}/login")
            ok_api, api_status, api_detail = _http_observation(f"{runtime_api}/health/live")
            if not ok_web or web_status is None or not 200 <= web_status < 300 or not ok_api or api_status is None or not 200 <= api_status < 300:
                detail = f"approved external web/API runtime unavailable ({web_detail}; {api_detail})"
                return _blocked_browser_checks(detail), False, {"status": "BLOCKED_EXTERNAL", "runtime_claim": False, "web_status": web_status, "api_status": api_status}

        if runtime_url is None or runtime_api is None:
            return _blocked_browser_checks("web/API runtime URL resolution failed"), False, {"status": "BLOCKED_EXTERNAL", "runtime_claim": False}
        email = os.getenv("RICK_FRONTEND_LOGIN_EMAIL", "").strip()
        password = os.getenv("RICK_FRONTEND_LOGIN_PASSWORD", "")
        if not email or not password:
            if managed is not None:
                # These are the repository's explicit test-mode identity inputs,
                # sent only to the local API and never persisted in evidence.
                email, password = "km@example.com", "password123"
            else:
                return _blocked_browser_checks("external browser run requires injected login credentials"), False, {"status": "BLOCKED_EXTERNAL", "runtime_claim": False}
        evidence_dir.mkdir(parents=True, exist_ok=True)
        report_path = evidence_dir / "browser-evidence.json"
        screenshot_dir = evidence_dir / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rick-phase3-browser-probe-") as temp_dir:
            probe_path = Path(temp_dir) / "probe.cjs"
            probe_path.write_text(_BROWSER_PROBE, encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "RICK_FRONTEND_PLAYWRIGHT_MODULE": str(module),
                    "RICK_FRONTEND_AXE_PATH": str(axe),
                    "RICK_FRONTEND_BROWSER_EXECUTABLE": browser,
                    "RICK_FRONTEND_WEB_URL": runtime_url,
                    "RICK_FRONTEND_API_URL": runtime_api,
                    "RICK_FRONTEND_EVIDENCE": str(report_path),
                    "RICK_FRONTEND_SCREENSHOT_DIR": str(screenshot_dir),
                    "RICK_FRONTEND_LOGIN_EMAIL": email,
                    "RICK_FRONTEND_LOGIN_PASSWORD": password,
                    "RICK_FRONTEND_LOGIN_TENANT": os.getenv("RICK_FRONTEND_LOGIN_TENANT", "default"),
                    "RICK_FRONTEND_VIEWPORTS": json.dumps(VIEWPORTS),
                    "RICK_FRONTEND_RUNTIME_MODE": "approved-external" if managed is None else ("managed-production" if production_runtime else "managed-dev"),
                }
            )
            try:
                process = _run_command([node, str(probe_path)], cwd=root, env=env, timeout=max(30.0, timeout * 3))
            except subprocess.TimeoutExpired:
                return _blocked_browser_checks("browser probe timed out before producing complete evidence", evidence=[_relative(root, report_path)]), False, {"status": "BLOCKED_EXTERNAL", "runtime_claim": False}
            if not report_path.is_file():
                detail = "browser probe did not emit its evidence artifact"
                if process.stderr:
                    detail += f" ({_redact_text(process.stderr[-500:])})"
                status = "BLOCKED_EXTERNAL" if process.returncode == EXIT_BLOCKED else "FAIL"
                return _blocked_browser_checks(detail), False, {"status": status, "runtime_claim": False}
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                return _blocked_browser_checks(f"browser evidence artifact is malformed ({type(exc).__name__})", evidence=[_relative(root, report_path)]), False, {"status": "FAIL", "runtime_claim": False}
            if not isinstance(report, dict):
                return _blocked_browser_checks("browser evidence artifact is not an object", evidence=[_relative(root, report_path)]), False, {"status": "FAIL", "runtime_claim": False}
            checks = _browser_checks_from_report(root, report, report_path)
            runtime_claim = report.get("runtime_claim") is True and report.get("real_runtime") is True and report.get("fixture_interception") is False and all(item.get("status") == "PASS" for item in checks)
            return checks, runtime_claim, report
    finally:
        if managed is not None:
            managed.__exit__(None, None, None)


def audit_frontend_sources(root: Path) -> dict[str, Any]:
    package_path = root / "apps/web/package.json"
    config_path = root / "apps/web/playwright.config.ts"
    workflow_path = root / ".github/workflows/quality.yml"
    missing = [str(path.relative_to(root)) for path in (package_path, config_path, workflow_path) if not path.is_file()]
    fixture_files: list[str] = []
    for path in sorted((root / "apps/web/tests").glob("*.spec.ts")) if (root / "apps/web/tests").is_dir() else []:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "page.route(" in source or "route.fulfill(" in source:
            fixture_files.append(str(path.relative_to(root)))
    values: dict[str, Any] = {"required_files_present": not missing, "missing": missing, "fixture_test_files_excluded_from_runtime": fixture_files}
    if missing:
        return _check("frontend-source-audit", "FAIL", "canonical web package/config/workflow files are missing", evidence=[], observations=values)
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        config = config_path.read_text(encoding="utf-8")
        workflow = workflow_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _check("frontend-source-audit", "FAIL", f"frontend source audit could not parse inputs ({type(exc).__name__})", evidence=[], observations=values)
    required_scripts = {"build", "lint", "typecheck", "test:e2e"}
    configured_viewports = {
        str(width): f"{width}x{height}"
        for width, height in ((375, 812), (768, 1024), (1440, 1000))
        if re.search(rf"width:\s*{width}\s*,\s*height:\s*{height}", config)
    }
    values.update(
        {
            "required_scripts": sorted(required_scripts),
            "missing_scripts": sorted(required_scripts - set(scripts)),
            "configured_viewports": configured_viewports,
            "workflow_has_frontend_runtime": "frontend-runtime:" in workflow,
            "workflow_runtime_command": "make web-e2e" in workflow,
            "workflow_runtime_event_scope": "github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'" in workflow,
            "runtime_fixture_files_not_used": True,
        }
    )
    if values["missing_scripts"] or len(values["configured_viewports"]) != 3 or not values["workflow_has_frontend_runtime"]:
        return _check("frontend-source-audit", "FAIL", "frontend source contract is incomplete", evidence=[_relative(root, package_path), _relative(root, config_path), _relative(root, workflow_path)], observations=values)
    detail = "canonical frontend config and workflow were audited; fixture-intercepting visual tests are explicitly excluded from runtime evidence"
    if values["workflow_runtime_event_scope"]:
        detail += "; existing workflow runs the browser job only on manual/scheduled events"
    return _check("frontend-source-audit", "PASS", detail, evidence=[_relative(root, package_path), _relative(root, config_path), _relative(root, workflow_path)], observations=values)


def _node_components(root: Path) -> list[tuple[str, Path, Path, dict[str, Any]]]:
    components: list[tuple[str, Path, Path, dict[str, Any]]] = []
    for relative in NODE_COMPONENTS:
        directory = root / relative
        package_path = directory / "package.json"
        lock_path = directory / "package-lock.json"
        if not package_path.is_file():
            continue
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            package = {}
        components.append((relative, package_path, lock_path, package if isinstance(package, dict) else {}))
    return components


def _missing_node_components(root: Path) -> list[str]:
    return [
        relative
        for relative in NODE_COMPONENTS
        if not (root / relative / "package.json").is_file()
    ]


def check_lockfiles(root: Path, *, npm: str | None = None, timeout: float = 90.0) -> dict[str, Any]:
    components = _node_components(root)
    missing_packages = _missing_node_components(root)
    if not components:
        return _check("lockfiles", "FAIL", "no canonical Node component with package.json was found")
    missing: list[str] = list(missing_packages)
    mismatches: list[str] = []
    malformed: list[str] = []
    static_components: list[str] = []
    for relative, _package_path, lock_path, package in components:
        if not lock_path.is_file():
            missing.append(relative)
            continue
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            malformed.append(relative)
            continue
        if not isinstance(lock, dict) or not isinstance(lock.get("packages"), dict) or lock.get("lockfileVersion", 0) < 2:
            malformed.append(relative)
            continue
        root_lock = lock["packages"].get("", {})
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            if package.get(section, {}) != root_lock.get(section, {}):
                mismatches.append(f"{relative}:{section}")
        static_components.append(relative)
    if missing or malformed or mismatches:
        return _check("lockfiles", "FAIL", "package manifests and lockfiles are missing, malformed or out of sync", evidence=[f"{item}/package-lock.json" for item in static_components], observations={"missing": missing, "malformed": malformed, "manifest_mismatches": mismatches})
    if npm is None:
        return _check("lockfiles", "NOT_RUN", "npm is unavailable; structural lockfile checks passed but npm ci verification did not run", evidence=[f"{item}/package-lock.json" for item in static_components], tool="npm", observations={"components": static_components})
    failures: list[str] = []
    blocked: list[str] = []
    commands: dict[str, Any] = {}
    for relative, _package_path, _lock_path, _package in components:
        result = _run_command([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--dry-run"], cwd=root / relative, timeout=timeout)
        output = _command_tail(result)
        commands[relative] = {"exit_status": result.returncode, "output_tail": output}
        if result.returncode == 0:
            continue
        if _NETWORK_FAILURE.search(output):
            blocked.append(relative)
        else:
            failures.append(relative)
    if failures:
        return _check("lockfiles", "FAIL", "npm ci dry-run rejected one or more lockfiles", evidence=[f"{item}/package-lock.json" for item in static_components], tool="npm", observations={"components": static_components, "failed_components": failures, "commands": commands})
    if blocked:
        return _check("lockfiles", "BLOCKED_EXTERNAL", "npm ci dry-run could not complete because registry/network access was unavailable", evidence=[f"{item}/package-lock.json" for item in static_components], tool="npm", observations={"components": static_components, "blocked_components": blocked, "commands": commands})
    return _check("lockfiles", "PASS", "all canonical Node lockfiles passed structural and npm ci dry-run verification", evidence=[f"{item}/package-lock.json" for item in static_components], tool="npm", observations={"components": static_components, "commands": commands})


def _parse_sbom(value: str) -> tuple[bool, int, str]:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False, 0, "SBOM output was not valid JSON"
    if not isinstance(payload, dict):
        return False, 0, "SBOM output was not an object"
    components = payload.get("components")
    if payload.get("bomFormat") != "CycloneDX" or not isinstance(components, list) or not components:
        return False, len(components) if isinstance(components, list) else 0, "SBOM is missing CycloneDX components"
    return True, len(components), "CycloneDX SBOM contains components"


def check_sbom(root: Path, evidence_dir: Path, *, npm: str | None = None, syft: str | None = None, timeout: float = 120.0) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    components = _node_components(root)
    missing_packages = _missing_node_components(root)
    if not components:
        return _check("sbom", "FAIL", "no canonical Node component with package.json was found")
    if missing_packages:
        return _check("sbom", "FAIL", "one or more canonical Node components are missing package manifests", observations={"missing_components": missing_packages})
    reports: list[str] = []
    failures: list[str] = []
    blocked: list[str] = []
    counts: dict[str, int] = {}
    if npm:
        for relative, _package_path, lock_path, _package in components:
            if not lock_path.is_file():
                failures.append(relative)
                continue
            result = _run_command([npm, "sbom", "--sbom-format", "cyclonedx", "--sbom-type", "application"], cwd=root / relative, timeout=timeout)
            ok, count, detail = _parse_sbom(result.stdout)
            report_path = evidence_dir / f"sbom-{relative.replace('/', '-')}.json"
            if result.returncode == 0 and ok:
                _write_json(report_path, json.loads(result.stdout))
                reports.append(_relative(root, report_path))
                counts[relative] = count
            elif result.returncode != 0 and _NETWORK_FAILURE.search(_command_tail(result)):
                blocked.append(relative)
            else:
                failures.append(relative)
    elif syft:
        result = _run_command([syft, f"dir:{root}", "--output", "cyclonedx-json"], cwd=root, timeout=timeout)
        ok, count, _detail = _parse_sbom(result.stdout)
        report_path = evidence_dir / "sbom-repository.json"
        if result.returncode == 0 and ok:
            _write_json(report_path, json.loads(result.stdout))
            reports.append(_relative(root, report_path))
            counts["repository"] = count
        elif result.returncode != 0 and _NETWORK_FAILURE.search(_command_tail(result)):
            blocked.append("repository")
        else:
            failures.append("repository")
    else:
        return _check("sbom", "NOT_RUN", "no supported SBOM tool (npm sbom/syft) is available", tool="unavailable", observations={"tool_candidates": ["npm sbom", "syft"]})
    if failures:
        return _check("sbom", "FAIL", "an available SBOM tool failed or emitted an invalid inventory", evidence=reports, tool="npm sbom" if npm else "syft", observations={"failed_components": failures, "reports": reports, "component_counts": counts})
    if blocked:
        return _check("sbom", "BLOCKED_EXTERNAL", "SBOM generation could not complete because the selected tool needs unavailable external package data", evidence=reports, tool="npm sbom" if npm else "syft", observations={"blocked_components": blocked, "reports": reports, "component_counts": counts})
    return _check("sbom", "PASS", "available SBOM tooling produced a non-empty CycloneDX inventory", evidence=reports, tool="npm sbom" if npm else "syft", observations={"reports": reports, "component_counts": counts})


def _secret_scan_files(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in _git_files(root):
        if path.name in {".env", ".env.local", ".env.development", ".env.production"} or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz", ".sqlite", ".db", ".pyc"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            for kind, pattern in _HIGH_SIGNAL_SECRETS:
                if pattern.search(line):
                    findings.append({"path": _relative(root, path), "line": line_number, "kind": kind})
    return findings


def check_secrets(root: Path, evidence_dir: Path, *, python: str | None = None, gitleaks: str | None = None, timeout: float = 120.0) -> dict[str, Any]:
    if gitleaks:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        report_path = evidence_dir / "gitleaks.json"
        result = _run_command([gitleaks, "detect", "--source", str(root), "--no-banner", "--redact", "--report-format", "json", "--report-path", str(report_path)], cwd=root, timeout=timeout)
        if result.returncode == 0:
            return _check("secret-scan", "PASS", "gitleaks found no secret candidates", evidence=[_relative(root, report_path)], tool="gitleaks")
        if result.returncode == 1:
            return _check("secret-scan", "FAIL", "gitleaks found one or more secret candidates", evidence=[_relative(root, report_path)], tool="gitleaks")
        return _check("secret-scan", "FAIL", "gitleaks failed without a trustworthy clean result", evidence=[], tool="gitleaks", observations={"output_tail": _command_tail(result)})
    scanner = root / "cvg-master-rag-v2/src/scripts/scan_secrets.py"
    if python and scanner.is_file() and root.resolve() == ROOT.resolve():
        result = _run_command([python, str(scanner)], cwd=root, timeout=timeout)
        if result.returncode == 0:
            return _check("secret-scan", "PASS", "repository dependency-free high-signal secret scanner passed", evidence=[_relative(root, scanner)], tool="repository-secret-scanner")
        return _check("secret-scan", "FAIL", "repository dependency-free secret scanner found candidates", evidence=[_relative(root, scanner)], tool="repository-secret-scanner", observations={"output_tail": _command_tail(result)})
    findings = _secret_scan_files(root)
    if findings:
        return _check("secret-scan", "FAIL", "dependency-free high-signal secret scan found candidates", evidence=[], tool="built-in-static-scanner", observations={"finding_count": len(findings), "findings": findings[:24]})
    return _check("secret-scan", "PASS", "dependency-free high-signal secret scan found no candidates", evidence=[], tool="built-in-static-scanner", observations={"files_scanned": len(_git_files(root))})


_ALLOWED_LICENSE = re.compile(
    r"^(?:MIT|ISC|Apache-2\.0|BSD(?:-[0-9]+-Clause|-Clause)?|0BSD|Zlib|MPL-2\.0|LGPL-(?:2\.0|2\.1|3\.0)(?:-or-later)?|GPL-(?:2\.0|3\.0)(?:-or-later)?|CC0-1\.0|CC-BY-4\.0|Unlicense|Python-2\.0|BlueOak-1\.0\.0|WTFPL)$",
    re.IGNORECASE,
)


def _license_ok(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    tokens = re.split(r"\s+(?:OR|AND)\s+|\s*\|\s*", value.strip(), flags=re.IGNORECASE)
    return all(bool(_ALLOWED_LICENSE.fullmatch(token.strip())) for token in tokens if token.strip())


def check_licenses(root: Path) -> dict[str, Any]:
    components = _node_components(root)
    missing_packages = _missing_node_components(root)
    if not components:
        return _check("licenses", "FAIL", "no canonical Node component with package.json was found")
    missing: list[str] = []
    unknown: list[str] = []
    denied: list[dict[str, str]] = []
    package_count = 0
    for relative, _package_path, lock_path, _package in components:
        if not lock_path.is_file():
            missing.append(relative)
            continue
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            unknown.append(f"{relative}:malformed")
            continue
        packages = lock.get("packages", {}) if isinstance(lock, dict) else {}
        if not isinstance(packages, dict):
            unknown.append(f"{relative}:packages")
            continue
        for package_path, metadata in packages.items():
            if not package_path or not isinstance(metadata, dict) or metadata.get("link"):
                continue
            if "name" not in metadata and package_path.startswith("node_modules/"):
                metadata = {**metadata, "name": package_path.split("node_modules/")[-1]}
            if not metadata.get("name"):
                continue
            package_count += 1
            license_value = metadata.get("license")
            if license_value is None:
                unknown.append(f"{relative}:{metadata.get('name', package_path)}")
            elif not _license_ok(license_value):
                denied.append({"component": relative, "package": str(metadata.get("name", package_path)), "license": str(license_value)})
    if missing_packages:
        missing.extend(missing_packages)
    if missing or unknown or denied:
        return _check("licenses", "FAIL", "dependency licenses are not fully known or fall outside the local allowlist", evidence=[f"{item}/package-lock.json" for item, *_ in components if (root / item / "package-lock.json").is_file()], observations={"package_count": package_count, "missing_lockfiles": missing, "unknown": unknown[:24], "denied": denied[:24]})
    return _check("licenses", "PASS", "all locked Node dependencies have an allowlisted SPDX license", evidence=[f"{item}/package-lock.json" for item, *_ in components], tool="package-lock parser", observations={"package_count": package_count, "allowlist": "local SPDX-compatible policy"})


def _manifest_digest_state(root: Path) -> tuple[str, dict[str, Any]]:
    path = root / "infrastructure/docker/release-manifest.json"
    if not path.is_file():
        return "FAIL", {"detail": "release manifest is missing"}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "FAIL", {"detail": "release manifest is malformed"}
    if not isinstance(manifest, dict):
        return "FAIL", {"detail": "release manifest is not an object"}
    status = manifest.get("status")
    images = manifest.get("images", [])
    if status in {"CANDIDATE", "READY_FOR_REVIEW"}:
        bad: list[str] = []
        services: set[str] = set()
        for image in images if isinstance(images, list) else []:
            if not isinstance(image, dict):
                bad.append("non-object image")
                continue
            service = str(image.get("service", "unknown"))
            services.add(service)
            if not isinstance(image.get("digest"), str) or not _DIGEST.fullmatch(image["digest"]):
                bad.append(f"{service}:digest")
            if not isinstance(image.get("image_ref"), str) or not _DIGEST_REF.fullmatch(image["image_ref"]):
                bad.append(f"{service}:image_ref")
            elif isinstance(image.get("digest"), str) and not image["image_ref"].endswith(image["digest"]):
                bad.append(f"{service}:digest_mismatch")
        if len(images) != 3:
            bad.append("candidate must contain exactly three image records")
        if len(services) != len(images):
            bad.append("candidate contains duplicate service records")
        if services != {"api", "worker", "web"}:
            bad.append("candidate must capture api, worker and web exactly")
        return ("FAIL" if bad else "PASS"), {"manifest_status": status, "bad": bad, "captured_image_count": len(images) if isinstance(images, list) else 0}
    if status == "PREPARED_NOT_RUN":
        return "NOT_RUN", {"manifest_status": status, "detail": "release packet is prepared but no image digest has been captured"}
    return "FAIL", {"manifest_status": status, "detail": "unsupported release manifest status"}


def check_container_digests(root: Path, *, python: str | None = None, docker: str | None = None, timeout: float = 90.0) -> dict[str, Any]:
    status, observations = _manifest_digest_state(root)
    policy = root / "infrastructure/docker/check_release.py"
    policy_result: dict[str, Any] = {}
    if python and policy.is_file():
        result = _run_command([python, str(policy), "--mode", "prepared"], cwd=root, timeout=timeout)
        policy_result = {"exit_status": result.returncode, "output_tail": _command_tail(result)}
        if result.returncode != 0 and status != "FAIL":
            status = "FAIL"
    refs = {name: os.getenv(name, "").strip() for name in ("RICK_API_IMAGE", "RICK_WORKER_IMAGE", "RICK_WEB_IMAGE")}
    configured = {name: value for name, value in refs.items() if value}
    if configured:
        missing_configured = sorted(set(refs) - set(configured))
        if missing_configured:
            return _check("container-digests", "FAIL", "container image configuration is incomplete; all reviewed services require immutable references", evidence=[_relative(root, policy)] if policy.is_file() else [], observations={**observations, "missing_configured_refs": missing_configured, "policy": policy_result})
        invalid = [name for name, value in configured.items() if not _DIGEST_REF.fullmatch(value)]
        if invalid:
            return _check("container-digests", "FAIL", "configured container image references are mutable or malformed", evidence=[_relative(root, policy)] if policy.is_file() else [], observations={**observations, "invalid_configured_refs": invalid, "policy": policy_result})
        if docker is None:
            return _check("container-digests", "BLOCKED_EXTERNAL", "immutable image references were supplied but Docker is unavailable for digest inspection", evidence=[_relative(root, policy)] if policy.is_file() else [], tool="docker", observations={**observations, "configured_services": sorted(configured), "policy": policy_result})
        missing: list[str] = []
        for name, value in configured.items():
            result = _run_command([docker, "image", "inspect", value], cwd=root, timeout=timeout)
            if result.returncode != 0:
                missing.append(name)
        if missing:
            return _check("container-digests", "BLOCKED_EXTERNAL", "configured immutable images could not be inspected in the available Docker runtime", evidence=[_relative(root, policy)] if policy.is_file() else [], tool="docker", observations={**observations, "uninspectable_services": missing, "policy": policy_result})
        status = "PASS" if status != "FAIL" else status
        observations.update({"configured_services": sorted(configured), "docker_inspection": "PASS", "policy": policy_result})
    if status == "PASS":
        return _check("container-digests", "PASS", "all captured container references are immutable SHA-256 references", evidence=[_relative(root, policy)] if policy.is_file() else [], tool="release-manifest/check_release.py", observations=observations)
    if status == "NOT_RUN":
        return _check("container-digests", "NOT_RUN", "container release policy is structurally valid, but no candidate image digest was captured", evidence=[_relative(root, policy)] if policy.is_file() else [], tool="release-manifest/check_release.py", observations=observations)
    return _check("container-digests", "FAIL", str(observations.get("detail", "container digest policy failed")), evidence=[_relative(root, policy)] if policy.is_file() else [], tool="release-manifest/check_release.py", observations=observations)


def check_container_sbom(root: Path, evidence_dir: Path, *, trivy: str | None = None, syft: str | None = None, docker: str | None = None, timeout: float = 180.0) -> dict[str, Any]:
    refs = {name: os.getenv(name, "").strip() for name in ("RICK_API_IMAGE", "RICK_WORKER_IMAGE", "RICK_WEB_IMAGE")}
    configured = {name: value for name, value in refs.items() if value}
    tool = trivy or syft
    if not configured:
        return _check("container-sbom", "NOT_RUN", "no reviewed container image references were supplied; source SBOM is not an image SBOM", tool=tool or "unavailable")
    missing_configured = sorted(set(refs) - set(configured))
    if missing_configured:
        return _check("container-sbom", "FAIL", "container image configuration is incomplete; image SBOM coverage cannot be established", observations={"missing_configured_refs": missing_configured})
    invalid = [name for name, value in configured.items() if not _DIGEST_REF.fullmatch(value)]
    if invalid:
        return _check("container-sbom", "FAIL", "container SBOM requires immutable SHA-256 image references", observations={"invalid_configured_refs": invalid})
    if tool is None:
        return _check("container-sbom", "NOT_RUN", "no supported container SBOM tool (trivy/syft) is available", tool="unavailable", observations={"configured_services": sorted(configured)})
    if docker is None:
        return _check("container-sbom", "BLOCKED_EXTERNAL", "container SBOM requires an inspectable Docker/image runtime", tool=tool, observations={"configured_services": sorted(configured)})
    docker_probe = _run_command([docker, "info", "--format", "{{.ServerVersion}}"], cwd=root, timeout=min(timeout, 30.0))
    if docker_probe.returncode != 0:
        return _check("container-sbom", "BLOCKED_EXTERNAL", "Docker daemon is unavailable; image SBOM execution did not run", tool="docker", observations={"docker_output": _command_tail(docker_probe)})
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reports: list[str] = []
    failures: list[str] = []
    blocked: list[str] = []
    for name, image in configured.items():
        if trivy:
            command = [trivy, "image", "--quiet", "--format", "cyclonedx", image]
        else:
            command = [syft, image, "--output", "cyclonedx-json"]
        result = _run_command(command, cwd=root, timeout=timeout)
        ok, count, _detail = _parse_sbom(result.stdout)
        if result.returncode != 0 or not ok:
            if _NETWORK_FAILURE.search(_command_tail(result)) or re.search(r"cannot connect|docker daemon|no such image", _command_tail(result), re.IGNORECASE):
                blocked.append(name)
            else:
                failures.append(name)
            continue
        path = evidence_dir / f"container-sbom-{name.removeprefix('RICK_').removesuffix('_IMAGE').lower()}.json"
        _write_json(path, json.loads(result.stdout))
        reports.append(_relative(root, path))
    if failures:
        return _check("container-sbom", "FAIL", "container SBOM tool failed or emitted an invalid inventory", evidence=reports, tool="trivy" if trivy else "syft", observations={"failed_services": failures, "reports": reports})
    if blocked:
        return _check("container-sbom", "BLOCKED_EXTERNAL", "container SBOM could not complete because image/runtime access was unavailable", evidence=reports, tool="trivy" if trivy else "syft", observations={"blocked_services": blocked, "reports": reports})
    return _check("container-sbom", "PASS", "container SBOM was generated from each supplied immutable image", evidence=reports, tool="trivy" if trivy else "syft", observations={"reports": reports, "services": sorted(configured)})


def run_gate(
    root: Path = ROOT,
    *,
    output: str | Path = ".runtime/phase-3/frontend-supply-runtime-gate.json",
    web_url: str | None = None,
    api_url: str | None = None,
    browser_executable: str | None = None,
    managed_runtime: bool = True,
    production_runtime: bool = False,
    require_production: bool = False,
    timeout: float = 30.0,
) -> dict[str, Any]:
    root = root.resolve()
    output_path = _safe_path(root, output)
    evidence_dir = root / ".runtime/phase-3/frontend-supply"
    started_at = time.time()
    checks: list[dict[str, Any]] = []
    browser_claim = False
    browser_report: dict[str, Any] = {}
    try:
        checks.append(audit_frontend_sources(root))
        checks_result, browser_claim, browser_report = _run_browser_probe(
            root,
            web_url=web_url,
            api_url=api_url,
            browser_executable=browser_executable,
            managed_runtime=managed_runtime,
            production_runtime=production_runtime or require_production,
            timeout=timeout,
            evidence_dir=evidence_dir,
        )
        checks.extend(checks_result)
        npm = _tool("npm")
        checks.append(check_lockfiles(root, npm=npm))
        checks.append(check_sbom(root, evidence_dir, npm=npm, syft=_tool("syft")))
        checks.append(check_secrets(root, evidence_dir, python=sys.executable, gitleaks=_tool("gitleaks")))
        checks.append(check_licenses(root))
        checks.append(check_container_digests(root, python=sys.executable, docker=_tool("docker")))
        checks.append(check_container_sbom(root, evidence_dir, trivy=_tool("trivy"), syft=_tool("syft"), docker=_tool("docker")))
    except (OSError, ValueError, TypeError) as exc:
        checks.append(_check("gate-controller", "FAIL", f"gate controller failed ({type(exc).__name__})"))
        browser_claim = False
        browser_report = {"status": "FAIL", "runtime_claim": False}
    failures = [item for item in checks if item.get("status") == "FAIL"]
    blocked = [item for item in checks if item.get("status") in {"BLOCKED_EXTERNAL", "NOT_RUN", "WARN"}]
    if failures:
        status = "FAIL"
    elif blocked:
        status = "BLOCKED_EXTERNAL"
    else:
        status = "PASS"
    production_safe = (
        status == "PASS"
        and browser_claim
        and production_runtime
        and all(item.get("status") == "PASS" for item in checks)
    )
    if require_production and not production_safe:
        status = "BLOCKED_EXTERNAL" if not failures else "FAIL"
    payload: dict[str, Any] = {
        "schema_version": "phase11-frontend-supply-runtime-gate.v1",
        "status": status,
        "runtime_claim": browser_claim,
        "production_safe": production_safe,
        "environment": "approved-external" if web_url else "local-managed-api-backed-test",
        "observed_at": time.time(),
        "duration_seconds": round(time.time() - started_at, 3),
        "viewports": list(VIEWPORTS),
        "checks": checks,
        "browser_evidence": redact(browser_report),
        "limitations": [
            "Fixture-intercepting visual tests were not used as runtime evidence.",
            "Local managed API-backed test mode is not production evidence; production_safe requires an explicit production runtime and complete immutable image evidence.",
            "Missing browser, runtime, scanner or image evidence remains BLOCKED_EXTERNAL/NOT_RUN.",
        ],
        "next_action": "Provide the missing approved runtime/tools and rerun on the same clean candidate." if status != "PASS" else "Submit the current evidence to an independent review; this automated gate is not approval.",
    }
    _write_json(output_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", default=".runtime/phase-3/frontend-supply-runtime-gate.json")
    parser.add_argument("--web-url", default=os.getenv("RICK_FRONTEND_WEB_URL"))
    parser.add_argument("--api-url", default=os.getenv("RICK_FRONTEND_API_URL"))
    parser.add_argument("--browser-executable", default=None)
    parser.add_argument("--no-managed-runtime", action="store_true")
    parser.add_argument("--production-runtime", action="store_true")
    parser.add_argument("--require-production", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    root = (args.root or ROOT).resolve()
    try:
        payload = run_gate(
            root,
            output=args.output,
            web_url=args.web_url,
            api_url=args.api_url,
            browser_executable=args.browser_executable,
            managed_runtime=not args.no_managed_runtime,
            production_runtime=args.production_runtime,
            require_production=args.require_production,
            timeout=max(5.0, args.timeout_seconds),
        )
    except (OSError, ValueError, TypeError) as exc:
        fallback = {"schema_version": "phase11-frontend-supply-runtime-gate.v1", "status": "FAIL", "runtime_claim": False, "production_safe": False, "error": f"gate controller failed ({type(exc).__name__})"}
        try:
            _write_json(_safe_path(root, args.output), fallback)
        except (OSError, ValueError):
            pass
        print(json.dumps(redact(fallback), sort_keys=True))
        return EXIT_FAIL
    print(json.dumps({"output": str(args.output), "status": payload["status"], "runtime_claim": payload["runtime_claim"], "production_safe": payload["production_safe"]}, sort_keys=True))
    return EXIT_PASS if payload["status"] == "PASS" else EXIT_BLOCKED if payload["status"] == "BLOCKED_EXTERNAL" else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
