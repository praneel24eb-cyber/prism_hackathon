# 🛡️ CodeGuardian — Autonomous PR Review Agent

> **OpenClaw Hackathon | Theme 3: Productivity Platforms**
> *"What tools can you create to make AI your best colleague?"*

---

## 🚨 Problem

Modern engineering teams face a critical bottleneck in the code review process:

- **Reviews are slow** — developers wait hours or days for feedback, blocking delivery
- **Reviews are inconsistent** — quality depends on the reviewer's mood, expertise, and availability
- **Security gaps go unnoticed** — reviewers miss injection flaws, hardcoded secrets, and auth bypasses under time pressure
- **Context is lost** — reviewers have no memory of past patterns, repeat mistakes, or known false positives
- **Test coverage is ignored** — new features ship without tests because nobody explicitly checks
- **On-call fatigue** — senior engineers are pulled into every PR, burning out the people who can least afford to be interrupted

> The result: bugs reach production that a thorough, consistent reviewer would have caught.

---

## 💡 Solution

**CodeGuardian** is an autonomous AI-powered PR review agent that acts as an always-on senior engineer on your team.

It connects to your GitHub repository via webhook. Every time a pull request is opened or updated, CodeGuardian:

1. **Fetches the diff** from GitHub
2. **Runs 4 specialist AI agents in parallel**, each focused on a different risk dimension:
   - 🔒 **Security Agent** — SQL injection, XSS, hardcoded secrets, auth flaws
   - ⚡ **Performance Agent** — N+1 queries, blocking async calls, memory leaks
   - 🧪 **Test Coverage Agent** — Missing tests, untested edge cases, meaningless assertions
   - 🏗️ **Architecture Agent** — SOLID violations, tight coupling, code duplication
3. **Calculates a regression risk score** (1–10) based on issue severity, diff size, and file spread
4. **Posts a structured review** back to the PR with severity badges, evidence, and suggested fixes
5. **Persists review history** to learn from past patterns and suppress known false positives

### Key Features

| Feature | Description |
|--------|-------------|
| 4 Parallel Agents | Security, Performance, Test Coverage, Architecture run simultaneously |
| Groq-powered (Free) | Uses Llama 3 70B via Groq's free API — no OpenAI cost |
| Risk Score Engine | 1–10 regression risk score with contributing factors |
| Memory & Learning | Tracks author patterns, suppresses repeated false positives |
| GitHub Native | Posts reviews directly as PR comments with APPROVE/REQUEST_CHANGES |
| Webhook Verified | HMAC-SHA256 signature verification on all incoming events |
| Live Dashboard | Web UI showing total reviews, issues found, risk trends |
| Test Endpoint | Demo mode — submit any diff without needing GitHub |

---

## 🏗️ Architecture

```
GitHub PR Event
      │
      ▼
┌─────────────────┐
│  Webhook Handler │  ← Signature verification (HMAC-SHA256)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Diff Fetcher   │  ← GitHub API (unified diff)
└────────┬────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│              4 Parallel Agents             │
│  🔒 Security  ⚡ Perf  🧪 Tests  🏗️ Arch  │  ← asyncio.gather()
└────────────────────────┬───────────────────┘
                         │
                         ▼
              ┌─────────────────┐
              │  Risk Scorer    │  ← Score 1–10
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  Review Poster  │  ← GitHub PR Review API
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  Memory Layer   │  ← JSON persistence + author profiles
              └─────────────────┘
```

---

## 📁 Project Structure

```
prism_hackathon/
├── run.py                  # Entry point — starts the FastAPI server
├── requirements.txt        # Python dependencies
├── .env                    # Configuration (API keys, tokens)
├── test_review.py          # Quick test — submit a diff without GitHub
│
├── server/
│   ├── app.py              # FastAPI app (webhook, dashboard, test endpoint)
│   ├── agent.py            # Multi-agent review engine (4 parallel agents)
│   ├── github.py           # GitHub API integration
│   ├── models.py           # Pydantic data models
│   ├── memory.py           # Review history & learning layer
│   ├── utils.py            # Markdown formatting, severity badges
│   └── heartbeat.py        # Background daemon for stale PR detection
│
├── agent/
│   ├── soul.md             # Agent persona & review philosophy
│   ├── skill.md            # Skill registry (6-layer architecture)
│   ├── review_style.md     # Team coding conventions
│   └── heartbeat.md        # Heartbeat configuration
│
└── memory/
    └── history.json        # Persistent review history
```

---

## ⚙️ Setup

### Prerequisites

- Python 3.10+
- A [Groq API key](https://console.groq.com) (free)
- A GitHub account

### 1. Clone & enter the project

```bash
cd prism_hackathon
```

### 2. Create and activate virtual environment

```bash
python -m venv myenv

# Windows
myenv\Scripts\activate

# macOS/Linux
source myenv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Edit the `.env` file:

```env
# LLM Provider (groq is free and default)
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama3-70b-8192

# GitHub (required only for live webhook mode)
GITHUB_TOKEN=your_github_personal_access_token
GITHUB_WEBHOOK_SECRET=your_webhook_secret_string

# Server
HOST=0.0.0.0
PORT=8000
```

**Get a Groq API key**: [console.groq.com](https://console.groq.com) → Create API Key → Free tier

**Get a GitHub token**: GitHub → Settings → Developer settings → Personal access tokens → Generate (enable `repo` scope)

---

## 🚀 Usage

### Start the server

```bash
python run.py
```

Output:
```
============================================================
  [*] CodeGuardian - PR Review Agent
============================================================
  Server:    http://0.0.0.0:8000
  Webhook:   http://0.0.0.0:8000/webhook
  Health:    http://0.0.0.0:8000/health
  Dashboard: http://0.0.0.0:8000/dashboard
  LLM:       groq
============================================================
```

### Mode 1 — Test locally (no GitHub needed)

Run the built-in test script to send a sample diff directly:

```bash
python test_review.py
```

Or `POST` any diff to the test endpoint:

```bash
curl -X POST http://localhost:8000/test-review \
  -H "Content-Type: application/json" \
  -d '{"diff": "--- a/app.py\n+++ b/app.py\n+password = \"admin123\"", "repo": "my/repo", "pr_number": 1}'
```

### Mode 2 — Live GitHub webhook

**Step 1**: Expose your local server to the internet using ngrok:

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok.io` URL.

**Step 2**: Register a webhook on your GitHub repository:

1. Go to **Your Repo → Settings → Webhooks → Add webhook**
2. Set **Payload URL** to `https://xxxx.ngrok.io/webhook`
3. Set **Content type** to `application/json`
4. Set **Secret** to the same value as `GITHUB_WEBHOOK_SECRET` in `.env`
5. Under **events**, select **"Let me select individual events"** → check **Pull requests**
6. Click **Add webhook**

**Step 3**: Open a PR on that repo — CodeGuardian will automatically review it!

---

## 🌐 Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API info |
| `/health` | GET | Health check |
| `/dashboard` | GET | Visual review dashboard |
| `/webhook` | POST | GitHub webhook receiver |
| `/test-review` | POST | Submit diff directly for review (demo mode) |
| `/api/stats` | GET | Review statistics (JSON) |
| `/docs` | GET | FastAPI auto-generated API docs |

---

## 📊 Review Output Example

When a PR is reviewed, CodeGuardian posts a comment like:

```
🛡️ CodeGuardian — Automated PR Review
🔴 Regression Risk Score: 8/10 — HIGH RISK

Summary
| Metric      | Count |
| Blockers    |   2   |
| Warnings    |   3   |
| Suggestions |   1   |

🚨 BLOCKERS
1. [Security] Hardcoded API Secret
   File: config.py | Line: 14
   SECRET_KEY = "sk-12345" is hardcoded. Move to environment variables.

2. [Security] SQL Injection Risk
   File: db.py | Line: 32
   f"SELECT * FROM users WHERE id={user_id}" — use parameterized queries.
```

---

## 🧩 Technology Stack

| Layer | Technology |
|-------|-----------|
| Web Framework | FastAPI + Uvicorn |
| AI / LLM | Groq (Llama 3 70B) — free |
| Multi-Agent | Python asyncio (parallel execution) |
| GitHub Integration | GitHub REST API v3 |
| Data Models | Pydantic v2 |
| Persistence | JSON (memory/history.json) |
| Dashboard | FastAPI HTMLResponse (glassmorphism UI) |

---

## 👥 Team

**PRISM** — OpenClaw Hackathon 2026
Theme 3: Productivity Platforms

---

*Built with ❤️ for OpenClaw Hackathon*