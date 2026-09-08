# Rufus 报告编码修复验证

日期：2026-09-05

## 现象与证据

- 原报告是合法 UTF-8，远端与本地字节一致，中文未被上传过程损坏。
- QA OSS 响应为 `Content-Type: text/markdown`，没有 charset。
- 实测在 multipart 文件部分增加 `charset=utf-8` 后，服务端仍返回不带 charset 的类型；该尝试已撤销。

## 修复

- `AnswerReportWriter` 增加 encoding 参数，默认保持 `utf-8`。
- `AnswerReportPublisher` 使用 `utf-8-sig`，为新发布的报告增加 UTF-8 BOM。
- 批量写盘和通用上传客户端行为保持不变。
- 不修改报告正文，不覆盖旧报告或已有 OSS 对象。

## 验证

- 发布、MCP、共享上传、鉴权及批量流程测试：48 passed。
- QA 新报告：`B0CSN6FR1W-20260905-174206-2391b797695541e289e1aba91ed7fe99.md`。
- 下载 HTTP 200，远端有 UTF-8 BOM，本地和远端字节完全一致。
- 去掉 BOM 并统一换行后，正文与原报告一致。
- 未进行用户查看器的视觉验收；旧链接仍对应旧文件。
- 报告没有回答单题问题的内容问题不在本次编码修复范围。
