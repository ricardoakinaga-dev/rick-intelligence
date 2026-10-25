#!/usr/bin/env python3
"""Build local digest-addressed API/worker/web images and image SBOMs.

Uses only a loopback registry and cached base/scanner images. It never pushes
to an external registry or edits the canonical release manifest. Context bytes,
registry manifests, exported images and CycloneDX inventories are hash-bound.
Vulnerability/signature/production trust approval remains separate.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase11.frontend_supply_runtime_gate import _free_port, _parse_sbom
from scripts.phase11.owned_docker_creation import run_creation


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def context_member(path):
    prefixes = ("apps/api/src/", "apps/worker/", "packages/", "apps/web/app/", "apps/web/components/",
                "apps/web/lib/", "apps/web/types/", "infrastructure/docker/", "infrastructure/migrations/")
    exact = {".dockerignore", "requirements/runtime.lock", "apps/api/pyproject.toml", "infrastructure/scripts/migrate.py",
        "infrastructure/compose/bootstrap_qdrant.py", "apps/web/package.json", "apps/web/package-lock.json",
        "apps/web/middleware.ts", "apps/web/next-env.d.ts", "apps/web/next.config.mjs",
        "apps/web/tsconfig.json", "apps/web/eslint.config.mjs"}
    parts = Path(path).parts
    if any(part.startswith(".env") or part in {"__pycache__", "node_modules"} for part in parts):
        return False
    if path.startswith("packages/") and "/src/" not in path:
        return False
    if path.startswith("apps/worker/") and ("/" in path.removeprefix("apps/worker/") or not path.endswith(".py")):
        return False
    return path in exact or path.startswith(prefixes)


class Supply:
    def __init__(self, run_id):
        self.run_id = run_id
        self.output = ROOT / ".runtime/phase-3/supply-local" / run_id
        self.output.mkdir(parents=True)
        self.logs = self.output / "logs"
        self.logs.mkdir()
        self.registry = "rick-supply-" + run_id
        self.started = False
        self.refs = {}

    def command(self, argv, *, name, timeout=600, creation=False):
        target = self.logs / (name + ".log")
        with target.open("w") as log:
            execute = run_creation if creation else subprocess.run
            options = {} if creation else {"check": False}
            result = execute(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, timeout=timeout, **options)
        if result.returncode:
            raise RuntimeError(name + "_failed")
        return target

    def inspect(self, ref):
        result = subprocess.run(["docker", "image", "inspect", ref], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=15, check=True)
        return json.loads(result.stdout)[0]

    def snapshot(self):
        context = self.output / "context"
        context.mkdir()
        result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                cwd=ROOT, stdout=subprocess.PIPE, check=True)
        files = sorted(set(result.stdout.decode().strip("\0").split("\0")))
        manifest = []
        for name in files:
            if not context_member(name):
                continue
            source = ROOT / name
            if source.is_symlink() or not source.resolve().is_relative_to(ROOT) or not source.is_file():
                raise ValueError("unsafe_build_context_member")
            # A live managed Next instance temporarily rewrites these two
            # shared files. Refuse that input rather than silently snapshotting
            # an ephemeral development build into the candidate container.
            if name in {"apps/web/next-env.d.ts", "apps/web/tsconfig.json"} and b".next-phase3-" in source.read_bytes():
                raise ValueError("managed_web_build_still_active")
            target = context / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            manifest.append({"path": name, "sha256": digest(target)})
        encoded = json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        (self.output / "context-manifest.json").write_text(encoded)
        self.context_hash = hashlib.sha256(encoded.encode()).hexdigest()
        return context

    def start_registry(self):
        registry_image = self.inspect("registry:2")["Id"]
        self.scanner = self.inspect("aquasec/trivy:0.74.0")["Id"]
        self.port = _free_port()
        self.origin = f"127.0.0.1:{self.port}"
        store = self.output / "registry-data"
        store.mkdir()
        # Docker can create the resource even when its CLI times out. Retain
        # cleanup authority from the attempt, then verify ownership on removal.
        self.started = True
        self.command(["docker", "run", "-d", "--name", self.registry, "--label", "rick.phase3.owned-run=" + self.run_id,
            "--publish", f"127.0.0.1:{self.port}:5000", "--memory", "256m", "--cpus", "1", "--log-driver", "none",
            "--mount", f"type=bind,src={store},dst=/var/lib/registry", registry_image], name="registry-start", timeout=30, creation=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://{self.origin}/v2/", timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(.2)
        raise RuntimeError("owned_registry_not_ready")

    def push_local(self, source, name):
        # All tags/destinations are generated here. There is no remote registry
        # input and no credential/helper configuration is read by this script.
        tag = f"{self.origin}/{name}:{self.run_id}"
        self.command(["docker", "tag", source, tag], name="tag-" + name)
        self.command(["docker", "push", tag], name="push-" + name)
        from urllib.request import Request
        request = Request(f"http://{self.origin}/v2/{name}/manifests/{self.run_id}", headers={"Accept":
            "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json"})
        with urlopen(request, timeout=10) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            expected = response.headers.get("Docker-Content-Digest")
        actual = "sha256:" + hashlib.sha256(raw).hexdigest()
        if len(raw) > 4 * 1024 * 1024 or expected != actual:
            raise ValueError("registry_manifest_digest_mismatch")
        (self.output / (name + "-registry-manifest.json")).write_bytes(raw)
        immutable = f"{self.origin}/{name}@{actual}"
        # Containerd can retain a cached multiplatform index on the source
        # tag while push emits only its available platform manifest. Pull the
        # digest verified from our registry bytes, rather than confusing the
        # index/config/image ID with the actual published manifest digest.
        self.command(["docker", "pull", immutable], name="pin-local-" + name)
        if immutable not in self.inspect(immutable).get("RepoDigests", []):
            raise ValueError("daemon_registry_digest_mismatch")
        return immutable

    def build(self, context):
        python = self.push_local(self.inspect("rick-python:3.12.15")["Id"], "base-python")
        node = self.push_local(self.inspect("node:22.23.2-alpine3.24")["Id"], "base-node")
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        self.base_refs = {"PYTHON_IMAGE": python, "NODE_BUILD_IMAGE": node, "NODE_RUNTIME_IMAGE": node}
        for service in ("api", "worker", "web"):
            tag = f"{self.origin}/rick-{service}:{self.run_id}"
            arguments = {"PYTHON_IMAGE": python} if service != "web" else {"NODE_BUILD_IMAGE": node, "NODE_RUNTIME_IMAGE": node}
            args = ["docker", "build", "--progress=plain", "--pull=false", "--tag", tag,
                "--file", str(context / f"infrastructure/docker/{service}.Dockerfile"),
                "--label", "org.opencontainers.image.revision=" + head,
                "--label", "rick.source.context.sha256=" + self.context_hash]
            for key, value in arguments.items():
                args.extend(("--build-arg", key + "=" + value))
            args.append(str(context))
            self.command(args, name="build-" + service, timeout=900)
            ref = self.push_local(tag, "rick-" + service)
            self.refs[service] = ref
            image = self.output / (service + ".docker.tar")
            self.command(["docker", "save", "--output", str(image), ref], name="export-" + service, timeout=180)
            sbom = self.output / (service + "-sbom.json")
            args = ["docker", "run", "--rm", "--network", "none", "--memory", "1g", "--cpus", "2",
                "--mount", f"type=bind,src={self.output},dst=/evidence,readonly", self.scanner,
                "image", "--quiet", "--skip-db-update", "--skip-java-db-update", "--offline-scan",
                "--format", "cyclonedx", "--input", f"/evidence/{service}.docker.tar"]
            log = self.command(args, name="sbom-" + service, timeout=300)
            ok, count, _detail = _parse_sbom(log.read_text())
            if not ok or count <= 0:
                raise ValueError("nonempty_image_sbom_required")
            sbom.write_bytes(log.read_bytes())
            yield {"service": service, "image_ref": ref, "image_id": self.inspect(ref)["Id"],
                "dockerfile": f"infrastructure/docker/{service}.Dockerfile", "context_manifest_sha256": self.context_hash,
                "sbom": {"path": str(sbom.relative_to(ROOT)), "sha256": digest(sbom), "components": count},
                "image_archive": {"path": str(image.relative_to(ROOT)), "sha256": digest(image)}}

    def close(self):
        if not self.started:
            return
        existing = subprocess.run(["docker", "ps", "-a", "--filter", "name=^/" + self.registry + "$",
            "--format", "{{.ID}}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=15, check=True, text=True)
        if not existing.stdout.strip():
            self.started = False
            return
        value = json.loads(subprocess.check_output(["docker", "inspect", self.registry], text=True))[0]
        if value["Config"]["Labels"].get("rick.phase3.owned-run") != self.run_id:
            raise ValueError("refusing_nonowned_registry_cleanup")
        self.command(["docker", "rm", "-f", self.registry], name="registry-stop", timeout=30)
        self.started = False


def main():
    if os.environ.get("RICK_FORMAL_LAB_AUTHORIZED") != "1":
        raise SystemExit("explicit_formal_lab_authority_required")
    supply = Supply(uuid.uuid4().hex[:16])
    images, reason, status = [], None, "FAIL"
    try:
        context = supply.snapshot()
        supply.start_registry()
        for row in supply.build(context):
            images.append(row)
            (supply.output / "progress.json").write_text(json.dumps(images, sort_keys=True, indent=2) + "\n")
        if len(images) == 3:
            status = "PASS"
    except Exception as error:
        reason = str(error) if type(error) in {RuntimeError, ValueError} else type(error).__name__
    finally:
        try:
            supply.close()
        except Exception:
            status, reason = "FAIL", "owned_registry_cleanup_failed"
    payload = {"schema_version": "phase3-local-image-supply.v1", "run_id": supply.run_id,
        "status": status, "production_safe": False, "images": images, "reason": reason,
        "context_manifest_sha256": getattr(supply, "context_hash", None), "base_refs": getattr(supply, "base_refs", {}),
        "limitations": ["Loopback registry and retained local registry data; no external push, release manifest update or deployment.",
            "Image inventory is not a vulnerability scan, signature, independent review or production trust approval.",
            "Source context is explicitly hashed; a dirty checkout is not commit-bound release evidence."]}
    refs = [supply.output / "context-manifest.json"]
    for row in images:
        refs += [ROOT / row["sbom"]["path"], ROOT / row["image_archive"]["path"]]
    refs += list(supply.output.glob("*-registry-manifest.json"))
    payload["raw_artifacts"] = [{"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
        for path in refs if path.is_file()]
    encoded = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    (supply.output / "observation.json").write_text(encoded)
    (supply.output.parent / "current.json").write_text(encoded)
    print(json.dumps({"status": status, "images": len(images), "run_id": supply.run_id, "production_safe": False}))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
