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
    """Serve the CodeGuardian dashboard."""
    stats = await get_review_stats()

    # Build recent reviews rows
    rows_html = ""
    recent = stats.get("recent_reviews", [])
    if not recent:
        rows_html = """
        <tr>
          <td colspan="6" class="empty-row">
            <div class="empty-state">
              <div class="empty-icon">🚀</div>
              <div class="empty-title">No reviews yet</div>
              <div class="empty-sub">Open a pull request to see CodeGuardian in action</div>
            </div>
          </td>
        </tr>"""
    else:
        for r in recent:
            risk = r.get("risk_score", 0)
            safe_repo   = html_module.escape(str(r.get("repo", "unknown")))
            safe_pr     = html_module.escape(str(r.get("pr_number", "?")))
            safe_author = html_module.escape(str(r.get("author", "?")))
            safe_ts     = html_module.escape(str(r.get("timestamp", ""))[:16].replace("T", " "))
            b = r.get("blockers", 0)
            w = r.get("warnings", 0)
            s = r.get("suggestions", 0)
            if risk >= 7:
                risk_cls = "risk-high"; risk_label = f"HIGH {risk}/10"
            elif risk >= 4:
                risk_cls = "risk-med";  risk_label = f"MED {risk}/10"
            else:
                risk_cls = "risk-low";  risk_label = f"LOW {risk}/10"
            rows_html += f"""
        <tr class="review-row">
          <td><span class="repo-name">{safe_repo}</span><span class="pr-num"> #{safe_pr}</span></td>
          <td><span class="author-badge">@{safe_author}</span></td>
          <td class="center"><span class="pill pill-red">{b}</span></td>
          <td class="center"><span class="pill pill-amber">{w}</span></td>
          <td class="center"><span class="pill pill-sky">{s}</span></td>
          <td class="center"><span class="risk-badge {risk_cls}">{risk_label}</span></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CodeGuardian — Dashboard</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}

    :root {{
      --sky-50:  #f0f9ff;
      --sky-100: #e0f2fe;
      --sky-400: #38bdf8;
      --sky-500: #0ea5e9;
      --sky-600: #0284c7;
      --green-50:  #f0fdf4;
      --green-400: #4ade80;
      --green-500: #22c55e;
      --green-600: #16a34a;
      --eco-400: #34d399;
      --eco-500: #10b981;
      --eco-600: #059669;
      --red-400: #f87171;
      --red-500: #ef4444;
      --amber-400: #fbbf24;
      --amber-500: #f59e0b;
      --slate-50:  #f8fafc;
      --slate-100: #f1f5f9;
      --slate-200: #e2e8f0;
      --slate-400: #94a3b8;
      --slate-600: #475569;
      --slate-700: #334155;
      --slate-800: #1e293b;
      --slate-900: #0f172a;
      --white: #ffffff;
      --radius-sm: 8px;
      --radius-md: 14px;
      --radius-lg: 20px;
      --radius-xl: 28px;
      --shadow-sm: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
      --shadow-md: 0 4px 16px rgba(14,165,233,.10), 0 2px 6px rgba(0,0,0,.05);
      --shadow-lg: 0 12px 40px rgba(14,165,233,.15), 0 4px 12px rgba(0,0,0,.06);
      --shadow-card: 0 2px 12px rgba(14,165,233,.08), 0 1px 4px rgba(0,0,0,.04);
    }}

    html {{ scroll-behavior: smooth; }}

    body {{
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      background: linear-gradient(145deg, #f0f9ff 0%, #fafffe 40%, #f0fdf4 100%);
      min-height: 100vh;
      color: var(--slate-800);
      overflow-x: hidden;
      position: relative;
    }}

    /* ── Floating background blobs ── */
    .blob {{
      position: fixed;
      border-radius: 50%;
      filter: blur(72px);
      opacity: 0.35;
      pointer-events: none;
      z-index: 0;
    }}
    .blob-1 {{
      width: 520px; height: 520px;
      background: radial-gradient(circle, #7dd3fc 0%, #38bdf8 60%, transparent 100%);
      top: -160px; left: -160px;
      animation: drift1 18s ease-in-out infinite;
    }}
    .blob-2 {{
      width: 440px; height: 440px;
      background: radial-gradient(circle, #6ee7b7 0%, #34d399 60%, transparent 100%);
      top: 30%; right: -120px;
      animation: drift2 22s ease-in-out infinite;
    }}
    .blob-3 {{
      width: 360px; height: 360px;
      background: radial-gradient(circle, #bfdbfe 0%, #93c5fd 60%, transparent 100%);
      bottom: -100px; left: 30%;
      animation: drift3 26s ease-in-out infinite;
    }}
    .blob-4 {{
      width: 280px; height: 280px;
      background: radial-gradient(circle, #a7f3d0 0%, #6ee7b7 60%, transparent 100%);
      top: 55%; left: 10%;
      animation: drift4 20s ease-in-out infinite;
    }}
    .blob-5 {{
      width: 200px; height: 200px;
      background: radial-gradient(circle, #e0f2fe 0%, #7dd3fc 60%, transparent 100%);
      top: 20%; left: 50%;
      animation: drift1 15s ease-in-out infinite reverse;
    }}

    @keyframes drift1 {{
      0%,100% {{ transform: translate(0,0) scale(1); }}
      33%      {{ transform: translate(40px,-40px) scale(1.06); }}
      66%      {{ transform: translate(-30px,30px) scale(0.94); }}
    }}
    @keyframes drift2 {{
      0%,100% {{ transform: translate(0,0) scale(1); }}
      40%      {{ transform: translate(-50px,30px) scale(1.08); }}
      70%      {{ transform: translate(20px,-20px) scale(0.96); }}
    }}
    @keyframes drift3 {{
      0%,100% {{ transform: translate(0,0) scale(1); }}
      50%      {{ transform: translate(35px,-50px) scale(1.05); }}
    }}
    @keyframes drift4 {{
      0%,100% {{ transform: translate(0,0) scale(1); }}
      45%      {{ transform: translate(-25px,45px) scale(1.07); }}
      80%      {{ transform: translate(30px,-15px) scale(0.97); }}
    }}

    /* ── Floating particles ── */
    .particles {{ position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }}
    .particle {{
      position: absolute;
      border-radius: 50%;
      animation: rise linear infinite;
      opacity: 0;
    }}
    @keyframes rise {{
      0%   {{ transform: translateY(100vh) scale(0); opacity: 0; }}
      10%  {{ opacity: 0.6; }}
      90%  {{ opacity: 0.3; }}
      100% {{ transform: translateY(-100px) scale(1.2); opacity: 0; }}
    }}

    /* ── Layout ── */
    .page {{ position: relative; z-index: 1; max-width: 1180px; margin: 0 auto; padding: 2.5rem 2rem 4rem; }}

    /* ── Header ── */
    .header {{
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 2.8rem; flex-wrap: wrap; gap: 1rem;
    }}
    .header-left {{ display: flex; align-items: center; gap: 1rem; }}
    .logo-wrap {{
      width: 52px; height: 52px;
      background: linear-gradient(135deg, var(--sky-500), var(--eco-500));
      border-radius: var(--radius-md);
      display: flex; align-items: center; justify-content: center;
      font-size: 1.6rem;
      box-shadow: 0 4px 16px rgba(14,165,233,.35);
      flex-shrink: 0;
    }}
    .header-text h1 {{
      font-size: 1.9rem; font-weight: 800; line-height: 1.1;
      background: linear-gradient(135deg, var(--sky-600) 0%, var(--eco-600) 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .header-text p {{
      font-size: 0.82rem; color: var(--slate-400); font-weight: 400; margin-top: 2px;
      letter-spacing: 0.02em;
    }}
    .header-right {{ display: flex; align-items: center; gap: 0.8rem; }}
    .live-badge {{
      display: flex; align-items: center; gap: 6px;
      background: white; border: 1px solid var(--slate-200);
      border-radius: 999px; padding: 0.35rem 0.9rem;
      font-size: 0.75rem; font-weight: 600; color: var(--eco-600);
      box-shadow: var(--shadow-sm);
    }}
    .live-dot {{
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--eco-500);
      animation: pulse-dot 2s ease-in-out infinite;
    }}
    @keyframes pulse-dot {{
      0%,100% {{ transform: scale(1); opacity:1; }}
      50%      {{ transform: scale(1.4); opacity:.6; }}
    }}
    .refresh-btn {{
      background: white; border: 1px solid var(--slate-200);
      border-radius: 999px; padding: 0.35rem 1rem;
      font-size: 0.75rem; font-weight: 600; color: var(--sky-600);
      cursor: pointer; transition: all .2s;
      box-shadow: var(--shadow-sm);
    }}
    .refresh-btn:hover {{ background: var(--sky-50); border-color: var(--sky-400); }}

    /* ── Stats grid ── */
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 1.1rem;
      margin-bottom: 2.5rem;
    }}
    @media (max-width: 1024px) {{ .stats-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
    @media (max-width: 640px)  {{ .stats-grid {{ grid-template-columns: repeat(2, 1fr); }} }}

    .stat-card {{
      background: var(--white);
      border-radius: var(--radius-lg);
      padding: 1.4rem 1.1rem 1.2rem;
      text-align: center;
      box-shadow: var(--shadow-card);
      border: 1.5px solid transparent;
      position: relative;
      overflow: hidden;
      transition: transform .25s cubic-bezier(.34,1.56,.64,1), box-shadow .25s;
      cursor: default;
    }}
    .stat-card::before {{
      content: '';
      position: absolute; inset: 0;
      border-radius: inherit;
      padding: 1.5px;
      background: linear-gradient(135deg, var(--card-from), var(--card-to));
      -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
      -webkit-mask-composite: xor;
      mask-composite: exclude;
      opacity: 0.6;
      transition: opacity .25s;
    }}
    .stat-card::after {{
      content: '';
      position: absolute;
      width: 90px; height: 90px;
      border-radius: 50%;
      background: radial-gradient(circle, var(--card-from) 0%, transparent 70%);
      top: -30px; right: -20px;
      opacity: 0.12;
      transition: opacity .25s, transform .25s;
    }}
    .stat-card:hover {{
      transform: translateY(-6px);
      box-shadow: var(--shadow-lg);
    }}
    .stat-card:hover::before {{ opacity: 1; }}
    .stat-card:hover::after  {{ opacity: 0.22; transform: scale(1.3); }}

    .stat-card.sky   {{ --card-from: #38bdf8; --card-to: #0ea5e9; }}
    .stat-card.red   {{ --card-from: #f87171; --card-to: #ef4444; }}
    .stat-card.amber {{ --card-from: #fbbf24; --card-to: #f59e0b; }}
    .stat-card.eco   {{ --card-from: #34d399; --card-to: #10b981; }}
    .stat-card.violet{{ --card-from: #a78bfa; --card-to: #7c3aed; }}
    .stat-card.teal  {{ --card-from: #2dd4bf; --card-to: #0d9488; }}

    .stat-icon {{
      font-size: 1.5rem;
      margin-bottom: 0.5rem;
      display: block;
      filter: drop-shadow(0 2px 4px rgba(0,0,0,.08));
    }}
    .stat-number {{
      font-size: 2.2rem; font-weight: 800; line-height: 1;
      background: linear-gradient(135deg, var(--card-from), var(--card-to));
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 0.35rem;
    }}
    .stat-label {{
      font-size: 0.72rem; font-weight: 600;
      color: var(--slate-400); letter-spacing: 0.06em; text-transform: uppercase;
    }}

    /* ── Section header ── */
    .section-header {{
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 1.1rem;
    }}
    .section-title {{
      font-size: 1.05rem; font-weight: 700; color: var(--slate-800);
      display: flex; align-items: center; gap: 0.5rem;
    }}
    .section-title .icon-chip {{
      width: 28px; height: 28px;
      background: linear-gradient(135deg, var(--sky-400), var(--eco-400));
      border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      font-size: 0.85rem;
    }}
    .count-chip {{
      background: var(--sky-50); color: var(--sky-600);
      border: 1px solid var(--sky-100);
      border-radius: 999px; padding: 0.15rem 0.65rem;
      font-size: 0.72rem; font-weight: 700;
    }}

    /* ── Table card ── */
    .table-card {{
      background: var(--white);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
      border: 1px solid rgba(14,165,233,.08);
      overflow: hidden;
    }}
    .reviews-table {{
      width: 100%; border-collapse: collapse;
    }}
    .reviews-table thead tr {{
      background: linear-gradient(135deg, var(--sky-50) 0%, var(--green-50) 100%);
      border-bottom: 1.5px solid var(--slate-100);
    }}
    .reviews-table thead th {{
      padding: 0.85rem 1.1rem;
      font-size: 0.7rem; font-weight: 700;
      color: var(--slate-400); text-transform: uppercase; letter-spacing: 0.07em;
      text-align: left;
    }}
    .reviews-table thead th.center {{ text-align: center; }}
    .reviews-table tbody tr {{
      border-bottom: 1px solid var(--slate-100);
      transition: background .15s;
    }}
    .reviews-table tbody tr:last-child {{ border-bottom: none; }}
    .reviews-table tbody tr:hover {{ background: var(--sky-50); }}
    .reviews-table td {{
      padding: 0.95rem 1.1rem;
      font-size: 0.83rem; color: var(--slate-700);
      vertical-align: middle;
    }}
    .reviews-table td.center {{ text-align: center; }}

    .repo-name {{ font-weight: 700; color: var(--sky-600); }}
    .pr-num    {{ color: var(--slate-400); font-size: 0.78rem; }}
    .author-badge {{
      background: var(--slate-100); color: var(--slate-600);
      border-radius: 999px; padding: 0.2rem 0.65rem;
      font-size: 0.75rem; font-weight: 500;
    }}

    .pill {{
      display: inline-block; min-width: 28px;
      border-radius: 999px; padding: 0.18rem 0.55rem;
      font-size: 0.72rem; font-weight: 700; text-align: center;
    }}
    .pill-red   {{ background: #fef2f2; color: var(--red-500); }}
    .pill-amber {{ background: #fffbeb; color: var(--amber-500); }}
    .pill-sky   {{ background: var(--sky-50); color: var(--sky-600); }}

    .risk-badge {{
      display: inline-block; border-radius: 999px;
      padding: 0.25rem 0.75rem;
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em;
    }}
    .risk-high {{ background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }}
    .risk-med  {{ background: #fffbeb; color: #d97706; border: 1px solid #fde68a; }}
    .risk-low  {{ background: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0; }}

    /* ── Empty state ── */
    .empty-row td {{ padding: 0 !important; }}
    .empty-state {{
      padding: 3.5rem 2rem; text-align: center;
    }}
    .empty-icon  {{ font-size: 2.5rem; margin-bottom: 0.75rem; }}
    .empty-title {{ font-size: 1rem; font-weight: 700; color: var(--slate-700); }}
    .empty-sub   {{ font-size: 0.83rem; color: var(--slate-400); margin-top: 0.3rem; }}

    /* ── Footer ── */
    .footer {{
      margin-top: 3rem; text-align: center;
      font-size: 0.75rem; color: var(--slate-400);
      display: flex; align-items: center; justify-content: center; gap: 0.5rem;
    }}
    .footer-dot {{ width: 3px; height: 3px; border-radius: 50%; background: var(--slate-300); }}

    /* ── Entrance animations ── */
    .fade-up {{
      opacity: 0; transform: translateY(22px);
      animation: fadeUp .55s cubic-bezier(.22,1,.36,1) forwards;
    }}
    @keyframes fadeUp {{
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    .delay-1 {{ animation-delay: .08s; }}
    .delay-2 {{ animation-delay: .16s; }}
    .delay-3 {{ animation-delay: .24s; }}
    .delay-4 {{ animation-delay: .32s; }}
    .delay-5 {{ animation-delay: .40s; }}
    .delay-6 {{ animation-delay: .48s; }}
    .delay-7 {{ animation-delay: .56s; }}
  </style>
</head>
<body>

  <!-- Floating blobs -->
  <div class="blob blob-1"></div>
  <div class="blob blob-2"></div>
  <div class="blob blob-3"></div>
  <div class="blob blob-4"></div>
  <div class="blob blob-5"></div>

  <!-- Rising particles -->
  <div class="particles" id="particles"></div>

  <div class="page">

    <!-- Header -->
    <header class="header fade-up">
      <div class="header-left">
        <div class="logo-wrap">🛡️</div>
        <div class="header-text">
          <h1>CodeGuardian</h1>
          <p>Autonomous AI PR Review Agent &nbsp;·&nbsp; 4 Parallel Specialists</p>
        </div>
      </div>
      <div class="header-right">
        <div class="live-badge"><div class="live-dot"></div>Live</div>
        <button class="refresh-btn" onclick="location.reload()">↻ Refresh</button>
      </div>
    </header>

    <!-- Stats -->
    <div class="stats-grid">
      <div class="stat-card sky fade-up delay-1">
        <span class="stat-icon">📋</span>
        <div class="stat-number" data-target="{stats['total_reviews']}">0</div>
        <div class="stat-label">Total Reviews</div>
      </div>
      <div class="stat-card red fade-up delay-2">
        <span class="stat-icon">🔴</span>
        <div class="stat-number" data-target="{stats['total_blockers']}">0</div>
        <div class="stat-label">Blockers Found</div>
      </div>
      <div class="stat-card amber fade-up delay-3">
        <span class="stat-icon">🟡</span>
        <div class="stat-number" data-target="{stats['total_warnings']}">0</div>
        <div class="stat-label">Warnings Found</div>
      </div>
      <div class="stat-card eco fade-up delay-4">
        <span class="stat-icon">💡</span>
        <div class="stat-number" data-target="{stats['total_suggestions']}">0</div>
        <div class="stat-label">Suggestions</div>
      </div>
      <div class="stat-card violet fade-up delay-5">
        <span class="stat-icon">🐛</span>
        <div class="stat-number" data-target="{stats['total_issues_found']}">0</div>
        <div class="stat-label">Total Issues</div>
      </div>
      <div class="stat-card teal fade-up delay-6">
        <span class="stat-icon">⚡</span>
        <div class="stat-number" data-target-float="{stats['avg_risk_score']}">0</div>
        <div class="stat-label">Avg Risk Score</div>
      </div>
    </div>

    <!-- Recent Reviews -->
    <div class="fade-up delay-7">
      <div class="section-header">
        <div class="section-title">
          <div class="icon-chip">📄</div>
          Recent Reviews
        </div>
        <span class="count-chip">{len(recent)} review{"s" if len(recent) != 1 else ""}</span>
      </div>

      <div class="table-card">
        <table class="reviews-table">
          <thead>
            <tr>
              <th>Repository / PR</th>
              <th>Author</th>
              <th class="center">🔴 Blockers</th>
              <th class="center">🟡 Warnings</th>
              <th class="center">💡 Suggestions</th>
              <th class="center">Risk</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Footer -->
    <div class="footer" style="margin-top:2.5rem">
      🛡️ CodeGuardian v1.0
      <div class="footer-dot"></div>
      OpenClaw Hackathon 2026
      <div class="footer-dot"></div>
      Theme 3: Productivity Platforms
      <div class="footer-dot"></div>
      Team PRISM
    </div>

  </div><!-- /page -->

  <script>
    // ── Animated counters ──
    function animateCount(el, target, isFloat) {{
      const duration = 1100;
      const start = performance.now();
      const update = (now) => {{
        const p = Math.min((now - start) / duration, 1);
        const ease = 1 - Math.pow(1 - p, 3);
        if (isFloat) {{
          el.textContent = (ease * target).toFixed(1);
        }} else {{
          el.textContent = Math.round(ease * target);
        }}
        if (p < 1) requestAnimationFrame(update);
        else el.textContent = isFloat ? target.toFixed(1) : target;
      }};
      requestAnimationFrame(update);
    }}
    document.querySelectorAll('[data-target]').forEach(el => {{
      animateCount(el, parseInt(el.dataset.target), false);
    }});
    document.querySelectorAll('[data-target-float]').forEach(el => {{
      animateCount(el, parseFloat(el.dataset.targetFloat), true);
    }});

    // ── Rising particles ──
    const container = document.getElementById('particles');
    const colors = ['#38bdf8','#0ea5e9','#34d399','#10b981','#6ee7b7','#7dd3fc','#a7f3d0'];
    for (let i = 0; i < 22; i++) {{
      const p = document.createElement('div');
      p.className = 'particle';
      const size = 4 + Math.random() * 10;
      p.style.cssText = `
        width:${{size}}px; height:${{size}}px;
        left:${{Math.random()*100}}%;
        background:${{colors[Math.floor(Math.random()*colors.length)]}};
        animation-duration:${{8+Math.random()*14}}s;
        animation-delay:${{Math.random()*12}}s;
        opacity:0;
      `;
      container.appendChild(p);
    }}

    // ── Auto-refresh every 30s ──
    setTimeout(() => location.reload(), 30000);
  </script>
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