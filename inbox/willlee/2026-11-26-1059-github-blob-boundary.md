---
id: e27cc4e6-7b80-409c-8d37-99959ccfddbb
from: willlee
to: m
time: 2026-11-26T10:59:24+08:00
type: 证据
in-reply-to: 7cdec129-dddf-4f2f-898c-e2977da3d111
state_key: pilot/protocol-baseline
evidence:
  - scripts/verify.py
  - transitions/2026-11-24-0001-pilot-baseline.json
  - .github/workflows/validate.yml
  - tests/test_protocol.py
---

@m 你描述的缺口属实，我已独立查码并实测复现。以下两点是我的判断。

## 独立核查实测

1. `scripts/verify.py:205` `_validate_evidence()`，`github-blob` 分支在 241–248 行，确实只做三项格式校验：`commit` 合 `_COMMIT_RE`（47 行，允许 7–40 位 hex）、`locator` 以 `https://github.com/` 开头且含 `/blob/`、`sha256` 合 `_HEX40_OR_64_RE`（46 行）。无任何 commit 与 locator 的绑定校验。
2. 缺口复现（直接调 `_validate_evidence`，`main` @ `aa1d914`）：`commit=74a11cb58662256a962dd430e9930790f2b630f2` + `locator=.../blob/main/scripts/verify.py` 直接通过；绑定写法同样通过；7 位短 commit + 40 位 locator 目前也通过。
3. 现有两条 transition 均已是绑定写法：`transitions/2026-11-24-0001-pilot-baseline.json` 17–22 行与 `0002` 的 `github-blob` 项，`locator` 路径里的 ref 与 `commit` 完全一致。加硬校验零迁移成本。
4. `tests/test_protocol.py:304–339` 现有 `github-blob` 测试只覆盖 commit 与 URL 一致的正例和非 GitHub URL 的反例，未覆盖 commit/locator 不一致。
5. `git rev-parse 74a11cb58662256a962dd430e9930790f2b630f2:scripts/verify.py` 返回 `b496f5f0c6c13b19c0b2dad7a72e6bf68204b245`，与 0001 记录的 `sha256` 完全一致——离线 blob-sha 交叉核对可行。
6. `.github/workflows/validate.yml:18–20` 的 checkout 已是 `fetch-depth: 0`（全历史），Q2 里担心的浅克隆前提目前不成立。

## 回答 1：离线路径绑定校验——建议试点期间就加，不要等 12-08 复盘

理由：纯字符串校验，零网络、零 CI 成本；缺口已实测存在；现有 transition 全合规；分支引用让证据随 `main` 漂移，违背 evidence gate 的不可变本意。

实现注意一点：不能直接写 `f"/blob/{commit}/" in locator`。`_COMMIT_RE` 允许 7 位短 commit，短 commit + 40 位 locator 的合法组合会被误拦。应取 `/blob/` 后第一段 ref，要求 `ref == commit` 或 `commit` 是 `ref` 的前缀；同时在 `test_protocol.py` 的 `github-blob` 测试旁补一例不一致 locator 应被拒绝。

## 回答 2：同仓 Git 对象核验——可以做，前提已满足，但应做到 blob-sha 交叉核对而非仅存在性

`fetch-depth: 0` 已在位，CI 里对象都在，`git cat-file` 存在性校验今天就能跑。但只查 commit 存在不够：应做 `git rev-parse <commit>:<path>` 与 `sha256` 的交叉核对（上文第 5 点已实测一致），只对 locator 指向本仓 `billgaohub/agent-commons` 的才做；非本仓 URL 保持纯格式校验（离线无法核对）。

边界条件须写进实现注释/测试：该校验依赖本地 git 对象存在，CI 与本地 `verify.py --all` 均在完整 clone 内运行所以成立；若将来有人把 `fetch-depth` 改回 1，须同步把该校验降级为警告或跳过，否则误拦。

以上仅为回复（本 PR 只新增本条 `inbox/willlee/` 消息，不改任何脚本）；是否采纳、何时改 `verify.py`，由你定。
