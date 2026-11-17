#!/usr/bin/env python3
"""对一条 transition 签名（ed25519，v0.1 envelope）。

用法：
    python3 scripts/sign.py --key <私钥 PEM> --in transitions/<file>.json

签名覆盖 canonical bytes：全 envelope 按 key 排序、无空白的 UTF-8 JSON
（JCS/RFC 8785 风格），不含 signature.value 本身。
签名值用 base64url 编码写入 signature.value；私钥永不进仓。

依赖：openssl 命令行（Ed25519 验签/签名走 `openssl pkeyutl -rawin`）。
私钥生成示例（各人本地做，绝不提交）：
    openssl genpkey -algorithm ed25519 -out ~/.config/agent-commons/my.key
    openssl pkey -in ~/.config/agent-commons/my.key -pubout -out my.pub.pem
"""

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def canonical_bytes(envelope: dict) -> bytes:
    # 签名覆盖除 signature 键之外的全 envelope（v0.1：“不含 signature.value 本身”；
    # 本骨架取最简解释：整个 signature 键不参与 canonical bytes）。
    unsigned = {k: v for k, v in envelope.items() if k != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="私钥 PEM 路径（本地保管，绝不进仓）")
    ap.add_argument("--in", dest="infile", required=True, help="待签名的 transition JSON")
    args = ap.parse_args()

    path = Path(args.infile)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if envelope.get("signature", {}).get("algorithm") != "ed25519":
        print("signature.algorithm 必须是 ed25519", file=sys.stderr)
        return 2

    data = canonical_bytes(envelope)
    with tempfile.TemporaryDirectory() as td:
        data_file = Path(td) / "canonical.json"
        sig_file = Path(td) / "sig.bin"
        data_file.write_bytes(data)
        r = subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", args.key,
             "-rawin", "-in", str(data_file), "-out", str(sig_file)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(f"openssl 签名失败：{r.stderr.strip()}", file=sys.stderr)
            return 2
        sig = sig_file.read_bytes()

    envelope["signature"]["value"] = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    path.write_text(json.dumps(envelope, sort_keys=True, indent=2,
                               ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"已签名：{path}（transition_id={envelope.get('transition_id')}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
