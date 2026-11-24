#!/usr/bin/env python3
"""对一条 transition 签名（ed25519，v0.1 envelope）。

用法：
    python3 scripts/sign.py --key <私钥 PEM> --in transitions/<file>.json

签名覆盖 canonical bytes：
- 按 RFC 8785 UTF-16-BE key 顺序递归排序、无多余空白的 UTF-8 JSON；
- 禁止浮点数（请用整数或字符串）；
- 仅排除 `signature.value`，保留 `signature.algorithm` 并受签名绑定。
签名值用无填充 base64url 编码写入 `signature.value`；私钥永不进仓。

依赖：openssl 命令行（Ed25519 签名走 `openssl pkeyutl -rawin`）。
私钥生成示例（各人本地做，绝不提交）：
    openssl genpkey -algorithm ed25519 -out ~/.config/agent-commons/my.key
    openssl pkey -in ~/.config/agent-commons/my.key -pubout -out my.pub.pem
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from canonical import b64url_encode, canonical_bytes  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="私钥 PEM 路径（本地保管，绝不进仓）")
    ap.add_argument("--in", dest="infile", required=True, help="待签名的 transition JSON")
    args = ap.parse_args()

    path = Path(args.infile)
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        data = canonical_bytes(envelope)
    except Exception as exc:  # noqa: BLE001
        print(f"输入 envelope 校验失败：{exc}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as td:
        data_file = Path(td) / "canonical.json"
        sig_file = Path(td) / "sig.bin"
        data_file.write_bytes(data)
        r = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                args.key,
                "-rawin",
                "-in",
                str(data_file),
                "-out",
                str(sig_file),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"openssl 签名失败：{r.stderr.strip()}", file=sys.stderr)
            return 2
        sig = sig_file.read_bytes()

    envelope["signature"]["value"] = b64url_encode(sig)
    path.write_text(
        json.dumps(envelope, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"已签名：{path}（transition_id={envelope.get('transition_id')}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
