"""
ClawSight — Multi-Agent Code Review Engine
Supports Groq (FREE - default), OpenAI, and Anthropic
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from server.memory import get_author_context, get_suppressed_patterns
from server.models import (
    AgentResult,
    AgentType,
    ReviewIssue,
    ReviewReport,
    RiskScore,
    Severity,
)

logger = logging.getLogger("codeguardian.agent")

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"


# ================================
# CONTEXT LOADING
# ================================

def _load_agent_context() -> str:
    context_parts = []

    for file in ["soul.md", "review_style.md"]:
        path = AGENT_DIR / file
        if path.exists():
            context_parts.append(path.read_text(encoding="utf-8"))

    return "\n\n".join(context_parts)


# ================================
# LLM ROUTER
# ================================

async def _call_llm(system_prompt: str, user_prompt: str) -> str:
    provider = os.getenv("LLM_PROVIDER", "groq").lower()

    if provider == "groq":
        return await _call_groq(system_prompt, user_prompt)
    elif provider == "anthropic":
        return await _call_anthropic(system_prompt, user_prompt)
    else:
        return await _call_openai(system_prompt, user_prompt)


# ================================
# SINGLETON LLM CLIENTS
# ================================

_groq_client = None
_openai_client = None
_anthropic_client = None

LLM_TIMEOUT = 60.0  # seconds per agent call


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from openai import AsyncOpenAI
        _groq_client = AsyncOpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
            timeout=LLM_TIMEOUT,
        )
    return _groq_client


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            timeout=LLM_TIMEOUT,
        )
    return _openai_client


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            timeout=LLM_TIMEOUT,
        )
    return _anthropic_client


# ================================
# GROQ (FREE - DEFAULT)
# ================================

async def _call_groq(system_prompt: str, user_prompt: str) -> str:
    client = _get_groq_client()
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return json.dumps({"issues": [], "summary": f"Groq error: {e}"})


# ================================
# OPENAI (fallback)
# ================================

async def _call_openai(system_prompt: str, user_prompt: str) -> str:
    client = _get_openai_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return json.dumps({"issues": [], "summary": f"OpenAI error: {e}"})


# ================================
# ANTHROPIC (fallback)
# ================================

async def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    client = _get_anthropic_client()
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Anthropic error: {e}")
        return json.dumps({"issues": [], "summary": f"Anthropic error: {e}"})


# ================================
# OUTPUT FORMAT
# ================================

OUTPUT_SCHEMA = """
You MUST respond with valid JSON only. No markdown fences, no extra text.
Schema:
{
  "issues": [
    {
      "severity": "BLOCKER" | "WARNING" | "SUGGESTION",
      "title": "Short issue title",
      "description": "Detailed explanation",
      "file": "path/to/file.py" or null,
      "line": 42 or null,
      "why": "Why this is a problem",
      "evidence": "Code snippet" or null,
      "suggested_fix": "How to fix it" or null,
      "confidence": 0.9
    }
  ],
  "summary": "Brief summary"
}

Severity rules:
- BLOCKER: Security vulnerabilities, crashes, data loss — MUST fix before merge
- WARNING: Performance issues, missing error handling — SHOULD fix
- SUGGESTION: Readability, naming, minor improvements — COULD improve

If no issues found, return: {"issues": [], "summary": "No issues found."}
"""


# ================================
# SPECIALIST AGENT PROMPTS
# ================================

SECURITY_PROMPT = """You are a **Security Code Reviewer**. Analyze the diff for:
1. Injection attacks (SQL, XSS, command injection)
2. Hardcoded secrets (API keys, passwords, tokens)
3. Authentication/authorization flaws
4. Unsafe deserialization (eval, exec, pickle)
5. SSRF, path traversal, info disclosure
Be specific — reference file names and line numbers. Only flag real security risks."""

PERFORMANCE_PROMPT = """You are a **Performance Code Reviewer**. Analyze the diff for:
1. N+1 queries (DB calls inside loops)
2. Blocking calls in async contexts
3. Memory leaks (unclosed resources, growing collections)
4. Inefficient algorithms (O(n^2) where O(n) works)
5. Missing caching, unbounded queries, connection issues
Be specific — reference file names and line numbers. Only flag genuine performance issues."""

TEST_PROMPT = """You are a **Test Coverage Reviewer**. Analyze the diff for:
1. New functions/endpoints without tests
2. Untested edge cases (null, empty, boundary values)
3. Error paths without test coverage
4. Modified logic without updated tests
5. Tests that don't actually assert anything meaningful
Be specific — suggest concrete test cases that should be written."""

ARCH_PROMPT = """You are an **Architecture Code Reviewer**. Analyze the diff for:
1. SOLID principle violations
2. Layer boundary violations (business logic in controllers, etc.)
3. Code duplication that should be abstracted
4. Circular dependencies, tight coupling
5. Inconsistent patterns, magic numbers, misleading names
Be specific — reference file names and explain the design concern."""

AGENTS = {
    AgentType.SECURITY: SECURITY_PROMPT,
    AgentType.PERFORMANCE: PERFORMANCE_PROMPT,
    AgentType.TEST_COVERAGE: TEST_PROMPT,
    AgentType.ARCHITECTURE: ARCH_PROMPT,
}


# ================================
# SINGLE AGENT RUNNER
# ================================

async def _run_single_agent(
    agent_type: AgentType,
    diff: str,
    context: str,
    pr_files_info: str = "",
) -> AgentResult:
    start = time.monotonic()

    system_prompt = f"{AGENTS[agent_type]}\n\n{context}\n\n{OUTPUT_SCHEMA}"

    user_prompt = f"Analyze this pull request diff:\n\n{diff[:12000]}"
    if pr_files_info:
        user_prompt += f"\n\nChanged files:\n{pr_files_info}"

    try:
        raw = await _call_llm(system_prompt, user_prompt)

        # Strip markdown code fences (handles ```json, ```python, ``` etc.)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])   # drop opening fence line
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
            raw = raw.strip()

        data = json.loads(raw)

        issues = []
        for item in data.get("issues", []):
            try:
                issues.append(
                    ReviewIssue(
                        severity=Severity(item.get("severity", "SUGGESTION")),
                        agent=agent_type,
                        title=item.get("title", "Untitled"),
                        description=item.get("description", ""),
                        file=item.get("file"),
                        line=item.get("line"),
                        why=item.get("why", ""),
                        evidence=item.get("evidence"),
                        suggested_fix=item.get("suggested_fix"),
                        confidence=float(item.get("confidence", 0.8)),
                    )
                )
            except Exception as e:
                logger.warning(f"Parse issue from {agent_type.value}: {e}")

        elapsed = int((time.monotonic() - start) * 1000)

        return AgentResult(
            agent=agent_type,
            issues=issues,
            summary=data.get("summary", ""),
            execution_time_ms=elapsed,
        )

    except json.JSONDecodeError as e:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.error(f"{agent_type.value} returned invalid JSON: {e}")
        return AgentResult(
            agent=agent_type, issues=[], summary="Invalid JSON response",
            execution_time_ms=elapsed, error=str(e),
        )
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.error(f"{agent_type.value} failed: {e}")
        return AgentResult(
            agent=agent_type, issues=[], summary=f"Error: {e}",
            execution_time_ms=elapsed, error=str(e),
        )


# ================================
# RISK SCORE CALCULATOR
# ================================

def _calculate_risk_score(issues: list[ReviewIssue], diff: str) -> RiskScore:
    """Risk score 1-10 based on issues, diff size, file spread, test presence."""
    score = 1
    factors = []

    # Blocker count
    blockers = sum(1 for i in issues if i.severity == Severity.BLOCKER)
    if blockers >= 3:
        score += 3
        factors.append(f"{blockers} blockers found")
    elif blockers >= 1:
        score += 2
        factors.append(f"{blockers} blocker(s) found")

    # Total issues
    total = len(issues)
    if total >= 10:
        score += 2
        factors.append(f"{total} total issues - high density")
    elif total >= 5:
        score += 1
        factors.append(f"{total} total issues")

    # Diff size
    diff_lines = diff.count("\n")
    if diff_lines > 500:
        score += 2
        factors.append(f"Large diff ({diff_lines} lines)")
    elif diff_lines > 200:
        score += 1
        factors.append(f"Medium diff ({diff_lines} lines)")

    # Files changed
    files = set()
    for line in diff.split("\n"):
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            files.add(line.split("/", 1)[-1] if "/" in line else line)
    if len(files) > 10:
        score += 1
        factors.append(f"{len(files)} files changed - wide blast radius")

    # No tests
    has_tests = any("test" in f.lower() for f in files)
    if not has_tests and files:
        score += 1
        factors.append("No test files modified")

    score = min(score, 10)

    if score >= 7:
        label = "HIGH RISK"
    elif score >= 4:
        label = "MEDIUM RISK"
    else:
        label = "LOW RISK"

    return RiskScore(
        score=score,
        factors=factors,
        explanation=f"Regression risk: {score}/10 - {label}",
    )


# ================================
# MAIN PIPELINE
# ================================

async def analyze_pr(
    diff: str,
    pr_number: int,
    repo: str,
    pr_title: str = "",
    pr_author: str = "",
    pr_files_info: str = "",
) -> ReviewReport:
    """Run all 4 specialist agents in parallel and merge results."""
    start = time.monotonic()
    context = _load_agent_context()

    # Inject author history for context-aware reviews
    author_ctx = await get_author_context(pr_author) if pr_author else ""
    if author_ctx:
        context = f"{context}\n\n{author_ctx}"

    # Load false positive patterns to skip known noise
    suppressed = set(await get_suppressed_patterns())

    logger.info(f"Starting 4-agent parallel analysis of {repo}#{pr_number}...")

    # Run all 4 agents concurrently
    tasks = [
        _run_single_agent(agent_type, diff, context, pr_files_info)
        for agent_type in AgentType
    ]
    results: list[AgentResult] = await asyncio.gather(*tasks)

    # Merge, deduplicate, and suppress known false positives
    all_issues: list[ReviewIssue] = []
    for r in results:
        all_issues.extend(r.issues)

    seen = set()
    unique_issues: list[ReviewIssue] = []
    for issue in all_issues:
        title_lower = issue.title.lower().strip()
        if title_lower in suppressed:
            logger.debug(f"Suppressing false positive: {issue.title}")
            continue
        key = (title_lower, issue.file, issue.severity)
        if key not in seen:
            seen.add(key)
            unique_issues.append(issue)

    # Sort: BLOCKER > WARNING > SUGGESTION
    order = {Severity.BLOCKER: 0, Severity.WARNING: 1, Severity.SUGGESTION: 2}
    unique_issues.sort(key=lambda i: order.get(i.severity, 3))

    # Calculate risk score
    risk_score = _calculate_risk_score(unique_issues, diff)

    elapsed = int((time.monotonic() - start) * 1000)

    report = ReviewReport(
        pr_number=pr_number,
        repo=repo,
        pr_title=pr_title,
        pr_author=pr_author,
        issues=unique_issues,
        risk_score=risk_score,
        summary=_build_summary(unique_issues, risk_score),
        review_time_ms=elapsed,
        agent_results=list(results),
    )
    report.count_by_severity()

    logger.info(
        f"Analysis complete: {len(unique_issues)} issues "
        f"({report.total_blockers}B/{report.total_warnings}W/{report.total_suggestions}S) "
        f"Risk: {risk_score.score}/10 - {elapsed}ms"
    )

    return report


def _build_summary(issues: list[ReviewIssue], risk: RiskScore) -> str:
    if not issues:
        return "No issues found. Code looks clean!"

    b = sum(1 for i in issues if i.severity == Severity.BLOCKER)
    w = sum(1 for i in issues if i.severity == Severity.WARNING)
    s = sum(1 for i in issues if i.severity == Severity.SUGGESTION)

    parts = []
    if b: parts.append(f"{b} blocker(s)")
    if w: parts.append(f"{w} warning(s)")
    if s: parts.append(f"{s} suggestion(s)")

    return f"Found {len(issues)} issue(s): {', '.join(parts)}. Risk: {risk.score}/10."


# ================================
# SYNC WRAPPER (legacy)
# ================================

def analyze_code(diff: str) -> str:
    report = asyncio.run(analyze_pr(diff, 0, "repo"))

    from server.utils import format_review_comment
    return format_review_comment(report)