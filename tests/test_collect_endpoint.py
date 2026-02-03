import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure project root is on sys.path so pytest can import application packages
project_root = str(Path(__file__).resolve().parents[1])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import api.main as main


def test_trigger_collectors_endpoint(monkeypatch):
    """Ensure the collector trigger endpoint returns started flag (mocked)."""
    # Prevent actually starting collectors in test by mocking
    monkeypatch.setattr(main, "run_collectors_once", lambda: True)

    client = TestClient(main.app)
    resp = client.post("/api/jobs/collect")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("started") is True
