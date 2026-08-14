---
name: sy-save
description: Use when the user says to remember something ("이거 기억해", "다음부터 이렇게", "규칙으로 정하자"), corrects a repeated mistake, or settles a decision worth carrying into later sessions. The Stop hook also invokes this at session end.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# 메모리 저장

## 먼저: 저장할 가치가 있는가

**빈 메모리가 틀린 메모리보다 낫다.** 아래면 저장하지 말고 그렇다고 말하라.

- 질문에 답만 한 대화
- 이미 저장된 것의 재확인·재요약
- 코드·git 히스토리·CLAUDE.md를 읽으면 알 수 있는 것
- 이 대화에서만 의미 있는 것

## 어디에

| | 위치 | 접두사 |
|---|---|---|
| 프로젝트를 넘어 재사용 | `~/.sy/memory/` (`$SY_MEMORY_GLOBAL`) | `user_` 선호 · `feedback_` 지시 · `tech_` 패턴 · `lesson_` 교훈 |
| 이 저장소에서만 | `.sy-memory/` (`$SY_MEMORY_PROJECT`) | `arch_` 구조 · `decision_` 결정 · `issue_` 이슈 · `session_YYYY-MM-DD` 요약 |

**쓰기 전에 기존 파일 목록을 확인하라.** 이름이 비슷하면 새로 만들지 말고 그 파일을 고쳐라.
`[[링크]]`는 실재하는 파일명만 쓴다 — 두 디렉토리를 합쳐 한 네임스페이스다.

## 형식

```markdown
---
type: <tech|lesson|feedback|user|arch|decision|issue|session>
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [관련, 태그]
verify: "<선택 — 이 주장을 반증하는 명령>"
---

# 제목

내용. `feedback`·`lesson`은 **왜**와 **어떻게 적용하는지**를 함께.
```

## verify: 를 언제 쓰나

**환경·능력에 대한 주장은 기억하면 안 된다.** "X는 차단됨", "Y는 설치 안 됨", "Z는 실패함" —
세션·권한·버전에 따라 뒤집힌다. 굳이 적어야 하면 1초에 반증할 명령을 `verify:`에 함께 적어라.

> 실화: `ls` 한 번 막힌 것을 "디렉토리 쓰기 불가"로 적었고, 이후 두 세션이 **재검증 없이 그 기록을 인용**해
> 3주간 거짓이 사실로 굳었다. 실제로는 쓰기가 처음부터 정상이었다.

인접 동작의 실패는 근거가 아니다. 단정하기 전에 **그 동작 자체를** 해보라.

## 공유 파일은 반드시 도구로 (동시 세션 보호)

같은 프로젝트에서 다른 Claude 세션이 동시에 돌 수 있다. `INDEX.md`와 세션 파일은
공유 자원이라 `Write`로 덮으면 남의 저장분이 사라진다. **실측 유실률 30건 중 29건.**

```bash
T=<이 저장소>/scripts/memory_tool.py

python3 $T index <디렉토리> <파일명> "<한 줄 요약>"   # INDEX 등록 (잠금·멱등)
printf '%s' "$본문" | python3 $T append <세션파일>     # 세션 파일 덧붙이기
python3 $T sync <디렉토리>                            # 색인 ↔ 파일 정합 점검
```

새로 만드는 개별 메모리 파일은 이름이 겹치지 않으므로 `Write`로 써도 된다.

## 중복은 삭제하지 말고 강등하라

```bash
python3 $T supersede <디렉토리> <중복본> <정본>
```

두 세션이 같은 중복 쌍을 **서로 반대 방향으로** 정리해 양쪽 다 사라진 적이 있다.
중복은 파일이 2개 남지만, 어긋난 정리는 0개를 만든다.
이 명령은 정본이 없거나 스텁이면 거부한다.

## 마무리 (빠뜨리면 저장이 무효다)

1. **INDEX 등록은 필수.** INDEX에 없는 파일은 다음 세션 목차에 안 뜬다. 있어도 없는 것이다.
2. 틀린 것으로 밝혀진 메모리는 지우지 말고 **취소선 + 정정 사유**를 남겨라.
   왜 틀렸는지가 사실보다 재사용성이 높다.
3. `## SY Memory Saved` 아래 저장·수정한 파일을 나열하라.
