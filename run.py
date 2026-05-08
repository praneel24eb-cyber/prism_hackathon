"""
CodeGuardian — Autonomous PR Review Agent
Entry point for the server.

Usage:
    python run.py
"""

import os
import uvicorn
from dotenv import load_dotenv

# Load environment variables BEFORE importing anything else
load_dotenv()

from server.app import app  # noqa: E402


def main():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    print("=" * 60)
    print("  [*] CodeGuardian - PR Review Agent")
    print("=" * 60)
    print(f"  Server:    http://{host}:{port}")
    print(f"  Webhook:   http://{host}:{port}/webhook")
    print(f"  Health:    http://{host}:{port}/health")
    print(f"  Dashboard: http://{host}:{port}/dashboard")
    print(f"  LLM:       {os.getenv('LLM_PROVIDER', 'openai')}")
    print("=" * 60)

    dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    uvicorn.run(
        "server.app:app",
        host=host,
        port=port,
        reload=dev_mode,
        log_level="info",
    )


if __name__ == "__main__":
    main()
