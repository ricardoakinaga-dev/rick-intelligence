"""Protected disposable installer checkout; never chmod the shared sources."""
from pathlib import Path
import sys
import os
import pytest
sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
import assets

@pytest.fixture(autouse=True)
def protected_checkout(tmp_path, monkeypatch, protected_test_umask):
    installed = tmp_path/'protected-installer'
    for name in assets.REPOSITORY_ASSETS:
        p = installed/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((assets.ROOT/name).read_bytes()); p.chmod(0o600)
    monkeypatch.setattr(assets, 'ROOT', installed)
    return installed


@pytest.fixture(autouse=True)
def simulated_installer_for_unit_boundaries(monkeypatch):
    """Nonprivileged tests model the installer seam; no cross-UID DAC claim.

    Root/DAC validation uses the separate real root test and does not apply
    this substitute. Public production installer_owner remains strict.
    """
    if os.geteuid() != 0:
        monkeypatch.setattr(assets,'installer_owner',lambda op,tls:os.geteuid())


@pytest.fixture
def protected_test_umask():
    old = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(old)
