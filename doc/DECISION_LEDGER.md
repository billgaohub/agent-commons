# 决策账本（Decision Ledger）

复用 aiobn-site `doc/DECISION_LEDGER.md` 的 D-编号逻辑。
Agent 直接用 GitHub blob URL 直读，不经过任何一方中转。

| 编号 | 日期 | 决定 | 依据/证据 | 批准人 |
| --- | --- | --- | --- | --- |
| D-0001 | 2026-11-17 | （示例）试点范围：两人、两 Agent、一话题、两周 | Bill 口头定 | Bill |
| D-0002 | 2026-11-17 | （示例）钱/对外承诺/删数据/改生产状态必须人点头 | 铁律，见 README | Bill |

## 规则

- 决定当时记账，不事后补。
- 涉及钱、对外承诺、删数据、改生产状态的决定，只有人的批准才生效。
- Agent 之间的共识只记 OBSERVED，进不了这张表，除非按 transition 流程升到 VERIFIED。
