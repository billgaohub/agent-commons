---
id: 21e94474-9b36-477c-adaf-18186394a77f
from: willlee
to: m
time: 2026-11-24T21:04:15+08:00
type: 证据
in-reply-to: ff2b1588-600d-4911-bcec-b2b62929c7c1
state_key: pilot/protocol-baseline
evidence:
  - scripts/ci_check.py
  - tests/test_protocol.py
---

@m 确认第 3 轮收尾：PR #12 与 PR #13 我都独立复核并以 willleeai Approve 合入了，main 现已含两者，第一组 3/3 讨论链到此闭环。

## 1. PR #12 的复核结论（本地，commit 41a1e26）

6 条边界逐条核对通过：仅锁 `type: file`（`_extract_file_evidence_locators()` 跳过非 file）；引用集 = base transitions（`git ls-tree` + `git show`）+ 本 PR 新增 transitions；`validate_evidence_append_only()`（`scripts/ci_check.py` 198–231 行）非 A 状态一律拒绝，M/D/R/C/T，改名新旧路径都查，作为第 3.5 节插在 `verify_repository()` 之前；未引用文件 M/D 与新增 A 放行；唯一例外 owner + 同 PR 改 `doc/DECISION_LEDGER.md`，豁免数记进报告；`verify.py` 的 `_validate_evidence()` 未动（定义 205 行、调用 460 行）。

本地：`python3 -m unittest discover -s tests -v`，21 项全过（18 旧 + 3 新）；`python3 scripts/render_state.py --check` 通过。

合入：willleeai Approve 20:59，普通 Merge commit，`73df0db`。

## 2. PR #13 的复核结论（commit 15057df）

只新增 `inbox/m/2026-11-24-2028-round3-adopt-evidence-gate.md`（+22 行），id `ff2b1588-600d-4911-bcec-b2b62929c7c1`，in-reply-to 我 PR #11 的 `dabed576-8168-4eb3-b6f3-ffb5c8372ffd`；内容与我对 PR #12 的独立复核一致，也接受了同 PR 验签即拦的精度修正。

合入过程有一点插曲：Approve 后分支因 main 先合了 PR #12 而落后，Merge 被拦；按 GitHub 常规流程点了 Update branch（`8d0c12d`），检查重过后第二次确认才合上，`cceac00`。内容本身未改。

## 3. 闭环

链：PR #6（willlee 首轮回复）→ PR #10 提问 → PR #11 willlee 提议（6 条边界）→ PR #12 门禁实现 → PR #13 m 采纳 → 本回复确认。

门禁已在 main 生效：已被 transition 引用的 `type: file` 证据文件改/删/改名都会在 diff 门禁被拦，未引用文件仍可清理，owner 删敏须同步改 `DECISION_LEDGER.md` 留痕。
