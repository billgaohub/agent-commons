# 已验证的共享状态（STATE）

本文件由 `scripts/render_state.py` 根据 `transitions/` 确定性投影生成，**禁止手工直接编辑**。
任何一行都必须能在 `transitions/` 里找到对应的已验签 `transition_id`。

| state key | value | version | verdict | transition_id | verified_by | observed_at |
| --- | --- | --- | --- | --- | --- | --- |
| pilot/protocol-baseline | dual-verified-by-willlee | 2 | VERIFIED_CHANGE | aee3eaa0-6499-4565-9a4d-b292e0b6ef82 | willlee | 2026-11-24T15:52:19+08:00 |
| registry/willlee-active-key | willlee-2026-02 | 1 | VERIFIED_CHANGE | cf3dc53b-52f2-4708-b785-0bca592aaf45 | m | 2026-11-24T15:39:30+08:00 |

## 档位说明

- OBSERVED：刚收到（合入 `inbox/`），还没验——不进这张表。
- CANDIDATE：有证据、有签名、CI 验签通过——在 PR 中待复核。
- VERIFIED：对方 Agent 复算一遍或人看一眼关键证据，由约定批准人合入 `main` 后生效。
