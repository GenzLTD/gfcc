# 贡献指南 — szpeter2026 / DemoPeter

感谢参与 DemoPeter 知识库平台的协作。本文描述**从零代码开始**的团队流程：授权、审阅、知识沉淀。

---

## 1. 仓库与溯源

| 范围 | 说明 |
|------|------|
| **DemoPeter（本仓）** | GitHub `szpeter2026/DemoPeter`，RAG 知识库主项目 |
| **溯源源头（本机）** | 当前 Mac 集齐关联源码，作为按图索骥式重构与文档对齐的基准 |
| **阿里云 Gitea** | PlanetX / ImartOS 等内网仓，PR 流程与本指南原则一致 |

新成员 clone 本仓后，以 **`main` + 本文 + `knowledge_base/documents/md/postmortems/`** 为入口，再扩展到其他仓库。

---

## 2. Git 身份（一人一套）

提交署名（Author）与推送认证（PAT / SSH）是两套机制：

| 层级 | 含义 | 要求 |
|------|------|------|
| **Author** | commit 里显示的姓名与邮箱 | 每人固定一套，邮箱已在 GitHub/Gitea 验证 |
| **推送认证** | 谁有权 push | 每人独立 PAT 或 SSH key，禁止共享 `macos.token` |

**DemoPeter 本仓** 历史提交使用组织身份：

```bash
git config user.name "zervi"
git config user.email "zervi@genz.ltd"
```

团队成员加入后，请使用**个人**姓名与邮箱（便于贡献统计与责任追溯）；组织品牌见仓库 README，不与个人 Author 混用。

查看当前生效配置：

```bash
git config user.name
git config user.email
```

---

## 3. 分支与 Pull Request

```
main（保护分支，禁止直推）
  ↑ merge
feature/<topic> 或 fix/<topic>
  ↑ 开发 + 自测
```

### 流程

1. 从最新 `main` 拉分支
2. 本地开发与自测（见下文「验证清单」）
3. 提交 PR，**填写 PR 模板全部必填项**（含「本次心得」）
4. 至少 **1 名 Reviewer Approve** 后合并
5. 若心得标记「建议写入知识库」，合并后补充 `knowledge_base/documents/md/postmortems/` 或 `runbooks/`

### 提交信息

遵循现有风格，例如：

```
fix: 简短说明根因与修复

可选正文：影响模块、Breaking change、关联 postmortem 路径
```

---

## 4. 验证清单（合并前）

按变更类型执行：

| 类型 | 命令 / 动作 |
|------|-------------|
| 通用 | `python -m unittest discover -s tests` |
| 向量库 / 导入 / RAG | `python scripts/verify_persistence.py` |
| 检索质量调优 | `python scripts/bench_retrieval.py`（按需） |
| 部署 / Docker | `docker compose config`；生产 nginx 用 `--profile production` |
| 文档 / 知识库 | 确认路径存在、无真实密钥 |

---

## 5. 知识沉淀（与代码同等重要）

DemoPeter 不仅是代码仓，也是**团队经验库**。目标闭环：

```
PR 心得 → 结构化文档 → 审核 → 向量库 → RAG 可检索
```

### 文档目录

```
knowledge_base/documents/md/
├── postmortems/     # 踩坑复盘（现象 / 根因 / 解决 / 预防）
├── runbooks/        # 操作手册（部署、回滚、巡检）
├── decisions/       # ADR 架构决策
└── onboarding/    # 新人与环境规范
```

### 模板（postmortem 最小字段）

- 日期 / 作者 / 关联 PR 或 commit
- 现象
- 根因
- 解决
- 预防检查清单
- 标签（如 `#docker` `#embedding` `#git`）

首篇示例：[postmortems/2026-05-27-persistence-review-fixes.md](knowledge_base/documents/md/postmortems/2026-05-27-persistence-review-fixes.md)

### 谁写、谁审

| 动作 | 建议角色 |
|------|----------|
| PR 内「本次心得」 | 作者（必填） |
| 整理为 postmortem MD | 作者或 Reviewer |
| 合并进向量库 | Maintainer（`import` / 审核队列，流程演进中） |

---

## 6. 密钥与安全

- **勿提交**：`.env`、`.env.production`、`macos.token`、任何 API Key
- 生产配置从 **`.env.production.example`** 复制模板，在服务器或本地单独填写
- 撤销成员权限时：删除其 PAT/SSH，不必更换全员密钥（若未共享）

---

## 7. 相关文档

| 文档 | 说明 |
|------|------|
| [README.md](README.md) | 项目概览与快速开始 |
| [docs/知识运营闭环规划.md](docs/知识运营闭环规划.md) | 知识库自动化演进路线图 |
| [docs/快速开始.md](docs/快速开始.md) | 环境与 Docker |
| [deploy.sh](deploy.sh) | 阿里云 ECS 部署 |

---

## 8. 获取帮助

- 架构与模块边界：先问 RAG「DemoPeter 架构是什么」或查阅 `docs/架构设计.md`
- 合并争议：PR 讨论区 + Reviewer 裁决；架构级变更建议补充 ADR

---

**原则：代码可回滚，经验不可丢。** 每次值得记录的坑，都应有机会成为下一人的捷径。
