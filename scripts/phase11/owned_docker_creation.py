"""Settle an owned Docker creation request before reporting its deadline.

Killing the CLI does not cancel daemon-side creation. After a readiness deadline
we keep the request alive until the CLI acknowledges completion, then report
the original deadline failure so the owner can remove the settled resource.
A stuck daemon therefore leaves the operation pending, never cleanup PASS.
This helper is for explicitly authorized lab tooling, not an ASGI request path.
"""
from __future__ import annotations

import subprocess


def run_creation(argv, *, timeout, **kwargs):
    process = subprocess.Popen(argv, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Do not kill a client while its daemon-side side effect is unsettled.
        # The caller must retain ownership until this terminal acknowledgement.
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr) from None
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
