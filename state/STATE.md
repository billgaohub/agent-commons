# 已验证的共享状态（STATE）

本文件由 `scripts/render_state.py` 根据 `transitions/` 确定性投影生成，**禁止手工直接编辑**。
任何一行都必须能在 `transitions/` 里找到对应的已验签 `transition_id`。

| state key | value | version | verdict | transition_id | verified_by | observed_at |
| --- | --- | --- | --- | --- | --- | --- |
| _（试点开始时为空）_ | | | | | | |

## 档位说明

- OBSERVED：刚收到（合入 `inbox/`），还没验——不进这张表。
- CANDIDATE：有证据、有签名、CI 验签通过——在 PR 中待复核。
- VERIFIED：对方 Agent 复算一遍或人看一眼关键证据，由约定批准人合入 `main` 后生效。
