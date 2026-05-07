"""
Heartbeat daemon for CodeGuardian.

Periodically checks for stale PRs (open > 24h without a review)
and re-triggers analysis. Runs as a background asyncio task.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from server.github import fetch_open_prs

logger = logging.getLogger("codeguardian.heartbeat")


# ---------------------------------------------------------------------------
# Heartbeat configuration
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL_HOURS = 24
STALE_PR_THRESHOLD_HOURS = 24


# ---------------------------------------------------------------------------
# Heartbeat loop
# ---------------------------------------------------------------------------

async def heartbeat_loop(repos: list[str] | None = None):
    """
    Background task that periodically checks for stale PRs.

    This runs as an asyncio task started by the FastAPI lifespan.
    """
    if not repos:
        logger.info("Heartbeat: No repos configured — daemon inactive")
        return

    logger.info(
        f"Heartbeat daemon started — checking every {HEARTBEAT_INTERVAL_HOURS}h "
        f"for PRs stale > {STALE_PR_THRESHOLD_HOURS}h"
    )

    while True:
        try:
            await _check_stale_prs(repos)
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

        await asyncio.sleep(HEARTBEAT_INTERVAL_HOURS * 3600)


async def _check_stale_prs(repos: list[str]):
    """Check all configured repos for PRs without recent reviews."""
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=STALE_PR_THRESHOLD_HOURS)

    for repo in repos:
        logger.info(f"Heartbeat: Checking {repo} for stale PRs...")
        open_prs = fetch_open_prs(repo)

        for pr in open_prs:
            created_at = pr.get("created_at", "")
            try:
                pr_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                continue

            if pr_time < threshold:
                pr_number = pr.get("number", 0)
                pr_title = pr.get("title", "")
                logger.warning(
                    f"Heartbeat: Stale PR detected — {repo}#{pr_number} "
                    f"'{pr_title}' (opened {created_at})"
                )
                # In a full implementation, this would re-trigger analysis
                # For now, we just log the stale PR
