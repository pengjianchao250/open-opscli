"""新品计算器异常定义。"""

from __future__ import annotations


class CalculatorError(Exception):
    """新品计算器模块基础异常。"""


class CalculatorValidationError(CalculatorError):
    """草稿校验失败异常。"""
