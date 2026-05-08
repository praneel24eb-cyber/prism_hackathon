# 🤖 AI Disclosure — ClawSight

**Project**: ClawSight — Autonomous PR Review Agent
**Hackathon**: OpenClaw Hackathon 2026 | Theme 3: Productivity Platforms
**Team**: ClawForge

---

## Overview

This document transparently discloses all AI tools and models used during the development of ClawSight, in accordance with hackathon integrity guidelines.

---

## AI Tools Used





---

### 1. Groq API — Llama 3 70B (`llama3-70b-8192`)
**Role**: Runtime LLM powering the 4 specialist review agents
**Used for**:
- Security Agent: Detecting injection risks, hardcoded secrets, auth flaws
- Performance Agent: Identifying N+1 queries, blocking async calls, memory leaks
- Test Coverage Agent: Flagging missing tests, untested edge cases
- Architecture Agent: Detecting SOLID violations, tight coupling, duplication

**Extent**: Core runtime component — ClawSight's review intelligence is powered by this model at runtime. All prompts, output parsing, and agent orchestration logic was written by the team.

**Provider**: [Groq](https://groq.com) (free tier, open model)
**Model**: Meta's Llama 3 70B Instruct

---

### 2. ChatGPT (OpenAI)
**Role**: Initial scaffolding / boilerplate generation
**Used for**:
- Generating initial placeholder code for `server/app.py`, `server/github.py`, and `server/agent.py` before refinement
- Brainstorming the multi-agent architecture concept

**Extent**: Limited — the initial output was largely replaced or significantly rewritten during development. Used only in the early ideation and scaffolding phase.

---

## What Was NOT AI-Generated

The following elements represent original human decisions and contributions by the team:

- **Product concept**: The idea to build an autonomous PR review agent for the OpenClaw hackathon
- **Architecture decisions**: Choosing FastAPI over Flask, asyncio parallelism for agents, JSON-based memory layer
- **Groq integration**: Decision to switch from OpenAI to Groq for a free, open-source LLM
- **Agent prompt design**: Refinement of the 4 specialist system prompts to produce structured JSON output
- **Risk scoring logic**: The 5-factor regression risk scoring formula
- **Project configuration**: `.env` setup, `requirements.txt` curation, `run.py` entry point design
- **Hackathon strategy**: Feature prioritization, demo design, presentation slides

---

## Summary Table

| AI Tool | Purpose | Extent |
|---------|---------|--------|
| Groq / Llama 3 70B | Runtime LLM for review agents | Core — powers all review intelligence |
| ChatGPT (OpenAI) | Early scaffolding & brainstorming | Low — replaced/rewritten during dev |

---

## Compliance Statement

All AI assistance was used as a productivity tool to accelerate development. The team maintains full understanding of the codebase and the architectural decisions made. No AI tool was used to fabricate results, game metrics, or misrepresent the capabilities of the system.

---

*Disclosed honestly by Team ClawForge | OpenClaw Hackathon 2026*
