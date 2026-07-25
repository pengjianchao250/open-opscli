"""规划器内核包。

把 ops-dataset-query Skill 的取数规划器迁入 opscli 内核：数据源从 Skill 的
data/*.csv 改为后端 query-metadata（经用户级元数据缓存），对外暴露统一入口
run_plan / run_flow（见 entry.py，后续任务补齐）。

依赖方向约束（铁律2）：本包只依赖 opscli.query.* + opscli.config +
opscli.shared + 标准库，禁止 import opscli.mcp。
"""

from opscli.query.services.planner.entry import run_flow, run_plan

__all__ = ["run_plan", "run_flow"]
