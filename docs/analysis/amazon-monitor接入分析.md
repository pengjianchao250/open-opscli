# Amazon Monitor 接入分析

## 1. 当前 `amazon-monitor-1.0.0` 的真实结构

`/Users/mask/Downloads/amazon-monitor-1.0.0` 不是一个完整 Skill 框架，而是一组以脚本为中心的抓取工具：

- `amazon_monitor_core.py`：单商品抓取、历史保存、趋势图、变化检测
- `amazon_competitor_search.py`：搜索结果页抓取、竞品详情抓取、简单分析报告
- `amazon_task_scheduler.py`：本地 JSON 任务配置、串行调度
- `amazon_main.py`：命令分发入口
- `amazon_own_product.py`：单商品抓取演示入口

真正需要复用的核心能力只有两类：

1. Playwright 采集页面数据
2. 采集结果结构化后进入业务系统

## 2. 数据获取逻辑拆解

### 2.1 商品页抓取链路

原脚本 `get_product_data()` 的步骤是：

1. 启动 Playwright Chromium
2. 打开 `https://www.amazon.com/dp/{asin}`
3. 固定 `sleep`
4. 点击地址组件并设置邮编
5. reload 页面
6. 用 CSS selector 提取：
   - `#productTitle`
   - `.a-price .a-offscreen`
   - `#acrPopover .a-icon-alt`
   - `#acrCustomerReviewText`
   - `#glow-ingress-line2`
7. 直接返回字符串字段

### 2.2 搜索页抓取链路

原脚本 `search_competitors()` 的步骤是：

1. 打开 `https://www.amazon.com/s?k={keyword}&s=review-rank`
2. 设置邮编并 reload
3. 读取 `[data-component-type="s-search-result"]`
4. 从每个结果上提取：
   - `data-asin`
   - 标题
   - 价格
   - 评分
   - 评论数
   - Best Seller 标签

### 2.3 原脚本的几个关键问题

1. **抓取与业务耦合过重**：抓取、历史存盘、趋势图、告警、CLI 都写在一起，无法在 `opscli` 内复用。
2. **数据未标准化**：价格、评分、评论数都保留原始文案，后续入库和比对成本高。
3. **每次调用都新开浏览器**：没有会话复用，但在 CLI 场景下还能接受。
4. **等待策略过于固定**：大量 `sleep`，稳定性一般，但迁移后可以先保留“简单可用”，后续再做显式等待优化。
5. **历史落盘位置错误**：直接写当前目录，不符合 `opscli` 统一配置目录规范。
6. **没有 ops 提交链路**：抓回来的数据只停留在本地 JSON / TXT / PNG。

## 3. 接入 `opscli` 的设计原则

结合当前项目规范，Amazon 能力应该按 `query`/`skills` 的方式落地：

- CLI 入口：`opscli amazon`
- 抓取逻辑：`opscli/amazon/scraping/scraper.py`
- 业务编排：`opscli/amazon/services/manager.py`
- ops 提交：`opscli/amazon/transport/client.py`
- 本地历史：`~/.config/opscli/amazon/history/*.jsonl`

认证和远端提交必须复用：

- `AuthClient.build_request_auth("ops")`
- `OPS_URL`
- `config.ini`

## 4. 本次落地方案

本次先完成第一阶段闭环：

1. `amazon scrape`
   - 抓取单个 ASIN
   - 返回原始字段 + 标准化字段
   - 可落本地历史
2. `amazon payload`
   - 在抓取基础上输出未来提交给 ops 的标准 payload
   - 作为后端接口和数据表设计依据
3. `amazon search`
   - 抓取搜索结果页
   - 输出竞品基础信息
4. `amazon history`
   - 读取本地历史快照
5. `amazon schema`
   - 输出当前抓取字段与预留接口结构

暂不迁移：

- 本地定时任务调度
- matplotlib 趋势图
- 文本竞品分析报告

原因：这些都属于“消费数据”的第二层能力，应建立在稳定的抓取和提交通道之上。

## 5. ops API 集成建议

当前仓库里还没有 Amazon 专用后端接口契约，因此本次实现采用“结构先收敛、接口先预留”的方式：

- `config.ini` 已预留：
  - `amazon_submit_endpoint`
- 但当前阶段不要求 CLI 直接提交通道
- 未来提交报文结构统一为：

```json
{
  "source": "opscli.amazon",
  "snapshot": {
    "asin": "B0XXXXXXX",
    "zip_code": "10001",
    "product_name": "...",
    "price_text": "$19.99",
    "price_amount": 19.99,
    "rating_text": "4.6 out of 5 stars",
    "rating_value": 4.6,
    "review_count_text": "1,234 ratings",
    "review_count_value": 1234,
    "valid": true,
    "raw": {}
  }
}
```

建议后端接口至少返回：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "task_id": "..."
  }
}
```

## 6. 下一阶段建议

如果你准备继续往下做，建议按这个顺序推进：

1. 先基于 `opscli amazon payload` 和 `opscli amazon schema` 确认字段契约
2. 再设计后端表：原始快照表、搜索结果表、采集任务表
3. 然后补正式入库 API
4. 最后再加 `amazon monitor` 子命令、告警和回调能力

这样可以避免我们先把本地监控逻辑做重，结果后端入库模型又返工一轮。
