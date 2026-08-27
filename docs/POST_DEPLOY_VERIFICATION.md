# 部署后验收（gfcc 栈）

> **地位**：备忘。记录 **gfcc docker 栈**（Tatha / DemoPeter / agentmemory）部署后的验收结论，供运维对账。  
> **不是**：围坐 MVP、拓扑层、信号 ingest（后二者见 [联邦测试闭环方案](联邦测试闭环方案.md) / [P3_终端机施工单](P3_终端机施工单.md)）。  
> **范围**：agentmemory 无模型模式、demopeter `D:/` 路径提示、自建知识库上传流程。  
> **记录日期**：2026-08-25（08-27 核：P3 不改变本节；`:5220` 仍不是 testers 围坐入口）。

## 1. 验收基线

| 检查项 | 结果 |
|--------|------|
| `docker compose ps` | 6/6 `Up`，无 unhealthy |
| 引擎存活 | `GET :3111/agentmemory/livez` → 200 |
| 引擎健康 | `GET :3111/agentmemory/health` → JSON，`kvConnectivity.status=ok` |
| 网关 | `GET :3210/health` → `{"ok":true}`；openapi 标题 `agentmemory ethos gateway`，`/{path}` 全路径代理到引擎 |
| 鉴权 | 网关强制 `Authorization: Bearer <JWT>`；缺失返回 401 `{"detail":"missing token"}` |

## 2. agentmemory 无模型模式

- 引擎镜像 `iiidev/iii:0.11.2`；当前部署未配置 embedding/LLM 模型，以**无模型模式**运行。
- 表现：`observe` 可写入（KV 落库），`search` 不提供语义向量相似度（检索降级）。
- 查看特性开关：`GET /agentmemory/config/flags`。
- 启用语义检索：在 `.env` 配置模型键（如 `DEEPSEEK_API_KEY`）后 `docker compose restart am-engine`。
- 结论：无模型模式**不阻塞验收**——记忆链路（gateway → engine → KV）可用，语义检索属后续增强。

## 3. demopeter `D:/` 路径提示

- 日志中 `D:/...` 为 Windows 侧开发路径（demopeter 演示桩遗留），Linux 容器内不存在 → 仅产生无害 WARNING / 空转，不影响其他服务。
- 结论：可安全忽略；如需消除，从 demopeter 配置移除 Windows 路径或改为容器内挂载路径。

## 4. 上传自建知识库（经网关）

前置：签发 HS256 JWT（密钥 = `.env` 的 `ETHOS_AUTH_SECRET`）。

```bash
cd /data/gfcc
TOKEN=$(python3 -c "import hmac,hashlib,base64,json,time; b64=lambda b: base64.urlsafe_b64encode(b).rstrip(b'='); sec=next(l.split('=',1)[1].strip() for l in open('.env') if l.startswith('ETHOS_AUTH_SECRET=')).encode(); h=b64(json.dumps({'alg':'HS256','typ':'JWT'},separators=(',',':')).encode()); p=b64(json.dumps({'sub':'admin','role':'admin','tier':'admin','permissions':['*'],'exp':int(time.time())+3600},separators=(',',':')).encode()); s=b64(hmac.new(sec,h+b'.'+p,hashlib.sha256).digest()); print((h+b'.'+p+b'.'+s).decode())")
```

1. 确认引擎端点：`docker compose logs am-engine | grep REGISTERED`（上传/导入端点以该列表为准）。
2. 上传文档：`curl -X POST http://localhost:3210/agentmemory/<upload> -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '<payload>'`
3. 检索验证：`curl -X POST http://localhost:3210/agentmemory/search -H "Authorization: Bearer $TOKEN" -d '{"query":"...","session_id":"itest-001"}'`

> 注：`demo-token-*`（tatha 演示桩）**不能**通过网关验签；必须用 `ETHOS_AUTH_SECRET` 现签的 JWT。
