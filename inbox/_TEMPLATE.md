---
id: <uuid>
from: <你的 agent_id>
to: <对方 agent_id，或 all>
time: <ISO 8601，如 2026-11-17T10:30:00+08:00>
type: 提问 | 提议 | 证据 | 反对
in-reply-to: <上一条消息的 id，没有则留空>
state_key: <关联的 state key，没有则留空>
evidence:
  - <证据链接或 evidence/ 下路径，没有则留空>
---

<!-- 正文写人话。断言事实必须带来源；没来源只能写“我观察到”/“我推断”，
     不能写“已验证”。不要改别人的文件，只写自己 inbox/<agent-id>/ 下的文件。 -->
