# [postmortem] 持久化验证修复 — 代码审阅复盘

- **日期：** 2026-05-27
- **作者：** zervi（多设备统一协作身份）
- **关联提交：** `4fd8bc9` / `0e1a2fe` — fix: 持久化验证修复 + 质量评估脚本 + 依赖补全
- **关联 PR：** （待团队启用 PR 流程后补链接）
- **标签：** `#embedding` `#chroma` `#docker` `#nginx` `#git` `#security` `#testing`

---

## 现象

1. **向量检索间歇性空结果**：Chroma 可用但语义搜索无命中，Dashboard 无明确报错。
2. **部署构建失败风险**：`docker-compose.yml` 引用 `./docker/nginx/Dockerfile`，而 `docker/` 已在 `.gitignore` 中且目录不存在。
3. **环境脚本隐患**：`manage.ps1` 将 `.env` 复制为 `.env.production`，可能把含真实 API Key 的本地配置带入 Docker 生产编排。
4. **协作署名混乱**：同一维护者在 Mac / Windows 等设备上出现 `Jason`、`zervi`、`szben` 等多套 Author，不利于团队扩容后的追溯。

---

## 根因

| 问题 | 根因 |
|------|------|
| 检索空结果 | Chroma **隐式**加载 `DefaultEmbeddingFunction`；缺少 `onnxruntime` 时初始化失败被吞掉，集合看似正常但 query 无效 |
| nginx 构建失败 | 生产 profile 改为自定义镜像 build，但未将 `docker/nginx` 纳入版本管理 |
| `.env.production` 风险 | setup 脚本图省事从 `.env` 复制，未区分「开发密钥」与「生产模板」 |
| 署名不一致 | 各设备使用不同全局 `git config`，无仓库级规范与 CONTRIBUTING 约束 |
| 相似度公式隐患 | 使用 `1 - squared_L2/2` 转 cosine，**前提**为 embedding 向量已 L2 归一化；换模型时易误用 |

---

## 解决

### 已合并 / 审阅肯定的核心修复

- **`vector_store.py`**：显式注入 `DefaultEmbeddingFunction`，捕获异常并提示安装 `onnxruntime`。
- **`health_check()` + `/api/health/vector`**：启动与运行时主动探测 embedding 与 query 链路。
- **`scripts/verify_persistence.py`**：Embedding → 向量健康 → 导入-检索冒烟测试，适合作 CI 门禁。
- **`scripts/bench_retrieval.py`**：MRR / NDCG@K / Recall@K 等质量评估与 chunk 对比模式。
- **`requirements.txt`**：补充 `onnxruntime>=1.18.0`。
- **`docker-compose.yml` production profile**：开发直连 `5220`，生产 `--profile production` 才启 nginx。

### 溯源源头（Mac）已完成的文档与工程化补充

- **`.github/pull_request_template.md`**：强制「本次心得」字段，作为知识沉淀入口。
- **`CONTRIBUTING.md`**：分支保护原则、Git 身份、验证清单、postmortem 目录约定。
- **nginx**：改回 `nginx:alpine` + 挂载根目录 `nginx.conf`（与历史可构建方式一致）。
- **`manage.ps1`**：`.env.production` 改从 `.env.production.example` 生成；移除硬编码 `E:\` / `C:\` 路径。
- **`squared_l2_to_cosine_similarity()`**：提取函数并注释 squared L2 + 归一化前提。
- **`tests/test_vector_store.py`**：覆盖相似度转换与 `health_check()` 分支。

---

## 预防检查清单

合并或部署前逐项确认：

- [ ] 向量相关改动已跑 `python scripts/verify_persistence.py`
- [ ] `docker compose config` 无引用仓库外或 `.gitignore` 中的 build context
- [ ] 生产 compose 使用 `.env.production.example` 模板，**未**从 `.env` 直接复制
- [ ] `.env.production`、token 文件仍在 `.gitignore` 中
- [ ] 更换 embedding 模型时，重新验证 L2→相似度公式是否仍适用
- [ ] 新成员已读 `CONTRIBUTING.md` 并配置个人 Git Author
- [ ] PR 模板「本次心得」已填写；值得保留的已写入 `postmortems/` 或 `runbooks/`

---

## 待办（低优先级，记录备查）

| 优先级 | 项 | 说明 |
|--------|-----|------|
| 低 | 拆分 `bench_retrieval.py` | 超 1000 行，可按 dataclass / metrics / dataset 模块化 |
| 中 | CI 集成 | `verify_persistence.py` + `unittest` 作为 GitHub Actions 门禁 |
| 中 | Webhook → 知识库 | `gitea_webhook.py` 从 Notion 扩展到 KB 待审队列（见知识运营闭环 Phase 3） |

---

## 经验摘要（给 RAG / 新人）

> **一句话：** 向量库「能连上」不等于「能检索」；必须显式验证 embedding，并在 Docker/Git/密钥三处避免「看起来能跑、上线才炸」的配置。

**关键文件：**

- 向量与健康检查：`src/vector_store.py`
- 冒烟测试：`scripts/verify_persistence.py`
- 部署编排：`docker-compose.yml`、`nginx.conf`
- 协作规范：`CONTRIBUTING.md`、`.github/pull_request_template.md`

---

## 变更记录

| 日期 | 说明 |
|------|------|
| 2026-05-27 | 由远端代码审阅报告改写为首篇 postmortem，并对齐 Mac 溯源源头已做修复 |
