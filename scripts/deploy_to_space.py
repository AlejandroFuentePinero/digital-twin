"""Deploy the working tree to the HF Space via huggingface_hub.upload_folder.

Why this and not ``git push``: HF Spaces rejects any blob >10 MB across the
entire git history unless tracked via LFS. The repo's git history carries
several historical large files (a regenerated ``eval/results/comparison.png``
from Sessions 24/27, the early-Session ``data/raw_me/*.pdf`` before it was
gitignored) that would force us to either migrate the GitHub repo to LFS
or rewrite history. Both are heavier than the Space deserves.

``upload_folder`` uploads a snapshot of the working tree directly via the
Hub API — LFS is negotiated transparently for files crossing the size
threshold, and the Space's git history is rebuilt as a single commit per
upload. The GitHub repo stays untouched.

Run from repo root:

    uv run python scripts/deploy_to_space.py

Reads ``HF_TOKEN`` from ``.env`` (write scope on the Space).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import HfApi

REPO_ROOT = Path(__file__).resolve().parent.parent
SPACE_ID = "Alejandrofupi/digital-twin"

# Files / directories NOT to upload. Mirrors .gitignore plus the Space's
# operational shape: no .env (secrets live in Space config), no virtualenv,
# no test caches, no IDE state, no internal-only docs, no per-session
# research drafts. The ChromaDB at ``data/preprocessed_db/`` IS uploaded
# (gitignored on GitHub for size reasons; the Space needs it at runtime).
IGNORE_PATTERNS = [
    ".git/**",
    ".venv/**",
    ".vscode/**",
    ".idea/**",
    ".claude/**",
    ".pytest_cache/**",
    ".DS_Store",
    "**/.DS_Store",
    "**/__pycache__/**",
    "**/*.pyc",
    ".module_health_report.json",
    "uv.lock",
    "data/logs/**",
    "data/raw_me/**",
    "docs/audits/**",
    "docs/agents/**",
    "docs/RELEASE_CHECKLIST.md",
    "docs/HUMAN_EVAL_QUESTIONS.md",
    "docs/PLAN.md",
    "docs/ARCHITECTURE.md",
    "docs/MAP.html",
    "course_skills.md",
    "course-notebooks/**",
    "example/**",
    ".env",
    ".env.example",
    "scripts/deploy_to_space.py",
    "scripts/verify_slice_b*.py",
]


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=True)
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN not set in .env", file=sys.stderr)
        return 1

    api = HfApi(token=token)
    print(f"Uploading working tree at {REPO_ROOT} -> {SPACE_ID} (Space)...")
    api.upload_folder(
        folder_path=str(REPO_ROOT),
        repo_id=SPACE_ID,
        repo_type="space",
        ignore_patterns=IGNORE_PATTERNS,
        commit_message="Deploy: Phase 7 slice 1 (#51) — Space packaging + privacy note",
    )
    print(f"Done. Watch the build at https://huggingface.co/spaces/{SPACE_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
