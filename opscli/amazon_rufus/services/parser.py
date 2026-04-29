"""Rufus SSE 解析服务。"""

from __future__ import annotations

import json
import re
from typing import Any

from opscli.amazon_rufus.domain.models import AnswerData


class RufusParserService:
    """解析 Rufus SSE 文本为结构化回答。"""

    def parse(self, raw_text: str) -> AnswerData:
        """解析 SSE 文本。"""
        text_parts: list[str] = []
        html_parts: list[str] = []
        blocks: list[dict] = []
        json_patch_text_snapshots_by_group_id: dict[str, dict[str, Any]] = {}
        card_recommendations: dict[str, dict] = {}
        footer_descriptions: dict[str, str] = {}
        thread_id: str | None = None
        for index, event in enumerate(self._iter_sse_data(raw_text)):
            if thread_id is None:
                thread_id = self._extract_thread_id(event)
            self._collect_json_patch_text_snapshots(event, index, json_patch_text_snapshots_by_group_id)
            self._extract_card_sections(event, text_parts, blocks, card_recommendations, footer_descriptions)
            extracted = self._extract_text(event)
            if extracted:
                text_parts.append(extracted)
            if isinstance(event.get("blocks"), list):
                blocks.extend(event["blocks"])
            html = self._extract_html(event)
            if html:
                html_parts.append(html)
        json_patch_text_snapshots = list(json_patch_text_snapshots_by_group_id.values())
        patch_text = self._extract_patch_text(json_patch_text_snapshots).strip()
        product_links = self._extract_product_links(json_patch_text_snapshots)
        recommended_asins = self._merge_recommended_asins(
            self._extract_recommended_asins(product_links),
            card_recommendations,
            footer_descriptions,
        )
        if not blocks:
            blocks = [
                snapshot["tree"]
                for snapshot in json_patch_text_snapshots
                if isinstance(snapshot.get("tree"), dict)
            ]
        text = patch_text or "".join(text_parts).strip()
        html_text = "".join(html_parts)
        if not text and html_text:
            text = self._html_to_text(html_text)
        return AnswerData(
            text=text,
            html=html_text,
            summary_text=patch_text,
            product_links=product_links,
            recommended_asins=recommended_asins,
            blocks=blocks,
            is_success=bool(text or html_text),
            thread_id=thread_id,
        )

    def _iter_sse_data(self, raw_text: str) -> list[dict[str, Any]]:
        """提取 SSE data 行。"""
        events: list[dict[str, Any]] = []
        for line in raw_text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
        return events

    def _extract_text(self, event: dict[str, Any]) -> str:
        """从常见 Rufus 字段中提取文本。"""
        for key in ("answer", "text", "content", "message"):
            value = event.get(key)
            if isinstance(value, str):
                return value
        inference = event.get("inference")
        if isinstance(inference, dict):
            return self._extract_text(inference)
        return ""

    def _extract_html(self, event: dict[str, Any]) -> str:
        """从 Rufus message.sections 中提取 HTML 片段。"""
        sections = event.get("sections")
        if not isinstance(sections, list):
            return ""
        html_parts: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            content = section.get("content")
            if not isinstance(content, dict):
                continue
            data = content.get("data")
            if isinstance(data, str) and data:
                html_parts.append(data)
        return "".join(html_parts)

    def _html_to_text(self, html: str) -> str:
        """将简单 HTML 回答转换为纯文本。"""
        without_scripts = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
        without_styles = re.sub(r"<style\b[^>]*>.*?</style>", "", without_scripts, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", without_styles)
        return " ".join(text.split())

    def _extract_card_sections(
        self,
        event: dict[str, Any],
        text_parts: list[str],
        blocks: list[dict],
        recommendations: dict[str, dict],
        footer_descriptions: dict[str, str],
    ) -> None:
        """解析插件端支持的 Rufus HTML 卡片 section。"""
        sections = event.get("sections")
        if not isinstance(sections, list):
            return
        faceout_group_asins: dict[str, str] = {}
        for section in sections:
            if not isinstance(section, dict):
                continue
            target = section.get("target") if isinstance(section.get("target"), dict) else {}
            section_type = target.get("type") if isinstance(target, dict) else None
            group_id = target.get("groupId") if isinstance(target, dict) else None
            html = self._section_html(section)
            if not html:
                continue
            if section_type == "ReviewAspectFlow":
                summary = self._extract_review_summary(html)
                if summary:
                    text_parts.append(summary)
                    blocks.append({"type": "paragraph", "text": summary})
                continue
            if section_type == "AsinFaceoutList":
                items = self._extract_asin_faceout_items(html)
                for item in items:
                    recommendations[item["asin"]] = item
                if isinstance(group_id, str) and len(items) == 1:
                    faceout_group_asins[group_id] = items[0]["asin"]
                continue
            if section_type == "AsinFaceoutFooter":
                description = self._extract_faceout_footer_description(html)
                asin = self._extract_asin_from_link(html)
                if not asin and isinstance(group_id, str):
                    base_group_id = group_id.removesuffix("_asinFooter")
                    asin = faceout_group_asins.get(base_group_id, "")
                if description and asin:
                    footer_descriptions[asin] = description

    def _section_html(self, section: dict[str, Any]) -> str:
        """读取 section.content.data HTML。"""
        content = section.get("content")
        if not isinstance(content, dict):
            return ""
        data = content.get("data")
        return data if isinstance(data, str) else ""

    def _extract_review_summary(self, html: str) -> str:
        """提取 ReviewAspectFlow 的 overall summary。"""
        summary = self._extract_tag_text_by_testid(html, "overall-summary")
        if summary:
            return summary
        aspect_summaries = self._extract_all_tag_text_by_testid(html, "aspect-summary")
        if aspect_summaries:
            return max(aspect_summaries, key=len)
        return self._html_to_text(html)

    def _extract_tag_text_by_testid(self, html: str, testid: str) -> str:
        """按 data-testid 提取首个标签文本。"""
        values = self._extract_all_tag_text_by_testid(html, testid)
        return values[0] if values else ""

    def _extract_all_tag_text_by_testid(self, html: str, testid: str) -> list[str]:
        """按 data-testid 提取所有标签文本。"""
        pattern = rf"<[^>]*data-testid=[\"']{re.escape(testid)}[\"'][^>]*>(.*?)</[^>]+>"
        values: list[str] = []
        for match in re.finditer(pattern, html, flags=re.IGNORECASE | re.DOTALL):
            text = self._html_to_text(match.group(1))
            if text:
                values.append(text)
        return values

    def _extract_asin_faceout_items(self, html: str) -> list[dict]:
        """提取 AsinFaceoutList 推荐卡片。"""
        items: list[dict] = []
        anchor_pattern = r"<a\b(?P<attrs>[^>]*href=[\"'][^\"']+[\"'][^>]*)>(?P<body>.*?)</a>"
        for match in re.finditer(anchor_pattern, html, flags=re.IGNORECASE | re.DOTALL):
            attrs = match.group("attrs")
            body = match.group("body")
            href_match = re.search(r"href=[\"']([^\"']+)[\"']", attrs, flags=re.IGNORECASE)
            if not href_match:
                continue
            raw_href = href_match.group(1)
            asin = self._extract_asin_from_link(raw_href)
            if not asin:
                continue
            items.append(
                {
                    "asin": asin,
                    "title": self._extract_faceout_title(body),
                    "href": self._normalize_amazon_href(raw_href),
                    "source": "AsinFaceoutList",
                    "description": "",
                }
            )
        return items

    def _extract_faceout_title(self, html: str) -> str:
        """提取推荐卡片标题。"""
        for pattern in (r"<h2\b[^>]*aria-label=[\"']([^\"']+)[\"']", r"<img\b[^>]*alt=[\"']([^\"']+)[\"']"):
            match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
            if match:
                return " ".join(match.group(1).split())
        return self._html_to_text(html)

    def _extract_faceout_footer_description(self, html: str) -> str:
        """提取 AsinFaceoutFooter 描述并移除 More details 尾巴。"""
        text = self._html_to_text(html)
        index = text.lower().find("more details")
        if index >= 0:
            text = text[:index]
        return text.strip()

    def _normalize_amazon_href(self, href: str) -> str:
        """补齐 Amazon 相对链接。"""
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if href.startswith("/"):
            return f"https://www.amazon.com{href}"
        return href

    def _collect_json_patch_text_snapshots(
        self,
        event: dict[str, Any],
        index: int,
        by_group_id: dict[str, dict[str, Any]],
    ) -> None:
        """对齐插件端 collectJsonPatchTextSnapshots 聚合正文 patch。"""
        if event.get("type") != "JSONPatches":
            return
        patches = event.get("patches")
        if not isinstance(patches, list):
            return
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            group_id = patch.get("groupId")
            op = patch.get("op")
            path = patch.get("path")
            if not isinstance(group_id, str) or not self._is_text_patch_group(group_id):
                continue
            if op not in {"add", "replace", "remove"} or not isinstance(path, str):
                continue
            snapshot = by_group_id.setdefault(group_id, {"groupId": group_id, "tree": None, "index": index})
            snapshot["index"] = index
            if op == "remove":
                root = snapshot.get("tree")
                if root is not None:
                    self._remove_json_pointer(root, path)
                continue
            value = patch.get("value")
            if path == "/":
                snapshot["tree"] = value
                continue
            root = snapshot.get("tree")
            if root is not None:
                self._set_json_pointer(root, path, value)

    def _is_text_patch_group(self, group_id: str) -> bool:
        """识别插件端纳入正文解析的 JSONPatch group。"""
        return group_id.startswith("markdown_processor_") or group_id.startswith("text_template_")

    def _set_json_pointer(self, root: Any, path: str, value: Any) -> None:
        """按 JSON Pointer 路径写入节点。"""
        parts = [self._unescape_pointer(part) for part in path.strip("/").split("/") if part]
        if not parts:
            return
        current = root
        for part in parts[:-1]:
            current = self._get_child(current, part)
            if current is None:
                return
        self._set_child(current, parts[-1], value)

    def _remove_json_pointer(self, root: Any, path: str) -> None:
        """按 JSON Pointer 路径删除节点。"""
        parts = [self._unescape_pointer(part) for part in path.strip("/").split("/") if part]
        if not parts:
            return
        current = root
        for part in parts[:-1]:
            current = self._get_child(current, part)
            if current is None:
                return
        self._remove_child(current, parts[-1])

    def _get_child(self, current: Any, part: str) -> Any:
        """读取 JSON Pointer 的中间节点。"""
        if isinstance(current, dict):
            return current.get(part)
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                return current[index]
        return None

    def _set_child(self, current: Any, part: str, value: Any) -> None:
        """写入 JSON Pointer 的末端节点。"""
        if isinstance(current, dict):
            current[part] = value
            return
        if not isinstance(current, list) or not part.isdigit():
            return
        index = int(part)
        if index == len(current):
            current.append(value)
        elif 0 <= index < len(current):
            current[index] = value

    def _remove_child(self, current: Any, part: str) -> None:
        """删除 JSON Pointer 的末端节点。"""
        if isinstance(current, dict):
            current.pop(part, None)
            return
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current.pop(index)

    def _unescape_pointer(self, part: str) -> str:
        """还原 JSON Pointer 转义字符。"""
        return part.replace("~1", "/").replace("~0", "~")

    def _extract_patch_text(self, json_patch_text_snapshots: list[dict[str, Any]]) -> str:
        """从重建后的 Rufus UI 树提取可读正文。"""
        parts: list[str] = []
        for snapshot in sorted(json_patch_text_snapshots, key=lambda item: int(item.get("index") or 0)):
            group_id = snapshot.get("groupId")
            if not isinstance(group_id, str):
                continue
            if not self._is_text_patch_group(group_id):
                continue
            text = self._extract_node_text(snapshot.get("tree"))
            if text:
                parts.append(text)
        return "\n".join(parts)

    def _extract_node_text(self, node: Any) -> str:
        """递归提取 Rufus UI 节点文本。"""
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            return "".join(self._extract_node_text(item) for item in node)
        if not isinstance(node, dict):
            return ""
        copy_template = node.get("copyTemplate")
        prefix = ""
        suffix = ""
        if isinstance(copy_template, dict):
            raw_prefix = copy_template.get("prefix")
            raw_suffix = copy_template.get("suffix")
            prefix = raw_prefix if isinstance(raw_prefix, str) else ""
            suffix = raw_suffix if isinstance(raw_suffix, str) else ""
        children = node.get("children")
        if isinstance(children, str):
            return f"{prefix}{children}{suffix}"
        if isinstance(children, list):
            child_texts = [self._extract_node_text(child) for child in children]
            separator = "\n" if self._is_block_node(node) else ""
            return f"{prefix}{separator.join(text for text in child_texts if text)}{suffix}"
        return ""

    def _is_block_node(self, node: dict[str, Any]) -> bool:
        """识别需要换行拼接的块级节点。"""
        node_type = node.get("type")
        children = node.get("children")
        return node_type == "container" and isinstance(children, list) and len(children) > 1

    def _extract_product_links(self, json_patch_text_snapshots: list[dict[str, Any]]) -> list[str]:
        """从 Rufus UI 树提取商品链接。"""
        links: list[str] = []
        seen: set[str] = set()
        for snapshot in json_patch_text_snapshots:
            for url in self._iter_node_urls(snapshot.get("tree")):
                if url not in seen:
                    seen.add(url)
                    links.append(url)
        return links

    def _iter_node_urls(self, node: Any) -> list[str]:
        """递归收集节点中的 URL。"""
        urls: list[str] = []
        if isinstance(node, list):
            for item in node:
                urls.extend(self._iter_node_urls(item))
            return urls
        if not isinstance(node, dict):
            return urls
        on_press = node.get("onPress")
        if isinstance(on_press, dict) and isinstance(on_press.get("url"), str):
            urls.append(on_press["url"])
        children = node.get("children")
        if isinstance(children, (list, dict)):
            urls.extend(self._iter_node_urls(children))
        return urls

    def _extract_recommended_asins(self, product_links: list[str]) -> list[str]:
        """从商品链接中提取推荐 ASIN。"""
        asins: list[str] = []
        seen: set[str] = set()
        for link in product_links:
            match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", link, flags=re.IGNORECASE)
            if not match:
                continue
            asin = match.group(1).upper()
            if asin in seen:
                continue
            seen.add(asin)
            asins.append(asin)
        return asins

    def _extract_asin_from_link(self, value: str) -> str:
        """从 Amazon 链接或文本中提取 ASIN。"""
        match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", value, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
        fallback = re.search(r"\b(B[A-Z0-9]{9})\b", value, flags=re.IGNORECASE)
        return fallback.group(1).upper() if fallback else ""

    def _merge_recommended_asins(
        self,
        link_asins: list[str],
        card_recommendations: dict[str, dict],
        footer_descriptions: dict[str, str],
    ) -> list:
        """合并链接 ASIN 与推荐卡片结构。"""
        if card_recommendations:
            merged: list[dict] = []
            for asin, item in card_recommendations.items():
                copied = dict(item)
                if footer_descriptions.get(asin):
                    copied["description"] = footer_descriptions[asin]
                merged.append(copied)
            return merged
        return link_asins

    def _extract_thread_id(self, event: dict[str, Any]) -> str | None:
        """提取会话线程 ID。"""
        value = event.get("threadId") or event.get("thread_id")
        if isinstance(value, str):
            return value
        metadata = event.get("conversation_metadata") or event.get("conversationMetadata")
        if isinstance(metadata, dict):
            value = metadata.get("threadId") or metadata.get("thread_id")
            if isinstance(value, str):
                return value
        return None
