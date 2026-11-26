#!/usr/bin/env python3
"""验签并校验 transition 链（ed25519，v0.1 envelope），供 CI 与人工复核调用。

用法：
    python3 scripts/verify.py --registry agents.yaml transitions/<file>.json
    python3 scripts/verify.py --registry agents.yaml --all [--new-files ...] [--pr-author ...]
    # 成功 exit 0 并打印 PASS；失败 exit 1 并打印原因。

校验内容：
  1. v0.1 envelope 必填字段、封闭枚举（verdict）与非占位符检查（拒绝浮点数）。
  2. 注册表校验：key_id 存在、agent_id 匹配、algorithm=ed25519、scope 含 transitions/、
     可选 state_keys 白名单、expires 有效期，以及新提交的 active 与 PR 作者一致性。
  3. Ed25519 验签（RFC 8785 UTF-16-BE canonical JSON，仅排除 signature.value）。
  4. R2 证据校验：非空 evidence、type ∈ {file, github-blob}、file 类型路径防穿越且
     真实 sha256 一致、receipt.evidence_refs 可回溯到 evidence。
  5. R1/R6/R7 跨文件链校验：transition_id 全局唯一、(state.key, version) 唯一、
     version=1 禁止 supersedes、version>1 的 supersedes 必须指向同 key 的 version-1 且无分叉。

依赖：python3 + PyYAML + openssl 命令行。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from canonical import b64url_decode, canonical_bytes  # noqa: E402

ALLOWED_VERDICTS = frozenset({"VERIFIED_CHANGE", "VERIFIED_NO_CHANGE", "INCONCLUSIVE"})
ALLOWED_EVIDENCE_TYPES = frozenset({"file", "github-blob"})
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_HEX40_OR_64_RE = re.compile(r"^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_GITHUB_BLOB_PATH_RE = re.compile(r"^/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")
_GITHUB_REMOTE_RE = re.compile(r"^(?:https://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?$")


class VerificationError(Exception):
    """Raised when any protocol, registry, crypto, evidence, or chain check fails."""


def is_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    return s.startswith("<") and s.endswith(">")


def require_nonempty_str(obj: dict[str, Any], field: str, ctx: str) -> str:
    val = obj.get(field)
    if not isinstance(val, str) or not val.strip() or is_placeholder(val):
        raise VerificationError(f"{ctx}：缺少有效字符串字段 {field!r}（实际={val!r}）")
    return val


def parse_iso8601_tz(value: Any, ctx: str) -> datetime:
    if not isinstance(value, str) or not value.strip() or is_placeholder(value):
        raise VerificationError(f"{ctx}：时间字段不是有效 ISO 8601 字符串（实际={value!r}）")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise VerificationError(f"{ctx}：ISO 8601 时间解析失败 {value!r}：{exc}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise VerificationError(f"{ctx}：ISO 8601 时间必须带时区偏移（实际={value!r}）")
    return dt


def parse_expires_date(value: Any, ctx: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip() or is_placeholder(value):
        raise VerificationError(f"{ctx}：expires 不是有效日期（实际={value!r}）")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise VerificationError(f"{ctx}：expires 日期格式必须为 YYYY-MM-DD（实际={value!r}）") from exc


def load_registry(registry_path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise VerificationError(f"读取注册表 {registry_path} 失败：{exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("agents"), list):
        raise VerificationError(f"注册表 {registry_path} 格式非法：缺少 agents 列表")
    by_key: dict[str, dict[str, Any]] = {}
    for idx, entry in enumerate(raw["agents"]):
        if not isinstance(entry, dict):
            raise VerificationError(f"注册表 {registry_path} 第 {idx} 项不是 mapping")
        key_id = entry.get("key_id")
        if not isinstance(key_id, str) or not key_id.strip():
            raise VerificationError(f"注册表 {registry_path} 第 {idx} 项缺少 key_id")
        if key_id in by_key:
            raise VerificationError(f"注册表 {registry_path} 存在重复 key_id：{key_id!r}")
        by_key[key_id] = entry
    return by_key


def _validate_envelope_structure(envelope: dict[str, Any], label: str) -> tuple[datetime, str, int, int, str]:
    if not isinstance(envelope, dict):
        raise VerificationError(f"{label}：transition 顶层必须是 JSON object")
    if envelope.get("protocol") != "agent-os/world-state-transition":
        raise VerificationError(f"{label}：protocol 必须为 'agent-os/world-state-transition'")
    if envelope.get("protocol_version") != "0.1":
        raise VerificationError(f"{label}：protocol_version 必须为 '0.1'")

    tid = require_nonempty_str(envelope, "transition_id", label)
    observed_dt = parse_iso8601_tz(envelope.get("observed_at"), f"{label}.observed_at")

    ident = envelope.get("identity")
    if not isinstance(ident, dict):
        raise VerificationError(f"{label}：identity 必须是 object")
    ident_agent = require_nonempty_str(ident, "agent", f"{label}.identity")
    require_nonempty_str(ident, "key_id", f"{label}.identity")

    claim = envelope.get("claim")
    if not isinstance(claim, dict):
        raise VerificationError(f"{label}：claim 必须是 object")
    claim_agent = require_nonempty_str(claim, "agent", f"{label}.claim")
    require_nonempty_str(claim, "statement", f"{label}.claim")
    require_nonempty_str(claim, "target", f"{label}.claim")
    require_nonempty_str(claim, "intervention", f"{label}.claim")
    if claim_agent != ident_agent:
        raise VerificationError(
            f"{label}：claim.agent {claim_agent!r} 与 identity.agent {ident_agent!r} 不一致"
        )

    ver = envelope.get("verification")
    if not isinstance(ver, dict):
        raise VerificationError(f"{label}：verification 必须是 object")
    verdict = ver.get("verdict")
    if verdict not in ALLOWED_VERDICTS:
        raise VerificationError(
            f"{label}：verification.verdict 必须属于 {sorted(ALLOWED_VERDICTS)}（实际={verdict!r}）"
        )
    verified_by = require_nonempty_str(ver, "verified_by", f"{label}.verification")
    require_nonempty_str(ver, "gate_version", f"{label}.verification")
    require_nonempty_str(ver, "before", f"{label}.verification")
    require_nonempty_str(ver, "after", f"{label}.verification")
    require_nonempty_str(ver, "attribution", f"{label}.verification")
    require_nonempty_str(ver, "durability", f"{label}.verification")

    state = envelope.get("state")
    if not isinstance(state, dict):
        raise VerificationError(f"{label}：state 必须是 object")
    state_key = require_nonempty_str(state, "key", f"{label}.state")
    state_val = state.get("value")
    if state_val is None or (
        isinstance(state_val, str) and (not state_val.strip() or is_placeholder(state_val))
    ):
        raise VerificationError(f"{label}：state.value 不能为空或占位符")
    version = state.get("version")
    prev_version = state.get("previous_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise VerificationError(f"{label}：state.version 必须是 >= 1 的整数（实际={version!r}）")
    if isinstance(prev_version, bool) or not isinstance(prev_version, int) or prev_version != version - 1:
        raise VerificationError(
            f"{label}：state.previous_version {prev_version!r} 与 version {version!r} 不连续（应为 version - 1）"
        )

    supersedes = envelope.get("supersedes")
    if supersedes is not None and not isinstance(supersedes, str):
        raise VerificationError(f"{label}：supersedes 必须是字符串或 null")
    if isinstance(supersedes, str) and is_placeholder(supersedes):
        raise VerificationError(f"{label}：supersedes 不能是模板占位符 {supersedes!r}")

    receipt = envelope.get("receipt")
    if not isinstance(receipt, dict):
        raise VerificationError(f"{label}：receipt 必须是 object")
    require_nonempty_str(receipt, "id", f"{label}.receipt")
    r_tid = require_nonempty_str(receipt, "transition_id", f"{label}.receipt")
    if r_tid != tid:
        raise VerificationError(f"{label}：receipt.transition_id {r_tid!r} 与 transition_id {tid!r} 不一致")
    require_nonempty_str(receipt, "summary", f"{label}.receipt")
    r_vby = require_nonempty_str(receipt, "verified_by", f"{label}.receipt")
    if r_vby != verified_by:
        raise VerificationError(
            f"{label}：receipt.verified_by {r_vby!r} 与 verification.verified_by {verified_by!r} 不一致"
        )
    ev_refs = receipt.get("evidence_refs")
    if not isinstance(ev_refs, list) or not ev_refs:
        raise VerificationError(f"{label}：receipt.evidence_refs 必须是非空数组")
    for idx, ref in enumerate(ev_refs):
        if not isinstance(ref, str) or not ref.strip() or is_placeholder(ref):
            raise VerificationError(f"{label}：receipt.evidence_refs[{idx}] 无效：{ref!r}")

    return observed_dt, tid, version, prev_version, state_key


def _detect_repo_github_slug(repo_root: Path) -> str | None:
    """Return lowercase 'owner/repo' if repo_root is a git root with a GitHub origin."""
    top_res = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if top_res.returncode != 0 or Path(top_res.stdout.strip()).resolve() != repo_root.resolve():
        return None
    remote_res = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if remote_res.returncode != 0:
        return None
    match = _GITHUB_REMOTE_RE.match(remote_res.stdout.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}".lower()


def _is_shallow_git_repo(repo_root: Path) -> bool:
    """Return True if repo_root is a shallow git clone without full object history."""
    res = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0 and res.stdout.strip() == "true"


def _verify_same_repo_github_blob(
    repo_root: Path,
    url_ref: str,
    relpath: str,
    declared_sha: str,
    ctx: str,
) -> None:
    """Cross-check same-repo github-blob against local git object hash when full history is present."""
    if _is_shallow_git_repo(repo_root):
        print(
            f"WARNING: shallow git repository detected; skipping local git blob verification for {url_ref}:{relpath}",
            file=sys.stderr,
        )
        return

    if relpath.startswith(("/", "\\")) or "\\" in relpath or ".." in Path(relpath).parts:
        raise VerificationError(f"{ctx}：github-blob 路径非法：{relpath!r}")

    rev_res = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", f"{url_ref}:{relpath}"],
        capture_output=True,
        text=True,
    )
    if rev_res.returncode != 0:
        raise VerificationError(f"{ctx}：同仓 github-blob 在本地 git 中不存在：{url_ref}:{relpath}")
    blob_sha = rev_res.stdout.strip().lower()

    type_res = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-t", blob_sha],
        capture_output=True,
        text=True,
    )
    if type_res.returncode != 0 or type_res.stdout.strip() != "blob":
        raise VerificationError(f"{ctx}：同仓 github-blob 指向的不是 blob 对象：{url_ref}:{relpath}")

    declared_lower = declared_sha.lower()
    if len(declared_lower) == 40:
        if blob_sha != declared_lower:
            raise VerificationError(
                f"{ctx}：同仓 github-blob git blob SHA 不匹配（声明={declared_lower}，实际={blob_sha}）"
            )
    else:
        raw_res = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "blob", blob_sha],
            capture_output=True,
        )
        if raw_res.returncode != 0:
            raise VerificationError(f"{ctx}：无法读取本地 git blob 内容：{blob_sha}")
        actual_sha256 = hashlib.sha256(raw_res.stdout).hexdigest()
        if actual_sha256 != declared_lower:
            raise VerificationError(
                f"{ctx}：同仓 github-blob 内容 sha256 不匹配（声明={declared_lower}，实际={actual_sha256}）"
            )


def _validate_evidence(envelope: dict[str, Any], repo_root: Path, label: str) -> None:
    evidence = envelope.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise VerificationError(f"{label}：evidence 必须是非空数组（禁止无证据断言）")

    ref_pool: set[str] = set()
    repo_root_resolved = repo_root.resolve()
    repo_github_slug = _detect_repo_github_slug(repo_root_resolved)

    for idx, item in enumerate(evidence):
        ctx = f"{label}.evidence[{idx}]"
        if not isinstance(item, dict):
            raise VerificationError(f"{ctx}：证据项必须是 object")
        ev_type = require_nonempty_str(item, "type", ctx)
        if ev_type not in ALLOWED_EVIDENCE_TYPES:
            raise VerificationError(
                f"{ctx}：不支持的证据 type {ev_type!r}（仅允许 {sorted(ALLOWED_EVIDENCE_TYPES)}）"
            )
        locator = require_nonempty_str(item, "locator", ctx)
        sha = require_nonempty_str(item, "sha256", ctx)
        parse_iso8601_tz(item.get("observed_at"), f"{ctx}.observed_at")

        if ev_type == "file":
            if locator.startswith(("/", "\\")) or ".." in Path(locator).parts:
                raise VerificationError(f"{ctx}：file locator 不允许绝对路径或 '..' 穿越（{locator!r}）")
            target = (repo_root_resolved / locator).resolve()
            if not target.is_relative_to(repo_root_resolved):
                raise VerificationError(f"{ctx}：file locator 越出仓库根目录（{locator!r}）")
            if not target.is_file():
                raise VerificationError(f"{ctx}：证据文件不存在：{locator}")
            if not _HEX64_RE.match(sha):
                raise VerificationError(f"{ctx}：file sha256 必须是 64 位十六进制（实际={sha!r}）")
            actual_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual_sha != sha.lower():
                raise VerificationError(
                    f"{ctx}：证据文件 {locator} sha256 不匹配（声明={sha.lower()}，实际={actual_sha}）"
                )
        elif ev_type == "github-blob":
            commit = require_nonempty_str(item, "commit", ctx)
            if not _COMMIT_RE.match(commit):
                raise VerificationError(f"{ctx}：github-blob commit 格式非法：{commit!r}")
            parsed = urlsplit(locator)
            blob_match = (
                _GITHUB_BLOB_PATH_RE.match(parsed.path)
                if parsed.scheme == "https" and parsed.netloc == "github.com" and not parsed.query
                else None
            )
            if blob_match is None:
                raise VerificationError(f"{ctx}：github-blob locator 必须是 GitHub blob URL（{locator!r}）")
            url_owner, url_repo, url_ref, raw_relpath = blob_match.groups()
            commit_lower = commit.lower()
            ref_lower = url_ref.lower()
            if not _COMMIT_RE.match(url_ref) or (ref_lower != commit_lower and not ref_lower.startswith(commit_lower)):
                raise VerificationError(
                    f"{ctx}：github-blob locator 的路径 ref {url_ref!r} 未绑定到 commit {commit!r}"
                )
            if not _HEX40_OR_64_RE.match(sha):
                raise VerificationError(f"{ctx}：github-blob sha256/blob-sha 格式非法（{sha!r}）")
            if repo_github_slug is not None and f"{url_owner}/{url_repo}".lower() == repo_github_slug:
                _verify_same_repo_github_blob(
                    repo_root_resolved,
                    url_ref,
                    unquote(raw_relpath),
                    sha,
                    ctx,
                )

        ref_pool.add(locator)
        ref_pool.add(sha)
        ref_pool.add(sha.lower())

    for idx, ref in enumerate(envelope["receipt"]["evidence_refs"]):
        if ref not in ref_pool and ref.lower() not in ref_pool:
            raise VerificationError(
                f"{label}：receipt.evidence_refs[{idx}]={ref!r} 未引用任何已校验的 evidence"
            )


def _validate_registry_and_crypto(
    envelope: dict[str, Any],
    observed_dt: datetime,
    agents: dict[str, dict[str, Any]],
    *,
    is_new: bool,
    pr_author: str | None,
    as_of_date: date,
    label: str,
) -> tuple[str, str]:
    ident = envelope["identity"]
    key_id = ident["key_id"]
    agent_id = ident["agent"]
    agent = agents.get(key_id)
    if agent is None:
        raise VerificationError(f"{label}：key_id {key_id!r} 不在注册表 agents.yaml 里")
    if agent.get("agent_id") != agent_id:
        raise VerificationError(
            f"{label}：identity.agent {agent_id!r} 与登记的 agent_id {agent.get('agent_id')!r} 不一致"
        )
    if agent.get("algorithm") != "ed25519":
        raise VerificationError(f"{label}：agents.yaml 中 {key_id!r} algorithm 不是 ed25519")

    status = agent.get("status")
    if is_new:
        if status != "active":
            raise VerificationError(f"{label}：key_id {key_id!r} 状态为 {status!r}，新 transition 必须 active")
    else:
        if status not in {"active", "revoked"}:
            raise VerificationError(f"{label}：历史 transition 密钥 {key_id!r} 状态非法：{status!r}")

    scope = agent.get("scope")
    if not isinstance(scope, list) or "transitions/" not in scope:
        raise VerificationError(f"{label}：agent {agent_id!r} 未获 'transitions/' 写入授权（scope={scope!r}）")

    state_keys = agent.get("state_keys")
    if state_keys is not None:
        if not isinstance(state_keys, list) or envelope["state"]["key"] not in state_keys:
            raise VerificationError(
                f"{label}：agent {agent_id!r} 无权修改 state key {envelope['state']['key']!r}"
            )

    expires_date = parse_expires_date(agent.get("expires"), f"agents.yaml[{key_id}]")
    observed_utc_date = observed_dt.astimezone(timezone.utc).date()
    if observed_utc_date > expires_date:
        raise VerificationError(
            f"{label}：observed_at ({observed_utc_date}) 已超过密钥 {key_id!r} 有效期 ({expires_date})"
        )
    if is_new and as_of_date > expires_date:
        raise VerificationError(
            f"{label}：密钥 {key_id!r} 已于 {expires_date} 过期（当前日期 {as_of_date}）"
        )

    if is_new and pr_author is not None:
        gh_user = agent.get("github_user")
        if gh_user != pr_author:
            raise VerificationError(
                f"{label}：PR 作者 {pr_author!r} 与签名身份 {agent_id!r} 绑定的 github_user {gh_user!r} 不一致"
            )

    sig = envelope.get("signature")
    if not isinstance(sig, dict) or sig.get("algorithm") != "ed25519":
        raise VerificationError(f"{label}：signature.algorithm 必须是 ed25519")
    try:
        sig_bytes = b64url_decode(sig.get("value", ""))
    except ValueError as exc:
        raise VerificationError(f"{label}：{exc}") from exc
    if len(sig_bytes) != 64:
        raise VerificationError(f"{label}：ed25519 签名长度必须为 64 字节（实际={len(sig_bytes)}）")

    pub_pem = agent.get("public_key_pem")
    if not isinstance(pub_pem, str) or "BEGIN PUBLIC KEY" not in pub_pem or is_placeholder(pub_pem):
        raise VerificationError(f"{label}：agents.yaml 中 {key_id!r} 的 public_key_pem 无效")

    try:
        payload_bytes = canonical_bytes(envelope)
    except ValueError as exc:
        raise VerificationError(f"{label}：canonical 序列化失败：{exc}") from exc

    with tempfile.TemporaryDirectory() as td:
        pub = Path(td) / "pub.pem"
        data_file = Path(td) / "canonical.json"
        sig_file = Path(td) / "sig.bin"
        pub.write_text(pub_pem, encoding="utf-8")
        data_file.write_bytes(payload_bytes)
        sig_file.write_bytes(sig_bytes)
        res = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(pub),
                "-rawin",
                "-in",
                str(data_file),
                "-sigfile",
                str(sig_file),
            ],
            capture_output=True,
            text=True,
        )
    if res.returncode != 0:
        raise VerificationError(
            f"{label}：ed25519 验签未通过（{res.stderr.strip() or 'openssl 返回非 0'}）"
        )
    return agent_id, key_id


def _load_transitions_for_chain(
    transitions_dir: Path,
    extra_target: Path | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    paths: list[Path] = []
    if transitions_dir.is_dir():
        for p in sorted(transitions_dir.glob("*.json")):
            if p.name == "_TEMPLATE.json":
                continue
            paths.append(p.resolve())
    if extra_target is not None:
        resolved_target = extra_target.resolve()
        if not resolved_target.is_file():
            raise VerificationError(f"目标 transition 文件不存在：{extra_target}")
        if resolved_target not in paths:
            paths.append(resolved_target)

    loaded: list[tuple[Path, dict[str, Any]]] = []
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise VerificationError(f"解析 {p} JSON 失败：{exc}") from exc
        loaded.append((p, data))
    return loaded


def verify_repository(
    *,
    registry_path: Path,
    transitions_dir: Path,
    repo_root: Path,
    target_file: Path | None = None,
    new_files: list[Path] | None = None,
    pr_author: str | None = None,
    as_of_date: date | None = None,
) -> list[str]:
    """验证单个目标或全量 transitions 目录，并返回通过摘要列表；失败抛出 VerificationError。"""
    if as_of_date is None:
        as_of_date = datetime.now(timezone.utc).date()

    agents = load_registry(registry_path)
    loaded = _load_transitions_for_chain(transitions_dir, extra_target=target_file)
    if not loaded:
        return []

    strict_paths: set[Path] = set()
    if target_file is not None:
        strict_paths.add(target_file.resolve())
    if new_files:
        loaded_path_set = {p for p, _ in loaded}
        for nf in new_files:
            resolved_nf = (nf if nf.is_absolute() else (repo_root / nf)).resolve()
            if resolved_nf not in loaded_path_set:
                raise VerificationError(f"--new-files 指定的文件未在待验集合中找到：{nf}")
            strict_paths.add(resolved_nf)

    # 第一遍：结构、证据、签名与注册表校验，同时建立全局索引检查唯一性
    by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    seen_state_versions: dict[tuple[str, int], Path] = {}
    seen_supersedes: dict[str, Path] = {}
    summaries: list[str] = []

    for path, env in loaded:
        try:
            label = str(path.relative_to(repo_root.resolve()))
        except ValueError:
            label = str(path)

        observed_dt, tid, version, _prev_ver, state_key = _validate_envelope_structure(env, label)
        if tid in by_id:
            raise VerificationError(f"{label}：transition_id {tid!r} 与 {by_id[tid][0]} 重复")
        by_id[tid] = (path, env)

        sv_key = (state_key, version)
        if sv_key in seen_state_versions:
            raise VerificationError(
                f"{label}：状态 ({state_key!r}, v{version}) 与 {seen_state_versions[sv_key]} 冲突"
            )
        seen_state_versions[sv_key] = path

        sup = env.get("supersedes") or ""
        if sup:
            if sup in seen_supersedes:
                raise VerificationError(
                    f"{label}：supersedes={sup!r} 发生分叉（已被 {seen_supersedes[sup]} 继承）"
                )
            seen_supersedes[sup] = path

        _validate_evidence(env, repo_root, label)
        is_new = path in strict_paths
        agent_id, key_id = _validate_registry_and_crypto(
            env,
            observed_dt,
            agents,
            is_new=is_new,
            pr_author=pr_author if is_new else None,
            as_of_date=as_of_date,
            label=label,
        )
        summaries.append(f"PASS：{label}（{agent_id} / {key_id}，state {state_key} v{version}）")

    # 第二遍：跨文件 supersedes / predecessor 链校验
    for path, env in loaded:
        try:
            label = str(path.relative_to(repo_root.resolve()))
        except ValueError:
            label = str(path)
        version = env["state"]["version"]
        state_key = env["state"]["key"]
        sup = env.get("supersedes") or ""

        if version == 1:
            if sup:
                raise VerificationError(f"{label}：version=1 时 supersedes 必须为空（实际={sup!r}）")
        else:
            if not sup:
                raise VerificationError(f"{label}：version={version} > 1 时必须声明 supersedes")
            if sup not in by_id:
                raise VerificationError(f"{label}：supersedes={sup!r} 指向不存在的 transition_id")
            _p_path, parent = by_id[sup]
            if parent["state"]["key"] != state_key:
                raise VerificationError(
                    f"{label}：supersedes={sup!r} 属于不同 state.key "
                    f"{parent['state']['key']!r}（当前={state_key!r}）"
                )
            if parent["state"]["version"] != version - 1:
                raise VerificationError(
                    f"{label}：supersedes={sup!r} 的 version={parent['state']['version']} "
                    f"不是当前 version-1（{version - 1}）"
                )

    return summaries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="agents.yaml", help="agents.yaml 注册表路径")
    ap.add_argument("--transitions-dir", default="transitions", help="transitions 目录路径")
    ap.add_argument("--repo-root", default=".", help="仓库根目录（解析 file 证据路径）")
    ap.add_argument("--all", action="store_true", help="校验 transitions/ 下全部非模板文件")
    ap.add_argument("--new-files", nargs="*", default=[], help="本次 PR 新增的 transition 文件列表")
    ap.add_argument("--pr-author", default=None, help="PR 作者 GitHub 登录名")
    ap.add_argument("--as-of", default=None, help="有效期校验日期 YYYY-MM-DD（默认当前 UTC 日期）")
    ap.add_argument("transition", nargs="?", help="待验签的单个 transition JSON 文件")
    args = ap.parse_args(argv)

    if not args.all and not args.transition:
        ap.error("必须提供 transition 文件路径，或传入 --all")
    if args.all and args.transition:
        ap.error("不能同时传入 --all 与单个 transition 位置参数")

    as_of_date = date.fromisoformat(args.as_of) if args.as_of else None
    target_file = Path(args.transition) if args.transition else None
    new_files = [Path(f) for f in args.new_files]

    try:
        summaries = verify_repository(
            registry_path=Path(args.registry),
            transitions_dir=Path(args.transitions_dir),
            repo_root=Path(args.repo_root),
            target_file=target_file,
            new_files=new_files,
            pr_author=args.pr_author,
            as_of_date=as_of_date,
        )
    except VerificationError as exc:
        print(f"FAIL：{exc}")
        return 1

    if not summaries:
        print("PASS：transitions/ 下暂无非模板 transition 记录")
    else:
        for line in summaries:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
