## 变更摘要

<!-- 用 1–3 句话说明本 PR 解决什么问题、影响哪些模块 -->

## 变更类型

- [ ] Bug 修复
- [ ] 新功能
- [ ] 重构 / 工程化
- [ ] 文档 / 知识库
- [ ] 依赖 / 部署
- [ ] 测试

## 关联

- 关联 Issue（如有）：
- 关联 postmortem / ADR（如有）：`knowledge_base/documents/md/postmortems/...`

## 测试与验证

<!-- 勾选已执行项，并补充命令或结果 -->

- [ ] `python -m unittest discover -s tests`
- [ ] `python scripts/verify_persistence.py`（涉及向量库 / 导入 / 检索时必跑）
- [ ] 本地 Web 面板手动验证（涉及 UI / API 时）
- [ ] Docker Compose 相关变更已在 `--profile production` 下检查（如涉及 nginx / 部署）

## 本次心得（必填）

<!-- 团队知识沉淀入口：踩坑、误判、新认知、后续建议。合并后整理进 knowledge_base/postmortems/ -->

**现象 / 背景：**


**根因（若已知）：**


**解决 / 本次做法：**


**预防清单（下次如何避免）：**

- [ ]

**是否建议写入知识库？**

- [ ] 否，仅代码变更
- [ ] 是，合并后由作者整理为 postmortem / runbook
- [ ] 是，Reviewer 协助整理

## Reviewer 检查清单

- [ ] 变更范围与摘要一致，无无关改动
- [ ] 敏感信息未入库（`.env`、token、真实 API Key）
- [ ] 部署路径 / docker 引用在仓库内真实存在
- [ ] 「本次心得」有沉淀价值或已说明为何无需沉淀

## 截图 / 日志（可选）

<!-- 错误现象、修复前后对比、bench 结果等 -->
