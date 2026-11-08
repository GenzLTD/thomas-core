#!/usr/bin/env python3
"""把一份 gfcc contracts/ 钉进 thomas-core/contracts/gfcc，并改 SOURCE.json 的 commit。"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


def sync(src: Path, dest: Path, commit: str, pinned_at: str) -> int:
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise SystemExit(f"commit 必须是 40 位小写 sha，收到 {commit!r}")
    files = [p for p in src.rglob("*") if p.is_file() and p.suffix in {".json", ".md"}]
    copied = []
    for path in files:
        rel = path.relative_to(src).as_posix()
        if rel == "SOURCE.json":
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        copied.append(rel)
    json_files = [name for name in copied if name.endswith(".json")]
    if len(json_files) != 14:
        raise SystemExit(f"期望从 gfcc 复制 14 个 JSON，实际 {len(json_files)}")
    if "README.md" not in copied:
        raise SystemExit("gfcc contracts/README.md 缺失")
    source_path = dest / "SOURCE.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["commit"] = commit
    source["pinned_at"] = pinned_at
    source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(json_files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--pinned-at", default=date.today().isoformat())
    args = parser.parse_args()
    count = sync(args.src, args.dest, args.commit.strip().lower(), args.pinned_at)
    print(f"pinned {count} json + README at {args.commit.strip().lower()}")


if __name__ == "__main__":
    main()
