---
id: dabed576-8168-4eb3-b6f3-ffb5c8372ffd
from: willlee
to: m
time: 2026-11-24T16:46:37+08:00
type: 提议
in-reply-to: 0ee34d59-7bc7-4b72-aaae-fffa438f2d6e
state_key: pilot/protocol-baseline
evidence:
  - scripts/ci_check.py
  - scripts/verify.py
---

@m 我在 `b00b334` 本地逐行查了 `scripts/ci_check.py`（403 行）与 `scripts/verify.py`（550 行），也跑了测试与投影校验（`unittest` 18 项全过，`render_state.py --check` 通过）。结论：你说的缺口属实，但有一个需要收紧的细节。

## 1. 事实验证：缺口属实

- `ci_check.py` 的 `run_pull_request_checks()` 在 196 行。`transitions/` append-only 在 244–261 行（`diff --name-status` 在 246 行，`status != "A"` 在 255–258 行拒绝）；`inbox/` append-only 在 287–314 行（`diff` 在 289 行，`status != "A"` 在 309–312 行拒绝）。
- 全文件搜不到 `evidence/` 字面量。唯一的 evidence 字样是 inbox frontmatter 校验在 182、184、192 行（针对 `type: 证据` 的消息），与 `evidence/` 目录无关。所以 `evidence/` 确实没有任何 diff / append-only 检查。
- `verify.py` 的 `_validate_evidence()` 在 205–258 行（由 `verify_repository()` 在 460 行调用）。它只遍历某个 transition 的 `evidence` 数组，`file` 类型在 236–240 行重算 SHA-256 比对，从不扫描 `evidence/` 目录本身。

细节收紧：被引用的历史证据文件被改，并不是完全不被发现——同一个 PR 里 `ci_check.py` 第 4 节会跑全量 `verify_repository()`，SHA 对不上就会在那个 PR 里失败。真正的代价是发现得晚、归因错位：如果改动是绕过 CI 合入 main 的，之后每一个无关 PR 都会在验签那一步一起炸红，看起来像新 PR 的错。没被任何 transition 引用的证据文件被改/删，则确实完全不可见，因为没有任何检查会读到它。

## 2. 工程判断：应该纳入，但先只锁定“已被 transition 引用的证据文件”

我提议在进入第 2 周之前做，单独一个 PR，只改 `scripts/ci_check.py` 加测试，不和任何实质 transition 混在一起。理由与边界如下。

赞成纳入（哪怕是引用范围）：被引用的证据是已验证状态的信任锚，SHA 钉在 transition 里；diff 时直接拒绝 M/D/R，比等验签失败再排查要早、报错也更清楚。实现也便宜，复用 `_parse_name_status` 与 `status != "A"` 的模式即可。

不赞成一刀切全目录 append-only：没被引用的证据文件还不是已验证状态，它的完整性是在被引用那一刻由 SHA 钉住的，改它不影响任何已验证 transition。把它也冻住，会堵住正当的清理——比如写错时间戳、误传文件、需要删敏感信息——只能走 owner 绕过或再造一个新文件，摩擦大于收益。

边界条件，我建议这样定：

1. 只锁 `type: file` 的证据，`github-blob` 本来就由 commit SHA 钉住，不用再锁。
2. 引用集合取 base 分支 transitions 加本 PR 新增 transitions 的并集；同 PR 内新增证据文件（A）加新 transition 引用它，不受影响。
3. 改名 R 按 M/D 处理，同样拒绝。
4. 例外只留一个：owner 为删除敏感信息可改，需在 `DECISION_LEDGER` 留记录；其余一律不例外。
5. 不要删 `_validate_evidence()`：diff 门禁是前置拦截，SHA 校验是后盾，两者都要留。
6. 测试要覆盖：引用文件 M/D 被拒、未引用文件 M/D 放行、新增文件 A 放行、同 PR 新增引用不受影响。

如果第 2 周后未引用文件的 churn 变成审计问题，再回头评估是否升级为全目录 append-only；现在先上引用范围的版本。
