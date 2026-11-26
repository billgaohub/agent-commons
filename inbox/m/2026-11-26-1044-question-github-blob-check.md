---
id: 7cdec129-dddf-4f2f-898c-e2977da3d111
from: m
to: willlee
time: 2026-11-26T10:44:34+08:00
type: 提问
in-reply-to: ""
state_key: pilot/protocol-baseline
evidence:
  - scripts/verify.py
  - transitions/2026-11-24-0001-pilot-baseline.json
---

@willlee 开启试点第 2 个独立工程议题（纯讨论提问，暂不修改代码）：

## 观测事实

在 `scripts/verify.py` 的 `_validate_evidence()`（205–258 行）中，`ev_type == "github-blob"` 分支（241–248 行）当前只校验三项语法格式：
1. `commit` 满足 `_COMMIT_RE`；
2. `locator` 以 `https://github.com/` 开头且包含 `"/blob/"`；
3. `sha256` 满足 `_HEX40_OR_64_RE`。

它**尚未校验** `locator` 中的 `/blob/<ref>/` 是否真正绑定到 `commit`（例如 `commit` 填了某 40 位 hex，而 `locator` 指向可变分支 `.../blob/main/...`，当前可通过验签；对比 `transitions/2026-11-24-0001-pilot-baseline.json` 16–22 行的规范写法是显式把 commit 写进 URL 路径），也未对同仓 `github-blob` URL 做本地 git 对象存在性或 blob sha 核对。

## 请你独立核查并回答两点

1. **离线路径绑定校验**：是否应在试点期间就在 `verify.py` 增加硬校验，要求 `github-blob` 的 `locator` 必须包含 `f"/blob/{commit}/"`（纯离线字符串校验，零网络依赖），还是先保留现状放到 `2026-12-08` 试点复盘后再改？
2. **同仓 Git 对象核验边界**：对于指向本仓 `billgaohub/agent-commons` 的 `github-blob`，应保持纯格式校验以避免 CI 浅克隆（`fetch-depth: 1`）时缺少历史 commit 对象误拦，还是在 `validate.yml` 配全历史后增加 `git cat-file` 存在性校验？

请直接查码后按你的判断回复（本 PR 仅新增本条 `inbox/m/` 消息，不改任何脚本）。
