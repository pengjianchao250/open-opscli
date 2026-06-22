# Data Contract

## Input Record

```json
{
  "asin": "B0XXXXXXX",
  "site": "US",
  "keyword": "solar outdoor lights",
  "keywords": ["solar outdoor lights", "outdoor solar lamp"],
  "row_index": 2,
  "source_file": "asins.csv",
  "source_row": {
    "asin": "B0XXXXXXX",
    "keyword": "solar outdoor lights"
  }
}
```

## Output Record

```json
{
  "asin": "B0XXXXXXX",
  "site": "US",
  "input": {
    "keyword": "solar outdoor lights",
    "keywords": ["solar outdoor lights", "outdoor solar lamp"],
    "keyword_count": 2,
    "keyword_source": "input"
  },
  "seller_sprite": {
    "keyword_reverse": {
      "status": "success",
      "job_id": "SellerSprite-ReverseASIN-US-B0XXXXXXX-...",
      "row_count": 100,
      "export_path": "..."
    },
    "keyword_miner": {
      "status": "success",
      "seed_keywords": ["solar outdoor lights"],
      "jobs": []
    },
    "listing_analysis": {
      "status": "success",
      "job_id": "SellerSprite-ListingAnalysis-US-B0XXXXXXX-...",
      "task_id": "f8c83463849334d52121f025af335d75",
      "task_status": "COMPLETED",
      "completed_time": "2026-06-08 12:08:13",
      "export_path": "...",
      "content": {
        "moduleName": "LA",
        "reportDetails": {}
      }
    }
  },
  "amazon": {
    "scrape": {
      "status": "success",
      "product_name": "...",
      "price_amount": 29.99,
      "rating_value": 4.4,
      "review_count_value": 1234
    }
  },
  "rufus": {
    "status": "success",
    "country": "US",
    "questions": [
      "这个产品ASIN B0XXXXXXX，标题写得清楚吗？如果我要找这个产品ASIN B0XXXXXXX，一般搜什么词能找到他？",
      "这个产品ASIN B0XXXXXXX五点卖点描述里，最重要的一条是什么？有没有买家很想知道但没写进去的事？",
      "看完这个产品ASIN B0XXXXXXX这些图，还有什么是我想知道但看不出来的？要是再加一张图，加什么最有用？",
      "这个产品ASIN B0XXXXXXX下面那个长的图文介绍，跟上面五点说的有区别吗？看完能让我更放心买吗？还少介绍了什么？",
      "这个产品ASIN B0XXXXXXX评价里大家最常夸和最常抱怨的是什么？这些在介绍里提前说清楚了吗？",
      "这个产品ASIN B0XXXXXXX如果让你给这个产品页面只提一个最着急改的地方，会是什么？"
    ],
    "question_count": 6,
    "answer_count": 2,
    "report_path": "output/amazon-rufus/B0XXXXXXX-20260608-180214.md",
    "answers": [
      {
        "index": 1,
        "question": "这个产品ASIN B0XXXXXXX，标题写得清楚吗？如果我要找这个产品ASIN B0XXXXXXX，一般搜什么词能找到他？",
        "related_products": ["https://www.amazon.com/dp/B0XXXXXXX"],
        "answer": "...",
        "recommended_asins": ["B0XXXXXXX"],
        "summary": "..."
      }
    ]
  },
  "query": {
    "sales": {
      "status": "success",
      "rows": []
    },
    "crawler_listing": {
      "status": "success",
      "rows": []
    }
  },
  "frontend_data": {
    "基础数据": {
      "ASIN": "B0XXXXXXX",
      "站点": "US",
      "输入关键词": "solar outdoor lights",
      "输入关键词列表": ["solar outdoor lights", "outdoor solar lamp"],
      "关键词数量": 2,
      "关键词来源": "输入文件",
      "Amazon抓取数据": {},
      "BI销售数据": {
        "明细": [
          {
            "ASIN": "B0XXXXXXX",
            "产品名称": "...",
            "销量": 12,
            "订单量": 10,
            "流量": 300,
            "浏览量": 450,
            "转化率": 0.04,
            "销售额": 299.99,
            "平均售价": 29.99,
            "广告费": -20.5,
            "广告销售额(CNY)": 120.0,
            "ACOS": 0.17,
            "广告点击量": 80,
            "广告曝光量": 2000,
            "退款金额": -5.0,
            "退款数量": 1,
            "退款率": 0.02
          }
        ]
      },
      "爬虫Listing数据": {
        "明细": [
          {
            "ASIN": "B0XXXXXXX",
            "快照日期": "2026-06-08",
            "A+图片": "...",
            "A+文案": "...",
            "产品详情": "...",
            "五点描述": "...",
            "QA": "...",
            "星级": 4.5,
            "划线价": "39.99",
            "售价": 29.99,
            "折扣百分比": "25%",
            "评论": "...",
            "评论数": 1234
          }
        ]
      },
      "错误列表": []
    },
    "卖家精灵关键词数据": {
      "关键词输入": {
        "状态": "成功",
        "原始状态": "success",
        "关键词来源": "输入文件",
        "关键词列表": ["solar outdoor lights", "outdoor solar lamp"],
        "关键词数量": 2
      },
      "关键词反查": {},
      "关键词挖掘": {}
    },
    "卖家精灵AI全景分析数据": {
      "状态": "成功",
      "报告任务ID": "f8c83463849334d52121f025af335d75",
      "content": {
        "moduleName": "LA",
        "reportDetails": {}
      }
    },
    "Rufus优化建议数据": {
      "状态": "成功",
      "接入状态": "已接入",
      "国家站点": "US",
      "问题列表": [
        "这个产品ASIN B0XXXXXXX，标题写得清楚吗？如果我要找这个产品ASIN B0XXXXXXX，一般搜什么词能找到他？",
        "这个产品ASIN B0XXXXXXX五点卖点描述里，最重要的一条是什么？有没有买家很想知道但没写进去的事？",
        "看完这个产品ASIN B0XXXXXXX这些图，还有什么是我想知道但看不出来的？要是再加一张图，加什么最有用？",
        "这个产品ASIN B0XXXXXXX下面那个长的图文介绍，跟上面五点说的有区别吗？看完能让我更放心买吗？还少介绍了什么？",
        "这个产品ASIN B0XXXXXXX评价里大家最常夸和最常抱怨的是什么？这些在介绍里提前说清楚了吗？",
        "这个产品ASIN B0XXXXXXX如果让你给这个产品页面只提一个最着急改的地方，会是什么？"
      ],
      "答案数量": 2,
      "报告路径": "output/amazon-rufus/B0XXXXXXX-20260608-180214.md",
      "数据": [
        {
          "题号": 1,
          "问题": "这个产品ASIN B0XXXXXXX，标题写得清楚吗？如果我要找这个产品ASIN B0XXXXXXX，一般搜什么词能找到他？",
          "相关产品": ["https://www.amazon.com/dp/B0XXXXXXX"],
          "答案": "...",
          "推荐ASIN": ["B0XXXXXXX"],
          "总结": "..."
        }
      ]
    }
  },
  "errors": []
}
```

## Frontend Output

In addition to `asin-data.jsonl`, each run writes:

- `frontend-data.json`: frontend-friendly aggregate JSON. Keys are Chinese and grouped into four fixed sections.
- `frontend-data.md`: lightweight Markdown handoff that points frontend developers to the JSON file and section contract.

Each ASIN record also includes `frontend_data` with the same four sections:

1. `基础数据`
2. `卖家精灵关键词数据`
3. `卖家精灵AI全景分析数据`
4. `Rufus优化建议数据`

`卖家精灵AI全景分析数据.content` must be the complete SellerSprite AI task `content`. The collector may parse the JSON string into an object, but it must not summarize, filter, or flatten the content.

Input keyword data is machine-readable in three places:

- `input.keywords`
- `frontend_data.基础数据.输入关键词列表`
- `frontend_data.卖家精灵关键词数据.关键词输入.关键词列表`

Rufus answer data is machine-readable in two places:

- `rufus.answers`
- `frontend_data.Rufus优化建议数据.数据`

Rufus data must come from the current `opscli amazon-rufus get-backend` run. The collector reads only the returned Markdown `report_path` and does not read local Rufus browser state, cookies, headers, or request seeds.

## Status Values

| Status | Meaning |
| --- | --- |
| `success` | Source completed successfully |
| `skipped` | Source was intentionally skipped |
| `failed` | Source failed |
| `partial` | Source completed with warnings or incomplete sub-results |
| `planned` | Dry-run command plan only |

## Error Record

```json
{
  "asin": "B0XXXXXXX",
  "source": "seller_sprite.keyword_reverse",
  "tool": "opscli seller-sprite run keyword-reverse",
  "status": "failed",
  "exit_code": 1,
  "error_message": "...",
  "retry_count": 1
}
```
