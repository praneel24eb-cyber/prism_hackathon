# 🐾 ClawSight — Autonomous PR Review Agent

> **OpenClaw Hackathon 2026 | Theme 3: Productivity Platforms**
> *"What tools can you create to make AI your best colleague?"*
>
> Team: **PRISM / ClawForge**

---

## 📹 Video Demo

<video src="demo_video.mp4" controls width="100%"></video>

> The demo walks through:
> - Live PR opened on GitHub
> - 4 agents running in parallel in real-time
> - Structured review posted back with risk score
> - Dashboard showing cumulative stats

---

## 🚨 Problem

Modern engineering teams face a critical bottleneck in code review:

| Pain Point | Impact |
|------------|--------|
| Reviews are slow | Developers wait hours/days for feedback, blocking delivery |
| Reviews are inconsistent | Quality depends on reviewer mood, expertise, availability |
| Security gaps slip through | SQL injection, hardcoded secrets, auth bypasses go unnoticed under time pressure |
| No institutional memory | Reviewers don't know past patterns, repeat the same mistakes |
| Test coverage ignored | New features ship untested because nobody explicitly checks |
| Senior engineer burnout | Best engineers pulled into every PR instead of doing deep work |

> The result: **bugs reach production that a thorough, consistent reviewer would have caught.**

---

## 💡 Solution

**ClawSight** is an autonomous AI-powered PR review agent — an always-on senior engineer that never misses a PR, never has a bad day, and gets smarter over time.

It connects to your GitHub repository via webhook. Every time a PR is opened or updated, ClawSight:

1. **Fetches the diff** from GitHub using the REST API
2. **Runs 4 specialist AI agents in parallel** via `asyncio.gather()`:
   - 🔒 **Security Agent** — SQL injection, XSS, hardcoded secrets, auth flaws, SSRF
   - ⚡ **Performance Agent** — N+1 queries, blocking async calls, memory leaks, O(n²) algorithms
   - 🧪 **Test Coverage Agent** — Missing tests, untested edge cases, meaningless assertions
   - 🏗️ **Architecture Agent** — SOLID violations, tight coupling, code duplication, layer boundary violations
3. **Calculates a regression risk score** (1–10) based on severity, diff size, file spread, and test presence
4. **Posts a structured review** back to the PR with severity badges, evidence, and suggested fixes
5. **Learns from history** — tracks author patterns, suppresses repeated false positives

### Key Features

| Feature | Description |
|---------|-------------|
| 4 Parallel Agents | All 4 specialists run simultaneously — full review in seconds, not minutes |
| Groq-powered (Free) | Uses Llama 3 70B via Groq's free tier — zero LLM cost |
| Risk Score Engine | 1–10 regression risk with detailed contributing factors |
| Memory & Learning | Author profiles + false positive suppression that improves over time |
| GitHub Native | Posts reviews as APPROVE / COMMENT / REQUEST_CHANGES |
| Webhook Verified | HMAC-SHA256 signature verification — fail-closed when unconfigured |
| Live Dashboard | Glassmorphism UI showing total reviews, issues, and risk trends |
| Test Endpoint | Demo mode — submit any diff without needing a GitHub repo |
| Docker Ready | Single `docker-compose up` for full deployment |

---

## 🏗️ Architecture

```
GitHub PR Event (opened / synchronize / reopened)
        │
        ▼
┌──────────────────┐
│  Webhook Handler │  ← HMAC-SHA256 signature verification (fail-closed)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Diff Fetcher   │  ← GitHub API async HTTP (unified diff + file metadata)
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│                4 Parallel Agents                 │
│  🔒 Security  ⚡ Performance  🧪 Tests  🏗️ Arch │  ← asyncio.gather()
│           Groq Llama 3 70B (FREE)               │
└─────────────────────┬────────────────────────────┘
                      │
                      ▼
             ┌────────────────┐
             │  Deduplicator  │  ← Merge + suppress false positives
             └───────┬────────┘
                     │
                     ▼
             ┌────────────────┐
             │  Risk Scorer   │  ← Score 1–10 with factor breakdown
             └───────┬────────┘
                     │
                     ▼
             ┌────────────────┐
             │ Review Poster  │  ← GitHub PR Review API (APPROVE / REQUEST_CHANGES)
             └───────┬────────┘
                     │
                     ▼
             ┌────────────────┐
             │  Memory Layer  │  ← Async-safe JSON, author profiles, history cap
             └────────────────┘
```

---

## 📁 Project Structure

```
codeguardian/
├── run.py                   # Entry point — starts FastAPI server
├── test_review.py           # Demo test — submit a diff without GitHub
├── requirements.txt         # Python dependencies (minimal, no bloat)
├── .env.example             # Configuration template
├── Dockerfile               # Container image
├── docker-compose.yml       # One-command deployment
│
├── server/
│   ├── app.py               # FastAPI app (webhook, dashboard, test endpoint)
│   ├── agent.py             # Multi-agent engine (4 parallel LLM agents)
│   ├── github.py            # GitHub API async integration
│   ├── models.py            # Pydantic v2 data models
│   ├── memory.py            # Async-safe review history & learning layer
│   ├── utils.py             # Markdown formatting + review event logic
│   └── heartbeat.py        # Background daemon for stale PR detection
│
├── agent/
│   ├── soul.md              # Agent persona & review philosophy
│   ├── skill.md             # 6-layer skill registry
│   ├── review_style.md      # Team coding conventions injected into prompts
│   └── heartbeat.md        # Heartbeat daemon configuration
│
└── memory/
    └── history.json         # Persistent review history (auto-pruned at 500 entries)
```

---

## ⚙️ Setup & Installation

### Prerequisites

- Python 3.11+ (or Docker)
- [Groq API key](https://console.groq.com) — **completely free**
- GitHub Personal Access Token with `repo` scope
- A GitHub repo to connect to (any public or private repo you own)

---

### Option A — Run with Python (local)

**1. Clone the repo**

```bash
git clone https://github.com/PRATHVI9607/prism_hackathon.git
cd prism_hackathon
```

**2. Create virtual environment**

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Configure environment**

```bash
cp .env.example .env
# Now edit .env with your API keys (see Configuration section below)
```

**5. Start the server**

```bash
python run.py
```

```
============================================================
  [*] ClawSight — PR Review Agent
============================================================
  Server:    http://0.0.0.0:8000
  Webhook:   http://0.0.0.0:8000/webhook
  Health:    http://0.0.0.0:8000/health
  Dashboard: http://0.0.0.0:8000/dashboard
  LLM:       groq
============================================================
```

---

### Option B — Run with Docker

```bash
cp .env.example .env
# Edit .env with your keys

docker-compose up --build
```

That's it. ClawSight is running at `http://localhost:8000`.

---

## 🔑 Configuration

Edit `.env` (copy from `.env.example`):

```env
# LLM Provider — groq is free and recommended
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_xxxxxxxxxxxx         # https://console.groq.com → Create API Key

# GitHub
GITHUB_TOKEN=ghp_xxxxxxxxxxxx         # github.com/settings/tokens (repo scope)
GITHUB_WEBHOOK_SECRET=your_secret     # Must match what you set in GitHub webhook

# Server
HOST=0.0.0.0
PORT=8000
DEV_MODE=false                         # Set to true only for local development
```

**Generate a webhook secret:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 🚀 Usage

### Mode 1 — Quick Test (no GitHub needed)

Test the full review pipeline locally with a sample diff:

```bash
python test_review.py
```

Or call the endpoint directly:

```bash
curl -X POST http://localhost:8000/test-review \
  -H "Content-Type: application/json" \
  -d '{
    "diff": "--- a/auth.py\n+++ b/auth.py\n+password = \"admin123\"\n+query = f\"SELECT * FROM users WHERE id={user_id}\"",
    "repo": "my/repo",
    "pr_number": 1
  }'
```

You'll get a full review back with issues, risk score, and formatted GitHub markdown.

---

### Mode 2 — Live GitHub Webhook

**Step 1 — Expose your server** using [ngrok](https://ngrok.com):

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok.io` URL.

**Step 2 — Register webhook** on your GitHub repo:

1. Go to **Repo → Settings → Webhooks → Add webhook**
2. **Payload URL**: `https://xxxx.ngrok.io/webhook`
3. **Content type**: `application/json`
4. **Secret**: same value as `GITHUB_WEBHOOK_SECRET` in your `.env`
5. **Events**: select **"Pull requests"** only
6. Click **Add webhook**

**Step 3 — Open a PR** — ClawSight will instantly post a structured review.

---

### Mode 3 — Cloud Deployment (Railway / Render / Fly.io)

Deploy in one click on Railway:

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app)

Or push the Docker image to any cloud that accepts containers (Render, Fly.io, AWS ECS, GCP Cloud Run):

```bash
docker build -t clawsight .
docker run -p 8000:8000 --env-file .env clawsight
```

Then register your production URL as the GitHub webhook endpoint instead of ngrok.

---

## 🌐 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check — returns status and LLM provider |
| `/dashboard` | GET | Visual dashboard (reviews, issues, risk trends) |
| `/webhook` | POST | GitHub webhook receiver (HMAC-verified) |
| `/test-review` | POST | Submit a diff directly for review (demo mode) |
| `/api/stats` | GET | Review statistics as JSON |
| `/docs` | GET | Auto-generated Swagger API documentation |

---

## 📊 Sample Review Output

When ClawSight reviews a PR, it posts a comment like this:

```markdown
# 🐾 ClawSight — Automated PR Review

> 🔴 Regression Risk Score: 8/10 — HIGH RISK
> - 2 blockers found
> - Large diff (580 lines)
> - No test files modified

## 📊 Summary
| Metric       | Count |
|--------------|-------|
| 🔴 Blockers  |   2   |
| 🟡 Warnings  |   3   |
| 🔵 Suggestions |  1  |
| ⏱️ Review Time | 4200ms |

## 🔴 BLOCKER (2)

### 1. Hardcoded API Secret — `config.py:14`
*Agent: 🔒 Security | Confidence: 95%*

**Description:** API key hardcoded directly in source file
**Why:** Secrets in source code get committed to git history and are visible to anyone with repo access
**Evidence:**
```python
SECRET_KEY = "sk-proj-abc123xyz"
```
**Suggested Fix:** Move to environment variable: `SECRET_KEY = os.getenv("SECRET_KEY")`
```

---

## 🧩 Technology Stack

| Layer | Technology | Why |
|-------|------------|-----|
| Web Framework | FastAPI + Uvicorn | Async-native, fast, auto-docs |
| AI / LLM | Groq API + Llama 3 70B | **Free tier**, fast inference |
| Multi-Agent | Python asyncio | 4 agents run truly in parallel |
| GitHub API | httpx (async) | Non-blocking GitHub calls |
| Data Models | Pydantic v2 | Validated structured output |
| Persistence | JSON (memory/) | Zero-dependency, portable |
| Dashboard | FastAPI HTMLResponse | No frontend framework needed |
| Containers | Docker + Compose | One-command deployment |

---

## 📱 APK / SDK

**An Android APK is not applicable** — ClawSight is a server-side webhook agent, not a mobile app.

However, it ships with two integration paths:

### 1. REST API (built-in)
Any tool can POST to `/test-review` to get a code review. No SDK needed — it's just JSON over HTTP.

```bash
curl -X POST https://your-server.com/test-review \
  -H "Content-Type: application/json" \
  -d '{"diff": "<your diff>", "repo": "owner/repo", "pr_number": 42}'
```

### 2. Python SDK (installable)

A lightweight wrapper is available for programmatic use:

```python
import httpx

class ClawSightClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def review(self, diff: str, repo: str = "local", pr_number: int = 0) -> dict:
        resp = httpx.post(
            f"{self.base_url}/test-review",
            json={"diff": diff, "repo": repo, "pr_number": pr_number},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

# Usage
client = ClawSightClient("http://localhost:8000")
result = client.review(open("my.patch").read())
print(f"Risk: {result['risk_score']}/10, Issues: {result['issues']}")
```

### 3. GitHub App (production distribution)
For enterprise use, ClawSight can be packaged as a GitHub App and installed org-wide — no per-repo webhook setup needed.

---

## 👥 Team

**PRISM** — OpenClaw Hackathon 2026, Theme 3: Productivity Platforms

---

## 📄 AI Disclosure

See [AI_DISCLOSURE.md](AI_DISCLOSURE.md) for full details on how AI tools were used in this project.

**Summary:**
- **Runtime AI**: Groq API (Llama 3 70B) — the core 4-agent review engine
- **Development AI**: Claude Code (Anthropic) — code review, security audit, bug fixes
- **No AI-generated boilerplate** submitted as original — all architecture, prompt design, risk scoring, and integration logic was hand-authored

---

## 📑 PPT / Presentation

> **[View Presentation →](YOUR_PPT_LINK_HERE)**

Covers:
- Problem framing (bottlenecks in modern code review)
- Solution architecture (6-layer multi-agent pipeline)
- Live demo walkthrough
- Technical deep-dive (prompts, risk scoring, memory layer)
- Hackathon theme alignment

---

*🐾 ClawSight v1.0 — Built for OpenClaw Hackathon 2026*
