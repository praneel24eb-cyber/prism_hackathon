"""
GitHub API integration for CodeGuardian.

Handles:
- Fetching PR diffs and file contents
- Posting structured review comments
- Webhook signature verification
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("codeguardian.github")

_GITHUB_API = "https://api.github.com"


def _get_token() -> str:
    token = os.getenv("GITHUB_TOKEN", "")
    if not token or token == "your_github_token_here":
        logger.warning("GITHUB_TOKEN is not set — GitHub API calls will fail")
    return token


def _headers(accept: str = "application/vnd.github.v3+json") -> dict:
    return {
        "Authorization": f"token {_get_token()}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ---------------------------------------------------------------------------
# Webhook verification
# ---------------------------------------------------------------------------

def verify_webhook_signature(payload_body: bytes, signature: Optional[str]) -> bool:
    """
    Verify GitHub webhook signature using HMAC-SHA256.
    Returns False if secret is not configured (fail-closed).
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret or secret == "your_webhook_secret_here":
        logger.warning("GITHUB_WEBHOOK_SECRET not set — rejecting webhook")
        return False

    if not signature:
        logger.error("No X-Hub-Signature-256 header present")
        return False

    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Async fetch functions
# ---------------------------------------------------------------------------

async def fetch_pr_diff(diff_url: str) -> str:
    """Fetch the unified diff for a pull request."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                diff_url,
                headers=_headers("application/vnd.github.v3.diff"),
            )
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch PR diff: {e}")
        return ""


async def fetch_pr_files(repo: str, pr_number: int) -> list[dict]:
    """Fetch list of changed files in a PR (paginates up to 300 files)."""
    results: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            url = f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}"
            try:
                response = await client.get(url, headers=_headers())
                response.raise_for_status()
                batch = response.json()
                if not batch:
                    break
                results.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
                if page > 3:  # cap at 300 files
                    break
            except httpx.HTTPError as e:
                logger.error(f"Failed to fetch PR files (page {page}): {e}")
                break
    return results


async def fetch_file_content(repo: str, path: str, ref: str = "main") -> str:
    """Fetch raw content of a file from a repository."""
    url = f"{_GITHUB_API}/repos/{repo}/contents/{path}?ref={ref}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers=_headers("application/vnd.github.v3.raw"),
            )
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch file {path}: {e}")
        return ""


async def fetch_open_prs(repo: str) -> list[dict]:
    """Fetch all open PRs for a repository (used by heartbeat)."""
    url = f"{_GITHUB_API}/repos/{repo}/pulls?state=open&per_page=100"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers())
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch open PRs: {e}")
        return []


# ---------------------------------------------------------------------------
# Async post functions
# ---------------------------------------------------------------------------

async def post_comment(repo: str, pr_number: int, comment: str) -> bool:
    """Post a general comment on a PR (issue comment)."""
    url = f"{_GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=_headers(),
                json={"body": comment},
            )
            response.raise_for_status()
            logger.info(f"Posted comment on {repo}#{pr_number}")
            return True
    except httpx.HTTPError as e:
        logger.error(f"Failed to post comment: {e}")
        return False


async def post_review(
    repo: str,
    pr_number: int,
    body: str,
    event: str = "COMMENT",
    comments: list[dict] | None = None,
) -> bool:
    """
    Post a pull request review.

    Args:
        repo: "owner/repo"
        pr_number: PR number
        body: Top-level review body
        event: "APPROVE", "REQUEST_CHANGES", or "COMMENT"
        comments: Optional list of inline review comments
    """
    url = f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews"
    payload: dict = {"body": body, "event": event}
    if comments:
        payload["comments"] = comments

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=_headers(), json=payload)
            response.raise_for_status()
            logger.info(f"Posted review ({event}) on {repo}#{pr_number}")
            return True
    except httpx.HTTPError as e:
        logger.error(f"Failed to post review: {e}")
        return False
