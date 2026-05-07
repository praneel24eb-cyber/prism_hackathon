# CodeGuardian — Skill Registry

skills:

  # --- Layer 1: Input ---
  - name: webhook_receiver
    description: Receives GitHub webhook events and verifies HMAC-SHA256 signatures
    trigger: GitHub PR event (opened, synchronize, reopened)
    module: server.app

  # --- Layer 2: Context Retrieval ---
  - name: pr_diff_fetcher
    description: Fetches unified diff for a pull request via GitHub API
    input: diff_url from webhook payload
    output: Raw diff text
    module: server.github

  - name: pr_files_fetcher
    description: Fetches list of changed files with additions/deletions metadata
    input: repo, pr_number
    output: List of file change summaries
    module: server.github

  - name: file_content_fetcher
    description: Fetches raw content of individual files from the repository
    input: repo, file_path, branch_ref
    output: File source code
    module: server.github

  # --- Layer 3: Multi-Agent Processing ---
  - name: security_analyzer
    description: Analyzes code for security vulnerabilities (injection, secrets, auth flaws, SSRF, crypto issues)
    input: diff + context
    output: Structured list of security findings with severity
    module: server.agent

  - name: performance_analyzer
    description: Analyzes code for performance issues (N+1 queries, blocking calls, memory leaks, inefficient algorithms)
    input: diff + context
    output: Structured list of performance findings with severity
    module: server.agent

  - name: test_coverage_analyzer
    description: Identifies missing tests, untested edge cases, and coverage gaps
    input: diff + context
    output: Structured list of test coverage findings with severity
    module: server.agent

  - name: architecture_analyzer
    description: Reviews code for architectural issues (SOLID violations, layer boundaries, duplication)
    input: diff + context
    output: Structured list of architecture findings with severity
    module: server.agent

  # --- Layer 4: Reasoning & Triage ---
  - name: severity_classifier
    description: Classifies issues into BLOCKER, WARNING, SUGGESTION based on impact
    module: server.utils

  - name: risk_scorer
    description: Calculates regression risk score (1-10) based on diff size, file spread, test coverage, and issue severity
    module: server.agent

  - name: issue_deduplicator
    description: Merges identical issues flagged by multiple agents
    module: server.agent

  # --- Layer 5: Action & Notification ---
  - name: github_review_poster
    description: Posts structured review to GitHub PR with appropriate action (APPROVE, COMMENT, REQUEST_CHANGES)
    module: server.github

  # --- Layer 6: Memory & Learning ---
  - name: review_historian
    description: Persists review results to history.json for learning
    module: server.memory

  - name: author_profiler
    description: Tracks per-developer patterns and common issues
    module: server.memory

  - name: false_positive_tracker
    description: Records dismissed flags and suppresses issues flagged as false positive 3+ times
    module: server.memory