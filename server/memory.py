"""
Memory & Learning layer for CodeGuardian — SQLite backend.

Tables:
  reviews          — one row per completed PR review
  author_profiles  — per-developer aggregates (upserted on each review)
  false_positives  — issue titles flagged as noise by users
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from server.models import ReviewReport

logger = logging.getLogger("codeguardian.memory")

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"
DB_PATH    = MEMORY_DIR / "codeguardian.db"
AGENT_DIR  = Path(__file__).resolve().parent.parent / "agent"
REVIEW_STYLE_FILE = AGENT_DIR / "review_style.md"

FP_SUPPRESS_THRESHOLD = 3

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS reviews (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number      INTEGER NOT NULL,
    repo           TEXT    NOT NULL,
    author         TEXT    NOT NULL DEFAULT '',
    timestamp      TEXT    NOT NULL,
    total_issues   INTEGER NOT NULL DEFAULT 0,
    blockers       INTEGER NOT NULL DEFAULT 0,
    warnings       INTEGER NOT NULL DEFAULT 0,
    suggestions    INTEGER NOT NULL DEFAULT 0,
    risk_score     INTEGER NOT NULL DEFAULT 0,
    issues_summary TEXT    NOT NULL DEFAULT '[]',
    was_merged     INTEGER,
    false_positives TEXT   NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS author_profiles (
    author         TEXT    PRIMARY KEY,
    total_prs      INTEGER NOT NULL DEFAULT 0,
    total_blockers INTEGER NOT NULL DEFAULT 0,
    total_warnings INTEGER NOT NULL DEFAULT 0,
    common_issues  TEXT    NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS false_positives (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number   INTEGER,
    issue_title TEXT    NOT NULL,
    reason      TEXT    NOT NULL DEFAULT '',
    timestamp   TEXT    NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Init — called once at FastAPI startup
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Create tables if they don't exist. Call from FastAPI lifespan."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(_DDL)
        await conn.commit()
    logger.info(f"Database ready: {DB_PATH}")


# ---------------------------------------------------------------------------
# Save review
# ---------------------------------------------------------------------------

async def save_review(report: ReviewReport) -> None:
    """Persist a completed review and upsert the author profile."""
    ts = datetime.now(timezone.utc).isoformat()
    issues_summary = json.dumps(
        [f"[{i.severity.value}] {i.title}" for i in report.issues[:20]]
    )
    risk = report.risk_score.score if report.risk_score else 0

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            """
            INSERT INTO reviews
                (pr_number, repo, author, timestamp, total_issues,
                 blockers, warnings, suggestions, risk_score, issues_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.pr_number, report.repo, report.pr_author, ts,
                len(report.issues), report.total_blockers,
                report.total_warnings, report.total_suggestions,
                risk, issues_summary,
            ),
        )

        if report.pr_author:
            async with conn.execute(
                "SELECT common_issues FROM author_profiles WHERE author = ?",
                (report.pr_author,),
            ) as cur:
                row = await cur.fetchone()

            existing: list[str] = json.loads(row["common_issues"]) if row else []
            merged = ([i.title for i in report.issues] + existing)[:20]

            await conn.execute(
                """
                INSERT INTO author_profiles
                    (author, total_prs, total_blockers, total_warnings, common_issues)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(author) DO UPDATE SET
                    total_prs      = total_prs + 1,
                    total_blockers = total_blockers + excluded.total_blockers,
                    total_warnings = total_warnings + excluded.total_warnings,
                    common_issues  = excluded.common_issues
                """,
                (report.pr_author, report.total_blockers,
                 report.total_warnings, json.dumps(merged)),
            )

        await conn.commit()

    logger.info(f"Saved review for {report.repo}#{report.pr_number}")


# ---------------------------------------------------------------------------
# Author profiles
# ---------------------------------------------------------------------------

async def get_author_profile(author: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM author_profiles WHERE author = ?", (author,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "total_prs":      row["total_prs"],
                "total_blockers": row["total_blockers"],
                "total_warnings": row["total_warnings"],
                "common_issues":  json.loads(row["common_issues"]),
            }


async def get_author_context(author: str) -> str:
    profile = await get_author_profile(author)
    if not profile:
        return ""
    common = ", ".join(profile["common_issues"][:5]) or "none yet"
    return (
        f"Author Profile ({author}):\n"
        f"  - Total PRs reviewed: {profile['total_prs']}\n"
        f"  - Historical blockers: {profile['total_blockers']}\n"
        f"  - Historical warnings: {profile['total_warnings']}\n"
        f"  - Common issues: {common}\n"
    )


# ---------------------------------------------------------------------------
# False positive management
# ---------------------------------------------------------------------------

async def log_false_positive(pr_number: int, issue_title: str, reason: str = "") -> None:
    ts = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO false_positives (pr_number, issue_title, reason, timestamp) VALUES (?, ?, ?, ?)",
            (pr_number, issue_title, reason, ts),
        )
        await conn.commit()
    logger.info(f"Logged false positive: {issue_title}")


async def get_suppressed_patterns() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT issue_title FROM false_positives
            GROUP BY LOWER(issue_title)
            HAVING COUNT(*) >= ?
            """,
            (FP_SUPPRESS_THRESHOLD,),
        ) as cur:
            rows = await cur.fetchall()
            return [r["issue_title"].lower() for r in rows]


# ---------------------------------------------------------------------------
# Review style (file-based)
# ---------------------------------------------------------------------------

def load_review_style() -> str:
    try:
        if REVIEW_STYLE_FILE.exists():
            return REVIEW_STYLE_FILE.read_text(encoding="utf-8")
    except IOError as e:
        logger.error(f"Failed to load review style: {e}")
    return ""


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------

async def get_review_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT
                COUNT(*)          AS total_reviews,
                SUM(total_issues) AS total_issues_found,
                SUM(blockers)     AS total_blockers,
                SUM(warnings)     AS total_warnings,
                SUM(suggestions)  AS total_suggestions,
                AVG(risk_score)   AS avg_risk_score
            FROM reviews
            """
        ) as cur:
            agg = await cur.fetchone()

        if not agg or agg["total_reviews"] == 0:
            return {
                "total_reviews": 0, "total_issues_found": 0,
                "total_blockers": 0, "total_warnings": 0,
                "total_suggestions": 0, "avg_risk_score": 0,
                "recent_reviews": [],
            }

        async with conn.execute(
            """
            SELECT pr_number, repo, author, risk_score,
                   blockers, warnings, suggestions, timestamp
            FROM reviews ORDER BY id DESC LIMIT 10
            """
        ) as cur:
            recent = [dict(r) for r in await cur.fetchall()]

    return {
        "total_reviews":      agg["total_reviews"],
        "total_issues_found": agg["total_issues_found"] or 0,
        "total_blockers":     agg["total_blockers"] or 0,
        "total_warnings":     agg["total_warnings"] or 0,
        "total_suggestions":  agg["total_suggestions"] or 0,
        "avg_risk_score":     round(agg["avg_risk_score"] or 0, 1),
        "recent_reviews":     recent,
    }
