#!/usr/bin/env python3
"""SessionStart hook — inject a bounded memory table of contents.

The measured bottleneck of this memory system was never retrieval accuracy; it
was that the model never went looking. Benchmark: autonomous recall fired on
2/20 probes (D1=0.10) while retrieval, once forced, scored P@1=0.60. Memory the
model does not know exists is memory that does not exist.

This hook makes existence free: every session starts already knowing what is
stored, so "should I look this up" becomes answerable without a tool call.

Budget is enforced structurally. Entries are truncated to fit SY_MEMORY_BUDGET
characters rather than relying on humans to keep INDEX.md short — an index that
depends on discipline degrades into a second copy of the memory files.

Never fails a session: any error exits 0 with no injection.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ENTRY_RE = re.compile(r"^-\s*\[(?P<label>[^\]]+)\]\([^)]+\)\s*(?:—|-|:)?\s*(?P<summary>.*)$")
VERIFY_RE = re.compile(r"^verify:\s*(.+)$", re.MULTILINE)

DEFAULT_BUDGET = 5000
SUMMARY_STEPS = [140, 110, 90, 70, 55, 40, 25, 0]


def read_index(mem_dir: Path, skip_sessions: bool) -> tuple[list[tuple[str, str]], int]:
    """Return ([(filename, summary)], skipped_session_count).

    Session logs are dated journal entries, not topic-retrievable knowledge, and
    they outnumber everything else. Listing them crowds out the entries that a
    keyword actually matches, so they are summarized as a count instead.
    """
    index = mem_dir / "INDEX.md"
    rows: list[tuple[str, str]] = []
    indexed: set[str] = set()
    skipped = 0

    if index.exists():
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            m = ENTRY_RE.match(line.strip())
            if not m:
                continue
            name = m.group("label").strip()
            indexed.add(name)
            if skip_sessions and name.startswith("session_"):
                skipped += 1
                continue
            rows.append((name, " ".join(m.group("summary").split())))

    # Orphans still exist even when the index forgot them — list them, or the
    # injection would silently hide memories that are on disk.
    for p in sorted(mem_dir.glob("*.md")):
        if p.name == "INDEX.md" or p.name in indexed:
            continue
        if skip_sessions and p.name.startswith("session_"):
            skipped += 1
            continue
        rows.append((p.name, ""))
    return rows, skipped


def find_verifiable(mem_dir: Path) -> list[str]:
    """Memory files carrying a `verify:` command — claims that must be retested."""
    out = []
    for p in sorted(mem_dir.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:600]
        except OSError:
            continue
        if VERIFY_RE.search(head):
            out.append(p.name)
    return out


def render(sections: list[tuple[str, Path, list[tuple[str, str]], int]], budget: int) -> str:
    """Render at the largest summary length that fits the budget."""
    for width in SUMMARY_STEPS:
        parts = []
        for title, path, rows, skipped in sections:
            note = f" (+ session 로그 {skipped}건은 Glob으로 조회)" if skipped else ""
            parts.append(f"\n## {title} — {len(rows)}개{note}  `{path}`")
            for name, summary in rows:
                if width and summary:
                    s = summary if len(summary) <= width else summary[: width - 1] + "…"
                    parts.append(f"- {name} — {s}")
                else:
                    parts.append(f"- {name}")
        body = "\n".join(parts)
        if len(body) <= budget:
            return body

    # Floor reached (filenames only) and still over budget: drop entries rather
    # than blow the budget, and say how many were dropped so the omission is
    # visible instead of silent. Past this point the index is too large for the
    # inject-a-map approach — see README on scale limits.
    kept, dropped = [], 0
    used = 0
    for title, path, rows, skipped in sections:
        head = f"\n## {title} — {len(rows)}개  `{path}`"
        kept.append(head)
        used += len(head) + 1
        for name, _ in rows:
            line = f"- {name}"
            if used + len(line) + 80 > budget:
                dropped += 1
                continue
            kept.append(line)
            used += len(line) + 1
    if dropped:
        kept.append(f"\n(+ {dropped}개는 예산 초과로 생략 — `Glob` 으로 조회)")
    return "\n".join(kept)


def main() -> int:
    try:
        sys.stdin.read()  # drain; payload unused
    except Exception:
        pass

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    global_dir = Path(os.environ.get("SY_MEMORY_GLOBAL", Path.home() / ".sy" / "memory"))
    project_dir = Path(os.environ.get("SY_MEMORY_PROJECT", cwd / ".sy-memory"))
    budget = int(os.environ.get("SY_MEMORY_BUDGET", DEFAULT_BUDGET))
    skip_sessions = os.environ.get("SY_MEMORY_INCLUDE_SESSIONS", "0") != "1"

    sections = []
    verifiable: list[str] = []
    for title, d in (("프로젝트", project_dir), ("전역", global_dir)):
        if not d.is_dir():
            continue
        rows, skipped = read_index(d, skip_sessions)
        if rows or skipped:
            sections.append((title, d, rows, skipped))
            verifiable += find_verifiable(d)

    if not sections:
        return 0

    header = (
        "# 저장된 메모리 목차 (SY Memory)\n"
        "이전 세션들이 남긴 결정·교훈·선호의 목록이다. **본문이 아니라 목차다.**\n"
        "관련 있어 보이는 항목이 있으면 그 파일을 Read로 열어 전문을 확인한 뒤 답하라.\n"
        "지금 질문과 무관하면 무시하면 된다 — 언급할 필요 없다."
    )
    footer = ""
    if verifiable:
        names = ", ".join(sorted(set(verifiable))[:8])
        footer = (
            f"\n\n**재검증 필요**: frontmatter에 `verify:`가 있는 메모리는 "
            f"환경·능력에 대한 주장이라 시간이 지나면 거짓이 될 수 있다. "
            f"본문을 인용하기 전에 그 명령을 실행해 확인하라. ({names})"
        )

    body = render(sections, budget)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": header + "\n" + body + footer,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never break a session over memory injection
