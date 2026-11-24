#!/usr/bin/env python3
"""根据 transitions/*.json 确定性投影生成 state/STATE.md（Protocol v0.1 R7）。

用法：
    python3 scripts/render_state.py                 # 重新生成 state/STATE.md
    python3 scripts/render_state.py --check         # 校验 state/STATE.md 与投影是否完全一致
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

PROJECTING_VERDICTS = frozenset({"VERIFIED_CHANGE", "VERIFIED_NO_CHANGE"})


def _escape_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def load_all_transitions(transitions_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not transitions_dir.is_dir():
        return records
    for p in sorted(transitions_dir.glob("*.json")):
        if p.name == "_TEMPLATE.json":
            continue
        records.append(json.loads(p.read_text(encoding="utf-8")))
    return records


def compute_active_heads(transitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 R7 active-head 投影规则计算每个 state.key 的当前生效记录。

    - 只有 VERIFIED_CHANGE 与 VERIFIED_NO_CHANGE 参与状态投影；
      INCONCLUSIVE 记入历史但不覆盖现有激活状态。
    - 顺着 supersedes 链回溯被已投影记录取代的所有前驱（包括中间 INCONCLUSIVE）。
    - 若同一 state.key 出现多个未取代的 active head（分叉），抛出 ValueError。
    """
    by_id: dict[str, dict[str, Any]] = {}
    for t in transitions:
        tid = t.get("transition_id")
        if isinstance(tid, str) and tid:
            by_id[tid] = t

    projecting = [
        t for t in transitions if t.get("verification", {}).get("verdict") in PROJECTING_VERDICTS
    ]

    superseded_ids: set[str] = set()
    for t in projecting:
        cur_sup = t.get("supersedes") or ""
        while cur_sup and cur_sup in by_id and cur_sup not in superseded_ids:
            superseded_ids.add(cur_sup)
            cur_sup = by_id[cur_sup].get("supersedes") or ""

    heads_by_key: dict[str, list[dict[str, Any]]] = {}
    for t in projecting:
        tid = t["transition_id"]
        if tid in superseded_ids:
            continue
        skey = t["state"]["key"]
        heads_by_key.setdefault(skey, []).append(t)

    result: list[dict[str, Any]] = []
    for skey in sorted(heads_by_key):
        candidates = heads_by_key[skey]
        if len(candidates) != 1:
            tids = [c.get("transition_id") for c in candidates]
            raise ValueError(f"state key {skey!r} 存在多个未取代的 active head：{tids}")
        result.append(candidates[0])
    return result


def render_state_markdown(transitions_dir: Path) -> str:
    transitions = load_all_transitions(transitions_dir)
    active_heads = compute_active_heads(transitions)

    lines = [
        "# 已验证的共享状态（STATE）",
        "",
        "本文件由 `scripts/render_state.py` 根据 `transitions/` 确定性投影生成，**禁止手工直接编辑**。",
        "任何一行都必须能在 `transitions/` 里找到对应的已验签 `transition_id`。",
        "",
        "| state key | value | version | verdict | transition_id | verified_by | observed_at |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not active_heads:
        lines.append("| _（试点开始时为空）_ | | | | | | |")
    else:
        for t in active_heads:
            st = t["state"]
            ver = t["verification"]
            row = [
                _escape_cell(st["key"]),
                _escape_cell(st["value"]),
                str(st["version"]),
                _escape_cell(ver["verdict"]),
                _escape_cell(t["transition_id"]),
                _escape_cell(ver["verified_by"]),
                _escape_cell(t["observed_at"]),
            ]
            lines.append("| " + " | ".join(row) + " |")

    lines.extend(
        [
            "",
            "## 档位说明",
            "",
            "- OBSERVED：刚收到（合入 `inbox/`），还没验——不进这张表。",
            "- CANDIDATE：有证据、有签名、CI 验签通过——在 PR 中待复核。",
            "- VERIFIED：对方 Agent 复算一遍或人看一眼关键证据，由约定批准人合入 `main` 后生效。",
            "",
        ]
    )
    return "\n".join(lines)


def check_state(transitions_dir: Path, out_path: Path) -> tuple[bool, str]:
    expected = render_state_markdown(transitions_dir)
    if not out_path.is_file():
        return False, f"目标状态文件不存在：{out_path}"
    actual = out_path.read_text(encoding="utf-8")
    if actual == expected:
        return True, "STATE.md 投影校验通过（与 transitions/ 完全一致）"
    diff = "".join(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=f"{out_path} (actual)",
            tofile=f"{out_path} (expected)",
        )
    )
    return False, f"STATE.md 与 transitions/ 确定性投影不一致（禁止手工编辑）：\n{diff}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transitions-dir", default="transitions", help="transitions 目录")
    ap.add_argument("--out", default="state/STATE.md", help="输出 STATE.md 路径")
    ap.add_argument("--check", action="store_true", help="只检查不写入，不一致时返回非 0")
    args = ap.parse_args(argv)

    tdir = Path(args.transitions_dir)
    out = Path(args.out)

    try:
        if args.check:
            ok, msg = check_state(tdir, out)
            print(msg if ok else f"FAIL：{msg}")
            return 0 if ok else 1

        content = render_state_markdown(tdir)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL：{exc}", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"已生成 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
