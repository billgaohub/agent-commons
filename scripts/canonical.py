#!/usr/bin/env python3
"""RFC 8785 (JCS) 风格且禁止浮点数的规范化 JSON 序列化。

规范约定（agent-commons / agent-os v0.1）：
1. 签名覆盖除 `signature.value` 之外的全 envelope（保留 `signature.algorithm`，
   将算法字段纳入密码学签名绑定，防降级/算法替换）。
2. 禁止任何 JSON float（要求用整数或字符串表达数值），以在无第三方 JCS 库的
   情况下保证跨语言、跨 runtime 的 UTF-8 字节级完全一致。
3. 所有 JSON object key 按 RFC 8785 §3.2.3 规定以 UTF-16-BE 码元序递归排序。
4. 输出无多余空白、UTF-8 编码、允许非 ASCII 原样输出的紧凑 JSON 字节流。
"""

from __future__ import annotations

import base64
import copy
import json
import re
from typing import Any

_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+=*$")


def _validate_no_floats(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float):
        raise ValueError(
            f"v0.1 canonical JSON 禁止浮点数（{path}={obj!r}），请改用整数或字符串"
        )
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValueError(f"JSON object key 必须是字符串（{path}: {k!r}）")
            _validate_no_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _validate_no_floats(item, f"{path}[{idx}]")


def _sort_rfc8785(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _sort_rfc8785(obj[k])
            for k in sorted(obj.keys(), key=lambda s: s.encode("utf-16-be"))
        }
    if isinstance(obj, list):
        return [_sort_rfc8785(item) for item in obj]
    return obj


def canonical_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ValueError("envelope 必须是 JSON object")
    sig = envelope.get("signature")
    if not isinstance(sig, dict) or sig.get("algorithm") != "ed25519":
        raise ValueError("signature.algorithm 必须是 'ed25519'")
    copied = copy.deepcopy(envelope)
    copied["signature"].pop("value", None)
    return copied


def canonical_bytes(envelope: dict[str, Any]) -> bytes:
    payload = canonical_payload(envelope)
    _validate_no_floats(payload)
    ordered = _sort_rfc8785(payload)
    return json.dumps(
        ordered,
        sort_keys=False,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or not _B64URL_RE.match(value):
        raise ValueError("signature.value 不是合法的 base64url 字符串")
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
