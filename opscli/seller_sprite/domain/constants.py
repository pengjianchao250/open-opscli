"""卖家精灵账号与会话状态共用的领域常量。"""


# 明确认证失败会同时触发账号隔离和 Profile 隔离，统一取值避免跨模块字符串漂移。
ACCOUNT_FAILURE_REASON_AUTHENTICATION = "authentication_failed"
