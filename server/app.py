"""
CodeGuardian — FastAPI Application

Main server that:
1. Receives GitHub webhook events (PR opened/updated)
2. Verifies webhook signatures
3. Orchestrates 4 parallel specialist agents
4. Posts structured reviews back to GitHub
5. Persists review history for learning
6. Serves a dashboard with review statistics
"""

from __future__ import annotations

import html as html_module
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from server.agent import analyze_pr
from server.github import (
    fetch_pr_diff,
    fetch_pr_files,
    post_review,
    verify_webhook_signature,
)
from server.memory import save_review, get_review_stats, load_review_style, init_db
from server.models import PRPayload
from server.utils import format_review_comment, determine_review_event

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-28s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("codeguardian.app")


# ---------------------------------------------------------------------------
# Lifespan — startup/shutdown tasks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown events."""
    await init_db()
    logger.info("🛡️  CodeGuardian starting up...")
    logger.info(f"   LLM Provider: {os.getenv('LLM_PROVIDER', 'openai')}")
    logger.info(f"   Review Style: {len(load_review_style())} chars loaded")

    # Start heartbeat daemon in background (optional)
    # heartbeat_task = asyncio.create_task(heartbeat_loop([]))
    yield
    logger.info("🛡️  CodeGuardian shutting down...")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CodeGuardian",
    description="Autonomous PR Review Agent — Context-Aware, Always-On, Learning",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "CodeGuardian",
        "version": "1.0.0",
        "llm_provider": os.getenv("LLM_PROVIDER", "openai"),
    }


# ---------------------------------------------------------------------------
# GitHub Webhook
# ---------------------------------------------------------------------------

VALID_PR_ACTIONS = {"opened", "synchronize", "reopened"}


@app.post("/webhook")
async def github_webhook(request: Request):
    """
    Handle GitHub webhook events for pull requests.

    Flow:
    1. Verify webhook signature
    2. Parse PR payload
    3. Fetch diff
    4. Run 4 specialist agents in parallel
    5. Format review with severity + risk score
    6. Post review to GitHub
    7. Save to memory for learning
    """
    body = await request.body()

    # Step 1: Verify signature
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_webhook_signature(body, signature):
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    # Check event type
    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type == "ping":
        return {"msg": "pong 🏓"}

    if event_type != "pull_request":
        return {"msg": f"Ignoring event: {event_type}"}

    # Check PR action
    action = payload.get("action", "")
    if action not in VALID_PR_ACTIONS:
        return {"msg": f"Ignoring action: {action}"}

    # Step 2: Parse PR data
    pr_data = payload.get("pull_request", {})
    pr_payload = PRPayload(
        action=action,
        pr_number=pr_data.get("number", 0),
        pr_title=pr_data.get("title", ""),
        pr_author=pr_data.get("user", {}).get("login", ""),
        repo_full_name=payload.get("repository", {}).get("full_name", ""),
        diff_url=pr_data.get("diff_url", ""),
        head_sha=pr_data.get("head", {}).get("sha", ""),
        base_branch=pr_data.get("base", {}).get("ref", ""),
        head_branch=pr_data.get("head", {}).get("ref", ""),
        changed_files=pr_data.get("changed_files", 0),
    )

    logger.info(
        f"📥 PR Event: {pr_payload.repo_full_name}#{pr_payload.pr_number} "
        f"'{pr_payload.pr_title}' by @{pr_payload.pr_author} ({action})"
    )

    # Step 3: Fetch diff
    diff = await fetch_pr_diff(pr_payload.diff_url)
    if not diff:
        logger.error("Failed to fetch PR diff — aborting review")
        return {"msg": "Failed to fetch diff", "error": True}

    # Fetch file metadata for extra context
    pr_files = await fetch_pr_files(pr_payload.repo_full_name, pr_payload.pr_number)
    files_info = "\n".join(
        f"- {f.get('filename', '?')} ({f.get('status', '?')}, +{f.get('additions', 0)}/-{f.get('deletions', 0)})"
        for f in pr_files[:30]
    )

    # Step 4: Run 4 agents in parallel
    report = await analyze_pr(
        diff=diff,
        pr_number=pr_payload.pr_number,
        repo=pr_payload.repo_full_name,
        pr_title=pr_payload.pr_title,
        pr_author=pr_payload.pr_author,
        pr_files_info=files_info,
    )

    # Step 5: Format review
    review_body = format_review_comment(report)
    event = determine_review_event(report)

    # Step 6: Post to GitHub
    await post_review(
        repo=pr_payload.repo_full_name,
        pr_number=pr_payload.pr_number,
        body=review_body,
        event=event,
    )

    # Step 7: Save to memory
    await save_review(report)

    logger.info(
        f"✅ Review complete: {report.total_blockers}B/{report.total_warnings}W/"
        f"{report.total_suggestions}S | Risk: {report.risk_score.score}/10 | "
        f"Action: {event} | Time: {report.review_time_ms}ms"
    )

    return {
        "msg": "Review posted",
        "pr": pr_payload.pr_number,
        "issues": len(report.issues),
        "risk_score": report.risk_score.score if report.risk_score else 0,
        "action": event,
        "review_time_ms": report.review_time_ms,
    }


# ---------------------------------------------------------------------------
# Dashboard API
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def api_stats():
    """Get review statistics for the dashboard."""
    return await get_review_stats()


# ---------------------------------------------------------------------------
# Dashboard UI
# ---------------------------------------------------------------------------

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve a simple dashboard showing review history and stats."""
    stats = await get_review_stats()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CodeGuardian Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 2rem;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        h1 {{
            font-size: 2.2rem;
            background: linear-gradient(90deg, #00d2ff, #3a7bd5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }}
        .subtitle {{ color: #888; margin-bottom: 2rem; font-size: 1rem; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1.2rem;
            margin-bottom: 2.5rem;
        }}
        .stat-card {{
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 16px;
            padding: 1.5rem;
            text-align: center;
            backdrop-filter: blur(10px);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .stat-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 8px 30px rgba(0,0,0,0.3);
        }}
        .stat-number {{
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, #00d2ff, #928dab);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .stat-label {{ font-size: 0.85rem; color: #999; margin-top: 0.3rem; }}
        .blocker {{ border-color: rgba(255,71,87,0.4); }}
        .blocker .stat-number {{ background: linear-gradient(135deg, #ff4757, #ff6b81); -webkit-background-clip: text; }}
        .warning {{ border-color: rgba(255,165,2,0.4); }}
        .warning .stat-number {{ background: linear-gradient(135deg, #ffa502, #ffbe76); -webkit-background-clip: text; }}
        .suggestion {{ border-color: rgba(69,170,242,0.4); }}
        .suggestion .stat-number {{ background: linear-gradient(135deg, #45aaf2, #78e1f7); -webkit-background-clip: text; }}
        h2 {{ margin-bottom: 1rem; font-size: 1.4rem; }}
        .review-list {{ list-style: none; }}
        .review-item {{
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 1rem 1.3rem;
            margin-bottom: 0.8rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .review-repo {{ font-weight: 600; color: #45aaf2; }}
        .review-meta {{ font-size: 0.85rem; color: #888; }}
        .badge {{
            padding: 0.2rem 0.6rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-risk-high {{ background: rgba(255,71,87,0.2); color: #ff4757; }}
        .badge-risk-med {{ background: rgba(255,165,2,0.2); color: #ffa502; }}
        .badge-risk-low {{ background: rgba(46,213,115,0.2); color: #2ed573; }}
        .empty {{ text-align: center; color: #666; padding: 3rem; }}
        .footer {{ text-align: center; color: #555; margin-top: 3rem; font-size: 0.85rem; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ CodeGuardian</h1>
        <p class="subtitle">Autonomous PR Review Agent — Dashboard</p>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number">{stats['total_reviews']}</div>
                <div class="stat-label">Total Reviews</div>
            </div>
            <div class="stat-card blocker">
                <div class="stat-number">{stats['total_blockers']}</div>
                <div class="stat-label">Blockers Found</div>
            </div>
            <div class="stat-card warning">
                <div class="stat-number">{stats['total_warnings']}</div>
                <div class="stat-label">Warnings Found</div>
            </div>
            <div class="stat-card suggestion">
                <div class="stat-number">{stats['total_suggestions']}</div>
                <div class="stat-label">Suggestions</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{stats['total_issues_found']}</div>
                <div class="stat-label">Total Issues</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{stats['avg_risk_score']}</div>
                <div class="stat-label">Avg Risk Score</div>
            </div>
        </div>

        <h2>📋 Recent Reviews</h2>
        <ul class="review-list">
"""

    recent = stats.get("recent_reviews", [])
    if not recent:
        html += '<li class="empty">No reviews yet. Push a PR to get started! 🚀</li>'
    else:
        for r in recent:
            risk = r.get("risk_score", 0)
            if risk >= 7:
                badge_class = "badge-risk-high"
                badge_text = f"Risk {risk}/10"
            elif risk >= 4:
                badge_class = "badge-risk-med"
                badge_text = f"Risk {risk}/10"
            else:
                badge_class = "badge-risk-low"
                badge_text = f"Risk {risk}/10"

            safe_repo = html_module.escape(str(r.get('repo', 'unknown')))
            safe_pr = html_module.escape(str(r.get('pr_number', '?')))
            safe_author = html_module.escape(str(r.get('author', '?')))
            safe_badge_class = html_module.escape(badge_class)
            safe_badge_text = html_module.escape(badge_text)
            html += f"""
            <li class="review-item">
                <div>
                    <span class="review-repo">{safe_repo}</span>
                    <span> #{safe_pr}</span>
                    <span class="review-meta"> by @{safe_author}</span>
                </div>
                <div>
                    <span class="review-meta">
                        🔴 {r.get('blockers', 0)} &nbsp;
                        🟡 {r.get('warnings', 0)} &nbsp;
                        🔵 {r.get('suggestions', 0)} &nbsp;
                    </span>
                    <span class="badge {safe_badge_class}">{safe_badge_text}</span>
                </div>
            </li>
"""

    html += f"""
        </ul>

        <p class="footer">
            🛡️ CodeGuardian v1.0 — Built on OpenClaw | Theme 3: Productivity Platforms
        </p>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Test endpoint (for demo without GitHub)
# ---------------------------------------------------------------------------

@app.post("/test-review")
async def test_review(request: Request):
    """
    Test endpoint — submit a code diff directly for review.
    
    Body: { "diff": "...", "repo": "owner/repo", "pr_number": 1 }
    """
    data = await request.json()
    diff = data.get("diff", "")
    repo = data.get("repo", "test/repo")
    pr_number = data.get("pr_number", 0)

    if not diff:
        raise HTTPException(status_code=400, detail="Missing 'diff' in request body")

    MAX_DIFF_BYTES = 500_000  # 500 KB hard cap
    if len(diff.encode()) > MAX_DIFF_BYTES:
        raise HTTPException(status_code=413, detail="Diff too large (max 500 KB)")

    report = await analyze_pr(
        diff=diff,
        pr_number=pr_number,
        repo=repo,
        pr_title="Test Review",
        pr_author="tester",
    )

    await save_review(report)

    return {
        "review": format_review_comment(report),
        "issues": len(report.issues),
        "risk_score": report.risk_score.score if report.risk_score else 0,
        "report": report.model_dump(),
    }