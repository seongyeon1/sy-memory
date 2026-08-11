#!/usr/bin/env bash
# Hook + linter regression tests. No model calls — pure I/O contract checks.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ok()   { PASS=$((PASS+1)); echo "ok - $1"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL - $1"; }
check(){ if [[ "$1" == "$2" ]]; then ok "$3"; else bad "$3 (기대 '$2', 실제 '$1')"; fi; }
has()  { if [[ "$1" == *"$2"* ]]; then ok "$3"; else bad "$3"; fi; }
hasnt(){ if [[ "$1" != *"$2"* ]]; then ok "$3"; else bad "$3"; fi; }

# ---- fixture: a small memory pair ----
G="$TMP/global"; P="$TMP/project/.sy-memory"
mkdir -p "$G" "$P"
cat > "$G/feedback_commit_style.md" <<'EOF'
---
type: feedback
---
# 커밋 스타일
트레일러 없음.
EOF
cat > "$G/lesson_env_probe.md" <<'EOF'
---
type: lesson
verify: "echo WRITABLE"
---
# 환경 주장
EOF
printf -- '- [feedback_commit_style.md](feedback_commit_style.md) — 트레일러 없음\n' > "$G/INDEX.md"
cat > "$P/decision_thing.md" <<'EOF'
---
type: decision
---
# 결정
링크 [[feedback_commit_style]] 와 [[decision_missing_one]]
EOF
: > "$P/session_2026-01-01.md"
printf -- '- [decision_thing.md](decision_thing.md) — 결정\n- [session_2026-01-01.md](session_2026-01-01.md) — 로그\n' > "$P/INDEX.md"

export SY_MEMORY_GLOBAL="$G" SY_MEMORY_PROJECT="$P"

# ---- SessionStart ----
OUT="$(echo '{}' | python3 "$ROOT/hooks/session_start.py")"
CTX="$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])')"
has "$OUT" '"hookEventName": "SessionStart"' "SessionStart 이벤트명 올바름"
has "$CTX" "feedback_commit_style.md" "전역 메모리가 목차에 포함됨"
has "$CTX" "decision_thing.md" "프로젝트 메모리가 목차에 포함됨"
hasnt "$CTX" "session_2026-01-01.md" "session 로그는 목차에서 제외됨"
has "$CTX" "session 로그 1건" "제외된 session 개수는 표기됨"
has "$CTX" "재검증 필요" "verify: 보유 메모리가 경고에 노출됨"

# orphan (INDEX에 없는 파일) 도 노출되어야 한다
has "$CTX" "lesson_env_probe.md" "INDEX 누락 파일도 목차에 노출됨"

# 예산 준수: 낮은 예산을 주면 잘려서라도 맞춘다
SMALL="$(SY_MEMORY_BUDGET=300 bash -c "echo '{}' | python3 '$ROOT/hooks/session_start.py'" \
  | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"]))')"
if [[ "$SMALL" -lt 1200 ]]; then ok "예산 축소 시 주입량 감소 (${SMALL}자)"; else bad "예산 무시됨 (${SMALL}자)"; fi

# 메모리 디렉토리가 없으면 조용히 아무것도 안 한다
EMPTY="$(SY_MEMORY_GLOBAL=$TMP/none SY_MEMORY_PROJECT=$TMP/none2 bash -c "echo '{}' | python3 '$ROOT/hooks/session_start.py'")"
check "$EMPTY" "" "메모리 없으면 무출력"

# ---- Stop ----
S1="$(echo '{"session_id":"x"}' | CLAUDE_SESSION_ID=t-$$-1 python3 "$ROOT/hooks/stop.py")"
has "$S1" '"decision": "block"' "Stop이 저장을 요청함"
has "$S1" "SY Memory Skipped" "저장 생략 경로를 제공함"
has "$S1" "쓰기 확인됨" "쓰기 가능 여부를 실측해 보고함"
has "$S1" "feedback_commit_style.md" "기존 파일 목록을 함께 전달함"
has "$S1" "verify:" "환경 주장 규칙을 안내함"

S2="$(echo '{"session_id":"x"}' | CLAUDE_SESSION_ID=t-$$-1 python3 "$ROOT/hooks/stop.py")"
check "$S2" "" "같은 세션 재발화 안 함 (마커)"
S3="$(echo '{"t":"## SY Memory Saved"}' | CLAUDE_SESSION_ID=t-$$-2 python3 "$ROOT/hooks/stop.py")"
check "$S3" "" "이미 저장했으면 발화 안 함"
S4="$(echo '{"t":"## SY Memory Skipped — 없음"}' | CLAUDE_SESSION_ID=t-$$-3 python3 "$ROOT/hooks/stop.py")"
check "$S4" "" "생략 선언했으면 발화 안 함"
S5="$(echo '{"t":"<omb>step</omb>"}' | CLAUDE_SESSION_ID=t-$$-4 python3 "$ROOT/hooks/stop.py")"
check "$S5" "" "파이프라인 중간에는 발화 안 함"
S6="$(echo '{"stop_hook_active":true}' | CLAUDE_SESSION_ID=t-$$-5 python3 "$ROOT/hooks/stop.py")"
check "$S6" "" "stop_hook_active 루프 방지"

RO="$TMP/readonly"; mkdir -p "$RO"; chmod 500 "$RO"
S7="$(SY_MEMORY_GLOBAL=$RO SY_MEMORY_PROJECT=$RO bash -c "echo '{}' | CLAUDE_SESSION_ID=t-$$-6 python3 '$ROOT/hooks/stop.py'")"
chmod 700 "$RO"
check "$S7" "" "쓸 곳이 없으면 저장을 요구하지 않음"

# ---- linter ----
L="$(python3 "$ROOT/scripts/lint_index.py" "$G" "$P" 2>&1)"; LC=$?
has "$L" "dangling link — [[decision_missing_one]]" "실재하지 않는 링크를 잡아냄"
hasnt "$L" "[[feedback_commit_style]]" "디렉토리 교차 링크는 오탐하지 않음"
has "$L" "lesson_env_probe.md 인덱스에 없음" "orphan 을 잡아냄"
check "$LC" "1" "결함 있으면 exit 1"

python3 - "$G" "$P" <<'PY'
import sys
from pathlib import Path
g, p = Path(sys.argv[1]), Path(sys.argv[2])
idx = g / "INDEX.md"
idx.write_text(idx.read_text() + "- [lesson_env_probe.md](lesson_env_probe.md) — 환경 주장\n")
f = p / "decision_thing.md"
f.write_text(f.read_text().replace(" 와 [[decision_missing_one]]", ""))
PY
python3 "$ROOT/scripts/lint_index.py" "$G" "$P" >/dev/null 2>&1
check "$?" "0" "결함 해소 후 exit 0"

echo
echo "$PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
