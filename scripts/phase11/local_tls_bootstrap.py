#!/usr/bin/env python3
"""Proposed lab PKI and real Redis TLS/auth proof; never production approval."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import ssl
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.phase13.pyenv import source_paths
for path in reversed(source_paths()):
    sys.path.insert(0, str(path))
from scripts.phase11.local_lab_environment import _inspect
from scripts.state_of_art.runtime_preflight import canonical_compose_project
from scripts.phase11 import redis_runtime_gate as gate

LABEL = "rick.phase3.owned-run"
DOCKER_HOST = "unix:///var/run/docker.sock"


def checked_container(name, run_id):
    result = subprocess.run(["docker", "--host", DOCKER_HOST, "inspect", name], capture_output=True, timeout=20, text=True, check=True)
    value = json.loads(result.stdout)[0]
    if value["Config"].get("Labels", {}).get(LABEL) != run_id:
        raise ValueError("refusing_nonowned_tls_container")
    return value


class TLSLab:
    def __init__(self):
        if os.environ.get("RICK_FORMAL_LAB_AUTHORIZED") != "1":
            raise ValueError("explicit_formal_lab_authority_required")
        self.run_id = uuid.uuid4().hex[:16]
        self.output = ROOT / ".runtime/phase-3/production-inputs" / self.run_id
        self.secret = self.output / "secret-store"
        self.trust = self.output / "trust-store"
        self.output.mkdir(parents=True, mode=0o700)
        self.secret.mkdir(mode=0o700)
        self.trust.mkdir(mode=0o700)
        self.name = "rick-tls-redis-" + self.run_id
        self.created = False

    def command(self, args, timeout=60):
        if args[0] == "docker":
            args = ["docker", "--host", DOCKER_HOST, *args[1:]]
        result = subprocess.run(args, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError("owned_tls_command_failed")
        return result.stdout

    def start(self):
        previous = os.umask(0o077)
        try:
            self.password = secrets.token_urlsafe(32)
            (self.secret / "redis.password").write_text(self.password)
            for name in ("ca", "rogue-ca"):
                self.command(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "2",
                    "-subj", "/CN=RICK LAB ONLY " + name, "-keyout", str(self.secret / (name + ".key")),
                    "-out", str(self.trust / (name + ".crt"))])
            for name, usage in (("server", "serverAuth"), ("client", "clientAuth")):
                csr = self.output / (name + ".csr")
                extensions = self.output / (name + ".ext")
                extensions.write_text("basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
                    + "extendedKeyUsage=" + usage + "\n"
                    + ("subjectAltName=DNS:localhost,DNS:redis,IP:127.0.0.1\n" if name == "server" else ""))
                self.command(["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-sha256", "-subj", "/CN=rick-lab-" + name,
                    "-keyout", str(self.secret / (name + ".key")), "-out", str(csr)])
                self.command(["openssl", "x509", "-req", "-in", str(csr), "-CA", str(self.trust / "ca.crt"),
                    "-CAkey", str(self.secret / "ca.key"), "-CAcreateserial", "-days", "2", "-sha256",
                    "-extfile", str(extensions), "-out", str(self.trust / (name + ".crt"))])
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                self.port = listener.getsockname()[1]
            config = self.secret / "redis.conf"
            config.write_text(f'bind 127.0.0.1\nport 0\ntls-port {self.port}\n'
                'tls-cert-file /tls/server.crt\ntls-key-file /tls/server.key\ntls-ca-cert-file /tls/ca.crt\n'
                'tls-auth-clients yes\nsave ""\nappendonly no\n'
                + 'requirepass "' + self.password + '"\n')
        finally:
            os.umask(previous)
        project = canonical_compose_project(ROOT, "docker-compose.dev.yml")
        self.image = _inspect(project + "-redis-1")["Image"]
        args = ["docker", "run", "-d", "--name", self.name, "--label", LABEL + "=" + self.run_id,
            "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "256m", "--cpus", "1", "--log-driver", "none"]
        for path, target in ((config, "redis.conf"), (self.trust / "server.crt", "server.crt"),
            (self.secret / "server.key", "server.key"), (self.trust / "ca.crt", "ca.crt")):
            args += ["--mount", f"type=bind,src={path},dst=/tls/{target},readonly"]
        args += ["--entrypoint", "redis-server", self.image, "/tls/redis.conf"]
        self.created = True
        self.command(args)
        checked_container(self.name, self.run_id)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if self.ping():
                    return
            except Exception:
                pass
            time.sleep(.1)
        raise RuntimeError("owned_tls_redis_not_ready")

    def ping(self, *, password=None, certificate=True, plaintext=False):
        import redis
        options = dict(host="127.0.0.1", port=self.port, username="default",
            password=self.password if password is None else password, socket_connect_timeout=1, socket_timeout=1)
        if not plaintext:
            options.update(ssl=True, ssl_ca_certs=str(self.trust / "ca.crt"), ssl_check_hostname=True, ssl_cert_reqs="required")
            if certificate:
                options.update(ssl_certfile=str(self.trust / "client.crt"), ssl_keyfile=str(self.secret / "client.key"))
        with redis.Redis(**options) as client:
            return client.ping()

    def handshake(self, *, ca="ca", hostname="localhost"):
        context = ssl.create_default_context(cafile=str(self.trust / (ca + ".crt")))
        context.load_cert_chain(str(self.trust / "client.crt"), str(self.secret / "client.key"))
        with socket.create_connection(("127.0.0.1", self.port), timeout=1) as connection:
            with context.wrap_socket(connection, server_hostname=hostname) as secured:
                return secured.version()

    def close(self):
        if not self.created:
            return
        listing = self.command(["docker", "ps", "-a", "--filter", "name=^/" + self.name + "$", "--format", "{{.ID}}"])
        if listing.strip():
            value = checked_container(self.name, self.run_id)
            if value["State"].get("Paused"):
                self.command(["docker", "unpause", self.name])
            self.command(["docker", "rm", "-f", self.name])
        self.created = False


async def run():
    import redis
    owner = TLSLab()
    result = {"schema_version": "rick-proposed-tls-observation.v1", "run_id": owner.run_id,
              "status": "FAIL", "production_safe": False, "profile_review": "PENDING", "scope": "owned Redis lab only"}
    result["observed_at"] = datetime.now(timezone.utc).isoformat()
    result["source"] = {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "worktree": "DIRTY" if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT) else "CLEAN",
        "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "scripts/phase11/local_tls_bootstrap.py", "scripts/phase11/redis_runtime_gate.py",
            "scripts/phase11/redis_fault_harness.py", "packages/locking/src/rick_locking/redis_config.py")},
    }
    variables = ("RICK_REDIS_TLS_CA_FILE", "RICK_REDIS_TLS_CERT_FILE", "RICK_REDIS_TLS_KEY_FILE",
        "RICK_REDIS_CONTAINER", "RICK_TLS_LAB_RUN_ID", "RICK_REDIS_DOCKER_HOST", "RICK_REDIS_FAULT_HARNESS")
    previous_environment = {key: os.environ.get(key) for key in variables}
    checks = []
    try:
        await asyncio.to_thread(owner.start)
        version = owner.handshake()
        checks.append({"name": "tls-and-client-certificate", "passed": version in {"TLSv1.2", "TLSv1.3"}, "tls_version": version})
        for name, operation, expected in (
            ("wrong-ca-rejected", lambda: owner.handshake(ca="rogue-ca"), ssl.SSLCertVerificationError),
            ("wrong-hostname-rejected", lambda: owner.handshake(hostname="wrong.invalid"), ssl.SSLCertVerificationError),
            ("missing-client-certificate-rejected", lambda: owner.ping(certificate=False), redis.exceptions.ConnectionError),
            ("wrong-password-rejected", lambda: owner.ping(password="invalid-" + owner.run_id), redis.exceptions.AuthenticationError),
            ("plaintext-rejected", lambda: owner.ping(plaintext=True), (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)),
        ):
            try:
                operation()
            except expected:
                passed = True
            else:
                passed = False
            checks.append({"name": name, "passed": passed})
        os.environ.update(RICK_REDIS_TLS_CA_FILE=str(owner.trust / "ca.crt"),
            RICK_REDIS_TLS_CERT_FILE=str(owner.trust / "client.crt"), RICK_REDIS_TLS_KEY_FILE=str(owner.secret / "client.key"),
            RICK_REDIS_CONTAINER=owner.name, RICK_TLS_LAB_RUN_ID=owner.run_id,
            RICK_REDIS_DOCKER_HOST=DOCKER_HOST,
            RICK_REDIS_FAULT_HARNESS=shlex.join([sys.executable, str(Path(__file__)), "--fault-only"]))
        status, native, capability = await gate._run_checks(
            f"rediss://default:{owner.password}@127.0.0.1:{owner.port}/0", require_tls=True, allow_nonlocal=False)
        checks.append({"name": "native-redis-tls-lease-rate-reconnect-circuit", "passed": status == "PASS" and capability is True})
        result.update(native_gate_status=status, native_results=[row.to_dict() for row in native],
            native_transport_capability=capability, checks=checks, status="PASS" if all(c["passed"] for c in checks) else "FAIL")
    except Exception as error:
        result.update(reason=type(error).__name__, checks=checks)
    finally:
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            await asyncio.to_thread(owner.close)
            result["cleanup_status"] = "PASS"
        except Exception:
            result.update(status="FAIL", cleanup_status="FAIL")
    references = {"redis_password": owner.secret / "redis.password", "client_key": owner.secret / "client.key",
        "client_certificate": owner.trust / "client.crt", "server_key": owner.secret / "server.key", "ca": owner.trust / "ca.crt"}
    result["references"] = {name: {"path": str(path.relative_to(ROOT)), "mode": oct(stat.S_IMODE(path.stat().st_mode))}
        for name, path in references.items() if path.exists()}
    result["limitations"] = ["Locally generated two-day CA and synthetic credentials; not an approved production secret/trust store.",
        "Native TLS capability is a Redis transport fact, not product production_safe, domain evaluation, independent review or GO.",
        "PostgreSQL/object/Qdrant/edge production TLS and deployed identity policy still require their own approved profile and evidence."]
    raw = owner.output / "observation.json"
    raw.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    current = owner.output.parent / "tls-current.json"
    current.write_bytes(raw.read_bytes())
    return result


async def fault_only():
    from scripts.phase11.redis_fault_harness import _exercise
    if os.environ.get("RICK_FORMAL_LAB_AUTHORIZED") != "1":
        return False
    checked_container(os.environ["RICK_REDIS_CONTAINER"], os.environ["RICK_TLS_LAB_RUN_ID"])
    return await _exercise()


if __name__ == "__main__":
    if sys.argv[1:] == ["--fault-only"]:
        try:
            passed = asyncio.run(fault_only())
        except Exception:
            passed = False
        print(json.dumps({"circuit-breaker-recovery": "PASS" if passed else "FAIL"}))
        raise SystemExit(0 if passed else 1)
    result = asyncio.run(run())
    print(json.dumps({key: result[key] for key in ("status", "production_safe", "run_id", "cleanup_status")}))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
