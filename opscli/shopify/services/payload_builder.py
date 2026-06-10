"""Build and preview Polaris createCustomTask payloads."""

from __future__ import annotations

import time

from opscli.shopify.domain.exceptions import ShopifyParamsError
from opscli.shopify.services.template_registry import get_operation_config


class ShopifyTaskPayloadBuilder:
    """Single payload builder shared by CLI, MCP, and manager flows."""

    def build(
        self,
        *,
        operation: str,
        site_id: int,
        data_content: dict,
        variant_ids: list[int],
        product_id: int | str | None,
    ) -> dict:
        if not site_id:
            raise ShopifyParamsError("site_id 不能为空")
        if not variant_ids:
            raise ShopifyParamsError("shopify_product_variant_id 不能为空")

        op_config = get_operation_config(operation)
        now_ms = int(time.time() * 1000)

        return {
            "task_content": {
                "template_content": {
                    "fields": [
                        {
                            "__config__": {
                                "image": op_config.image,
                                "label": op_config.label,
                                "formId": 1,
                                "layout": "newPage",
                                "viewType": 2,
                                "renderKey": str(now_ms),
                                "showLabel": False,
                                "permission": [1],
                                "isExclusive": True,
                                "defaultValue": "",
                                "operateMethod": op_config.operate_method,
                                "filterComponents": [],
                            }
                        }
                    ],
                    "formRef": op_config.form_ref,
                    "labelWidth": 100,
                    "globalSetting": [],
                    "labelPosition": "left",
                    "conditionGroups": [],
                },
                "data_content": data_content,
                "original_data_content": None,
                "shopify_product_variant_id": variant_ids,
                "shopify_product_id": product_id,
            },
            "approve_state": 2,
            "task_id": "",
            "feed_task_template_id": op_config.template_id,
            "confirm_button": [],
            "_t": int(time.time()),
        }

    def preview(self, *, operation: str, site_id: int, payload: dict) -> dict:
        op_config = get_operation_config(operation)
        task_content = payload.get("task_content") or {}
        variant_ids = task_content.get("shopify_product_variant_id") or []

        return {
            "dry_run": True,
            "will_submit": False,
            "submit_target": "polaris_create_custom_task",
            "direct_shopify_api": False,
            "operation": operation,
            "operate_method": op_config.operate_method,
            "template_id": op_config.template_id,
            "site_id": site_id,
            "variant_count": len(variant_ids),
            "variant_ids": variant_ids,
            "product_id": task_content.get("shopify_product_id"),
            "payload": payload,
        }
