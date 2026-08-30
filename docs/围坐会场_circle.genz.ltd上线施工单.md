# 围坐会场：`circle.genz.ltd` 上线施工单

> **地位**：最短上架路径的**指向与切入口**施工单。不是账号体系、不是 App Store、不是改 `www.genz.ltd` 营销站。  
> **目标入口**：`https://circle.genz.ltd/circle/`（邀请 `?i=` 仍走此路径）。  
> **内核仍在天翼**：`127.0.0.1:5211`，安全组**继续不放行 5211**。只开/确认 **443**。  
> **对照**：拍板依据 [围坐上架路径内部决策备忘](reviews/围坐上架路径_内部决策备忘_2026-08-28.md)（D1+D2 同意、网站 ICP 通过、§0.1 四条绿后再对 testers 切域名）· [围坐会场部署手册](围坐会场部署手册.md) · [邀请深链](围坐会场_邀请深链实施.md) · nginx 样例 [`deploy/nginx-circle.genz.ltd.conf.example`](../deploy/nginx-circle.genz.ltd.conf.example)  
> **状态**：**待施工**（2026-08-28 夜与备忘对齐）。备案前只 hosts / IP 冒烟，不对外发 `circle.genz.ltd`。  
> **不要做**：把 `/circle/` 写进 Vercel 的 `www.genz.ltd`；动 `api.genz.ltd` / `tspace.genz.ltd`；给 5211 开公网；未备案就给 testers 发 https 域名。

---

## 0. 为什么是子域、不是 www

| 名 | 现在干什么 | 本单 |
|---|---|---|
| `www.genz.ltd` / `genz.ltd` | Vercel 营销 + 定价 + 隐私条款（PlanetX/GenZ） | **不动** |
| `tspace.genz.ltd` | 海外注册 | **不动** |
| `api.genz.ltd` | 海外大脑，ingest 必须空 | **不动** |
| `circle.genz.ltd` | 无 | **新建**：DNS A → 天翼，443 反代内核 `/circle/` |

页内请求写死 `/circle/api/…`，公网 URL 必须带 `/circle/`。邀请根：

```text
https://circle.genz.ltd/circle/
```

---

## 1. DNS（在 genz.ltd **当前生效**的解析控制台）

先确认权威 DNS（任选一台能出网的机器）：

```bash
dig NS genz.ltd +short
```

- 若是 `vercel-dns.com` → Vercel 项目 → Domains / DNS
- 若是 Cloudflare / 阿里云 / Namecheap → 对应解析页

只加这一条（TTL 先 300）：

| 类型 | 主机记录 | 值 |
|---|---|---|
| **A** | `circle` | `14.29.216.219` |

不要 CNAME 到 `www.genz.ltd`（会进 Vercel SPA）。不要橙云 / 加速，先 **DNS only**，TLS 在天翼终结。

等传播：

```bash
dig +short circle.genz.ltd A
# 期望只有 14.29.216.219
```

手机流量（非公司 Wi-Fi）`ping`/`nslookup` 同样指这台，再往下。

---

## 2. 天翼：安全组 + nginx + 证书

1. 安全组放行 **TCP 443**（80 已有则保持）。**5211 不放行**。
2. 备份现网：`cp /etc/nginx/sites-available/looma /etc/nginx/sites-available/looma.bak.circle-genz`
3. **不要改** `looma` 里 `listen 80 default_server`（IP 入口 PlanetX 仍走它）。
4. 拷样例为 `/etc/nginx/sites-available/circle-genz`，先只启用 **80** 段（证书文件还不存在时不要 load 443，否则 `nginx -t` 失败）。可临时注释 443 的 `server { }`。
5. `mkdir -p /var/www/certbot`；`ln -sf .../circle-genz .../sites-enabled/`；`nginx -t && systemctl reload nginx`
6. 签发（HTTP-01，依赖第 1 步 A 记录已指过来）：

```bash
sudo certbot certonly --webroot -w /var/www/certbot -d circle.genz.ltd
```

7. 打开 443 段，路径与 `/etc/letsencrypt/live/circle.genz.ltd/` 一致；再 `nginx -t && reload`。

样例见 [`deploy/nginx-circle.genz.ltd.conf.example`](../deploy/nginx-circle.genz.ltd.conf.example)。`/` → 302 `/circle/`，避免打开根域名落空。

---

## 3. 冒烟（证书起来之后、改 testers 之前）

备案未过：用本机 `hosts` 把 `circle.genz.ltd` 指到 `14.29.216.219` 测，或只测 IP。**不要**把 https 域名发到微信。

```bash
curl -sI https://circle.genz.ltd/circle/ | head -n 8
# 期望 HTTP/2 200，server 不要是 Vercel

curl -sI http://circle.genz.ltd/circle/ | head -n 5
# 期望 301 → https://circle.genz.ltd/circle/

curl -sS -o /dev/null -w "%{http_code}\n" -X POST https://circle.genz.ltd/circle/api/leave \
  -H 'Content-Type: application/json' -d '{"circle_id":"x"}'
# 期望 401 missing token（与 IP 入口同一内核）
```

浏览器无痕打开 `https://circle.genz.ltd/circle/`，标题「围坐会场」。打开 `https://www.genz.ltd` 仍应是营销首页。

---

## 4. 切邀请（主持人，云上签）

**前提**：该子域网站 ICP 已通过，且决策备忘 §0.1 四条绿。

天翼 `/data/gfcc`（与 `ETHOS_AUTH_SECRET` 同一把）：

```bash
cd /data/gfcc/services/gfcc_kernel
.venv/bin/python scripts/issue_persona_tokens.py \
  --subs <报名A-sub> <报名B-sub> <报名C-sub> \
  --invite-base https://circle.genz.ltd/circle/ \
  --out /tmp/circle_invites.json
```

微信只发 `invite_url`（形如 `https://circle.genz.ltd/circle/?i=…`）。**不要**再用 IP 发**新场**。

`http://14.29.216.219/circle/` **保留**作值班 curl 与回滚入口（稳定期建议 ≥ 7 天）。回滚：`--invite-base` 改回该 IP 根。

---

## 5. 切完才改的文档

- [围坐会场部署手册](围坐会场部署手册.md) §3 testers 入口 → `https://circle.genz.ltd/circle/`
- [邀请深链](围坐会场_邀请深链实施.md) `--invite-base` 示例
- [围坐testers须知](围坐testers须知.md) 场次当天由主持人发 https 链（页上仍无注册）

未 §0.1 四条绿之前不要改这三处，避免文档比现网快。

---

## 6. 与切流的关系（备忘 §6 / §10）

| 项 | 与本单关系 |
|---|---|
| 网站 ICP | **硬门禁**。`粤ICP备2026092569号-1` 主体下新增网站 `circle.genz.ltd`。未过 = 不对外发该域名（≠ 元服务备案） |
| R1 日志脱敏 | 切 testers 前 nginx `?i=` 脱敏须绿（§0.1 第 4 条） |
| `4b22dac` + 页上认定 | 切流前可并行，建议最前（兑得现） |
| PWA | HTTPS 通了再加独立 `manifest` + `scope=/circle/`；鸿蒙 NEXT 不承诺加到主屏幕 |
| 元服务 | 不在本单。预研见 [围坐元服务薄壳 · 技术可行性预研](reviews/围坐元服务薄壳_技术可行性预研_2026-08-28.md)。启用时 vhost 须放行 `https://circle.genz.ltd/<APPID>.txt`，勿被 `/circle/` 吞掉 |

---

## 7. 回滚

签发改回 `--invite-base http://14.29.216.219/circle/`，testers 须知改回 IP。IP 上的 `/circle/` location **不要删**。子域 vhost 可先 `return 503` 或摘 `sites-enabled`，DNS 短 TTL。`www` / `api` / `tspace` 一条都不要动。
