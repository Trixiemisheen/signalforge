"""Utilities for the web UI (HTML dashboard)

This file provides small helpers used by the UI and tests:
- fetch_jobs wrapper previously used by Streamlit
- run_collectors_once to trigger collectors in background
- send_alert_for_job to send alerts synchronously (used by UI tests)
- get_stats, get_score_distribution, get_trends, run_self_test

Ported back to ensure tests and API imports work.
"""
from typing import List, Optional, Dict, Any
from storage.db import get_db
from storage.models import Job
from alerts.telegram import send_job_alert_sync, TelegramAlerter
import threading
import logging
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def fetch_jobs(limit: int = 50, min_score: int = 0, location: Optional[str] = None, source: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch jobs from the database with simple filtering"""
    db = get_db()
    results = []
    with db.get_session() as session:
        query = session.query(Job)
        if min_score:
            query = query.filter(Job.score >= min_score)
        if location:
            query = query.filter(Job.location.ilike(f"%{location}%"))
        if source:
            query = query.filter(Job.source.ilike(f"%{source}%"))
        query = query.order_by(Job.score.desc()).limit(limit)
        for job in query.all():
            results.append(job.to_dict())
    return results


def run_collectors_once() -> bool:
    """Run collectors in a background thread so the UI stays responsive.

    Returns True if the collectors job was started successfully, False otherwise.
    """
    try:
        from scheduler.tasks import run_collectors

        thread = threading.Thread(target=run_collectors, daemon=True)
        thread.start()
        logger.info("Started collectors in background thread")
        return True
    except Exception as e:
        logger.error(f"Failed to start collectors: {e}")
        return False


def send_alert_for_job(job_id: str) -> bool:
    """Send alert for a job id using the existing Telegram helper. Marks job as alerted on success."""
    db = get_db()
    # Read job
    with db.get_session() as session:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job not found: {job_id}")
            return False
        job_dict = job.to_dict()

    try:
        sent = send_job_alert_sync(job_dict)
        if sent:
            # Mark as alerted in DB
            with db.get_session() as session:
                job = session.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.alerted = 1
            logger.info(f"Marked job {job_id} as alerted")
        return sent

    except Exception as e:
        logger.error(f"Error sending alert: {e}")
        return False


def _run_async(coro):
    """Run coroutine safely even if an event loop is already running by offloading to a thread."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Event loop already running; run in background thread
        result = {}

        def _target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result['value'] = loop.run_until_complete(coro)
            finally:
                loop.close()

        t = threading.Thread(target=_target)
        t.start()
        t.join()
        return result.get('value')


def test_telegram_connection() -> bool:
    """Test Telegram connectivity synchronously"""
    try:
        alerter = TelegramAlerter()
        return _run_async(alerter.test_connection())
    except Exception as e:
        logger.error(f"Telegram test failed: {e}")
        return False


def get_stats() -> Dict[str, int]:
    db = get_db()
    with db.get_session() as session:
        total = session.query(Job).count()
        high = session.query(Job).filter(Job.score >= 70).count()
        alerted = session.query(Job).filter(Job.alerted == 1).count()
    return {
        "total_jobs": total,
        "high_score_jobs": high,
        "alerted_jobs": alerted,
        "alert_threshold": 70,
    }


def get_score_distribution(limit: int = 500, min_score: int = 0, location: Optional[str] = None, source: Optional[str] = None, bins: int = 10):
    """Return score distribution as a pandas Series indexed by bin label."""
    try:
        import pandas as pd
        jobs = fetch_jobs(limit=limit, min_score=min_score, location=location, source=source)
        if not jobs:
            return pd.Series(dtype=int)
        scores = [int(j.get("score", 0) or 0) for j in jobs]
        s = pd.Series(scores)
        hist = pd.cut(s, bins=bins)
        hist_counts = hist.value_counts().sort_index()
        hist_counts.index = [str(interval) for interval in hist_counts.index]
        return hist_counts
    except Exception as e:
        logger.error(f"Error computing score distribution: {e}")
        return None


def get_trends(limit: int = 500, min_score: int = 0):
    """Analyze recent jobs and return top technologies and keywords."""
    try:
        from processors.trends import TrendDetector
        jobs = fetch_jobs(limit=limit, min_score=min_score)

        # Normalize stack to comma-separated string if it's a list (TrendDetector expects comma-separated string)
        normalized_jobs = []
        for j in jobs:
            job_copy = dict(j)
            stack_val = job_copy.get("stack")
            if isinstance(stack_val, list):
                job_copy["stack"] = ",".join(stack_val)
            normalized_jobs.append(job_copy)

        td = TrendDetector()
        analysis = td.analyze_trends(normalized_jobs)
        return analysis
    except Exception as e:
        logger.error(f"Error getting trends: {e}")
        return {}


def run_self_test(limit: int = 50, log_path: Optional[str] = "webapp/self_test.log") -> bool:
    """Run quick smoke tests and print a short report.

    Checks performed:
    - Database access and job count
    - Score distribution sampling
    - Trend analysis (top techs / keywords)
    - Telegram connectivity

    Results are printed and also appended to `log_path` if provided.

    Returns True if self-test completed without critical failures.
    """
    ok = True
    report_lines: list[str] = []

    def _print(line: str = ""):
        print(line)
        report_lines.append(line)

    _print("\n=== SignalForge Webapp Self-Test ===")

    # DB / stats
    try:
        stats = get_stats()
        _print(f"Total jobs: {stats.get('total_jobs')}")
        _print(f"High-score jobs: {stats.get('high_score_jobs')}")
        _print(f"Alerted jobs: {stats.get('alerted_jobs')}")
    except Exception as e:
        _print(f"[ERROR] Failed to fetch stats: {e}")
        ok = False

    # Score distribution
    try:
        dist = get_score_distribution(limit=limit, min_score=0)
        if dist is None or (hasattr(dist, 'empty') and dist.empty):
            _print("Score distribution: No data (run collectors to populate DB)")
        else:
            top_bins = dist.sort_values(ascending=False).head(3)
            _print("Score distribution (top bins):")
            for label, count in top_bins.items():
                _print(f"  {label}: {count}")
    except Exception as e:
        _print(f"[ERROR] Failed to compute score distribution: {e}")
        ok = False

    # Trends
    try:
        trends = get_trends(limit=limit, min_score=0)
        techs = trends.get('top_technologies', [])
        kws = trends.get('trending_keywords', [])

        if techs:
            _print("Top technologies:")
            for t, c in techs[:5]:
                _print(f"  {t}: {c}")
        else:
            _print("Top technologies: No data")

        if kws:
            _print("Trending keywords:")
            for k, c in kws[:5]:
                _print(f"  {k}: {c}")
        else:
            _print("Trending keywords: No data")

    except Exception as e:
        _print(f"[ERROR] Failed to run trends: {e}")
        ok = False

    # Telegram
    try:
        tg_ok = test_telegram_connection()
        _print(f"Telegram connectivity: {'OK' if tg_ok else 'FAILED'}")
        if not tg_ok:
            _print("  Ensure TELEGRAM_TOKEN and TELEGRAM_CHAT_ID are configured in .env or environment variables.")
    except Exception as e:
        _print(f"[ERROR] Telegram test failed: {e}")
        ok = False

    _print("=== Self-test completed ===\n")

    # Append to log file if requested
    if log_path:
        try:
            with open(log_path, 'a', encoding='utf-8') as fh:
                fh.write(f"--- Self-test: {datetime.now(timezone.utc).isoformat()} ---\n")
                for line in report_lines:
                    fh.write(line + "\n")
                fh.write("\n")
        except Exception as e:
            logger.error(f"Failed to write self-test log to {log_path}: {e}")

    return ok


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="webapp.utils", description="Webapp utilities and smoke tests")
    parser.add_argument('--self-test', action='store_true', help='Run quick smoke tests (DB, trends, Telegram)')
    parser.add_argument('--limit', type=int, default=50, help='Limit for job samples in tests')

    args = parser.parse_args()

    if args.self_test:
        success = run_self_test(limit=args.limit)
        sys.exit(0 if success else 2)
    else:
        parser.print_help()
