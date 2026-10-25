"""Native tenant/evidence negatives with four bounded background HTTP actors.

Keeps the existing 32-pair timing criteria (5ms delta / 2x ratio). A passing
run is a local observation, never a side-channel certification under arbitrary
production load. All load uses the same owned API and real retrieval store.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import os
from threading import Event, Lock, Thread
import time
import uuid

from scripts.phase11.local_tenant_evidence_runtime import TenantRuntime, ROOT


class ContendedTenantRuntime(TenantRuntime):
    def __init__(self, run_id):
        super().__init__(run_id, isolated_postgres=True)

    async def preflight(self):
        os.environ.update(CHAT_RATE_LIMIT_PER_MIN="100000", SEARCH_TENANT_RATE_LIMIT_PER_MIN="100000")
        result = await super().preflight()
        self.stopped, self.load_lock = Event(), Lock()
        self.load_counts, self.load_threads = Counter(), []
        self.load_started = time.monotonic()
        def actor(index):
            import httpx
            with httpx.Client(base_url=str(self.client_a.base_url), cookies=self.client_a.cookies,
                headers={self.a.settings.csrf_header_name: self.client_a.headers[self.a.settings.csrf_header_name]}, timeout=10) as client:
                while not self.stopped.is_set():
                    try:
                        response = client.get("/api/v1/collections") if index % 2 else client.post(
                            "/api/v1/search", json={"query": "como funcionam as citacoes no rick"})
                        key = f"http_{response.status_code}"
                    except httpx.HTTPError:
                        key = "transport_error"
                    with self.load_lock:
                        self.load_counts[key] += 1
                    self.stopped.wait(.02)
        for index in range(4):
            thread = Thread(target=actor, args=(index,), daemon=True)
            self.load_threads.append(thread)
            thread.start()
        await asyncio.sleep(1)
        return result

    async def run_negative_case(self, *, case, timeout_seconds):
        response = await super().run_negative_case(case=case, timeout_seconds=timeout_seconds)
        if case["case_id"] == "timing-sensitive-identifier":
            with self.load_lock:
                counts = dict(self.load_counts)
            healthy_load = counts.get("http_200", 0) >= 4 and set(counts) == {"http_200"}
            self.observations[-1]["measurement"].update(background_http_results=counts,
                successful_background_load=healthy_load)
            if not healthy_load:
                response.update(blocked=False, allowed=True, timing_leak_free=False)
        return response

    async def cleanup(self):
        if hasattr(self, "stopped"):
            self.stopped.set()
            for thread in self.load_threads:
                await asyncio.to_thread(thread.join, 12)
            self.observations.append({"case_id": "background-contention", "measurement": {
                "actors": 4, "duration_seconds": time.monotonic() - self.load_started,
                "owned_chat_search_limits_per_min": 100000,
                "http_results": dict(self.load_counts), "all_actors_stopped": all(not t.is_alive() for t in self.load_threads)}})
        await super().cleanup()


def create_runtime(run_id=""):
    return ContendedTenantRuntime(run_id or uuid.uuid4().hex)
