#!/usr/bin/env python3
"""Lint a memory directory: INDEX.md entry budget, orphans, dangling wikilinks.

Why the entry budget exists: INDEX.md is injected into context at SessionStart.
An index whose entries are paragraphs stops being an index and starts being a
second copy of the memory files, which is what it was supposed to summarize.

Exit codes: 0 clean, 1 violations found, 2 usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_MAX_ENTRY = 200
DEFAULT_MAX_TOTAL = 8000

# "- [name.md](name.md) — summary"
ENTRY_RE = re.compile(r"^-\s*\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)\s*(?P<summary>.*)$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
# Memory files are named <type>_<slug>.md. A wikilink that does not match this
# shape is referring to something else (a block id, a branch name) — not a
# broken memory link. Validating those produces false positives.
MEMORY_SLUG_RE = re.compile(r"^(user|feedback|tech|lesson|arch|decision|issue|session)_")


def scan(mem_dir: Path, max_entry: int, max_total: int, known_stems: set[str]) -> tuple[list[str], dict]:
    problems: list[str] = []
    index_path = mem_dir / "INDEX.md"

    md_files = {p.name for p in mem_dir.glob("*.md") if p.name != "INDEX.md"}
    if not index_path.exists():
        return ([f"{mem_dir}: INDEX.md 없음 ({len(md_files)}개 메모리 파일 존재)"], {})

    lines = index_path.read_text(encoding="utf-8").splitlines()
    entries: list[tuple[int, str, str]] = []  # (lineno, target, whole line)
    for i, line in enumerate(lines, 1):
        m = ENTRY_RE.match(line.strip())
        if m:
            entries.append((i, m.group("target"), line.strip()))

    # 1-2. Length is a WARNING, not a failure: the SessionStart hook truncates
    # each entry at injection time, so the budget is enforced structurally.
    # Long entries only mean the human-facing index is drifting into a log.
    warnings: list[str] = []
    over = [(n, t, len(l)) for n, t, l in entries if len(l) > max_entry]
    for n, t, ln in sorted(over, key=lambda x: -x[2])[:5]:
        warnings.append(f"{index_path.name}:{n} 항목 {ln}자 (>{max_entry}, 주입 시 잘림) — {t}")
    if len(over) > 5:
        warnings.append(f"... 외 {len(over) - 5}건 초과 항목")

    total = len(index_path.read_text(encoding="utf-8"))
    if total > max_total:
        warnings.append(f"{index_path.name} 전체 {total}자 (>{max_total}) — 주입 시 요약본 사용")

    # 3. index points at files that exist
    indexed = set()
    for n, target, _ in entries:
        indexed.add(target)
        if target not in md_files and not (mem_dir / target).exists():
            problems.append(f"{index_path.name}:{n} 대상 파일 없음 — {target}")

    # 4. files that exist but are not indexed
    for orphan in sorted(md_files - indexed):
        problems.append(f"{orphan} 인덱스에 없음 (orphan)")

    # 5. duplicate index entries
    seen: dict[str, int] = {}
    for n, target, _ in entries:
        if target in seen:
            problems.append(f"{index_path.name}:{n} 중복 항목 — {target} (최초 {seen[target]}행)")
        else:
            seen[target] = n

    # 6. dangling wikilinks — resolved against the union of ALL memory dirs,
    #    because the wikilink namespace spans global and project.
    for p in sorted(mem_dir.glob("*.md")):
        for raw in set(WIKILINK_RE.findall(p.read_text(encoding="utf-8"))):
            target = raw.strip()
            if not MEMORY_SLUG_RE.match(target):
                continue
            if target not in known_stems:
                problems.append(f"{p.name} dangling link — [[{target}]]")

    stats = {
        "entries": len(entries),
        "files": len(md_files),
        "total_chars": total,
        "max_entry": max(((len(l)) for _, _, l in entries), default=0),
        "avg_entry": round(sum(len(l) for _, _, l in entries) / len(entries)) if entries else 0,
        "over_budget": len(over),
        "warnings": warnings,
    }
    return problems, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dirs", nargs="+", help="memory directories to lint")
    ap.add_argument("--max-entry", type=int, default=DEFAULT_MAX_ENTRY)
    ap.add_argument("--max-total", type=int, default=DEFAULT_MAX_TOTAL)
    args = ap.parse_args()

    dirs = [Path(d).expanduser() for d in args.dirs]
    # Wikilinks resolve across every directory passed in — lint them together,
    # or every cross-directory link reads as dangling.
    known_stems = {p.stem for d in dirs if d.is_dir() for p in d.glob("*.md")}

    failed = False
    for mem_dir in dirs:
        if not mem_dir.is_dir():
            print(f"skip (없음): {mem_dir}")
            continue
        problems, stats = scan(mem_dir, args.max_entry, args.max_total, known_stems)
        print(f"\n=== {mem_dir} ===")
        if stats:
            print(
                f"파일 {stats['files']} · 항목 {stats['entries']} · "
                f"평균 {stats['avg_entry']}자 · 최대 {stats['max_entry']}자 · "
                f"총 {stats['total_chars']}자"
            )
        for w in stats.get("warnings", []):
            print(f"  WARN {w}")
        if problems:
            failed = True
            for p in problems:
                print(f"  FAIL {p}")
            print(f"  -- FAIL {len(problems)}건")
        elif not stats.get("warnings"):
            print("  OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
