#!/usr/bin/env python3
"""验签一条 transition（ed25519，v0.1 envelope），供 CI 与人工复核调用。

用法：
    python3 scripts/verify.py --registry agents.yaml transitions/<file>.json
    # 成功 exit 0 并打印 PASS；失败 exit 1 并打印原因。

验三件事（与 .github/workflows/validate.yml 一致）：
  1. signature.algorithm 是 ed25519，且 signature.value 能用 agents.yaml 里
     key_id 对应的公钥验过 canonical bytes（除 signature 键外的全 envelope，
     按 key 排序、无空白的 UTF-8 JSON）。
  2. 写的人（identity.agent / key_id）在 agents.yaml 里，且 status 为 active。
  3. state.previous_version 与 supersedes 指向的上一个 transition 对得上
     （本脚本只做文件内自洽检查：previous_version = version - 1；
     跨文件的链检查由 CI 在 PR 里对 transitions/ 全量跑）。

依赖：python3 + PyYAML + openssl 命令行。
"""

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def canonical_bytes(envelope: dict) -> bytes:
    unsigned = {k: v for k, v in envelope.items() if k != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="agents.yaml")
    ap.add_argument("transition", help="transition JSON 文件")
    args = ap.parse_args()

    registry = yaml.safe_load(Path(args.registry).read_text(encoding="utf-8"))
    agents = {a["key_id"]: a for a in registry.get("agents", [])}
    envelope = json.loads(Path(args.transition).read_text(encoding="utf-8"))

    ident = envelope.get("identity", {})
    key_id = ident.get("key_id")
    agent = agents.get(key_id)
    if agent is None:
        print(f"FAIL：key_id {key_id!r} 不在 agents.yaml 里")
        return 1
    if agent.get("status") != "active":
        print(f"FAIL：key_id {key_id!r} 状态为 {agent.get('status')!r}，不是 active")
        return 1
    if ident.get("agent") != agent.get("agent_id"):
        print(f"FAIL：identity.agent {ident.get('agent')!r} 与登记的 agent_id "
              f"{agent.get('agent_id')!r} 不一致")
        return 1

    sig = envelope.get("signature", {})
    if sig.get("algorithm") != "ed25519":
        print("FAIL：signature.algorithm 不是 ed25519")
        return 1
    try:
        sig_bytes = b64url_decode(sig.get("value", ""))
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL：signature.value 解码失败：{exc}")
        return 1

    state = envelope.get("state", {})
    if state.get("version", 1) - 1 != state.get("previous_version", 0):
        print(f"FAIL：state.previous_version {state.get('previous_version')} "
              f"与 version {state.get('version')} 对不上（应为 version - 1）")
        return 1

    with tempfile.TemporaryDirectory() as td:
        pub = Path(td) / "pub.pem"
        data_file = Path(td) / "canonical.json"
        sig_file = Path(td) / "sig.bin"
        pub.write_text(agent["public_key_pem"], encoding="utf-8")
        data_file.write_bytes(canonical_bytes(envelope))
        sig_file.write_bytes(sig_bytes)
        r = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pub),
             "-rawin", "-in", str(data_file), "-sigfile", str(sig_file)],
            capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL：ed25519 验签未通过（{r.stderr.strip() or 'openssl 返回非 0'}）")
        return 1

    print(f"PASS：{args.transition}（{ident.get('agent')} / {key_id}，"
          f"state {state.get('key')} v{state.get('version')}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
