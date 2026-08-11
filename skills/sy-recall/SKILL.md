---
name: sy-recall
description: Use when the user asks what was decided, learned, or preferred previously — "예전에 뭐라고 했지", "우리 컨벤션이 뭐였지", "지난번 결정", "기억나?", or before repeating work that may already have an established answer. Also use when a stored environment claim needs rechecking.
allowed-tools: Read, Glob, Grep, Bash
---

# 메모리 조회

세션 시작 시 훅이 **목차**를 이미 주입했다. 이 스킬은 목차에서 본문으로 내려가는 단계다.
목차에 없는 것을 찾을 때만 Glob으로 넓혀라.

## 순서

1. **주입된 목차부터 본다.** 파일명이 이미 키워드다 — `feedback_commit_style`, `lesson_pixel_art_iteration`.
   질문과 겹치는 이름이 있으면 그 파일을 Read로 연다.
2. 목차에 없으면 `Grep`으로 두 디렉토리 본문을 검색한다.
   - 프로젝트: `.sy-memory/` (`$SY_MEMORY_PROJECT`)
   - 전역: `~/.sy/memory/` (`$SY_MEMORY_GLOBAL`)
   - 목차는 `session_*.md`를 생략한다. 날짜·이력을 물으면 그쪽을 Glob으로 직접 찾아라.
3. 관련 파일을 **전문으로** 읽는다. 목차 한 줄로 답하지 마라 — 목차는 요약이라 조건·예외가 잘려 있다.

## 신뢰 규칙

- **`verify:` 필드가 있으면 본문을 인용하기 전에 그 명령을 실행하라.** 환경·능력 주장은
  세션마다 달라진다. 실행 결과가 본문과 다르면 **결과를 따르고 그 메모리를 정정하라.**
- 메모리와 현재 코드가 어긋나면 **코드를 믿고** 메모리가 낡았다고 알려라.
- 취소선(`~~`)으로 정정된 구간은 과거 기록이다. 정정문을 따르라.

## 출력

찾은 것을 짧게 보고하고 바로 본래 작업에 적용하라.

```
## 메모리
- `feedback_commit_style.md` — Co-Authored-By 트레일러 넣지 않음
```

관련 메모리가 없으면 **없다고 한 줄로 말하고 넘어가라.** 억지로 갖다 붙이지 마라.
