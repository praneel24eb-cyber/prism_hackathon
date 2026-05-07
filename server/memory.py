"""
Memory & Learning layer for CodeGuardian.

Persists review history, tracks author patterns,
and manages false positive suppression.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from server.models import ReviewHistoryEntry, ReviewReport

logger = logging.getLogger("codeguardian.memory")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"
HISTORY_FILE = MEMORY_DIR / "history.json"
AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
REVIEW_STYLE_FILE = AGENT_DIR / "review_style.md"


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------

def _load_history() -> dict:
    """Load review history from disk."""
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load history: {e}")
    return {"reviews": [], "author_profiles": {}, "false_positives": []}


def _save_history(data: dict) -> None:
    """Persist review history to disk."""
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except IOError as e:
        logger.error(f"Failed to save history: {e}")


def save_review(report: ReviewReport) -> None:
    """Save a completed review to history for learning."""
    history = _load_history()

    entry = ReviewHistoryEntry(
        pr_number=report.pr_number,
        repo=report.repo,
        author=report.pr_author,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_issues=len(report.issues),
        blockers=report.total_blockers,
        warnings=report.total_warnings,
        suggestions=report.total_suggestions,
        risk_score=report.risk_score.score if report.risk_score else 0,
        issues_summary=[f"[{i.severity.value}] {i.title}" for i in report.issues[:20]],
    )

    history["reviews"].append(entry.model_dump())

    # Update author profile
    author = report.pr_author
    if author:
        profiles = history.get("author_profiles", {})
        if author not in profiles:
            profiles[author] = {
                "total_prs": 0,
                "total_blockers": 0,
                "total_warnings": 0,
                "common_issues": [],
            }
        profiles[author]["total_prs"] += 1
        profiles[author]["total_blockers"] += report.total_blockers
        profiles[author]["total_warnings"] += report.total_warnings

        # Track common issue titles (most recent 10)
        issue_titles = [i.title for i in report.issues]
        existing = profiles[author].get("common_issues", [])
        profiles[author]["common_issues"] = (issue_titles + existing)[:20]

        history["author_profiles"] = profiles

    _save_history(history)
    logger.info(f"Saved review for {report.repo}#{report.pr_number} to history")


# ---------------------------------------------------------------------------
# Author profiles
# ---------------------------------------------------------------------------

def get_author_profile(author: str) -> Optional[dict]:
    """Get historical profile for a PR author."""
    history = _load_history()
    profiles = history.get("author_profiles", {})
    return profiles.get(author)


def get_author_context(author: str) -> str:
    """Get a text summary of author history for LLM context."""
    profile = get_author_profile(author)
    if not profile:
        return ""

    return (
        f"Author Profile ({author}):\n"
        f"  - Total PRs reviewed: {profile['total_prs']}\n"
        f"  - Historical blockers: {profile['total_blockers']}\n"
        f"  - Historical warnings: {profile['total_warnings']}\n"
        f"  - Common issues: {', '.join(profile.get('common_issues', [])[:5])}\n"
    )


# ---------------------------------------------------------------------------
# False positive management
# ---------------------------------------------------------------------------

def log_false_positive(pr_number: int, issue_title: str, reason: str = "") -> None:
    """Record a false positive to suppress in future reviews."""
    history = _load_history()
    fp_list = history.get("false_positives", [])
    fp_list.append({
        "pr_number": pr_number,
        "issue_title": issue_title,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    history["false_positives"] = fp_list
    _save_history(history)
    logger.info(f"Logged false positive: {issue_title}")


def get_suppressed_patterns() -> list[str]:
    """Get list of issue titles that have been repeatedly flagged as false positives."""
    history = _load_history()
    fp_list = history.get("false_positives", [])

    # Count occurrences of each issue title
    from collections import Counter
    counts = Counter(fp["issue_title"] for fp in fp_list)

    # Suppress issues flagged 3+ times
    return [title for title, count in counts.items() if count >= 3]


# ---------------------------------------------------------------------------
# Review style
# ---------------------------------------------------------------------------

def load_review_style() -> str:
    """Load team review conventions from review_style.md."""
    try:
        if REVIEW_STYLE_FILE.exists():
            return REVIEW_STYLE_FILE.read_text(encoding="utf-8")
    except IOError as e:
        logger.error(f"Failed to load review style: {e}")
    return ""


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def get_review_stats() -> dict:
    """Get aggregate review statistics for the dashboard."""
    history = _load_history()
    reviews = history.get("reviews", [])

    if not reviews:
        return {
            "total_reviews": 0,
            "total_issues_found": 0,
            "total_blockers": 0,
            "total_warnings": 0,
            "total_suggestions": 0,
            "avg_risk_score": 0,
            "recent_reviews": [],
        }

    return {
        "total_reviews": len(reviews),
        "total_issues_found": sum(r.get("total_issues", 0) for r in reviews),
        "total_blockers": sum(r.get("blockers", 0) for r in reviews),
        "total_warnings": sum(r.get("warnings", 0) for r in reviews),
        "total_suggestions": sum(r.get("suggestions", 0) for r in reviews),
        "avg_risk_score": round(
            sum(r.get("risk_score", 0) for r in reviews) / len(reviews), 1
        ),
        "recent_reviews": reviews[-10:][::-1],  # Last 10, newest first
    }
