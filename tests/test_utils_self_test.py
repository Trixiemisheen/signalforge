import os
import io
import sys
import pytest
import pandas as pd
from pathlib import Path

# Ensure project root is on sys.path for test import
project_root = str(Path(__file__).resolve().parents[1])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import webapp.utils as utils


def test_run_self_test_success(tmp_path, monkeypatch, capsys):
    # Mock dependencies
    monkeypatch.setattr(utils, 'get_stats', lambda: {'total_jobs': 10, 'high_score_jobs': 3, 'alerted_jobs': 1})
    monkeypatch.setattr(utils, 'get_score_distribution', lambda **kwargs: pd.Series([5, 3, 2], index=['0-33','34-66','67-100']))
    monkeypatch.setattr(utils, 'get_trends', lambda **kwargs: {'top_technologies': [('python', 4)], 'trending_keywords': [('ai', 2)]})
    monkeypatch.setattr(utils, 'test_telegram_connection', lambda: True)

    log_file = tmp_path / "self_test.log"
    success = utils.run_self_test(limit=10, log_path=str(log_file))
    captured = capsys.readouterr()

    assert success is True
    assert "Total jobs: 10" in captured.out
    assert log_file.exists()
    content = log_file.read_text()
    assert "Top technologies:" in content or "Trending keywords:" in content


def test_run_self_test_failure(tmp_path, monkeypatch, capsys):
    # Simulate DB failure
    def _bad_stats():
        raise RuntimeError("DB not reachable")

    monkeypatch.setattr(utils, 'get_stats', _bad_stats)
    monkeypatch.setattr(utils, 'get_score_distribution', lambda **kwargs: pd.Series([], dtype=int))
    monkeypatch.setattr(utils, 'get_trends', lambda **kwargs: {})
    monkeypatch.setattr(utils, 'test_telegram_connection', lambda: False)

    log_file = tmp_path / "self_test_fail.log"
    success = utils.run_self_test(limit=5, log_path=str(log_file))
    captured = capsys.readouterr()

    assert success is False
    assert "Failed to fetch stats" in captured.out
    assert log_file.exists()
    content = log_file.read_text()
    assert "[ERROR] Failed to fetch stats" in content
