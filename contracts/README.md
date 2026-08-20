# GFCC / 格契 · 契约真源（机器可读）

本目录是 **L0 真源** 的 JSON。人读提纲见 [`docs/ports/README.md`](../docs/ports/README.md)。

| 文件 | 端口 / 层 |
|---|---|
| `ask.envelope.v1.json` | 单入口信封 |
| `identity.v1.json` | PPI 身份 |
| `memory.v1.json` | Dual 七库记忆 |
| `consensus.v1.json` | 共议（阈值 + 双向确认） |
| `contribution.v1.json` | CoCo 贡献 |
| `roles.v1.json` | 八角梯（ethos claims，非独立服务） |
| `registry.v1.json` | 默认适配器 vs 可选画像 |

实现向这些文件适配。改能力先改 JSON，再改代码。
