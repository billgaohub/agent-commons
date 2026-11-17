# 已验证的共享状态（STATE）

只通过签名的 transition 更新。本文件本身不接受直接断言：
任何一行都必须能在 `transitions/` 里找到对应的 transition_id。

| state key | value | version | transition_id | verified_by | observed_at |
| --- | --- | --- | --- | --- | --- |
| _（试点开始时为空）_ | | | | | |

## 档位说明

- OBSERVED：刚收到，还没验——不进这张表。
- CANDIDATE：有证据、有签名、CI 验签通过——可列，标注 CANDIDATE。
- VERIFIED：对方 Agent 复算一遍，或人看一眼关键证据，再由约定批准人合 PR。
