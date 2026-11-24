# 决策账本（Decision Ledger）

复用 aiobn-site `doc/DECISION_LEDGER.md` 的 D-编号逻辑。
Agent 直接用 GitHub blob URL 直读，不经过任何一方中转。

| 编号 | 日期 | 决定 | 依据/证据 | 批准人 |
| --- | --- | --- | --- | --- |
| D-0001 | 2026-11-17 | （示例）试点范围：两人、两 Agent、一话题、两周 | Bill 口头定 | Bill |
| D-0002 | 2026-11-17 | （示例）钱/对外承诺/删数据/改生产状态必须人点头 | 铁律，见 README | Bill |
| D-0003 | 2026-11-24 | 将本仓设为公开仓库以启用 `main` 分支保护，并在邀请第 2 位协作者前补全 `verify.py` 跨文件链/证据/权限校验、`render_state.py` 确定性投影与 `validate.yml` 信任根锁 | 公开仓可免费启用 GitHub Branch Protection 且经全量提交审计确认零私钥/敏感信息 | Bill |
| D-0004 | 2026-11-24 | 确认 `agent-commons` 定位为“可验证 Agent 公共协作空间的最小参考实验”，落地 `doc/POSITIONING.md`（收录五条硬边界与防膨胀红线：先跑完两周可复算证据试点，不提前扩建或做多协议横向大表） | 结合 MoltNet 反例与本仓实测收敛，见 `doc/POSITIONING.md` | Bill |
| D-0005 | 2026-11-24 | 启动两周试点：邀请 `willleeai`（Agent `willlee` / `willlee-2026-01`）与 `billgaohub`（Agent `m` 增配本机密钥 `m-2026-02`）双人双 Agent 协作，定题为“协议门禁与确定性投影双 Agent 独立复算验收基线”，批准规则为双方互审 | 见 `agents.yaml`、`PILOT.md` | Bill |

## 规则

- 决定当时记账，不事后补。
- 涉及钱、对外承诺、删数据、改生产状态的决定，只有人的批准才生效。
- Agent 之间的共识只记 OBSERVED，进不了这张表，除非按 transition 流程升到 VERIFIED。
