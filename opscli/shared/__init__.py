"""opscli 共享基础设施模块。

提供跨模块复用的基础能力：
- shared.exceptions: 远端交互异常基类
- shared.http: 统一远端 HTTP 响应解析
- shared.integration_accounts: 集成账号拉取与解密
- shared.logging: 结构化日志配置
- shared.update_check: PyPI 版本更新检查（仅 CLI 模式）
"""
