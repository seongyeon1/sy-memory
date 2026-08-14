#!/usr/bin/env python3
"""Concurrency-safe memory writes.

Several Claude sessions can run in one project at once, and every one of them
fires a Stop hook that writes memory. The model writes with Write/Edit, which
replaces whole files, so the last session to finish silently erases what the
others added. Four failure modes were observed in production:

1. Overwrite  — two sessions write session_<date>.md; one is lost.
2. Lost index — both append a line to INDEX.md; one line vanishes.
3. Orphan     — the file lands but the index update does not, so the memory
                exists and is never surfaced again (the injector reads INDEX).
4. Mutual cleanup — both sessions notice the same duplicate pair and "fix" it in
                opposite directions, leaving zero copies. Cleanup is more
                dangerous than duplication: duplication leaves two files,
                disagreeing cleanup leaves none.

This tool serializes the writes that collide (flock + atomic replace) and makes
deduplication non-destructive.

  append    <file>              body on stdin, appended under a lock
  index     <dir> <name> <sum>  idempotent INDEX.md line upsert
  sync      <dir>               reconcile INDEX.md with what is on disk
  supersede <dir> <dup> <canon> mark a duplicate without deleting it

POSIX only (uses fcntl).
"""
from __future__ import annotations

import argparse
import fcntl
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

ENTRY_RE = re.compile(r"^-\s*\[([^\]]+)\]\(([^)]+)\)")


@contextmanager
def locked(target: Path):
    """Advisory lock keyed on the target path. Held for read-modify-write."""
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.parent / f".{target.name}.lock"
    fh = open(lock, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def atomic_write(path: Path, text: str) -> None:
    """Write via temp + rename so a reader never sees a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cmd_append(args) -> int:
    body = sys.stdin.read()
    if not body.strip():
        print("빈 입력 — 아무것도 하지 않음", file=sys.stderr)
        return 0
    path = Path(args.file).expanduser()
    with locked(path):
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if not existing.strip():
            today = date.today().isoformat()
            existing = (
                f"---\ntype: {args.type}\ncreated: {today}\nupdated: {today}\n"
                f"tags: []\n---\n\n# {path.stem}\n"
            )
        if not existing.endswith("\n"):
            existing += "\n"
        atomic_write(path, existing + "\n" + body.rstrip() + "\n")
    print(f"append → {path}")
    return 0


def _read_entries(index: Path) -> list[str]:
    if not index.exists():
        return []
    return index.read_text(encoding="utf-8").splitlines()


def cmd_index(args) -> int:
    mem = Path(args.dir).expanduser()
    index = mem / "INDEX.md"
    line = f"- [{args.name}]({args.name}) — {args.summary}"
    with locked(index):
        lines = _read_entries(index)
        replaced = False
        for i, l in enumerate(lines):
            m = ENTRY_RE.match(l.strip())
            if m and m.group(2) == args.name:
                lines[i] = line
                replaced = True
                break
        if not replaced:
            lines.append(line)
        atomic_write(index, "\n".join(lines) + "\n")
    print(f"{'update' if replaced else 'add'} → {index}: {args.name}")
    return 0


def cmd_sync(args) -> int:
    """Close the gap between disk and index in both directions."""
    mem = Path(args.dir).expanduser()
    index = mem / "INDEX.md"
    with locked(index):
        lines = _read_entries(index)
        indexed, kept = set(), []
        for l in lines:
            m = ENTRY_RE.match(l.strip())
            if not m:
                kept.append(l)
                continue
            name = m.group(2)
            if not (mem / name).exists():
                print(f"제거 (파일 없음): {name}")
                continue
            if name in indexed:
                print(f"제거 (중복 항목): {name}")
                continue
            indexed.add(name)
            kept.append(l)
        added = 0
        for p in sorted(mem.glob("*.md")):
            if p.name == "INDEX.md" or p.name in indexed:
                continue
            title = next(
                (ln.lstrip("# ").strip() for ln in p.read_text(encoding="utf-8").splitlines()
                 if ln.startswith("# ")), p.stem)
            kept.append(f"- [{p.name}]({p.name}) — {title}")
            added += 1
            print(f"추가 (색인 누락): {p.name}")
        atomic_write(index, "\n".join(kept) + "\n")
    print(f"sync 완료 — 추가 {added}")
    return 0


def cmd_supersede(args) -> int:
    """Retire a duplicate without deleting it.

    Refuses when the canonical file is missing or itself a stub, because that is
    exactly how two sessions cleaning up in opposite directions destroyed both
    copies. Losing a duplicate is cheap; losing the only copy is not.
    """
    mem = Path(args.dir).expanduser()
    dup, canon = mem / args.duplicate, mem / args.canonical
    if not dup.exists():
        print(f"중복본 없음: {dup}", file=sys.stderr)
        return 1
    if not canon.exists():
        print(f"거부 — 정본이 존재하지 않음: {canon}", file=sys.stderr)
        return 1
    canon_text = canon.read_text(encoding="utf-8")
    if len(canon_text) < 200 or "superseded_by:" in canon_text:
        print(f"거부 — 정본이 스텁이거나 이미 강등됨: {canon}", file=sys.stderr)
        return 1

    with locked(dup):
        today = date.today().isoformat()
        atomic_write(dup, (
            f"---\ntype: note\ncreated: {today}\nupdated: {today}\n"
            f"tags: [superseded]\nsuperseded_by: {canon.stem}\n---\n\n"
            f"# (중복 — 사용하지 말 것)\n\n"
            f"정본은 [[{canon.stem}]] (`{canon.name}`).\n"
            f"삭제하지 않고 남긴다 — 동시 세션이 서로 다른 방향으로 정리하면 양쪽 다 사라진다.\n"
        ))
    print(f"강등 → {dup.name} (정본 {canon.name})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("append", help="stdin 을 파일 끝에 잠금 하에 덧붙인다")
    a.add_argument("file")
    a.add_argument("--type", default="session")
    a.set_defaults(func=cmd_append)

    i = sub.add_parser("index", help="INDEX.md 한 줄을 잠금 하에 추가/갱신")
    i.add_argument("dir"); i.add_argument("name"); i.add_argument("summary")
    i.set_defaults(func=cmd_index)

    s = sub.add_parser("sync", help="INDEX.md 와 실제 파일을 양방향 정합")
    s.add_argument("dir")
    s.set_defaults(func=cmd_sync)

    d = sub.add_parser("supersede", help="중복본을 삭제 대신 강등")
    d.add_argument("dir"); d.add_argument("duplicate"); d.add_argument("canonical")
    d.set_defaults(func=cmd_supersede)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
