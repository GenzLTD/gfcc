# GFCC / 格契 · 契约真源（机器可读）

本目录是 **L0 真源** 的 JSON。人读先看 [`docs/vision.md`](../docs/vision.md)，再看 [`docs/ports/README.md`](../docs/ports/README.md)。版本规则见 [`docs/VERSIONING.md`](../docs/VERSIONING.md)。

当前契约版本：**1.1.0**

| 文件 | 端口 / 层 |
|---|---|
| `ask.envelope.v1.json` | 单入口信封（含 partial、dialog_mode） |
| `circle.v1.json` | 围坐容器 |
| `identity.v1.json` | PPI 身份 + 营造师 |
| `memory.v1.json` | Dual 七库（含方法论价值、AI 观察） |
| `consensus.v1.json` | 共议（阈值 + 证据 + 双向确认） |
| `contribution.v1.json` | CoCo 贡献 |
| `roles.v1.json` | 八角梯（ethos claims，非独立服务） |
| `registry.v1.json` | 默认适配器 vs 可选画像 |

实现向这些文件适配。改能力：过价值层 → 改 JSON → 改提纲 → 改代码。
