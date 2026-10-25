#!/usr/bin/env python3
"""Native local web/API/worker state matrix with owned dependency faults.

No interception or fulfillment is installed in the browser. Faults affect
only the owned fixture provider, worker and synthetic membership. Xvfb is an
owned display used for actual Chromium zoom accelerators. This is not release
approval, image provenance or independent accessibility review.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from threading import Thread
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase11.local_operational_harness import NativeLab
from scripts.phase11 import frontend_supply_runtime_gate as gate
from scripts.phase11.owned_lab_network import StreamingHTTPProxy


def verified_web_image(reference):
    """Bind a cached web image to the successful local build and its bytes."""
    from scripts.phase11.local_supply_chain import digest
    from scripts.state_of_art.prepare_phase3_handoff import safe_file
    if not isinstance(reference, str) or not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}/rick-web@sha256:[a-f0-9]{64}", reference):
        raise ValueError("web_image_not_in_local_supply")
    supply = json.loads((ROOT / ".runtime/phase-3/supply-local/current.json").read_text())
    if supply.get("status") != "PASS":
        raise ValueError("local_supply_not_pass")
    rows = [row for row in supply.get("images", []) if row.get("service") == "web" and row.get("image_ref") == reference]
    if len(rows) != 1 or "@sha256:" not in reference:
        raise ValueError("web_image_not_in_local_supply")
    row = rows[0]
    for key in ("sbom", "image_archive"):
        path = safe_file(ROOT, row[key]["path"])
        if digest(path) != row[key]["sha256"]:
            raise ValueError("local_web_artifact_hash_mismatch")
    context = safe_file(ROOT, ".runtime/phase-3/supply-local/" + supply["run_id"] + "/context-manifest.json")
    if digest(context) != supply["context_manifest_sha256"]:
        raise ValueError("web_context_manifest_mismatch")
    entries = json.loads(context.read_text())
    for entry in entries:
        if digest(safe_file(ROOT, entry["path"])) != entry["sha256"]:
            raise ValueError("web_build_context_changed")
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", reference], text=True))[0]
    if reference not in image.get("RepoDigests", []) or image["Config"].get("User") != "10001:10001":
        raise ValueError("web_image_digest_or_runtime_user_mismatch")
    return {"image_ref": reference, "sbom": row["sbom"], "context_manifest_sha256": supply["context_manifest_sha256"]}


def close_owned_web(name, run_id, *, network=False):
    inspect = ["docker", "network", "inspect", name] if network else ["docker", "inspect", name]
    result = subprocess.run(inspect, capture_output=True, text=True, timeout=15)
    if result.returncode:
        if "No such object" in result.stderr or "No such container" in result.stderr or network and "not found" in result.stderr:
            return
        raise RuntimeError("owned_web_inventory_failed")
    value = json.loads(result.stdout)[0]
    labels = value.get("Labels", {}) if network else value["Config"].get("Labels", {})
    if labels.get("rick.phase3.owned-run") != run_id:
        raise ValueError("refusing_nonowned_web_cleanup")
    command = ["docker", "network", "rm", name] if network else ["docker", "rm", "-f", name]
    subprocess.run(command, capture_output=True, check=True, timeout=20)


class Controller:
    def __init__(self, lab, proxy):
        self.lab = lab
        self.proxy = proxy
        self.secret = secrets.token_urlsafe(32)
        self.paused = False
        lab.owner.server.fault_counts = {}

    def command(self, name):
        fixture = self.lab.owner.server
        if name in {"normal", "slow", "unavailable"}:
            if name != "normal":
                fixture.fault_counts[name] = 0
            fixture.fault_mode = name
            if name == "normal":
                self.proxy.truncate_stream = False
        elif name == "stream-interruption":
            fixture.fault_mode = "normal"
            self.proxy.truncate_stream = True
            self.proxy.truncations = 0
        elif name in {"worker-pause", "worker-resume"}:
            if self.lab.worker.poll() is not None:
                raise ValueError("owned_worker_not_running")
            os.killpg(self.lab.worker.pid, signal.SIGSTOP if name == "worker-pause" else signal.SIGCONT)
            self.paused = name == "worker-pause"
        elif name == "retire-browser-uploads":
            # Keep the provider fault scenarios unambiguous. Equal synthetic
            # embeddings for the upload fixtures correctly trigger the real
            # Professor ambiguity policy before generation. Retire only this
            # run's uploads through the actual authorized product endpoint.
            documents = self.lab.graph.knowledge.list_documents(self.lab.scope["workspace_id"],
                tenant_id=self.lab.scope["tenant_id"])
            retired = 0
            for document in documents:
                if document.document_id != self.lab.baseline.document_id:
                    response = self.lab.session.delete("/api/v1/documents/" + document.document_id)
                    if response.status_code != 200:
                        raise ValueError("owned_browser_document_retirement_failed")
                    retired += 1
            fixture.fault_counts["retired_documents"] = retired
        elif name in {"deny", "allow"}:
            import psycopg
            from psycopg.types.json import Jsonb
            with psycopg.connect(self.lab.graph.settings.external_database_dsn, connect_timeout=5) as connection:
                count = connection.execute("UPDATE rick_memberships SET permission_overrides=%s "
                    "WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s",
                    (Jsonb({"add": [], "remove": ["chat.query"] if name == "deny" else []}),
                     self.lab.scope["tenant_id"], self.lab.scope["workspace_id"], self.lab.user)).rowcount
                if count != 1:
                    raise ValueError("owned_membership_not_found")
        else:
            raise ValueError("unknown_owned_fault")
        return {"status": "ok", "counts": {**fixture.fault_counts, "stream-interruption": self.proxy.truncations}}

    def handler(self):
        controller = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/control" or not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + controller.secret):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 4096:
                        raise ValueError("invalid_control_body")
                    payload = json.loads(self.rfile.read(length))
                    result = controller.command(payload.get("command"))
                    body = json.dumps(result).encode()
                except Exception:
                    self.send_error(400)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args):
                pass
        return Handler


async def run():
    run_id = uuid.uuid4().hex[:16]
    output = ROOT / ".runtime/phase-3/frontend-local" / run_id
    output.mkdir(parents=True, exist_ok=True)
    lab = web = controller = control_server = control_thread = display = proxy = None
    web_container = web_network = web_proxy = None
    report = {"status": "FAIL", "production_safe": False, "run_id": run_id}
    try:
        web_port = gate._free_port()
        os.environ["CORS_ALLOWED_ORIGINS"] = f"http://127.0.0.1:{web_port}"
        lab = NativeLab.__new__(NativeLab)
        lab.__init__(run_id, api_replicas=1, workers=1, web_origin=f"http://127.0.0.1:{web_port}")
        health = lab.session.get("/health/ready")
        report["initial_readiness"] = {"status_code": health.status_code, "body": health.json()}
        image_ref = os.environ.get("RICK_FRONTEND_WEB_IMAGE")
        if image_ref:
            report["web_image"] = verified_web_image(image_ref)
            web_network = "rick-frontend-net-" + run_id
            subprocess.run(["docker", "network", "create", "--internal", "--label", "rick.phase3.owned-run=" + run_id,
                web_network], capture_output=True, check=True, timeout=20)
            network = json.loads(subprocess.check_output(["docker", "network", "inspect", web_network], text=True))[0]
            if network["Labels"].get("rick.phase3.owned-run") != run_id:
                raise ValueError("refusing_foreign_web_network")
            gateway = network["IPAM"]["Config"][0]["Gateway"]
            proxy = StreamingHTTPProxy(str(lab.session.base_url), bind_host=gateway, bind_port=8000)
            report["compiled_api_origin"] = "http://api:8000"
        else:
            proxy = StreamingHTTPProxy(str(lab.session.base_url))
        web = gate._ManagedRuntime(ROOT, timeout=90)
        web.api_port = lab.session.base_url.port
        web.web_port = web_port
        web.web_dist_dir = ROOT / "apps/web" / f".next-phase3-{web_port}"
        env = {**os.environ, "RICK_API_INTERNAL_URL": proxy.url,
               "NEXT_TELEMETRY_DISABLED": "1", "NODE_ENV": "development", "NEXT_DIST_DIR": web.web_dist_dir.name}
        env.pop("NEXT_PUBLIC_API_BASE_URL", None)
        command = ["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(web_port)]
        if image_ref:
            web_container = "rick-frontend-web-" + run_id
            command = ["docker", "run", "--name", web_container, "--network", web_network, "--add-host", "api:" + gateway,
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--memory", "1g", "--cpus", "2",
                "--label", "rick.phase3.owned-run=" + run_id, "--env", "RICK_API_INTERNAL_URL", "--entrypoint", "node",
                image_ref, "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
        report["web_runtime"] = "immutable-local-image" if image_ref else "native-next-dev"
        web.web = web._start(command,
                             cwd=ROOT / "apps/web", env=env, log=web.web_log)
        if image_ref:
            # Internal-only Docker bridges do not publish external ports.
            # Expose the owned web container through a loopback-only forwarder.
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = subprocess.run(["docker", "inspect", web_container], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    value = json.loads(result.stdout)[0]
                    if value["Config"]["Labels"].get("rick.phase3.owned-run") != run_id:
                        raise ValueError("refusing_foreign_web_endpoint")
                    address = value["NetworkSettings"]["Networks"].get(web_network, {}).get("IPAddress")
                    if value["State"]["Running"] and address:
                        web_proxy = StreamingHTTPProxy(f"http://{address}:3000", bind_port=web_port)
                        break
                await asyncio.sleep(.1)
            else:
                raise RuntimeError("owned_web_endpoint_not_ready")
        await asyncio.to_thread(web._wait, web.web_url + "/login", web.web, "web")
        controller = Controller(lab, proxy)
        control_server = ThreadingHTTPServer(("127.0.0.1", 0), controller.handler())
        control_thread = Thread(target=control_server.serve_forever, daemon=True)
        control_thread.start()
        # -displayfd lets Xvfb allocate its own display. No shared desktop is
        # selected or modified. Only this process is terminated during cleanup.
        display = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "1920x1200x24", "-nolisten", "tcp"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True, text=True)
        import select
        if not select.select([display.stdout], [], [], 10)[0]:
            raise RuntimeError("owned_display_start_timeout")
        number = display.stdout.readline().strip()
        if not number.isdecimal() or len(number) > 5:
            raise ValueError("owned_display_invalid")
        os.environ.update(DISPLAY=":" + number, RICK_FRONTEND_NATIVE_ZOOM="1",
            RICK_FRONTEND_LOGIN_EMAIL=f"{lab.user}@runtime.invalid", RICK_FRONTEND_LOGIN_PASSWORD=lab.login_password,
            RICK_FRONTEND_LOGIN_TENANT=lab.scope["tenant_id"], RICK_FRONTEND_PROBE_QUERY="como funcionam as citacoes no rick",
            RICK_FRONTEND_LOCAL_CONTROL_URL=f"http://127.0.0.1:{control_server.server_port}/control",
            RICK_FRONTEND_LOCAL_CONTROL_SECRET=controller.secret)
        checks, claim, browser = await asyncio.to_thread(gate._run_browser_probe, ROOT,
            web_url=web.web_url, api_url=str(lab.session.base_url).rstrip("/"), browser_executable=None,
            managed_runtime=False, production_runtime=False, timeout=240, evidence_dir=output, owned_local_runtime=True)
        report.update(status="PASS" if claim and all(row["status"] == "PASS" for row in checks) else "FAIL",
                      checks=checks, browser=browser, provider_fixture=True, runtime_mode="owned-local-product")
    except Exception as error:
        report["reason"] = type(error).__name__
        import traceback
        report["failure_frames"] = [{"file": Path(frame.filename).name, "line": frame.lineno,
                                     "function": frame.name} for frame in traceback.extract_tb(error.__traceback__)]
    finally:
        errors = []
        if controller:
            try:
                if controller.paused:
                    controller.command("worker-resume")
                controller.command("allow")
                controller.command("normal")
            except Exception:
                errors.append("fault_restore")
        if control_server:
            await asyncio.to_thread(control_server.shutdown)
            control_server.server_close()
            control_thread.join(5)
        if display:
            gate._terminate_process(display)
        if web_proxy:
            try:
                await asyncio.to_thread(web_proxy.close)
            except Exception:
                errors.append("web_loopback_proxy_cleanup")
        if web_container:
            try:
                await asyncio.to_thread(close_owned_web, web_container, run_id)
            except Exception:
                errors.append("owned_web_container")
        if web:
            await asyncio.to_thread(web.__exit__, None, None, None)
        if proxy:
            try:
                await asyncio.to_thread(proxy.close)
            except Exception:
                errors.append("stream_proxy_cleanup")
        if web_network:
            try:
                await asyncio.to_thread(close_owned_web, web_network, run_id, network=True)
            except Exception:
                errors.append("owned_web_network")
        if lab and getattr(lab, "owner", None):
            try:
                await lab.owner.close()
            except Exception:
                errors.append("native_graph_cleanup")
        if errors:
            report.update(status="FAIL", cleanup_errors=errors)
        report["cleanup_status"] = "FAIL" if errors else "PASS"
    report["limitations"] = ["Local native graph with an explicit synthetic provider; not model quality or independent visual/AT approval.",
        "Owned provider/worker/membership faults; no browser interception and no shared backend shutdown.",
        "Image mode verifies local web bytes/SBOM references; remote provenance, signatures and production TLS/auth remain unapproved."]
    report["raw_artifacts"] = [{"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(output.rglob("*")) if path.is_file() and path.suffix in {".json", ".png"}
        and path.name != "observation.json"]
    encoded = json.dumps(gate.redact(report), sort_keys=True, indent=2) + "\n"
    (output / "observation.json").write_text(encoded)
    (output.parent / "current.json").write_text(encoded)
    return report


if __name__ == "__main__":
    report = asyncio.run(run())
    print(json.dumps({"status": report["status"], "production_safe": False, "run_id": report["run_id"]}))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
