#!/usr/bin/env bash
# Probe runner that cannot touch the real workspace.
#
# Why this exists: probes include imperative requests ("commit and push this"),
# and the runner drives Claude with --dangerously-skip-permissions. Run against
# the live repo, P-01 committed 12 real files and pushed them to origin. The
# probe was doing exactly what it was asked; the harness was the problem.
#
# The sandbox is a throwaway directory holding copies of the project context
# (CLAUDE.md, .sy-memory) plus a copy of global memory, with its own git repo
# and no remote. Action probes still act — into a scratch clone that is deleted.
#
# LIMITATION — this is mitigation, not containment. The agent runs with
# --dangerously-skip-permissions and can still read and write anywhere on the
# filesystem; one probe here read the real project directory from inside the
# sandbox. What the sandbox removes is the *default* target: cwd is a scratch
# repo with a clean tree and no remote, so "commit and push this" has nothing to
# sweep up and nowhere to send it. For real containment, use a VM or container.
#
#   bash runner_sandbox.sh B          # injection condition
#   bash runner_sandbox.sh A0         # pure-model control (no memory, no CLAUDE.md)
#   bash runner_sandbox.sh B P-04,P-05
set -uo pipefail

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS_DIR="${TARGET_PROJECT:-$(cd "$BENCH_DIR/.." && pwd)}"
RESULTS_DIR="$BENCH_DIR/results"
PROBES="$BENCH_DIR/probes.jsonl"
HOOK="${SY_MEMORY_HOOK:-$(cd "$BENCH_DIR/../hooks" && pwd)/session_start.py}"

MODE="${1:-B}"
ONLY="${2:-}"

mkdir -p "$RESULTS_DIR"
SANDBOX="$(mktemp -d -t syprobe)"
cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT INT TERM

# ---- build the sandbox ----
# Source dirs honour the same env vars the hooks use. Hardcoding ~/.sy/memory
# here meant a user with memory elsewhere measured an empty corpus.
SRC_PROJECT="${SY_MEMORY_PROJECT:-$HARNESS_DIR/.sy-memory}"
SRC_GLOBAL="${SY_MEMORY_GLOBAL:-$HOME/.sy/memory}"

cp "$HARNESS_DIR/CLAUDE.md" "$SANDBOX/" 2>/dev/null || true

# Fail loudly. Without this the script happily ran 20 expensive probes against a
# corpus that was never copied and reported the result as if it meant something
# — a benchmark that silently measures nothing is worse than one that crashes.
copied=0
if [[ -d "$SRC_PROJECT" ]]; then
  cp -R "$SRC_PROJECT" "$SANDBOX/.sy-memory" && copied=$((copied+1))
else
  echo "[sandbox] 프로젝트 메모리 없음: $SRC_PROJECT" >&2
fi
if [[ -d "$SRC_GLOBAL" ]]; then
  cp -R "$SRC_GLOBAL" "$SANDBOX/global-memory" && copied=$((copied+1))
else
  echo "[sandbox] 전역 메모리 없음: $SRC_GLOBAL" >&2
fi
if [[ "$MODE" != "A0" && "$copied" -eq 0 ]]; then
  echo "[sandbox] 중단 — 복사된 메모리가 없어 $MODE 조건이 성립하지 않는다." >&2
  echo "[sandbox] SY_MEMORY_PROJECT / SY_MEMORY_GLOBAL 로 경로를 지정하라." >&2
  exit 2
fi
mkdir -p "$SANDBOX/.claude"

# Only SessionStart. The Stop hook would overwrite answers with a save report.
#
# C is the control that actually isolates the hook: same day, same model, same
# memory corpus, same sandbox — injection is the only difference. The 2026-05
# "auto" baseline cannot play this role, since model version and memory contents
# both moved since then.
if [[ "$MODE" == "C" ]]; then
  echo '{}' > "$SANDBOX/.claude/settings.json"   # memory on disk, no injection
elif [[ "$MODE" == "B" ]]; then
  cat > "$SANDBOX/.claude/settings.json" <<EOF
{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"$HOOK","timeout":10000}]}]}}
EOF
else
  # A0: no memory, no project context — measures what the model says unaided.
  rm -rf "$SANDBOX/.sy-memory" "$SANDBOX/global-memory" "$SANDBOX/CLAUDE.md"
  echo '{}' > "$SANDBOX/.claude/settings.json"
fi

git -C "$SANDBOX" init -q 2>/dev/null
git -C "$SANDBOX" add -A 2>/dev/null
git -C "$SANDBOX" -c user.email=probe@local -c user.name=probe commit -qm "sandbox baseline" 2>/dev/null

export SY_MEMORY_GLOBAL="$SANDBOX/global-memory"
export SY_MEMORY_PROJECT="$SANDBOX/.sy-memory"

echo "[sandbox] $SANDBOX (mode=$MODE)"

total=$(wc -l < "$PROBES" | tr -d ' ')
i=0
while IFS= read -r line; do
  i=$((i+1))
  id=$(printf '%s' "$line" | python3 -c "import sys,json;print(json.loads(sys.stdin.read())['id'])")
  query=$(printf '%s' "$line" | python3 -c "import sys,json;print(json.loads(sys.stdin.read())['query'])")
  [[ -n "$ONLY" && ",$ONLY," != *",$id,"* ]] && continue

  out="$RESULTS_DIR/probe-${id}-${MODE}.txt"
  [[ -s "$out" ]] && { echo "[$i/$total] $id $MODE (cached)"; continue; }

  echo "[$i/$total] $id $MODE"
  if [[ "$MODE" == "B" || "$MODE" == "C" ]]; then
    # Same plugin, same memory, same sandbox — only the SessionStart hook differs.
    ( cd "$SANDBOX" && printf '%s\n' "$query" \
        | claude --dangerously-skip-permissions \
            --print ) > "$out" 2>&1 \
        || echo "[runner_sandbox] $id exit $?" >> "$out"
  else
    ( cd "$SANDBOX" && printf '%s\n' "$query" \
        | claude --dangerously-skip-permissions --print ) > "$out" 2>&1 \
        || echo "[runner_sandbox] $id exit $?" >> "$out"
  fi
done < "$PROBES"

echo "done ($MODE)"
