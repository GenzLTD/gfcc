# 环 2：天翼中央机挂 DemoPPI（发给机上操作的人）

> **地位（2026-08-26 夜）**：部署段 + 信号段均已通过，**不要当未完成施工单重跑**。验收见 [联邦测试闭环方案 §8.3 / §8.5](联邦测试闭环方案.md)。下文仅作复原/重建参考。

机器：`14.29.216.219`（root）。大约 20–40 分钟。做完把第 6 步输出发回即可。

Dashboard Redirect 已加好，操作的人**不用**进 Supabase。

---

## 不要动

- 不要 `docker compose down` 任何现有项目（Looma / 格契）
- 不要改 `docker-compose.tianyi.full.yml`，不要把 DemoPPI 并进去
- 不要改安全组（不要开 3000、5203、5211）
- 不要 `nginx -s reload`，改 Nginx 只用 `systemctl restart nginx`
- **不要** `git clone` Gitee/GitHub 的 `demo-ppi-mvp` `main`（缺 `/ppi` 与链 B，会挂错站）

源码由本机 rsync，见第 1 步。

---

## 第 1 步：在 Jason 的 Mac 上推代码（对方还没登录前先做）

```bash
rsync -avz --delete \
  --exclude node_modules --exclude .next --exclude .git \
  --exclude .env.local --exclude .env --exclude '.env.tianyi' \
  /Users/jason/THOMAS/demo-ppi-mvp/ \
  root@14.29.216.219:/opt/demo-ppi-mvp/
```

对方若自己拷：保证机上 `/opt/demo-ppi-mvp/` 里有 `docker-compose.tianyi.yml`、`deploy/nginx-ppi.snippet.conf`、`Dockerfile`。没有这两份 yml/conf 就停，不要用仓里旧的 `docker-compose.yml`（会把 3000 绑到 `0.0.0.0`）。

---

## 第 2 步：SSH 上天翼，只探活

```bash
ssh root@14.29.216.219

curl -sf -o /dev/null -w "looma_health %{http_code}\n" http://127.0.0.1/health
curl -sf -o /dev/null -w "kernel %{http_code}\n" http://127.0.0.1:5211/health
ss -tlnp | grep -E ':80|:3000|:5203|:5211'
ls /opt/demo-ppi-mvp/docker-compose.tianyi.yml /etc/nginx/sites-available/looma
```

停手：`/health` 或内核不是 200；`:3000` 已经被别人占用；没有 `looma` 站点文件。

---

## 第 3 步：写 `/opt/demo-ppi-mvp/.env.tianyi`

```bash
cd /opt/demo-ppi-mvp
cp .env.tianyi.example .env.tianyi
chmod 600 .env.tianyi
```

用编辑器填这几项（**不要**把值发到群里）：

| 变量 | 从哪取 | 注意 |
|------|--------|------|
| `NEXT_PUBLIC_SUPABASE_URL` | 已写好，勿改 | `https://ftsnrqwynofsxdvoxnsw.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | 找 Jason 要（Dashboard API Keys） | 构建期写入镜像 |
| `SUPABASE_SERVICE_ROLE_KEY` | 找 Jason 要 | 仅运行时，勿提交 git |
| `SIGNAL_INGEST_SECRET` | 与内核同一把，见下 | **不要**用 ethos 那把 |
| `PLANETX_SIGNAL_INGEST_URL` | **留空** | 天翼 Looma 无 DemoPPI 入站 |
| `SIGNAL_BRIDGE_SECRET` | 留空即可 | 环 2 不走链 A |

其余保持 example 默认：

```
NEXT_PUBLIC_SITE_URL=http://14.29.216.219/ppi
NEXT_PUBLIC_BASE_PATH=/ppi
NEXT_PUBLIC_PLANETX_URL=http://14.29.216.219
GFCC_SIGNAL_INGEST_URL=http://host.docker.internal:5211/v1/signal-ingest
```

取内核密钥（只在机上看，不要贴聊天）：

```bash
systemctl cat gfcc-kernel.service
# 看 EnvironmentFile= 指向的文件，再：
grep '^SIGNAL_INGEST_SECRET=' 那个文件
```

若内核文件里是空的或仍是联调值，停手问 Jason，不要自己编一把。

---

## 第 4 步：起独立 Compose（项目名 `demoppi`）

```bash
cd /opt/demo-ppi-mvp
docker compose -p demoppi -f docker-compose.tianyi.yml --env-file .env.tianyi up -d --build
docker compose -p demoppi -f docker-compose.tianyi.yml ps
curl -sS -o /dev/null -w "ppi_loopback %{http_code}\n" http://127.0.0.1:3000/ppi/
```

构建要几分钟。期望：容器 Up；回环 `/ppi/` 不是 000/连接拒绝（首次可能 404 直到 Nginx 配好，但 **本机 3000 必须有进程在听 `127.0.0.1`**）。

```bash
ss -tlnp | grep 3000
# 必须是 127.0.0.1:3000 ，不能是 0.0.0.0:3000
```

---

## 第 5 步：Nginx 只加 `/ppi/`，然后 restart

```bash
cp -a /etc/nginx/sites-available/looma /etc/nginx/sites-available/looma.bak.ring2
```

把下面整段粘进 `server { }` **里面**，和现有 `/v1/`、`/health` 并列。不要嵌进 `location /` 块里。

```nginx
location = /ppi {
    return 301 /ppi/;
}

location /ppi/ {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

```bash
nginx -t && systemctl restart nginx
```

`nginx -t` 失败就 `cp` 回 `.bak.ring2`，不要硬 restart。

---

## 第 6 步：验收（把输出发回）

```bash
echo '=== 现网入口 ==='
curl -sS -o /dev/null -w "GET /          %{http_code}\n" http://127.0.0.1/
curl -sS -o /dev/null -w "GET /health    %{http_code}\n" http://127.0.0.1/health
curl -sS -o /dev/null -w "GET /ppi/      %{http_code}\n" http://127.0.0.1/ppi/
curl -sS -o /dev/null -w "GET /ppi/auth/login  %{http_code}\n" http://127.0.0.1/ppi/auth/login

echo '=== 不该对外 ==='
ss -tlnp | grep -E ':3000|:5211|:5203'

echo '=== 容器 ==='
docker compose -p demoppi -f /opt/demo-ppi-mvp/docker-compose.tianyi.yml ps
```

期望：`/` 和 `/health` 仍 200（PlanetX / Looma 没被冲掉）；`/ppi/` 与 `/ppi/auth/login` 为 200 或 307/308（不要 502/504）；`:3000` 只绑 `127.0.0.1`。

浏览器打开：`http://14.29.216.219/ppi/auth/login`

---

## 回滚

```bash
docker compose -p demoppi -f /opt/demo-ppi-mvp/docker-compose.tianyi.yml down
cp -a /etc/nginx/sites-available/looma.bak.ring2 /etc/nginx/sites-available/looma
nginx -t && systemctl restart nginx
```

Looma / 格契不应被这条 down 碰到。
