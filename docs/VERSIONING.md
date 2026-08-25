# 契约版本策略

> 契约是权威，就必须回答权威怎么变。价值层 [`docs/vision.md`](vision.md) 约束本文件。

## Semver（`contracts/*.json` 的 `version`）

| 变更 | 版本 | 例子 |
|---|---|---|
| 破坏性 | **主版本** | 删字段、改枚举语义、去掉端口 |
| 兼容新增 | **次版本** | 加字段、加端口、加 `status=partial` |
| 文案/示例 | **修订号** | 注释、zh 标签 |

当前线：Ask / 五端口 **1.1.0**。信号线（`signal.envelope` + `contracts/signals/`）**1.0.0**，与 1.1.0 分家族，互不要求同号。

## 变更流程

1. 过 **L-1**：[vision.md](vision.md) 的定位句与五条成功判据仍成立。
2. 改 JSON（先真源）。
3. 改 [ports/README.md](ports/README.md)。
4. 记入 [CHANGELOG.md](CHANGELOG.md)。
5. 再改适配器 / 调用方。

禁止为迁就 JobFirst intent 表或某个 vendor 实现倒改契约。

部署后的信封时间窗、新 `signal_type` 等硬化，见 [`POST_DEPLOY_FEDERATION_HARDENING.md`](POST_DEPLOY_FEDERATION_HARDENING.md)；**上机完成前不实施**。动信封必须先改本页 Semver，再改 JSON。

## 谁评审

契约变更须能回答：人还是目的吗？AI 有没有变成决策者？治理权有没有被卖掉？有结果是否仍不等于成功？
