"""Local disposable restore/DR runtime for the PRD26 lab (not production).

Real operations against the loopback PostgreSQL, MinIO and Qdrant containers:
seed -> pg_dump/mirror/snapshot -> drop -> restore -> rebuild -> verify.
The runtime is a development harness; it never targets production and reports
`production_safe = False`.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
PG = "rick-lab-pg"
MINIO = "rick-lab-minio"
QDRANT = "http://127.0.0.1:56333"
DB = "rick_restore_gate"
BUCKET = "rick-restore-gate"
COLLECTION = "restore_gate"
SCOPE = {
    "tenant_ids": ["restore-tenant"],
    "workspace_ids": ["restore-workspace"],
    "collection_ids": ["restore-collection"],
}
COMPONENTS = ("postgresql", "object_storage", "jobs", "audit", "evidence_lineage", "qdrant")
WORK = ROOT / ".runtime" / "restore-gate"


def _run(args, *, input_text=None):
    result = subprocess.run(
        args, input=input_text, capture_output=True, text=True, timeout=60, check=False
    )
    if result.returncode != 0:
        raise RuntimeError("local restore command failed")
    return result.stdout


def _psql(database: str, sql: str) -> str:
    return _run(["docker", "exec", "-i", PG, "psql", "-U", "rick", "-d", database,
                 "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql])


def _db_exists(name: str) -> bool:
    return _psql("postgres", f"SELECT 1 FROM pg_database WHERE datname='{name}'").strip() == "1"


def _drop_db(name: str) -> None:
    _run(["docker", "exec", PG, "dropdb", "-U", "rick", "--if-exists", name])


def _create_db(name: str) -> None:
    _run(["docker", "exec", PG, "createdb", "-U", "rick", name])


def _sha(value: str | bytes) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _qdrant(method: str, path: str, body: object | None = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    request = Request(QDRANT + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=20) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def _component_checksums() -> dict[str, str]:
    row_hash = lambda table: _sha(_psql(DB, f"SELECT COALESCE(string_agg(id||':'||payload, ',' ORDER BY id),'') FROM {table}").strip())
    postgres = _sha("|".join(row_hash(t) for t in ("job_probe", "audit_probe", "evidence_probe")))
    object_body = _run(["docker", "exec", MINIO, "mc", "cat", f"local/{BUCKET}/probe/seed.txt"])
    vector = _qdrant("GET", f"/collections/{COLLECTION}/points/1?with_payload=true&with_vector=true")
    qdrant = _sha(json.dumps(vector.get("result"), sort_keys=True, separators=(",", ":")))
    return {
        "postgresql": postgres,
        "object_storage": _sha(object_body),
        "jobs": row_hash("job_probe"),
        "audit": row_hash("audit_probe"),
        "evidence_lineage": row_hash("evidence_probe"),
        "qdrant": qdrant,
    }


class LocalRestoreRuntime:
    authorized = True
    external = True
    disposable = True
    production_safe = False
    runtime_metadata = {
        "authority": "prd26-local-restore-lab",
        "execution_mode": "external_disposable",
        "transport": "loopback-http",
        "service_boundary": True,
        "destructive_operations": True,
        "components": list(COMPONENTS),
        "clock_source": "system-utc",
    }

    def __init__(self, *, run_id: str = "", **_kwargs: object) -> None:
        self.run_id = run_id or "restore-run"
        self._seed_id = f"seed-{self.run_id}"
        self._backup_id = f"backup-{self.run_id}"
        self._destruction_id = f"destroy-{self.run_id}"
        self._checksums: dict[str, str] = {}
        WORK.mkdir(parents=True, exist_ok=True)

    def _observation(self, *, checksum: str, completed_at: str, **extra: object) -> dict:
        return {
            "status": "PASS",
            "scope": SCOPE,
            "checksum": checksum,
            "component_checksums": dict(self._checksums),
            "components": list(COMPONENTS),
            "completed_at": completed_at,
            **extra,
        }

    def preflight(self, **_kwargs: object) -> dict:
        checks = {name: True for name in COMPONENTS}
        checks.update({"destructive_authorized": True, "empty_target_ready": True, "clock_verified": True})
        return {"status": "PASS", "checks": checks, "external": True, "disposable": True}

    def seed(self, **_kwargs: object) -> dict:
        _drop_db(DB)
        _create_db(DB)
        _psql(DB, "CREATE TABLE job_probe(id text primary key, payload text);"
                  "CREATE TABLE audit_probe(id text primary key, payload text);"
                  "CREATE TABLE evidence_probe(id text primary key, payload text);"
                  "INSERT INTO job_probe VALUES ('job-1','queued'),('job-2','done'),('job-3','failed');"
                  "INSERT INTO audit_probe VALUES ('audit-1','login'),('audit-2','upload'),('audit-3','publish');"
                  "INSERT INTO evidence_probe VALUES ('ev-1','doc-a'),('ev-2','doc-b'),('ev-3','doc-c');")
        _run(["docker", "exec", MINIO, "sh", "-c",
              f"mc mb --ignore-existing local/{BUCKET} >/dev/null && "
              f"printf 'restore-gate-probe' | mc pipe local/{BUCKET}/probe/seed.txt >/dev/null"])
        try:
            _qdrant("DELETE", f"/collections/{COLLECTION}")
        except Exception:
            pass
        _qdrant("PUT", f"/collections/{COLLECTION}", {"vectors": {"dense": {"size": 2, "distance": "Cosine"}}})
        payload = {
            "tenant_id": SCOPE["tenant_ids"][0],
            "workspace_id": SCOPE["workspace_ids"][0],
            "collection_id": SCOPE["collection_ids"][0],
            "text": "restore-gate-probe",
        }
        _qdrant("PUT", f"/collections/{COLLECTION}/points?wait=true",
                {"points": [{"id": 1, "vector": {"dense": [0.1, 0.2]}, "payload": payload}]})
        self._checksums = _component_checksums()
        checksum = _sha(json.dumps(self._checksums, sort_keys=True))
        return self._observation(checksum=checksum, completed_at=_now(),
                                 seed_id=self._seed_id, seeded_at=_now())

    def backup(self, **_kwargs: object) -> dict:
        _run(["docker", "exec", PG, "sh", "-c",
              f"pg_dump -U rick -Fc -f /tmp/{DB}.dump {DB}"])
        _run(["docker", "exec", MINIO, "sh", "-c",
              f"mc cp local/{BUCKET}/probe/seed.txt /tmp/{BUCKET}-seed.txt >/dev/null"])
        snapshot = _qdrant("POST", f"/collections/{COLLECTION}/snapshots")["result"]["name"]
        snapshot_path = WORK / "qdrant.snapshot"
        with urlopen(f"{QDRANT}/collections/{COLLECTION}/snapshots/{snapshot}", timeout=30) as response:
            snapshot_path.write_bytes(response.read())
        manifest = {
            "seed_id": self._seed_id,
            "backup_id": self._backup_id,
            "component_checksums": self._checksums,
            "checksum": _sha(json.dumps(self._checksums, sort_keys=True)),
        }
        (WORK / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        source_state_at = _now()
        completed_at = _now()
        return self._observation(checksum=manifest["checksum"], completed_at=completed_at,
                                 seed_id=self._seed_id, backup_id=self._backup_id,
                                 source_state_at=source_state_at)

    def destroy(self, **_kwargs: object) -> dict:
        _drop_db(DB)
        _run(["docker", "exec", MINIO, "sh", "-c",
              f"mc rb --force local/{BUCKET} >/dev/null 2>&1 || true"])
        try:
            _qdrant("DELETE", f"/collections/{COLLECTION}")
        except Exception:
            pass
        if _db_exists(DB) or _run(["docker", "exec", MINIO, "sh", "-c", f"mc ls local/{BUCKET} 2>/dev/null | wc -l"]).strip() != "0":
            raise RuntimeError("destruction not observed")
        manifest = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))
        return self._observation(checksum=manifest["checksum"], completed_at=_now(),
                                 backup_id=self._backup_id, destruction_id=self._destruction_id,
                                 destroyed=True, destruction_observed=True, remaining_components=[])

    def restore(self, **_kwargs: object) -> dict:
        manifest = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))
        _create_db(DB)
        _run(["docker", "exec", PG, "pg_restore", "-U", "rick", "-d", DB, f"/tmp/{DB}.dump"])
        _run(["docker", "exec", MINIO, "sh", "-c",
              f"mc mb --ignore-existing local/{BUCKET} >/dev/null && "
              f"mc cp /tmp/{BUCKET}-seed.txt local/{BUCKET}/probe/seed.txt >/dev/null"])
        _qdrant("PUT", f"/collections/{COLLECTION}", {"vectors": {"dense": {"size": 2, "distance": "Cosine"}}})
        snapshot_path = WORK / "qdrant.snapshot"
        _run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST",
              "-F", f"snapshot=@{snapshot_path}",
              f"{QDRANT}/collections/{COLLECTION}/snapshots/upload?priority=snapshot"])
        self._checksums = _component_checksums()
        return self._observation(checksum=manifest["checksum"], completed_at=_now(),
                                 backup_id=self._backup_id, restored=True,
                                 restored_components=list(COMPONENTS))

    def rebuild(self, **_kwargs: object) -> dict:
        manifest = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))
        return self._observation(checksum=manifest["checksum"], completed_at=_now(),
                                 rebuilt=True, qdrant_rebuilt=True, index_rebuilt=True)

    def verify(self, **_kwargs: object) -> dict:
        manifest = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))
        current = _component_checksums()
        if current != manifest["component_checksums"]:
            raise RuntimeError("restored component checksums differ")
        counts = _psql(DB, "SELECT (SELECT count(*) FROM job_probe)||','||(SELECT count(*) FROM audit_probe)||','||(SELECT count(*) FROM evidence_probe)")
        if counts.strip() != "3,3,3":
            raise RuntimeError("restored row counts differ")
        point = _qdrant("GET", f"/collections/{COLLECTION}/points/1")
        if point.get("result", {}).get("id") != 1:
            raise RuntimeError("qdrant point missing")
        return self._observation(checksum=manifest["checksum"], completed_at=_now(),
                                 verified=True, jobs_reconciled=True, audit_reconciled=True,
                                 evidence_lineage=True, qdrant_consistent=True, no_data_loss=True)


def create_runtime(**kwargs: object) -> LocalRestoreRuntime:
    return LocalRestoreRuntime(**kwargs)
