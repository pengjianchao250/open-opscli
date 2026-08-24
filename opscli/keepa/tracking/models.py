"""Keepa Tracking 创建对象及子对象模型。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from opscli.keepa.domain.exceptions import KeepaConfigError

# Keepa 官方文档列出的 Amazon locale domain ID。
VALID_TRACKING_DOMAIN_IDS = frozenset({1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12})

# Tracking API 当前要求 NotificationType 布尔数组固定包含 7 个位置。
TRACKING_NOTIFICATION_TYPE_LENGTH = 7

# Keepa API 通知通道位于 NotificationType 索引 5。
API_NOTIFICATION_TYPES = (False, False, False, False, False, True, False)

# ASIN 是由 10 位 ASCII 字母或数字组成的商品标识。
_ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")


@dataclass(frozen=True)
class TrackingThresholdValue:
    """Tracking 的价格或数值阈值规则。"""

    threshold_value: int
    domain: int
    csv_type: int
    is_drop: bool

    def to_api_dict(self) -> dict[str, Any]:
        """校验并转换为 Keepa TrackingThresholdValue。

        Returns:
            使用 Keepa 官方 camelCase 字段名的字典。

        Raises:
            KeepaConfigError: 字段类型、站点或价格类型不合法。
        """
        _validate_integer(self.threshold_value, field_name="thresholdValue")
        _validate_domain(self.domain, field_name="thresholdValues.domain")
        _validate_non_negative_integer(self.csv_type, field_name="thresholdValues.csvType")
        _validate_boolean(self.is_drop, field_name="thresholdValues.isDrop")
        return {
            "thresholdValue": self.threshold_value,
            "domain": self.domain,
            "csvType": self.csv_type,
            "isDrop": self.is_drop,
        }

    @classmethod
    def from_api_dict(cls, value: Mapping[str, Any]) -> TrackingThresholdValue:
        """从 Keepa 字段名构造阈值规则。

        Args:
            value: 包含 thresholdValue、domain、csvType 和 isDrop 的映射。

        Returns:
            尚未执行字段校验的阈值规则模型。
        """
        return cls(
            threshold_value=value.get("thresholdValue"),
            domain=value.get("domain"),
            csv_type=value.get("csvType"),
            is_drop=value.get("isDrop"),
        )


@dataclass(frozen=True)
class TrackingNotifyIf:
    """Tracking 的缺货或到货通知规则。"""

    domain: int
    csv_type: int
    notify_if_type: int

    def to_api_dict(self) -> dict[str, Any]:
        """校验并转换为 Keepa TrackingNotifyIf。

        Returns:
            使用 Keepa 官方 camelCase 字段名的字典。

        Raises:
            KeepaConfigError: 字段类型、站点、价格类型或触发类型不合法。
        """
        _validate_domain(self.domain, field_name="notifyIf.domain")
        _validate_non_negative_integer(self.csv_type, field_name="notifyIf.csvType")
        _validate_integer(self.notify_if_type, field_name="notifyIf.notifyIfType")
        if self.notify_if_type not in {0, 1}:
            raise KeepaConfigError("notifyIf.notifyIfType 仅支持 0（缺货）或 1（到货）")
        return {
            "domain": self.domain,
            "csvType": self.csv_type,
            "notifyIfType": self.notify_if_type,
        }

    @classmethod
    def from_api_dict(cls, value: Mapping[str, Any]) -> TrackingNotifyIf:
        """从 Keepa 字段名构造库存通知规则。

        Args:
            value: 包含 domain、csvType 和 notifyIfType 的映射。

        Returns:
            尚未执行字段校验的库存通知规则模型。
        """
        return cls(
            domain=value.get("domain"),
            csv_type=value.get("csvType"),
            notify_if_type=value.get("notifyIfType"),
        )


@dataclass(frozen=True)
class TrackingCreation:
    """用于 Add Tracking 的完整 Tracking Creation Object。"""

    asin: str
    main_domain_id: int
    ttl: int = 0
    expire_notify: bool = False
    desired_prices_in_main_currency: bool = True
    update_interval: int = 1
    metadata: str | None = None
    threshold_values: Sequence[TrackingThresholdValue] = field(default_factory=tuple)
    notify_if: Sequence[TrackingNotifyIf] = field(default_factory=tuple)
    notification_type: Sequence[bool] = API_NOTIFICATION_TYPES
    individual_notification_interval: int = -1

    def to_api_dict(self) -> dict[str, Any]:
        """校验并转换为 Keepa Tracking Creation Object。

        Returns:
            可直接作为 Tracking Add POST JSON 元素的字典。

        Raises:
            KeepaConfigError: 任一创建字段不符合 Keepa 官方边界。
        """
        asin = normalize_tracking_asin(self.asin)
        _validate_integer(self.ttl, field_name="ttl")
        _validate_boolean(self.expire_notify, field_name="expireNotify")
        _validate_boolean(
            self.desired_prices_in_main_currency,
            field_name="desiredPricesInMainCurrency",
        )
        _validate_domain(self.main_domain_id, field_name="mainDomainId")
        _validate_integer(self.update_interval, field_name="updateInterval")
        if not 1 <= self.update_interval <= 24:
            raise KeepaConfigError("updateInterval 必须是 1 到 24 之间的整数小时")
        if self.metadata is not None:
            if not isinstance(self.metadata, str):
                raise KeepaConfigError("metaData 必须是字符串")
            if len(self.metadata) > 500:
                raise KeepaConfigError("metaData 最长 500 个字符")
        if not isinstance(self.notification_type, Sequence) or isinstance(
            self.notification_type, (str, bytes)
        ):
            raise KeepaConfigError("notificationType 必须是包含 7 个布尔值的数组")
        notification_type = tuple(self.notification_type)
        if len(notification_type) != TRACKING_NOTIFICATION_TYPE_LENGTH:
            raise KeepaConfigError("notificationType 必须包含 7 个布尔值")
        if any(type(item) is not bool for item in notification_type):
            raise KeepaConfigError("notificationType 必须仅包含布尔值")
        _validate_integer(
            self.individual_notification_interval,
            field_name="individualNotificationInterval",
        )
        if self.individual_notification_interval < -1:
            raise KeepaConfigError("individualNotificationInterval 不能小于 -1")

        payload: dict[str, Any] = {
            "asin": asin,
            "ttl": self.ttl,
            "expireNotify": self.expire_notify,
            "desiredPricesInMainCurrency": self.desired_prices_in_main_currency,
            "mainDomainId": self.main_domain_id,
            "updateInterval": self.update_interval,
            "thresholdValues": [item.to_api_dict() for item in self.threshold_values],
            "notifyIf": [item.to_api_dict() for item in self.notify_if],
            "notificationType": list(notification_type),
            "individualNotificationInterval": self.individual_notification_interval,
        }
        if self.metadata is not None:
            payload["metaData"] = self.metadata
        return payload

    @classmethod
    def from_api_dict(cls, value: Mapping[str, Any]) -> TrackingCreation:
        """从 Keepa 官方字段名构造创建对象。

        Args:
            value: 一个 Tracking Creation Object 映射。

        Returns:
            可继续校验和序列化的创建对象模型。

        Raises:
            KeepaConfigError: 子对象不是 JSON 对象或字段容器类型错误。
        """
        threshold_values = _mapping_sequence(value.get("thresholdValues", ()), "thresholdValues")
        notify_if = _mapping_sequence(value.get("notifyIf", ()), "notifyIf")
        return cls(
            asin=value.get("asin"),
            ttl=value.get("ttl", 0),
            expire_notify=value.get("expireNotify", False),
            desired_prices_in_main_currency=value.get("desiredPricesInMainCurrency", True),
            main_domain_id=value.get("mainDomainId"),
            update_interval=value.get("updateInterval", 1),
            metadata=value.get("metaData"),
            threshold_values=tuple(
                TrackingThresholdValue.from_api_dict(item) for item in threshold_values
            ),
            notify_if=tuple(TrackingNotifyIf.from_api_dict(item) for item in notify_if),
            notification_type=value.get("notificationType", API_NOTIFICATION_TYPES),
            individual_notification_interval=value.get("individualNotificationInterval", -1),
        )


def normalize_tracking_asin(value: Any) -> str:
    """规范化并校验单个 Tracking ASIN。

    Args:
        value: 待校验的 ASIN。

    Returns:
        转为大写的 10 位 ASIN。

    Raises:
        KeepaConfigError: ASIN 类型或格式不合法。
    """
    if not isinstance(value, str):
        raise KeepaConfigError("ASIN 必须是字符串")
    asin = value.strip().upper()
    if not _ASIN_PATTERN.fullmatch(asin):
        raise KeepaConfigError("ASIN 必须由 10 位字母或数字组成")
    return asin


def _mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise KeepaConfigError(f"{field_name} 必须是 JSON 数组")
    if any(not isinstance(item, Mapping) for item in value):
        raise KeepaConfigError(f"{field_name} 的每一项都必须是 JSON 对象")
    return tuple(value)


def _validate_domain(value: Any, *, field_name: str) -> None:
    _validate_integer(value, field_name=field_name)
    if value not in VALID_TRACKING_DOMAIN_IDS:
        supported = ", ".join(str(item) for item in sorted(VALID_TRACKING_DOMAIN_IDS))
        raise KeepaConfigError(f"{field_name} 不是 Keepa 支持的站点 ID，可选值：{supported}")


def _validate_integer(value: Any, *, field_name: str) -> None:
    if type(value) is not int:
        raise KeepaConfigError(f"{field_name} 必须是整数")


def _validate_non_negative_integer(value: Any, *, field_name: str) -> None:
    _validate_integer(value, field_name=field_name)
    if value < 0:
        raise KeepaConfigError(f"{field_name} 不能小于 0")


def _validate_boolean(value: Any, *, field_name: str) -> None:
    if type(value) is not bool:
        raise KeepaConfigError(f"{field_name} 必须是布尔值")
