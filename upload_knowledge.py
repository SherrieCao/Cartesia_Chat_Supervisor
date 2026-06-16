#!/usr/bin/env python3
"""Upload the local knowledge/ docs to this agent's Cartesia knowledge base.

This populates the *native* `knowledge_base` tool (a platform-hosted document
store, separate from the deployed code). The local `look_up_menu` tool already
answers menu/FAQ questions from restaurant_data.py; run this only if you also
want the hosted knowledge base populated (e.g. to update content from the
dashboard later, or to exercise the knowledge_base tool).

It is idempotent: re-running replaces documents with the same name rather than
creating duplicates, so regenerate knowledge/ and re-run whenever the menu
changes.

Usage:
    CARTESIA_API_KEY=sk_car_... python upload_knowledge.py

Optional env vars:
    CARTESIA_AGENT_ID    Target agent (default: read from .cartesia/config.toml)
    KB_FOLDER_NAME       Folder name (default: "Taniku Izakaya")
    KNOWLEDGE_DIR        Docs directory (default: "knowledge")
    CARTESIA_BASE_URL    API base (default: https://api.cartesia.ai)
    CARTESIA_VERSION     API version header (default: 2026-03-01)
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NoReturn

BASE_URL = os.getenv("CARTESIA_BASE_URL", "https://api.cartesia.ai").rstrip("/")
VERSION = os.getenv("CARTESIA_VERSION", "2026-03-01")
FOLDER_NAME = os.getenv("KB_FOLDER_NAME", "Taniku Izakaya")
KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", "knowledge"))


def die(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def get_api_key() -> str:
    key = os.getenv("CARTESIA_API_KEY")
    if not key:
        die("CARTESIA_API_KEY is not set. Run with "
            "CARTESIA_API_KEY=sk_car_... python upload_knowledge.py")
    return key


def get_agent_id() -> str:
    agent_id = os.getenv("CARTESIA_AGENT_ID")
    if agent_id:
        return agent_id
    # Fall back to the CLI's linked agent in .cartesia/config.toml
    cfg = Path(".cartesia/config.toml")
    if cfg.exists():
        try:
            import tomllib  # Python 3.11+
            data = tomllib.loads(cfg.read_text())
            if data.get("agent-id"):
                return data["agent-id"]
        except Exception:
            # Minimal fallback parse: agent-id = '...'
            for line in cfg.read_text().splitlines():
                if line.strip().startswith("agent-id"):
                    return line.split("=", 1)[1].strip().strip("'\"")
    die("No agent id. Set CARTESIA_AGENT_ID or run from a directory with "
        ".cartesia/config.toml")


API_KEY = get_api_key()
AGENT_ID = get_agent_id()


def api(method: str, path: str, body: "dict | None" = None) -> dict:
    """Call the Cartesia API and return the parsed JSON response."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-Key", API_KEY)
    req.add_header("Cartesia-Version", VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        die(f"{method} {path} -> HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        die(f"{method} {path} -> {e.reason}")


def find_folder() -> "dict | None":
    """Return the folder named FOLDER_NAME (with its documents/agents), or None."""
    params = urllib.parse.urlencode({"limit": 100, "depth": 1})
    after = None
    while True:
        q = params + (f"&starting_after={after}" if after else "")
        page = api("GET", f"/agents/folders?{q}")
        for folder in page.get("data", []):
            if folder.get("name") == FOLDER_NAME:
                return folder
        if not page.get("has_more"):
            return None
        after = page.get("next_page")
        if not after:
            return None


def main() -> None:
    if not KNOWLEDGE_DIR.is_dir():
        die(f"knowledge dir not found: {KNOWLEDGE_DIR.resolve()}")
    docs = sorted(KNOWLEDGE_DIR.glob("*.md"))
    if not docs:
        die(f"no .md files in {KNOWLEDGE_DIR.resolve()}")

    print(f"Agent:  {AGENT_ID}")
    print(f"Folder: {FOLDER_NAME}")
    print(f"Docs:   {', '.join(d.name for d in docs)}\n")

    # 1. Find or create the folder.
    folder = find_folder()
    if folder:
        folder_id = folder["id"]
        print(f"Using existing folder {folder_id}")
    else:
        folder = api("POST", "/agents/folders",
                     {"name": FOLDER_NAME, "parent_id": None})
        folder_id = folder["id"]
        print(f"Created folder {folder_id}")

    # 2. Delete any existing docs in this folder with names we're about to upload,
    #    so re-runs replace rather than duplicate.
    existing = {d.get("name"): d.get("id") for d in folder.get("documents", [])}
    for path in docs:
        if path.name in existing:
            api("DELETE", f"/agents/documents/{existing[path.name]}")
            print(f"  replaced existing '{path.name}'")

    # 3. Upload each document.
    for path in docs:
        content = path.read_text()
        if len(content.encode()) > 1_000_000:
            die(f"{path.name} exceeds the 1 MB document limit")
        created = api("POST", "/agents/documents", {
            "folder_id": folder_id,
            "name": path.name,
            "content": content,
            "metadata": {"source": path.name, "restaurant": "Taniku Izakaya"},
        })
        print(f"  uploaded '{path.name}' -> {created.get('id', '?')}")

    # 4. Attach this agent to the folder (merge with any existing agents — the
    #    PATCH replaces the full set, so include the others to avoid revoking).
    agent_ids = {a.get("id") for a in folder.get("agents", []) if a.get("id")}
    agent_ids.add(AGENT_ID)
    api("PATCH", f"/agents/folders/{folder_id}",
        {"agents": [{"id": a} for a in sorted(agent_ids)]})
    print(f"\nAttached folder to agent(s): {', '.join(sorted(agent_ids))}")
    print("Done. The knowledge_base tool will now return these docs.")


if __name__ == "__main__":
    main()
