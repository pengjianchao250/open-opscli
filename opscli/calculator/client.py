"""Polaris 新品计算器 HTTP Client。"""

from __future__ import annotations

from typing import Any

import httpx

from opscli.auth import AuthClient
from opscli.auth.config import get_builtin_systems


class CalculatorClient:
    """封装 Polaris 新品计算器后端接口。"""

    def __init__(self, base_url: str | None = None, auth_client: Any | None = None, timeout: float = 10.0) -> None:
        """初始化 Client。

        Args:
            base_url: Polaris 服务地址，测试可传入假地址；默认读取内置系统配置。
            auth_client: 认证客户端，测试可传入 fake 对象。
            timeout: HTTP 超时时间，单位秒。
        """
        if base_url is None:
            base_url = self._get_polaris_base_url()
        self.base_url = base_url.rstrip("/")
        self.auth_client = auth_client or AuthClient()
        self.timeout = timeout

    @staticmethod
    def _get_polaris_base_url() -> str:
        """从内置系统配置中读取 Polaris 服务地址。"""
        for system in get_builtin_systems():
            if system.get("alias") == "polaris":
                return str(system["url"])
        raise RuntimeError("未启用 Polaris 系统配置，请设置 OPSCLI_POLARIS_ENABLED=true。")

    def dropdown_list(self) -> dict[str, Any]:
        """获取新品计算器公共下拉数据。"""
        return self._request("GET", "/calculator/newProduct/dropdownList")

    def zones_warehouse_list(self, country: str) -> dict[str, Any]:
        """获取指定站点的分区和仓库下拉数据。"""
        return self._request("GET", "/calculator/newProduct/zonesWarehouseList", params={"country": country})

    def query_cost(self, payload: dict[str, Any]) -> dict[str, Any]:
        """根据第一阶段参数查询默认试算成本参数。"""
        return self._request("POST", "/calculator/newProduct/queryCost", json=payload)

    def do_calc(self, payload: dict[str, Any]) -> dict[str, Any]:
        """提交完整新品试算任务。"""
        return self._request("POST", "/calculator/newProduct/doCalc", json=payload)

    def forecast_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        """查询新品试算任务列表。"""
        return self._request("POST", "/calculator/newProduct/forecastList", json=payload)

    def task_details(self, payload: dict[str, Any]) -> dict[str, Any]:
        """查询新品试算任务详情。"""
        return self._request("POST", "/calculator/newProduct/taskDetails", json=payload, timeout=30.0)

    def copy_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """复制已有新品试算任务，生成新草稿数据。"""
        return self._request("POST", "/calculator/newProduct/copyTask", json=payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """执行带 Polaris 认证的 HTTP 请求。"""
        headers, cookies = self.auth_client.build_request_auth("polaris")
        request_timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = httpx.request(
                method,
                self.base_url + path,
                headers=headers,
                cookies=cookies,
                timeout=request_timeout,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Polaris 接口请求失败：{exc}") from exc
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Polaris 接口返回不是 JSON 对象。")
        return data
