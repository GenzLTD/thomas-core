# GFCC / 格契 · 契约真源（机器可读）

本目录是 **L0 真源** 的 JSON。人读先看 [`docs/vision.md`](../docs/vision.md)，再看 [`docs/ports/README.md`](../docs/ports/README.md)。版本规则见 [`docs/VERSIONING.md`](../docs/VERSIONING.md)。

当前契约版本：**1.6.0**（L0 家族新增独立 `invitation` 联邦契约；外部身份映射到规范 `sub`，邀请、设备证明与归因各自独立；跨站只传短期 opaque handoff handle。设备证明只预留挑战/扩展，不代表 PWA 已实现硬件认证；既有 circle issuer-token 兑换为待迁移的 legacy）· 信号线 **1.1.0**（与 L0 分家族，互不影响；内核软件版本仍是 1.1.0）

| 文件 | 端口 / 层 |
|---|---|
| `ask.envelope.v1.json` | 单入口信封（含 partial、dialog_mode） |
| `signal.envelope.v1.json` | 机机信号信封（`POST /v1/signal-ingest`，与 Ask 并列） |
| `signals/consensus_match.v1.json` | DemoPPI 匹配事实 → consensus |
| `signals/personality_beacon.v1.json` | PlanetX 测评事实 → identity |
| `signals/value_axis_choice.v1.json` | PlanetX 叙事选择 → identity.value_axes |
| `circle.v1.json` | 围坐容器 |
| `identity.v1.json` | PPI 身份 + 营造师 |
| `memory.v1.json` | Dual 七库（含方法论价值、AI 观察） |
| `consensus.v1.json` | 共议（阈值 + 证据 + 双向确认） |
| `contribution.v1.json` | CoCo 贡献 |
| `roles.v1.json` | 八角梯（ethos claims，非独立服务） |
| `registry.v1.json` | 默认适配器 vs 可选画像 |
| `job_match.v1.json` | 职位分区间。auxiliary，不写价值轴 |
| `invitation.v1.json` | 跨产品邀请生命周期、受众/用途隔离、认证主体绑定与未来设备证明扩展点 |

实现向这些文件适配。改能力：过价值层 → 改 JSON → 改提纲 → 改代码。
