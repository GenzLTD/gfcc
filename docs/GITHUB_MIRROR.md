# GitHub 镜像使用指南（给 Mac 侧团队）

> **读者**：Jason + Cursor 团队（实现方）
> **写作者**：Peter 侧（评审/验收方）· 2026-08-21
> **一句话**：Gitee 是唯一真源；GitHub 是 CI 跑道。两边 commit 必须一致，CI 反馈双方共用。

---

## 1. 为什么建 GitHub 镜像

Gitee 没有可用的 Actions CI。为了让每次提交都有自动化验证（测试 + 契约校验 + 镜像构建），我们把同一份代码镜像到 GitHub 跑 CI：

| 仓库 | 地址 | 角色 |
|---|---|---|
| **Gitee（真源）** | `git@gitee.com:szbenyx/gfcc.git` | 代码权威。一切变更以这里为准 |
| **GitHub（CI 跑道）** | `git@github.com:szpeter2026/gfcc.git` | 只跑 CI、存镜像。Private，仅协作者可见 |

**不是双真源**：GitHub 上不直接做任何修改，所有代码变更先落 Gitee，再同步过来。

## 2. CI 每次提交检查什么

推送 main（或提 PR）自动触发，四个 job：

| Job | 内容 | 意义 |
|---|---|---|
| `test-libs` | ethos / tenet 单元测试 + tatha / gateway import 检查 | 共享内核回归 |
| `test-kernel` | gfcc_kernel 单测（信封 / 端口 / store 红线 / consensus 状态机 / 信号 ingest；项数以 CI 为准，CHANGELOG 曾记 98） | 格契内核契约红线 |
| `test-contracts` | `contracts/*.json` 合法性 + **分家族**版本号（Ask/五端口 1.1.0；信号信封+两种 payload 1.0.0） | **G1 冻结后防字段漂移的关键闸门** |
| `build-images` | 构建并推送 4 个 Docker 镜像到 GHCR（仅 main 触发） | 产出双方统一的构建产物 |

首次全绿基线：run #5（约 5 分半，当时 kernel 52 项）。之后已加信号家族与更多单测；以当前 Actions 为准。契约冻结线见 [`VERSIONING.md`](VERSIONING.md)。

## 3. 你的使用方法

### 3.1 首次配置（一次性）

1. **接受协作者邀请**：Peter 在 GitHub 仓库 Settings → Collaborators 发邀请到你的账号，邮箱确认接受。
2. **本地加第二个 remote**：

```bash
cd gfcc
git remote add github git@github.com:szpeter2026/gfcc.git
# 验证（需先在 GitHub 配好 SSH key）
ssh -T git@github.com
git fetch github
```

### 3.2 日常工作流

```bash
# 1. 正常开发，提交到真源 Gitee
git add ... && git commit -m "..."
git push origin main

# 2. 同步推 GitHub 触发 CI（同一份 commit）
git push github main

# 3. 浏览器看结果
#    https://github.com/szpeter2026/gfcc/actions
```

### 3.3 推荐：用 PR 预检（Step3 联调期特别有用）

不想直接推 main？可以先开分支提 PR——**PR 也会触发三个测试 job（不构建镜像）**，绿灯后再合入：

```bash
git checkout -b feat/step3-signal
# ... 开发 ...
git push github feat/step3-signal
# GitHub 网页上开 PR → CI 自动跑 → 绿了再 merge 到 main
```

### 3.4 拉取 CI 构建的镜像（联调统一产物）

CI 推送的镜像（每次 main 更新自动覆盖 `latest`）：

```
ghcr.io/szpeter2026/gfcc/tatha:latest
ghcr.io/szpeter2026/gfcc/demopeter:latest
ghcr.io/szpeter2026/gfcc/am-gateway:latest
ghcr.io/szpeter2026/gfcc/am-bridge:latest
```

拉取前需用 GitHub PAT 登录一次（PAT 需勾选 `read:packages`，生成路径：GitHub → Settings → Developer settings → Personal access tokens）：

```bash
echo <你的PAT> | docker login ghcr.io -u <你的GitHub用户名> --password-stdin
docker pull ghcr.io/szpeter2026/gfcc/tatha:latest
```

> 镜像继承仓库 Private 属性，只有协作者能拉。**联调时请用这份镜像，别本地自建**——保证 Mac / Windows 两边测的是同一个构建产物，消除"我这里能跑"的环境差异。

## 4. 同步纪律（三条规则）

1. **真源唯一**：Gitee 是权威。GitHub 上不做任何直接修改（PR 除外，merge 前先同步回 Gitee）。
2. **谁先推 Gitee，谁同步推 GitHub**：两边 main 的 commit hash 必须一致。发现不一致，以 Gitee 为准强制对齐。
3. **CI 红了先修再继续**：任何一方推的提交导致 CI 变红，修复优先级高于新功能。

## 5. 对照 Step3 三个门怎么用

| 阶段 | CI 用法 |
|---|---|
| **G1 契约冻结** | signal.envelope 等新契约入库 → `test-contracts` 自动校验 JSON 合法性与版本一致 → 冻结后任何字段改动都会被版本一致性检查拦住 |
| **G2 双方并行自测**（W1-W4 / M1-M3） | 每完成一步推 main → 三测试 job 回归；镜像由 build-images 统一产出，两边拉同一份 |
| **G3 真端对接** | Actions 运行日志（含每次 commit 的测试详情）作为双方共同认可的验收证据，可追溯 |

---

有疑问随时在 Gitee / GitHub 上提 issue，或线下对齐。
