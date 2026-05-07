"""
Pydantic models for CodeGuardian.

Defines structured data types for review issues, agent results,
risk scores, and the complete review report.
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    SUGGESTION = "SUGGESTION"


class AgentType(str, Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    TEST_COVERAGE = "test_coverage"
    ARCHITECTURE = "architecture"


# ---------------------------------------------------------------------------
# Review Issue — single finding from an agent
# ---------------------------------------------------------------------------

class ReviewIssue(BaseModel):
    """A single issue found during code review."""
    severity: Severity = Field(description="Issue severity level")
    agent: AgentType = Field(description="Which specialist agent found this")
    title: str = Field(description="Short title of the issue")
    description: str = Field(description="Detailed explanation of the issue")
    file: Optional[str] = Field(default=None, description="Affected file path")
    line: Optional[int] = Field(default=None, description="Affected line number")
    why: str = Field(description="Why this is a problem")
    evidence: Optional[str] = Field(default=None, description="Code snippet showing the issue")
    suggested_fix: Optional[str] = Field(default=None, description="Recommended fix")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence score 0-1")


# ---------------------------------------------------------------------------
# Agent Result — output from a single specialist agent
# ---------------------------------------------------------------------------

class AgentResult(BaseModel):
    """Result from a single specialist agent's analysis."""
    agent: AgentType
    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: str = Field(default="", description="Brief summary of findings")
    execution_time_ms: int = Field(default=0, description="Time taken in milliseconds")
    error: Optional[str] = Field(default=None, description="Error message if agent failed")


# ---------------------------------------------------------------------------
# Risk Score — regression risk assessment
# ---------------------------------------------------------------------------

class RiskScore(BaseModel):
    """Regression risk score for a PR."""
    score: int = Field(ge=1, le=10, description="Risk score from 1 (safe) to 10 (dangerous)")
    factors: list[str] = Field(default_factory=list, description="Factors contributing to the score")
    explanation: str = Field(default="", description="Human-readable explanation")


# ---------------------------------------------------------------------------
# Review Report — complete output
# ---------------------------------------------------------------------------

class ReviewReport(BaseModel):
    """Complete review report for a pull request."""
    pr_number: int
    repo: str
    pr_title: str = ""
    pr_author: str = ""
    issues: list[ReviewIssue] = Field(default_factory=list)
    risk_score: Optional[RiskScore] = None
    summary: str = ""
    total_blockers: int = 0
    total_warnings: int = 0
    total_suggestions: int = 0
    review_time_ms: int = 0
    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    agent_results: list[AgentResult] = Field(default_factory=list)

    def count_by_severity(self) -> None:
        """Update severity counts from issues list."""
        self.total_blockers = sum(1 for i in self.issues if i.severity == Severity.BLOCKER)
        self.total_warnings = sum(1 for i in self.issues if i.severity == Severity.WARNING)
        self.total_suggestions = sum(1 for i in self.issues if i.severity == Severity.SUGGESTION)


# ---------------------------------------------------------------------------
# Webhook payload models
# ---------------------------------------------------------------------------

class PRPayload(BaseModel):
    """Extracted PR data from GitHub webhook."""
    action: str
    pr_number: int
    pr_title: str
    pr_author: str
    repo_full_name: str
    diff_url: str
    head_sha: str
    base_branch: str
    head_branch: str
    changed_files: int = 0


# ---------------------------------------------------------------------------
# Review History Entry — for memory/learning
# ---------------------------------------------------------------------------

class ReviewHistoryEntry(BaseModel):
    """A record of a past review for learning."""
    pr_number: int
    repo: str
    author: str
    timestamp: str
    total_issues: int
    blockers: int
    warnings: int
    suggestions: int
    risk_score: int = 0
    issues_summary: list[str] = Field(default_factory=list)
    was_merged: Optional[bool] = None
    false_positives: list[str] = Field(default_factory=list)
