"""gfcc_kernel —— 格契内核。

契约层（gfcc）的实现层：POST /v1/ask 单入口 + 五槽（llm/tools/session/policy/store）
+ 五个一等端口（circle/identity/memory/consensus/contribution）。

设计原则（对齐 contracts/ask.envelope.v1.json 与 registry.v1.json）：
- 信封不可变；内部实现可替换。
- 默认组合 = 内核 + 五端口 stub；stub 合法，空数据合法。
- dispatch 只经 registry 绑定，不 import 任何命名厂商服务。
- 加能力 = 注册适配器 + 模式清单，不增长 JobFirst intent 表。
"""

__version__ = "1.1.0"
