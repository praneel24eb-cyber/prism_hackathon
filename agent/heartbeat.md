# CodeGuardian — Heartbeat Configuration

# How often the daemon checks for stale PRs
interval: 24h

# PRs without review older than this threshold are flagged
stale_threshold: 24h

# Tasks executed on each heartbeat cycle
tasks:
  - Check all configured repos for open PRs without CodeGuardian review
  - Flag PRs older than stale_threshold as needing attention
  - Re-trigger analysis on stale PRs if auto_retrigger is enabled
  - Log stale PR warnings with PR number, author, and age

# Configuration
auto_retrigger: false  # Set to true to automatically re-run analysis
notify_on_stale: true  # Log warnings for stale PRs
max_retriggers: 2      # Maximum re-analysis attempts per PR