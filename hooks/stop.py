#!/usr/bin/env python3
"""Stop hook — ask the model to persist what this session learned.

Three defects in the previous version, all observed in production:

1. It asserted where files could be written without checking. A sibling command
   (`ls`) was blocked once, the model generalized that to "the directory is
   unwritable", wrote that into memory, and two later sessions cited the note
   instead of retesting. This version probes each directory and states only what
   it measured.

2. "Do NOT skip saving — even short sessions have context worth preserving"
   made refusal impossible, so sessions with no substance manufactured filler.
   Skipping is now a first-class outcome with a stated reason.

3. It told the model to search for near-duplicates but gave it nothing to search
   against, so duplicates and dangling links got created anyway. The existing
   filenames are now handed over directly.

Never blocks a session on error: any exception exits 0.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

MARKER_TMPL = ".sy-memory-saved-{key}"
ALREADY_SAVED_SIGNALS = ("SY Memory Saved", "SY Memory Skipped")

# Tools whose use means the session actually changed something.
MUTATING_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Phrases that mean "save this" even in a session that touched no files.
SAVE_INTENT = ("기억해", "기억해줘", "remember", "다음부터", "규칙으로", "잊지", "메모해")


def did_substantive_work(transcript_path: str) -> bool:
    """Decide from the transcript whether asking the model to save is worth a turn.

    Blocking costs a full extra turn — the entire context is re-sent so the model
    can answer "nothing to save". Measured at ~36k input tokens for a trivial
    session, roughly 12x the cost of the SessionStart injection. A read-only Q&A
    session almost never produces a memory, so decide here instead of paying for
    the model to decide.
    """
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, TypeError):
        return True  # cannot tell → fall back to asking

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = entry.get("message") or {}
        content = msg.get("content")
        blocks = content if isinstance(content, list) else []

        if entry.get("type") == "assistant":
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_use" \
                        and b.get("name") in MUTATING_TOOLS:
                    return True

        elif entry.get("type") == "user" and not entry.get("isMeta"):
            # Scan only what the human typed. Scanning the raw transcript would
            # match the system prompt, which contains words like "remember" and
            # made this gate fire every time.
            texts = [content] if isinstance(content, str) else [
                b.get("text", "") for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = " ".join(texts).lower()
            if any(p in joined for p in SAVE_INTENT):
                return True

    return False


def writable(d: Path) -> bool:
    """Measure, do not assume. This check is the whole point of defect #1."""
    try:
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, prefix=".probe-", delete=True):
            return True
    except Exception:
        return False


def listing(d: Path, limit: int = 200) -> list[str]:
    try:
        return sorted(p.name for p in d.glob("*.md") if p.name != "INDEX.md")[:limit]
    except OSError:
        return []


def main() -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""

    # Loop guards
    if '"stop_hook_active": true' in raw.replace(" ", " ") or '"stop_hook_active":true' in raw:
        return 0
    if any(sig in raw for sig in ALREADY_SAVED_SIGNALS):
        return 0
    if "<omb>" in raw:  # mid-pipeline step, not a session end
        return 0

    # Cheap gate before the expensive one: if nothing was modified and the user
    # never asked to remember anything, stay silent rather than buy a turn.
    if os.environ.get("SY_MEMORY_ALWAYS_ASK") != "1":
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        tp = payload.get("transcript_path")
        if tp and not did_substantive_work(tp):
            return 0

    key = os.environ.get("CLAUDE_SESSION_ID") or str(os.getppid())
    marker = Path(tempfile.gettempdir()) / MARKER_TMPL.format(key=key)
    if marker.exists():
        return 0
    try:
        marker.touch()
    except OSError:
        pass

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    global_dir = Path(os.environ.get("SY_MEMORY_GLOBAL", Path.home() / ".sy" / "memory"))
    project_dir = Path(os.environ.get("SY_MEMORY_PROJECT", cwd / ".sy-memory"))

    g_ok, p_ok = writable(global_dir), writable(project_dir)
    if not (g_ok or p_ok):
        return 0  # nowhere to write; stay silent rather than demand the impossible

    targets = []
    if g_ok:
        targets.append(
            f"- **전역** `{global_dir}` (쓰기 확인됨) — 프로젝트를 넘어 재사용되는 것만:\n"
            f"  `user_*.md` 선호 · `feedback_*.md` 지시 · `tech_*.md` 패턴 · `lesson_*.md` 교훈"
        )
    if p_ok:
        targets.append(
            f"- **프로젝트** `{project_dir}` (쓰기 확인됨) — 이 저장소에서만 의미 있는 것만:\n"
            f"  `arch_*.md` 구조 · `decision_*.md` 결정 · `issue_*.md` 이슈 · `session_YYYY-MM-DD.md` 요약"
        )

    existing = []
    for label, d, ok in (("전역", global_dir, g_ok), ("프로젝트", project_dir, p_ok)):
        if not ok:
            continue
        names = listing(d)
        if names:
            existing.append(f"**{label}** ({len(names)}개): " + ", ".join(names))

    reason = f"""[SY Memory] 세션을 닫기 전에 이번에 알게 된 것을 남겨라.

## 먼저 판단하라 — 저장할 것이 있는가

다음뿐이라면 **저장하지 말고** `## SY Memory Skipped — <한 줄 사유>`만 출력하라. 그걸로 끝이다.
- 질문에 답만 한 대화
- 이미 저장된 내용의 재확인·재요약
- 다른 세션의 작업을 옮겨 적는 것

없는 교훈을 지어내는 것은 메모리를 오염시킨다. **비어 있는 편이 틀린 것보다 낫다.**

## 저장한다면

{chr(10).join(targets)}

### 기존 파일 (새로 만들기 전에 여기서 찾아라)
{chr(10).join(existing) if existing else "(없음)"}

이름이 비슷한 것이 있으면 **새 파일 대신 그 파일을 수정**하라. `[[링크]]`는 위 목록에 있는 이름만 써라.

### 형식
```
---
type: <tech|lesson|feedback|user|arch|decision|issue|session>
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [관련, 태그]
---
# 제목
내용...
```

**환경·능력에 대한 주장**("X는 차단됨", "Y는 설치 안 됨")을 적을 때는 `verify:` 필드에 그것을
1초에 반증할 수 있는 명령을 함께 적어라. 이런 주장은 세션마다 달라지므로 기억하면 안 되고 매번 재야 한다.
확신이 없으면 적지 마라.

### 마무리
1. 새 파일을 만들었으면 같은 디렉토리 `INDEX.md`에 **한 줄** 추가 (`- [파일명](파일명) — 한 줄 요약`).
   INDEX에 없는 파일은 다음 세션에서 보이지 않는다.
2. `## SY Memory Saved` 아래 저장·수정한 파일 목록을 출력하라.

사용자에게 확인을 묻지 마라."""

    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
