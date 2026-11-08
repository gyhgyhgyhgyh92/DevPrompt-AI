"""运行时层：会话生命周期、事件日志、执行器、审批与委派调度。

依赖方向：本层可 import `service` / `state` / `memory`，但 `service` 不得 import 本层
（避免环）。`domain/` 只经 Protocol 触达基础设施（MUST-06）。
"""
