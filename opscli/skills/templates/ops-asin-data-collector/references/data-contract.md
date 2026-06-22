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
      "分析这个ASIN B0XXXXXXX的标题是否清楚，是否能让买家搜索到产品并愿意点击查看详情？按这个格式输出：\n1、当前标题内容\n2、问题逐项分析\n问题类型｜具体问题 ｜ 问题依据｜建议修改\n3、建议优化标题\n4、优化核心逻辑总结",
      "分析这个ASIN B0XXXXXXX 的五点卖点，从消费者决策路径与商品信息表达优化的角度，对该商品进行系统分析。按这个格式输出：\n1、当前五点内容\n2、问题逐项分析 \n五点序号｜问题类型｜具体问题 ｜ 问题依据｜建议修改\n3、建议优化五点\n4、优化核心逻辑总结",
      "分析这个ASIN B0XXXXXXX 的图片是否解决买家购买疑问，从消费者决策路径与商品信息表达优化的角度。按这个格式输出：\n1、当前图片整体问题 \n2、问题逐项分析 \n每张图序号｜目标｜具体问题 ｜ 核心依据｜优化方案\n3、优化优先级总结\n优先级｜图片序号｜核心价值\n4、优化核心逻辑总结",
      "分析这个ASIN B0XXXXXXX 的 A+ 是否补充了关键信息、增强购买信任。按这个格式输出：\n1、当前A+内容整体问题\n2、问题逐项分析 \n每个模块｜目标｜具体问题 ｜ 核心依据｜优化方案\n3、优化优先级总结\n优先级｜优化项｜预期效果\n4、优化核心逻辑总结",
      "分析这个ASIN B0XXXXXXX 的评论中买家最常夸和最常抱怨的点，判断产品页面是否提前说明，并且需如何优化产品，按这个格式输出：\n1、评价整体总结分析\n2、问题逐项分析\n问题类型｜风险等级｜影响范围｜评论依据｜产品页面现状｜优化方案\n3、优化优先级总结\n优先级｜优化项｜预期效果\n4、优化核心逻辑总结",
      "从标题、五点、图片、A+、评论中，找出这个 ASIN B0XXXXXXX 最优先修改的一处。按这个格式输出：\n1、核心问题定位\n2、最优先修改原因\n问题维度｜影响范围｜具体分析｜建议方案\n3、总体执行修改方案\n4、优化核心逻辑总结"
    ],
    "question_count": 6,
    "answer_count": 2,
    "report_path": "output/amazon-rufus/B0XXXXXXX-20260608-180214.md",
    "answers": [
      {
        "index": 1,
        "question": "分析这个ASIN B0XXXXXXX的标题是否清楚，是否能让买家搜索到产品并愿意点击查看详情？按这个格式输出：\n1、当前标题内容\n2、问题逐项分析\n问题类型｜具体问题 ｜ 问题依据｜建议修改\n3、建议优化标题\n4、优化核心逻辑总结",
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
        "分析这个ASIN B0XXXXXXX的标题是否清楚，是否能让买家搜索到产品并愿意点击查看详情？按这个格式输出：\n1、当前标题内容\n2、问题逐项分析\n问题类型｜具体问题 ｜ 问题依据｜建议修改\n3、建议优化标题\n4、优化核心逻辑总结",
        "分析这个ASIN B0XXXXXXX 的五点卖点，从消费者决策路径与商品信息表达优化的角度，对该商品进行系统分析。按这个格式输出：\n1、当前五点内容\n2、问题逐项分析 \n五点序号｜问题类型｜具体问题 ｜ 问题依据｜建议修改\n3、建议优化五点\n4、优化核心逻辑总结",
        "分析这个ASIN B0XXXXXXX 的图片是否解决买家购买疑问，从消费者决策路径与商品信息表达优化的角度。按这个格式输出：\n1、当前图片整体问题 \n2、问题逐项分析 \n每张图序号｜目标｜具体问题 ｜ 核心依据｜优化方案\n3、优化优先级总结\n优先级｜图片序号｜核心价值\n4、优化核心逻辑总结",
        "分析这个ASIN B0XXXXXXX 的 A+ 是否补充了关键信息、增强购买信任。按这个格式输出：\n1、当前A+内容整体问题\n2、问题逐项分析 \n每个模块｜目标｜具体问题 ｜ 核心依据｜优化方案\n3、优化优先级总结\n优先级｜优化项｜预期效果\n4、优化核心逻辑总结",
        "分析这个ASIN B0XXXXXXX 的评论中买家最常夸和最常抱怨的点，判断产品页面是否提前说明，并且需如何优化产品，按这个格式输出：\n1、评价整体总结分析\n2、问题逐项分析\n问题类型｜风险等级｜影响范围｜评论依据｜产品页面现状｜优化方案\n3、优化优先级总结\n优先级｜优化项｜预期效果\n4、优化核心逻辑总结",
        "从标题、五点、图片、A+、评论中，找出这个 ASIN B0XXXXXXX 最优先修改的一处。按这个格式输出：\n1、核心问题定位\n2、最优先修改原因\n问题维度｜影响范围｜具体分析｜建议方案\n3、总体执行修改方案\n4、优化核心逻辑总结"
      ],
      "答案数量": 2,
      "报告路径": "output/amazon-rufus/B0XXXXXXX-20260608-180214.md",
      "数据": [
        {
          "题号": 1,
          "问题": "分析这个ASIN B0XXXXXXX的标题是否清楚，是否能让买家搜索到产品并愿意点击查看详情？按这个格式输出：\n1、当前标题内容\n2、问题逐项分析\n问题类型｜具体问题 ｜ 问题依据｜建议修改\n3、建议优化标题\n4、优化核心逻辑总结",
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
