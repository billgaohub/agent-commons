#!/usr/bin/env python3
"""agent-commons GitHub Actions PR / Push 统一治理门禁脚本。

所有检查均在纯 Python 中完成，所有来自 GitHub Actions 上下文的值均通过参数/环境变量
传递，避免 shell/heredoc 字符串插值注入。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from render_state import check_state  # noqa: E402
from verify import (  # noqa: E402
    VerificationError,
    is_placeholder,
    load_registry,
    parse_expires_date,
    parse_iso8601_tz,
    verify_repository,
)

ALLOWED_INBOX_TYPES = frozenset({"提问", "提议", "证据", "反对"})
ALLOWED_AGENT_STATUSES = frozenset({"active", "pending", "revoked"})
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)


class GateError(Exception):
    """Raised when CI governance validation fails."""


def _run_git(repo_root: Path, args: list[str]) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise GateError(f"git {' '.join(args)} 失败：{res.stderr.strip()}")
    return res.stdout


def validate_registry_schema(registry_path: Path) -> None:
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise GateError(f"agents.yaml 解析失败：{exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("agents"), list):
        raise GateError("agents.yaml 顶层必须包含 agents 列表")

    seen_keys: set[str] = set()
    seen_agents: dict[str, str] = {}
    for idx, entry in enumerate(raw["agents"]):
        if not isinstance(entry, dict):
            raise GateError(f"agents[{idx}] 必须是 mapping")
        for req in ("agent_id", "github_user", "key_id", "algorithm", "public_key_pem", "scope", "expires", "status"):
            if req not in entry:
                raise GateError(f"agents[{idx}] 缺少必填字段 {req!r}")

        status = entry["status"]
        if status not in ALLOWED_AGENT_STATUSES:
            raise GateError(f"agents[{idx}].status 非法：{status!r}")

        key_id = entry["key_id"]
        agent_id = entry["agent_id"]
        if not isinstance(key_id, str) or not key_id.strip():
            raise GateError(f"agents[{idx}].key_id 必须为非空字符串")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise GateError(f"agents[{idx}].agent_id 必须为非空字符串")
        if key_id in seen_keys:
            raise GateError(f"agents.yaml 存在重复 key_id：{key_id!r}")
        seen_keys.add(key_id)

        if status == "pending":
            continue

        for str_field in ("agent_id", "github_user", "key_id"):
            val = entry.get(str_field)
            if not isinstance(val, str) or not val.strip() or is_placeholder(val):
                raise GateError(f"agents[{idx}].{str_field} 不能是空值或模板占位符：{val!r}")

        if status == "active":
            gh_user = entry["github_user"]
            prev_user = seen_agents.get(agent_id)
            if prev_user is not None and prev_user != gh_user:
                raise GateError(
                    f"agents.yaml 中同 agent_id {agent_id!r} 绑定了不同的 github_user（{prev_user!r} vs {gh_user!r}）"
                )
            seen_agents[agent_id] = gh_user

        if entry.get("algorithm") != "ed25519":
            raise GateError(f"agents[{idx}].algorithm 必须为 'ed25519'")

        scope = entry.get("scope")
        if not isinstance(scope, list) or not scope or any(not isinstance(s, str) or is_placeholder(s) for s in scope):
            raise GateError(f"agents[{idx}].scope 必须是非空有效路径列表")

        try:
            parse_expires_date(entry.get("expires"), f"agents[{idx}]")
        except VerificationError as exc:
            raise GateError(str(exc)) from exc

        pem = entry.get("public_key_pem")
        if not isinstance(pem, str) or "BEGIN PUBLIC KEY" not in pem or is_placeholder(pem):
            raise GateError(f"agents[{idx}].public_key_pem 格式无效")
        with tempfile.TemporaryDirectory() as td:
            pub = Path(td) / "pub.pem"
            pub.write_text(pem, encoding="utf-8")
            res = subprocess.run(
                ["openssl", "pkey", "-pubin", "-in", str(pub), "-noout"],
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                raise GateError(
                    f"agents[{idx}] ({key_id}) public_key_pem 无法被 openssl 解析：{res.stderr.strip()}"
                )


def _parse_name_status(output: str) -> list[tuple[str, list[str]]]:
    entries: list[tuple[str, list[str]]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        entries.append((parts[0], parts[1:]))
    return entries


def _validate_inbox_message(path: Path, rel_path: str, expected_agent_id: str) -> None:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise GateError(f"{rel_path}：缺少合法 YAML frontmatter（必须以 --- 开头并成对闭合）")
    try:
        fm = yaml.safe_load(m.group(1))
    except Exception as exc:  # noqa: BLE001
        raise GateError(f"{rel_path}：frontmatter YAML 解析失败：{exc}") from exc
    if not isinstance(fm, dict):
        raise GateError(f"{rel_path}：frontmatter 必须是 YAML mapping")

    for req in ("id", "from", "to"):
        val = fm.get(req)
        if not isinstance(val, str) or not val.strip() or is_placeholder(val):
            raise GateError(f"{rel_path}：frontmatter 字段 {req!r} 无效或为占位符（{val!r}）")

    if fm["from"] != expected_agent_id:
        raise GateError(
            f"{rel_path}：frontmatter from={fm['from']!r} 与发送者身份 {expected_agent_id!r} 不一致"
        )

    time_val = fm.get("time")
    if isinstance(time_val, datetime):
        if time_val.tzinfo is None or time_val.utcoffset() is None:
            raise GateError(f"{rel_path}：frontmatter time 必须包含时区偏移")
    else:
        try:
            parse_iso8601_tz(time_val, f"{rel_path}.time")
        except VerificationError as exc:
            raise GateError(str(exc)) from exc

    msg_type = fm.get("type")
    if msg_type not in ALLOWED_INBOX_TYPES:
        raise GateError(
            f"{rel_path}：frontmatter type 必须属于 {sorted(ALLOWED_INBOX_TYPES)}（实际={msg_type!r}）"
        )

    if msg_type == "证据":
        ev = fm.get("evidence")
        if not isinstance(ev, list):
            raise GateError(f"{rel_path}：type='证据' 时 frontmatter.evidence 必须为非空列表")
        valid_ev = [
            item
            for item in ev
            if isinstance(item, str) and item.strip() and not is_placeholder(item)
        ]
        if not valid_ev:
            raise GateError(
                f"{rel_path}：type='证据' 的消息禁止无来源断言（evidence 不能为空或占位符）"
            )


def run_pull_request_checks(
    *,
    repo_root: Path,
    base_ref: str,
    pr_author: str,
    repo_owner: str,
    as_of_date: date,
) -> list[str]:
    if not pr_author:
        raise GateError("pull_request 检查必须提供 --pr-author")

    base_target = base_ref if base_ref.startswith("origin/") else f"origin/{base_ref}"
    _run_git(repo_root, ["rev-parse", "--verify", base_target])

    diff_range = f"{base_target}...HEAD"
    changed_files = [
        line.strip()
        for line in _run_git(repo_root, ["diff", "--name-only", diff_range]).splitlines()
        if line.strip()
    ]

    # 1. 受保护治理路径权限锁（以 base 分支上的 repo_owner 为准，防 PR 自修改信任根或 CI）
    protected_hits = [
        f
        for f in changed_files
        if f == "agents.yaml" or f.startswith(".github/") or f.startswith("scripts/")
    ]
    if protected_hits and pr_author != repo_owner:
        raise GateError(
            f"PR 作者 {pr_author!r} 无权修改受保护治理文件（仅 {repo_owner!r} 可改）：{protected_hits}"
        )

    # 若 owner 修改了 agents.yaml，校验新 agents.yaml schema
    if "agents.yaml" in changed_files:
        validate_registry_schema(repo_root / "agents.yaml")

    # 2. 强制从 base 分支提取信任根 agents.yaml
    base_agents_yaml = _run_git(repo_root, ["show", f"{base_target}:agents.yaml"])

    with tempfile.TemporaryDirectory() as td:
        base_reg_path = Path(td) / "base_agents.yaml"
        base_reg_path.write_text(base_agents_yaml, encoding="utf-8")

        try:
            base_agents = load_registry(base_reg_path)
        except VerificationError as exc:
            raise GateError(str(exc)) from exc

        # 3. transitions/ 必须严格 append-only
        trans_entries = _parse_name_status(
            _run_git(repo_root, ["diff", "--name-status", diff_range, "--", "transitions/"])
        )
        added_transitions: list[Path] = []
        for status, paths in trans_entries:
            primary = paths[-1]
            if primary == "transitions/_TEMPLATE.json":
                if pr_author != repo_owner:
                    raise GateError(f"非 owner ({pr_author!r}) 禁止修改 {primary}")
                continue
            if status != "A":
                raise GateError(
                    f"transitions/ 必须 append-only（禁止 {status} 操作：{paths}）"
                )
            if not primary.endswith(".json"):
                raise GateError(f"transitions/ 只允许 .json 文件：{primary}")
            added_transitions.append(Path(primary))

        # 4. 全量 transition 验签 + 链检查（新文件使用 base 信任根 + 强绑定 pr_author）
        try:
            trans_summaries = verify_repository(
                registry_path=base_reg_path,
                transitions_dir=repo_root / "transitions",
                repo_root=repo_root,
                new_files=added_transitions,
                pr_author=pr_author,
                as_of_date=as_of_date,
            )
        except VerificationError as exc:
            raise GateError(str(exc)) from exc

        # 5. state/ 确定性投影校验（禁止手改或新增其它 state/ 文件）
        state_entries = [
            f for f in changed_files if f.startswith("state/") and f != "state/STATE.md"
        ]
        if state_entries:
            raise GateError(f"state/ 目录除 STATE.md 外禁止私增或修改文件：{state_entries}")

        ok, state_msg = check_state(repo_root / "transitions", repo_root / "state/STATE.md")
        if not ok:
            raise GateError(state_msg)

        # 6. inbox/ 目录隔离 + append-only + frontmatter 校验
        inbox_entries = _parse_name_status(
            _run_git(repo_root, ["diff", "--name-status", diff_range, "--", "inbox/"])
        )
        inbox_checked = 0
        if inbox_entries:
            active_for_author: list[dict[str, Any]] = []
            for entry in base_agents.values():
                if entry.get("github_user") == pr_author and entry.get("status") == "active":
                    try:
                        exp = parse_expires_date(entry.get("expires"), f"base agents.yaml[{entry.get('key_id')}]")
                    except VerificationError as exc:
                        raise GateError(str(exc)) from exc
                    if as_of_date <= exp:
                        active_for_author.append(entry)

            for status, paths in inbox_entries:
                rel_path = paths[-1]
                if rel_path == "inbox/_TEMPLATE.md":
                    if pr_author != repo_owner:
                        raise GateError(f"非 owner ({pr_author!r}) 禁止修改 {rel_path}")
                    continue
                if status != "A":
                    raise GateError(
                        f"inbox/ 必须 append-only（禁止 {status} 操作：{paths}）"
                    )
                if not rel_path.endswith(".md"):
                    raise GateError(f"inbox/ 消息文件必须为 .md：{rel_path}")
                if not active_for_author:
                    raise GateError(
                        f"PR 作者 {pr_author!r} 在 base agents.yaml 中没有未过期的 active Agent 身份"
                    )
                matched_agent_id: str | None = None
                for entry in active_for_author:
                    aid = entry["agent_id"]
                    prefix = f"inbox/{aid}/"
                    scope = entry.get("scope", [])
                    if rel_path.startswith(prefix) and isinstance(scope, list) and prefix in scope:
                        matched_agent_id = aid
                        break
                if matched_agent_id is None:
                    allowed_dirs = [f"inbox/{e['agent_id']}/" for e in active_for_author]
                    raise GateError(
                        f"inbox 越权或无 scope 授权（{pr_author!r} 仅允许写入 {allowed_dirs}，实际={rel_path}）"
                    )
                _validate_inbox_message(repo_root / rel_path, rel_path, matched_agent_id)
                inbox_checked += 1

    msgs = [
        f"trust-root: base={base_target}, pr_author={pr_author}, protected_touched={len(protected_hits)}",
        f"transitions: {len(trans_summaries)} verified ({len(added_transitions)} new)",
        state_msg,
        f"inbox: {inbox_checked} message(s) validated",
    ]
    return msgs


def run_push_checks(repo_root: Path, as_of_date: date) -> list[str]:
    validate_registry_schema(repo_root / "agents.yaml")
    try:
        trans_summaries = verify_repository(
            registry_path=repo_root / "agents.yaml",
            transitions_dir=repo_root / "transitions",
            repo_root=repo_root,
            new_files=None,
            pr_author=None,
            as_of_date=as_of_date,
        )
    except VerificationError as exc:
        raise GateError(str(exc)) from exc

    ok, state_msg = check_state(repo_root / "transitions", repo_root / "state/STATE.md")
    if not ok:
        raise GateError(state_msg)

    return [
        "registry: agents.yaml schema valid",
        f"transitions: {len(trans_summaries)} historical record(s) verified",
        state_msg,
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True, choices=("pull_request", "push"))
    ap.add_argument("--base-ref", default="main")
    ap.add_argument("--pr-author", default="")
    ap.add_argument("--repo-owner", default="billgaohub")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--as-of", default=None, help="测试用日期覆盖 YYYY-MM-DD")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    as_of_date = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).date()

    try:
        if args.event == "pull_request":
            lines = run_pull_request_checks(
                repo_root=repo_root,
                base_ref=args.base_ref,
                pr_author=args.pr_author.strip(),
                repo_owner=args.repo_owner.strip(),
                as_of_date=as_of_date,
            )
        else:
            lines = run_push_checks(repo_root=repo_root, as_of_date=as_of_date)
    except GateError as exc:
        print(f"FAIL：{exc}")
        return 1

    for line in lines:
        print(f"PASS：{line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
