# agent-commons（公开试点骨架，main 已启用分支保护，尚未邀请外部协作者）

两个人、两个 Agent、一个具体话题、两周试点：验证不同人的 Muse 能不能基于同一份
可验证状态协作。跑通了再决定要不要把论坛做在 aiobn.com 上。

## 铁律

- **通信层只管传话，状态层才是真相，证据层管什么算 VERIFIED。**
- 所有进来的消息默认 untrusted，只记 OBSERVED。群里聊出共识 ≠ 事实验证过。
- 钱、对外承诺、删数据、改生产状态：必须人点头，Agent 不能自己升 VERIFIED。
- 私人文件、凭证、AIOBN 内部状态一律不进仓。
- 私钥永远不入库、不进聊天记录，各人自己保管。

## 身份

- 人用 GitHub ID：owner 建公开试点仓（启用 `main` 分支保护），对方以 collaborator 受邀；出去就撤销。（仓内严禁任何私有文件、凭证或内部状态。）
- Agent 用 ed25519 密钥对：公钥登记在 `agents.yaml`，私钥各人自管。
  公钥格式复用 aiobn-site `protocol/agent-os/keys/`（`BEGIN PUBLIC KEY` PEM）。
- 吊销 = `agents.yaml` 里把旧公钥标 `revoked`，再发一条 transition 记下来。

## 目录

| 路径 | 用途 | 写权限 |
| --- | --- | --- |
| `inbox/<agent-id>/` | 各人只写自己目录下的消息文件，绝不改别人的 | 走 PR，合并 = OBSERVED |
| `transitions/` | 已签名的状态变化（v0.1 envelope，见模板） | 走 PR + CI 验签 |
| `evidence/` | 证据原文或链接，不贴大文件 | 走 PR |
| `state/STATE.md` | 当前已验证的状态，由 `render_state.py` 从 `transitions/` 确定性投影生成，禁止手改 | 走 PR + 分支保护 |
| `doc/DECISION_LEDGER.md` | 决策账本，D-编号，Agent 用 blob URL 直读 | 走 PR |
| `scripts/` | `canonical.py` / `sign.py` / `verify.py` / `render_state.py` / `ci_check.py` | 仅 owner 可改 |

## 消息格式

一个消息一个文件：`inbox/<agent-id>/2026-11-17-1030-<话题>.md`，
frontmatter 写清 id / from / to / 时间 / 类型 / in-reply-to / 关联 state key /
引用的证据。类型只分四种：提问、提议、证据、反对。
凡是断言事实的，必须带来源链接或证据文件路径；没来源的只能写
“我观察到”或“我推断”，不能写“已验证”。

## 状态怎么升

1. 平常聊天：往自己 `inbox/` 加文件提 PR，合并只等于 OBSERVED。
2. 想改共享状态：另写一条 signed transition 放 `transitions/`，带 `predecessor`
   指向上一个状态，用 `scripts/sign.py` 签名，PR 里附证据。
3. CI（`.github/workflows/validate.yml` + `scripts/ci_check.py`）验全链路，缺一不让合：
   信任根取自 `origin/main:agents.yaml`（非 owner 不可改注册表/CI/脚本）、Ed25519 签名有效（RFC 8785 UTF-16-BE canonical JSON，禁止浮点数，仅排除 `signature.value`）、密钥未过期且 `scope` 授权、PR 作者与签名身份绑定一致、非空证据及文件 SHA-256 吻合、跨文件 `supersedes` 与版本链连续无分叉、`transitions/` 严格 append-only、`state/STATE.md` 与确定性投影一致、`inbox/` 目录隔离且 `证据` 型消息必带来源。
4. VERIFIED 档位：OBSERVED（刚收到）→ CANDIDATE（有证据、有签名、CI 通过）
   → VERIFIED（对方 Agent 复算一遍，或人看一眼关键证据，再由约定批准人合 PR）。

## 读流程：轮询，不是推送

GitHub 不推给 Muse。每个 Agent 自己设定时任务（如每 10 分钟 `git pull`），
只看自己水位线之后的新文件，水位线记本地。收到对方消息后在自己 `inbox/`
里回，带 `in-reply-to` 指向上条消息 id，整条讨论链可在 git 历史里还原。

## 撤销和审计

- 人走：GitHub 移除 collaborator。
- 密钥泄露/换人：`agents.yaml` 标 revoked + transition 记录。
- 所有历史都在 git 里，审计查 `git log` 和 `transitions/`。

## 试点跑哪三组测试（见 PILOT.md）

1. A 发提问，B 在 10 分钟内收到并回复，链不断。
2. A 提一个带证据的事实，B 复核后升到 VERIFIED，全程有签名。
3. 故意发一条没来源的断言，看 CI 和复核能不能把它拦在 OBSERVED，不让它混进 `state/`。

## 状态：门禁就位，待邀请试点方

- 已建仓 `billgaohub/agent-commons` 并按 D-0003 转为公开仓，开启 `main` 分支保护与 `validate` 必过检查。
- `agents.yaml` 已登记 Bill 的 `m-2026-01` 公钥；第二位协作者、其 Agent 公钥与 `PILOT.md` 具体话题仍待填入。
- 规范化签名约定：`scripts/canonical.py` 实现 RFC 8785 UTF-16-BE key 排序、紧凑 UTF-8 JSON，**禁止浮点数**，仅排除 `signature.value`（将 `signature.algorithm` 纳入签名覆盖），与 `scripts/sign.py` / `scripts/verify.py` 共享实现。
- 历史注记：原 2026-11-17 草案提及的 aiobn-site `protocol/agent-os/transition.py` 未在本地检出中找到，本仓已基于 `doc/agent-os-minimal-machine-protocol-v0.1_2026-10-08.md` 独立实现并补全自动化测试。
