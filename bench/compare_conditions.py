#!/usr/bin/env python3
"""Compare probe conditions on D1' (did memory reach the unforced answer).

Conditions are result-file suffixes:
  auto  memory on disk, no index injection, sy plugin   (2026-05 baseline)
  B     memory on disk + SessionStart index injection   (sandboxed)
  A0    no memory, no project CLAUDE.md                 (pure-model control)

Reports per-probe hits so inflated signals stay visible rather than averaged away.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RESULTS = BENCH / "results"
PROBES = [json.loads(l) for l in (BENCH / "probes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

RECALL_SIGNALS = [r"\bsy:recall\b", r"Skill\(['\"]sy:recall['\"]\)", r"sy 메모리.{0,20}검색"]
# A signal this short proves nothing on its own — a generic word can appear for
# a dozen reasons unrelated to memory.
WEAK_MAX_LEN = 4


def read(pid: str, suffix: str) -> str:
    p = RESULTS / f"probe-{pid}-{suffix}.txt"
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def hits(text: str, probe: dict) -> tuple[list[str], list[str]]:
    """Return (strong, weak) matched signals."""
    strong, weak = [], []
    for s in probe.get("expected_signals", []):
        if re.search(re.escape(s), text, re.IGNORECASE):
            (weak if len(s) <= WEAK_MAX_LEN else strong).append(s)
    for m in probe["expected"]:
        if m in text:
            strong.append(m)
    return strong, weak


def score(suffix: str) -> dict:
    rows = []
    for p in PROBES:
        t = read(p["id"], suffix)
        st, wk = hits(t, p)
        rows.append({
            "id": p["id"],
            "present": bool(t.strip()),
            "strong": st,
            "weak": wk,
            "recall_called": any(re.search(r, t, re.IGNORECASE) for r in RECALL_SIGNALS),
        })
    n = sum(1 for r in rows if r["present"]) or 1
    return {
        "suffix": suffix,
        "n": sum(1 for r in rows if r["present"]),
        "d1_strict": round(sum(1 for r in rows if r["strong"]) / n, 3),
        "d1_loose": round(sum(1 for r in rows if r["strong"] or r["weak"]) / n, 3),
        "recall_rate": round(sum(1 for r in rows if r["recall_called"]) / n, 3),
        "rows": rows,
    }


def main() -> int:
    suffixes = sys.argv[1:] or ["auto", "B", "A0"]
    scored = {s: score(s) for s in suffixes}

    print(f"{'조건':<6}{'n':>4}{'D1′ strong':>12}{'D1′ loose':>11}{'recall 호출':>12}")
    for s, d in scored.items():
        if d["n"] == 0:
            print(f"{s:<6}{'—':>4}  (결과 없음)")
            continue
        print(f"{s:<6}{d['n']:>4}{d['d1_strict']:>12}{d['d1_loose']:>11}{d['recall_rate']:>12}")

    have = [s for s in suffixes if scored[s]["n"] > 0]

    # Rates above are computed per condition over whatever completed, so a
    # partially-finished condition is not comparable to a finished one.
    # Restrict to probes present in every condition before comparing.
    if len(have) >= 2:
        common = [i for i in range(len(PROBES))
                  if all(scored[s]["rows"][i]["present"] for s in have)]
        if common and len(common) < len(PROBES):
            print(f"\n공통 프로브 {len(common)}개로 맞춘 비교")
            for s in have:
                rows = [scored[s]["rows"][i] for i in common]
                strict = sum(1 for r in rows if r["strong"]) / len(common)
                loose = sum(1 for r in rows if r["strong"] or r["weak"]) / len(common)
                print(f"  {s:<6} strong={strict:.3f}  loose={loose:.3f}")

    if len(have) >= 2:
        print("\n프로브별 strong 신호 (조건 비교)")
        print(f"{'ID':<6}" + "".join(f"{s:>8}" for s in have) + "  차이")
        for i, p in enumerate(PROBES):
            cells = []
            for s in have:
                r = scored[s]["rows"][i]
                cells.append("O" if r["strong"] else ("~" if r["weak"] else "."))
            note = ""
            if len(have) >= 2 and cells[0] != cells[-1]:
                note = f"{have[0]}={cells[0]} → {have[-1]}={cells[-1]}"
            print(f"{p['id']:<6}" + "".join(f"{c:>8}" for c in cells) + f"  {note}")
        print("\nO=강한 신호  ~=약한 신호(4자 이하)만  .=없음")

    (RESULTS / "condition_compare.json").write_text(
        json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
