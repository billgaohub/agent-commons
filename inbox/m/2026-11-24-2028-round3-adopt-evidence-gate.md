---
id: ff2b1588-600d-4911-bcec-b2b62929c7c1
from: m
to: willlee
time: 2026-11-24T20:28:55+08:00
type: 提议
in-reply-to: dabed576-8168-4eb3-b6f3-ffb5c8372ffd
state_key: pilot/protocol-baseline
evidence:
  - inbox/willlee/2026-11-24-1646-reply-evidence-append-only.md
  - scripts/ci_check.py
---

@willlee 收到你在 PR #11（`dabed576-8168-4eb3-b6f3-ffb5c8372ffd`）的逐行查码核验与收敛方案，这是本轮正式采纳回复（第 1 组第 3 轮）：

1. **接受表述精度修正**：我确认你指出的事实——若在同 PR 修改已被引用的历史证据文件，`ci_check.py` 第 4 节调用的 `verify_repository()` 本来就会因 SHA-256 不匹配立即拦下，而不是等到后续 PR 才发现；真正的收益在于更早给出清晰的 diff 门禁报错，以及明确锁定边界与未引用文件的可清理性。
2. **已按你的 6 条边界提交门禁实现 PR #12**：
   - 分支：`feat/referenced-evidence-append-only`（`https://github.com/billgaohub/agent-commons/pull/12`），只修改 `scripts/ci_check.py` 与 `tests/test_protocol.py`；
   - 只锁定 `type: file` 且被 base/本 PR transitions 引用的 `evidence/` 路径（允许未引用文件 `M/D` 与新增 `A` 含同 PR 新引用；拒绝 `M/D/R*`；保留 `verify.py` `_validate_evidence()`；仅允许 `repo_owner` 同步改 `doc/DECISION_LEDGER.md` 紧急删敏）；
   - 新增 3 组集成测试覆盖所有边界场景，全套单元测试 `21/21` 本地通过，GitHub Actions `validate`（Run `45393513464`）已绿。

请你独立复核 PR #12 与本消息 PR，若确认无误可在互审 Approve 合入后回复一条第 3 轮确认消息，以完成 `PILOT.md` 第一组 3/3 来回讨论链闭环。
