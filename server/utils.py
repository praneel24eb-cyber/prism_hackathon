"""
Utility functions for CodeGuardian.

- format_review_comment() — Format ReviewReport as GitHub-ready markdown
- deduplicate_issues() — Merge identical issues from multiple agents
"""

from __future__ import annotations

import logging
from server.models import ReviewReport, ReviewIssue, Severity, RiskScore

logger = logging.getLogger("codeguardian.utils")


# ---------------------------------------------------------------------------
# Severity badges
# ---------------------------------------------------------------------------

SEVERITY_BADGES = {
    Severity.BLOCKER: "🔴 **BLOCKER**",
    Severity.WARNING: "🟡 **WARNING**",
    Severity.SUGGESTION: "🔵 **SUGGESTION**",
}

AGENT_LABELS = {
    "security": "🔒 Security",
    "performance": "⚡ Performance",
    "test_coverage": "🧪 Test Coverage",
    "architecture": "🏗️ Architecture",
}


# ---------------------------------------------------------------------------
# Format review as GitHub markdown comment
# ---------------------------------------------------------------------------

def format_review_comment(report: ReviewReport) -> str:
    """
    Format a ReviewReport as a structured GitHub markdown comment.

    Produces a professional review with:
    - Header with risk score badge
    - Summary stats
    - Issues grouped by severity
    - Each issue with Why / Evidence / Fix / Confidence
    - Footer with agent execution times
    """
    lines: list[str] = []

    # Header
    lines.append("# 🛡️ CodeGuardian — Automated PR Review")
    lines.append("")

    # Risk score badge
    if report.risk_score:
        rs = report.risk_score
        if rs.score >= 7:
            emoji = "🔴"
            label = "HIGH RISK"
        elif rs.score >= 4:
            emoji = "🟡"
            label = "MEDIUM RISK"
        else:
            emoji = "🟢"
            label = "LOW RISK"
        lines.append(f"> {emoji} **Regression Risk Score: {rs.score}/10** — {label}")
        if rs.factors:
            for factor in rs.factors:
                lines.append(f"> - {factor}")
        lines.append("")

    # Summary
    lines.append("## 📊 Summary")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| 🔴 Blockers | {report.total_blockers} |")
    lines.append(f"| 🟡 Warnings | {report.total_warnings} |")
    lines.append(f"| 🔵 Suggestions | {report.total_suggestions} |")
    lines.append(f"| ⏱️ Review Time | {report.review_time_ms}ms |")
    lines.append("")

    if not report.issues:
        lines.append("✅ **No issues found — code looks clean!**")
        lines.append("")
        lines.append(_footer(report))
        return "\n".join(lines)

    # Issues grouped by severity
    for severity in [Severity.BLOCKER, Severity.WARNING, Severity.SUGGESTION]:
        severity_issues = [i for i in report.issues if i.severity == severity]
        if not severity_issues:
            continue

        badge = SEVERITY_BADGES[severity]
        lines.append(f"## {badge} ({len(severity_issues)})")
        lines.append("")

        for idx, issue in enumerate(severity_issues, 1):
            agent_label = AGENT_LABELS.get(issue.agent.value, issue.agent.value)
            location = ""
            if issue.file:
                location = f" — `{issue.file}`"
                if issue.line:
                    location += f":{issue.line}"

            lines.append(f"### {idx}. {issue.title}{location}")
            lines.append(f"*Agent: {agent_label} | Confidence: {issue.confidence:.0%}*")
            lines.append("")

            if issue.description:
                lines.append(f"**Description:** {issue.description}")
                lines.append("")

            if issue.why:
                lines.append(f"**Why:** {issue.why}")
                lines.append("")

            if issue.evidence:
                lines.append("**Evidence:**")
                lines.append(f"```")
                lines.append(issue.evidence)
                lines.append(f"```")
                lines.append("")

            if issue.suggested_fix:
                lines.append(f"**Suggested Fix:** {issue.suggested_fix}")
                lines.append("")

            lines.append("---")
            lines.append("")

    lines.append(_footer(report))
    return "\n".join(lines)


def _footer(report: ReviewReport) -> str:
    """Generate footer with agent execution times."""
    footer_lines = [
        "",
        "<details>",
        "<summary>🤖 Agent Execution Details</summary>",
        "",
        "| Agent | Issues Found | Time |",
        "|-------|-------------|------|",
    ]
    for ar in report.agent_results:
        agent_label = AGENT_LABELS.get(ar.agent.value, ar.agent.value)
        status = f"⚠️ Error: {ar.error}" if ar.error else f"{len(ar.issues)} issue(s)"
        footer_lines.append(f"| {agent_label} | {status} | {ar.execution_time_ms}ms |")

    footer_lines.extend([
        "",
        "</details>",
        "",
        "---",
        f"*🛡️ CodeGuardian v1.0 — Reviewed in {report.review_time_ms}ms using 4 parallel agents*",
        f"*Built on OpenClaw | Theme 3: Productivity Platforms*",
    ])
    return "\n".join(footer_lines)


# ---------------------------------------------------------------------------
# Determine review action
# ---------------------------------------------------------------------------

def determine_review_event(report: ReviewReport) -> str:
    """
    Determine the GitHub review event type based on findings.
    
    - BLOCKER present → REQUEST_CHANGES
    - Only WARNING/SUGGESTION → COMMENT
    - No issues → APPROVE
    """
    if report.total_blockers > 0:
        return "REQUEST_CHANGES"
    elif report.total_warnings > 0 or report.total_suggestions > 0:
        return "COMMENT"
    else:
        return "APPROVE"