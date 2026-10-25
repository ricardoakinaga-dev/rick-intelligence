"""Empty, owned PostgreSQL for bounded local load; no shared database DDL."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import time

from scripts.phase11.local_lab_environment import _inspect
from scripts.state_of_art.runtime_preflight import canonical_compose_project

ROOT = Path(__file__).resolve().parents[2]
LABEL = "rick.phase3.owned-run"


class OwnedPostgres:
    def __init__(self, run_id):
        if os.environ.get("RICK_FORMAL_LAB_AUTHORIZED") != "1":
            raise ValueError("explicit_formal_lab_authority_required")
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", run_id):
            raise ValueError("invalid_owned_postgres_run_id")
        self.run_id = run_id
        self.name = "rick-lab-pg-" + run_id
        self.network = self.name + "-net"
        self.created = self.network_created = False

    def docker(self, *args, env=None):
        result = subprocess.run(["docker", *args], env=env, capture_output=True, timeout=40, check=False, text=True)
        if result.returncode:
            raise RuntimeError("owned_postgres_container_failed")
        return result.stdout.strip()

    def checked(self, *, network=False):
        value = json.loads(self.docker(*(["network", "inspect", self.network] if network else ["inspect", self.name])))[0]
        labels = value.get("Labels", {}) if network else value.get("Config", {}).get("Labels", {})
        if labels.get(LABEL) != self.run_id:
            raise ValueError("refusing_nonowned_postgres")
        return value

    def start(self):
        import psycopg
        from infrastructure.scripts.migrate import apply
        project = canonical_compose_project(ROOT, "docker-compose.dev.yml")
        image = _inspect(f"{project}-postgres-1")["Image"]
        password = secrets.token_urlsafe(32)
        self.docker("network", "create", "--internal", "--label", LABEL + "=" + self.run_id, self.network)
        self.network_created = True
        # Env values are inherited by name, never interpolated into argv/logs.
        env = {**os.environ, "POSTGRES_USER": "rick_lab", "POSTGRES_DB": "rick_lab", "POSTGRES_PASSWORD": password}
        self.created = True  # Retain authority even if launch times out.
        self.docker("run", "-d", "--name", self.name, "--network", self.network,
            "--label", LABEL + "=" + self.run_id, "--memory", "2g", "--cpus", "2", "--log-driver", "none",
            "--env", "POSTGRES_USER", "--env", "POSTGRES_DB", "--env", "POSTGRES_PASSWORD",
            image, "-c", "max_connections=300", "-c", "shared_buffers=128MB", env=env)
        address = self.checked()["NetworkSettings"]["Networks"][self.network]["IPAddress"]
        dsn = f"postgresql://rick_lab:{password}@{address}:5432/rick_lab?connect_timeout=5"
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(dsn) as connection:
                    connection.execute("SELECT 1")
                break
            except psycopg.OperationalError:
                time.sleep(.2)
        else:
            raise RuntimeError("owned_postgres_readiness_timeout")
        self.checked()  # Authority must still match before migration DDL.
        if apply(ROOT / "infrastructure/migrations", dsn) != 0:
            raise RuntimeError("owned_postgres_migrations_failed")
        self.profile = {"owned": True, "empty_database_migrated": True, "image_id": image,
                        "max_connections": 300, "memory_limit_bytes": 2 * 1024**3, "cpu_limit": 2}
        return dsn

    def close(self):
        if self.created:
            existing = self.docker("ps", "-a", "--filter", "name=^/" + self.name + "$", "--format", "{{.ID}}")
            if existing:
                self.checked()
                self.docker("rm", "-f", "-v", self.name)
            self.created = False
        if self.network_created:
            self.checked(network=True)
            self.docker("network", "rm", self.network)
            self.network_created = False
