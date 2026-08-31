"""pytest 全局夹具：单测强制 stub 装配。

本地仓库存在 services/gfcc_kernel/.env（sqlite/ollama），若不加隔离，
app 单例在 import 时会读真实配置并把数据写进 data/memory.db，破坏测试
确定性。conftest.py 在收集阶段先于任何测试模块执行，保证：

- STORE_PROVIDER=stub：单测不触碰真实 SQLite 库
- CIRCLE_FLOW_PROVIDER=stub：G6 会务态落库默认跟随 STORE_PROVIDER，这里显式钉死
  （单测纯内存；落库用例自建临时库 CIRCLE_FLOW_DB → tmp_path）
- LLM_PROVIDER=stub：单测不依赖本地 Ollama（与 CI 无 .env 环境对齐）
- SIGNAL_INGEST_SECRET 留空：signal-ingest 默认走 dev 免签分支
  （验签分支由用例内 monkeypatch 单独覆盖）
- ETHOS_AUTH_SECRET 显式置空：即使 .env 配了密钥，单测也强制走 stub 验签
  （HS256 分支由用例内 monkeypatch 单独覆盖）
- GFCC_MODE 钉死 gfcc.default：单测默认不装配 L3 厂商适配器
  （profile.demo 装配由 tests/test_profile_demo.py 显式构造 + monkeypatch 覆盖）
"""

import os

os.environ["STORE_PROVIDER"] = "stub"
os.environ["CIRCLE_FLOW_PROVIDER"] = "stub"
os.environ["LLM_PROVIDER"] = "stub"
os.environ.pop("SIGNAL_INGEST_SECRET", None)
os.environ["ETHOS_AUTH_SECRET"] = ""
os.environ["GFCC_MODE"] = "gfcc.default"
