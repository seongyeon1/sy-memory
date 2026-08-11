#!/usr/bin/env bash
# Register the SessionStart + Stop hooks with Claude Code.
#
#   ./install.sh              → this project (.claude/settings.json)
#   ./install.sh --user       → every project (~/.claude/settings.json)
#   ./install.sh --uninstall  → remove both hooks, leave memory files alone
#
# Idempotent: re-running replaces the sy-memory entries and touches nothing else.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SCOPE="project"
ACTION="install"

for arg in "$@"; do
  case "$arg" in
    --user) SCOPE="user" ;;
    --uninstall) ACTION="uninstall" ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$SCOPE" == "user" ]]; then
  SETTINGS="$HOME/.claude/settings.json"
else
  SETTINGS="$PWD/.claude/settings.json"
fi
mkdir -p "$(dirname "$SETTINGS")"
[[ -f "$SETTINGS" ]] || echo '{}' > "$SETTINGS"

python3 - "$SETTINGS" "$ROOT" "$ACTION" <<'PY'
import json, sys, shutil
from pathlib import Path

settings_path, root, action = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

try:
    data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
except json.JSONDecodeError:
    sys.exit(f"[install] {settings_path} 가 올바른 JSON이 아닙니다. 먼저 고쳐주세요.")

if settings_path.exists():
    shutil.copy(settings_path, str(settings_path) + ".sy-backup")

hooks = data.setdefault("hooks", {})

def strip(event: str) -> None:
    """Drop only our own entries, preserving any other hooks on the event."""
    groups = []
    for group in hooks.get(event, []):
        kept = [h for h in group.get("hooks", []) if "sy-memory" not in str(h.get("command", ""))]
        if kept:
            groups.append({**group, "hooks": kept})
    if groups:
        hooks[event] = groups
    else:
        hooks.pop(event, None)

strip("SessionStart")
strip("Stop")

if action == "install":
    for event, script, timeout in (
        ("SessionStart", "hooks/session_start.py", 10000),
        ("Stop", "hooks/stop.py", 15000),
    ):
        entry = {"type": "command", "command": f"{root}/{script}", "timeout": timeout}
        hooks.setdefault(event, []).append({"hooks": [entry]})

if not hooks:
    data.pop("hooks", None)

settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"[install] {action} → {settings_path}")
PY

chmod +x "$ROOT/hooks/session_start.py" "$ROOT/hooks/stop.py" "$ROOT/scripts/lint_index.py"

if [[ "$ACTION" == "install" ]]; then
  mkdir -p "${SY_MEMORY_GLOBAL:-$HOME/.sy/memory}"
  [[ "$SCOPE" == "project" ]] && mkdir -p "${SY_MEMORY_PROJECT:-$PWD/.sy-memory}"
  echo "[install] 완료. 새 세션부터 메모리 목차가 주입됩니다."
  echo "[install] 스킬을 쓰려면: cp -r $ROOT/skills/* .claude/skills/"
fi
