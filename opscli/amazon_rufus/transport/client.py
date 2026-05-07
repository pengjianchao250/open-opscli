"""Amazon Rufus 远端传输预留。"""

from __future__ import annotations


class RufusTransportClient:
    """预留上传客户端；一期不主动调用。"""

    def build_disabled_upload_hint(self) -> dict:
        """返回上传禁用说明。"""
        return {"enabled": False, "reason": "一期只构造 upload_payload，不发送上传接口"}
