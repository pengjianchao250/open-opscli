const field = (key, label, type = "text", extra = {}) => ({ key, label, type, ...extra });
const range = (minimum, maximum, label, extra = {}) => [
  field(minimum, `${label}最小值`, "number", extra),
  field(maximum, `${label}最大值`, "number", extra),
];
const boolOptions = [["", "不限"], ["true", "是"], ["false", "否"]];

export const SITE_OPTIONS = [
  ["US", "美国"], ["UK", "英国"], ["DE", "德国"], ["FR", "法国"],
  ["JP", "日本"], ["CA", "加拿大"], ["IT", "意大利"], ["ES", "西班牙"],
  ["IN", "印度"], ["MX", "墨西哥"],
];

export function monthlyPeriodOptions(now = new Date(), count = 25) {
  const current = now instanceof Date ? now : new Date(now);
  if (Number.isNaN(current.getTime())) throw new Error("周期基准日期无效");
  const options = [["30d", "最近30天"]];
  // SellerSprite monthly datasets currently publish with a two-month calendar lag.
  for (let offset = 2; offset < count + 2; offset += 1) {
    const month = new Date(current.getFullYear(), current.getMonth() - offset, 1);
    const value = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}`;
    options.push([value, value]);
  }
  return options;
}

export function periodOptionsForScenario(scenarioId, now = new Date()) {
  const definition = SCENARIOS[scenarioId];
  if (!definition || definition.periodHidden) return [];
  if (definition.periodOptions) return definition.periodOptions;
  if (definition.periodMode === "aba") {
    return [["30d", "最近完整周"], ...monthlyPeriodOptions(now).slice(1)];
  }
  if (definition.periodMode === "monthly") return monthlyPeriodOptions(now);
  return [["30d", "最近30天"]];
}

export function scenarioPeriod(scenarioId, candidate, now = new Date()) {
  const definition = SCENARIOS[scenarioId];
  const options = periodOptionsForScenario(scenarioId, now);
  if (!options.length) return definition?.defaultPeriod || String(candidate || "30d");
  const value = String(candidate || "");
  return options.some(([option]) => option === value)
    ? value
    : definition?.defaultPeriod || options[0][0];
}

export const SCENARIO_GROUPS = [
  { label: "选品与市场", scenarios: ["product-research", "market-research", "competitor-lookup", "aba-research"] },
  { label: "关键词与流量", scenarios: ["keyword-miner", "keyword-research", "keyword-reverse", "traffic-source", "traffic-extend", "association-traffic", "keyword-comparison", "keyword-conversion-rate", "real-time-bidding"] },
];

export const SCENARIOS = {
  "product-research": {
    title: "选产品",
    description: "按销量、价格、竞争度和产品属性筛选潜力商品。",
    periodMode: "monthly",
    defaults: { recommendationMode: "", sellerTypes: "" },
    groups: [
      { label: "基础条件", open: true, fields: [
        field("recommendationMode", "推荐模式", "select", { options: [["", "自定义筛选"], ...["低价长尾选品", "研发新品榜", "潜力单变体", "销量飙升", "潜力市场", "未被满足的市场", "不压库存的市场", "投机市场", "高需求低要求市场", "全品类铺货", "精品铺货", "低价商品", "新手推荐"].map((value) => [value, value])] }),
        field("category", "类目或节点路径", "text", { placeholder: "例如 bed frames 或 1055398:1063236" }),
        field("keyword", "标题关键词", "text", { placeholder: "例如 rechargeable lamp" }),
        field("sellerTypes", "配送方式", "multi", { placeholder: "FBA, FBM, AMZ" }),
      ] },
      { label: "销售表现", fields: [
        ...range("minSales", "maxSales", "月销量", { min: 0 }),
        ...range("minAmount", "maxAmount", "月销售额", { min: 0 }),
        ...range("minPrice", "maxPrice", "价格", { min: 0, step: "0.01" }),
        ...range("minTotalUnitsGrowth", "maxTotalUnitsGrowth", "月销量增长率", { step: "0.01" }),
      ] },
      { label: "竞争与产品", fields: [
        ...range("minReviews", "maxReviews", "评分数", { min: 0 }),
        ...range("minReviewRating", "maxReviewRating", "评分", { min: 0, max: 5, step: "0.1" }),
        ...range("minSellers", "maxSellers", "卖家数", { min: 0 }),
        ...range("minVariations", "maxVariations", "变体数", { min: 0 }),
        field("putawayMonth", "上架月数不超过", "number", { min: 1, placeholder: "例如 12" }),
        field("productTags", "商品标签", "multi", { placeholder: "BestSeller, AmazonChoice, NewRelease" }),
      ] },
    ],
  },
  "market-research": {
    title: "选市场",
    description: "按类目市场规模、集中度和新品表现筛选市场。",
    periodMode: "monthly",
    groups: [
      { label: "基础条件", open: true, fields: [
        field("departmentKeyword", "类目或市场关键词", "text", { placeholder: "例如 bed frames" }),
        field("node", "精确类目节点", "text", { placeholder: "仅明确知道节点时填写" }),
        field("sampleNumber", "样本数量", "number", { min: 1 }),
        field("topn", "头部 Listing 数量", "number", { min: 1 }),
        field("newReleaseNum", "新品定义月数", "select", { options: [["", "默认 6 个月"], ["1", "1 个月"], ["3", "3 个月"], ["6", "6 个月"]], valueKind: "number" }),
      ] },
      { label: "市场规模", fields: [
        ...range("minAvgSales", "maxAvgSales", "月均销量", { min: 0 }),
        ...range("minTotalProducts", "maxTotalProducts", "商品总数", { min: 0 }),
        ...range("minAvgRevenue", "maxAvgRevenue", "月均销售额", { min: 0 }),
        ...range("minAvgPrice", "maxAvgPrice", "平均价格", { min: 0, step: "0.01" }),
      ] },
      { label: "竞争结构", fields: [
        ...range("minAvgReviews", "maxAvgReviews", "平均评分数", { min: 0 }),
        ...range("minAvgRating", "maxAvgRating", "平均评分", { min: 0, max: 5, step: "0.1" }),
        ...range("minHeadListingProductCrn", "maxHeadListingProductCrn", "商品集中度", { min: 0, max: 100, step: "0.1" }),
        ...range("minNewRatio", "maxNewRatio", "新品数量占比", { min: 0, max: 100, step: "0.1" }),
      ] },
    ],
  },
  "competitor-lookup": {
    title: "选竞品",
    description: "按关键词、品牌、卖家或指定 ASIN 查询产品数据。",
    periodMode: "monthly",
    requiredAny: ["keyword", "brand", "sellerName", "asin", "asins"],
    groups: [{ label: "查询条件", open: true, fields: [
      field("keyword", "关键词", "text", { placeholder: "例如 usb c charger" }),
      field("brand", "品牌", "text", { placeholder: "例如 Anker" }),
      field("sellerName", "卖家名称"),
      field("asin", "单个 ASIN", "text", { format: "asin", placeholder: "10 位 ASIN" }),
      field("asins", "批量 ASIN", "multi", { format: "asins", maxItems: 1000, placeholder: "逗号、空格或换行分隔" }),
      field("node", "类目节点"),
      field("includeVariations", "包含变体", "select", { options: boolOptions }),
    ] }],
  },
  "aba-research": {
    title: "ABA 数据选品",
    description: "基于 Amazon Brand Analytics 搜索行为发现需求与趋势。",
    periodMode: "aba",
    required: ["q"],
    groups: [
      { label: "查询条件", open: true, fields: [
        field("q", "ASIN 或关键词", "text", { placeholder: "例如 B07Z82895W 或 iphone charger" }),
        field("reverseType", "周期类型", "select", { options: [["", "自动识别"], ["W", "每周"], ["M", "每月"]] }),
        field("nodeIds", "类目节点", "multi", { placeholder: "多个节点用逗号分隔" }),
        field("orderField", "排序字段", "select", { options: [["", "默认排序"], ["searchRank", "搜索排名"], ["searches", "搜索量"], ["rankGrowthRate", "排名变化率"]] }),
      ] },
      { label: "结果筛选", fields: [
        ...range("minSearches", "maxSearches", "搜索量", { min: 0 }),
        ...range("minSearchRank", "maxSearchRank", "搜索排名", { min: 1 }),
        ...range("minConversionRate", "maxConversionRate", "转化率", { min: 0, max: 100, step: "0.01" }),
        ...range("minWordCount", "maxWordCount", "词数", { min: 1 }),
      ] },
    ],
  },
  "keyword-miner": {
    title: "关键词挖掘",
    description: "围绕一个核心词拓展相关搜索词与流量指标。",
    periodMode: "monthly",
    required: ["keyword"],
    defaults: { includeHighFrequency: true },
    groups: [{ label: "关键词条件", open: true, fields: [
      field("keyword", "核心关键词", "text", { placeholder: "例如 phone stand" }),
      field("filterRootWord", "过滤词根", "select", { options: [["", "不过滤"], ["1", "过滤相同词根"]], valueKind: "number" }),
      field("matchType", "匹配方式", "select", { options: [["", "默认"], ["0", "模糊匹配"], ["1", "词组匹配"], ["2", "精准匹配"]], valueKind: "number" }),
      field("amazonChoice", "Amazon's Choice", "select", { options: boolOptions }),
      field("includeHighFrequency", "包含高频词", "checkbox"),
    ] }],
  },
  "keyword-research": {
    title: "关键词选品",
    description: "按搜索需求、供需关系和市场竞争筛选关键词机会。",
    periodMode: "monthly",
    groups: [
      { label: "基础条件", open: true, fields: [
        field("keyword", "包含关键词"), field("category", "类目"),
        field("marketPeriod", "市场周期", "select", { options: [["", "不限"], ["N", "常年"], ["S1,S2,S3", "1-3 月"], ["S4,S5,S6", "4-6 月"], ["S7,S8,S9", "7-9 月"], ["S10,S11,S12", "10-12 月"], ["I", "增长"], ["D", "下降"]] }),
      ] },
      { label: "需求与竞争", fields: [
        ...range("minSearches", "maxSearches", "月搜索量", { min: 0 }),
        ...range("minProducts", "maxProducts", "商品数", { min: 0 }),
        ...range("minSupplyDemandRatio", "maxSupplyDemandRatio", "供需比", { min: 0, step: "0.01" }),
        ...range("minTitleDensity", "maxTitleDensity", "标题密度", { min: 0 }),
        ...range("minBid", "maxBid", "PPC 竞价", { min: 0, step: "0.01" }),
      ] },
    ],
  },
  "keyword-reverse": {
    title: "关键词反查",
    description: "按 ASIN 反查近 30 天搜索流量词、排名和转化指标。",
    periodMode: "monthly",
    required: ["asin"], defaults: { includeHighFrequency: true },
    groups: [{ label: "反查条件", open: true, fields: [
      field("asin", "ASIN", "text", { format: "asin", placeholder: "10 位父体或子体 ASIN" }),
      field("badges", "流量词类型", "multi"), field("conversionKeywordTypes", "转化效果", "multi"),
      field("trafficKeywordTypes", "关键词类型", "multi"), field("exactly", "精准匹配", "select", { options: boolOptions }),
      field("includeHighFrequency", "包含高频词", "checkbox"),
    ] }],
  },
  "traffic-source": {
    title: "查流量来源", description: "查询关键词或 ASIN 对应的自然、推荐和广告流量来源。", required: ["keywordOrAsin"],
    periodMode: "monthly",
    groups: [{ label: "查询条件", open: true, fields: [field("keywordOrAsin", "关键词或 ASIN", "text", { placeholder: "输入一个关键词或 ASIN" })] }],
  },
  "traffic-extend": {
    title: "拓展流量词", description: "合并多个 ASIN 及其变体的流量词并去重。", required: ["asins"], defaults: { variantSelection: "all" },
    periodMode: "monthly",
    groups: [{ label: "拓词条件", open: true, fields: [
      field("asins", "ASIN", "multi", { format: "asins", maxItems: 20, placeholder: "1-20 个 ASIN" }),
      field("variantSelection", "变体拓词", "select", { options: [["all", "全部变体"], ["sell_well", "畅销变体"], ["current", "当前变体"]] }),
    ] }],
  },
  "association-traffic": {
    title: "关联流量", description: "查询 ASIN 近 90 天关联曝光商品和关联类型。", required: ["asins"], defaults: { orderField: "createdTime", desc: "true" }, defaultPeriod: "90d", periodOptions: [["90d", "近90天"]],
    groups: [{ label: "关联条件", open: true, fields: [
      field("asins", "ASIN", "multi", { format: "asins", maxItems: 20, placeholder: "1-20 个 ASIN" }),
      field("relations", "关联类型", "multi", { placeholder: "VAV, CSI, AVP, BAV, MIB, FBT, MIE, BAB, COB, SP, FSA, BCA" }),
      field("orderField", "排序字段", "select", { options: [["createdTime", "引流时间"], ["relationCount", "关联次数"]] }),
      field("desc", "倒序", "select", { options: [["true", "是"], ["false", "否"]] }),
    ] }],
  },
  "keyword-comparison": {
    title: "流量词对比", description: "对比自己的 ASIN 与最多 10 个竞品的流量词占比。", required: ["ownAsin", "competitorAsins"], defaults: { variantSelection: "sell_well" }, periodHidden: true,
    groups: [{ label: "对比条件", open: true, fields: [
      field("ownAsin", "自己的 ASIN", "text", { format: "asin" }),
      field("competitorAsins", "竞品 ASIN", "multi", { format: "asins", maxItems: 10, placeholder: "1-10 个竞品 ASIN" }),
      field("variantSelection", "变体拓词", "select", { options: [["sell_well", "畅销变体"], ["current", "当前变体"]] }),
    ] }],
  },
  "keyword-conversion-rate": {
    title: "关键词转化率", description: "查询关键词的搜索、点击、购买、转化率和竞价数据。", required: ["keywords"], defaultPeriod: "W", periodOptions: [["W", "按周"], ["90D", "近 90 天"]],
    groups: [{ label: "关键词条件", open: true, fields: [field("keywords", "关键词词组", "multiline", { maxItems: 1000, placeholder: "每行一个词组，最多 1000 个" })] }],
  },
  "real-time-bidding": {
    title: "实时查竞价", description: "读取 ASIN 最新竞价任务并合并 SP、SB 与 SBV 建议竞价。", required: ["asin"], periodHidden: true,
    groups: [{ label: "竞价条件", open: true, fields: [field("asin", "ASIN", "text", { format: "asin" })] }],
  },
};

function splitMulti(value, preservePhrases = false) {
  if (Array.isArray(value)) return value;
  const separator = preservePhrases ? /[\n,，;；\t]+/ : /[\s,，;；\t\n]+/;
  return String(value || "").split(separator).map((item) => item.trim()).filter(Boolean);
}

function fieldList(definition) {
  return definition.groups.flatMap((group) => group.fields);
}

function hasValue(value) {
  return Array.isArray(value) ? value.length > 0 : value !== undefined && value !== null && value !== "";
}

export function scenarioDefaults(scenarioId) {
  return { ...(SCENARIOS[scenarioId]?.defaults || {}) };
}

export function buildScenarioParams(scenarioId, values, advancedJson = "") {
  const definition = SCENARIOS[scenarioId];
  if (!definition) throw new Error(`未知场景：${scenarioId}`);
  const params = {};
  for (const item of fieldList(definition)) {
    let value = values[item.key];
    if (item.type === "checkbox") {
      if (value === true) params[item.key] = true;
      continue;
    }
    if (typeof value === "string") value = value.trim();
    if (!hasValue(value)) continue;
    if (item.type === "multi" || item.type === "multiline") {
      value = splitMulti(value, item.type === "multiline");
    }
    if (item.type === "number" || item.valueKind === "number") {
      if (Array.isArray(value)) {
        value = value.map(Number);
        if (value.some((number) => !Number.isFinite(number))) throw new Error(`${item.label}必须是有效数字列表`);
      } else {
        value = Number(value);
        if (!Number.isFinite(value)) throw new Error(`${item.label}必须是有效数字`);
      }
    } else if (item.type === "select" && ["true", "false"].includes(value)) value = value === "true";
    if (item.maxItems && Array.isArray(value) && value.length > item.maxItems) throw new Error(`${item.label}最多支持 ${item.maxItems} 个值`);
    if (item.format === "asin" && !/^[A-Za-z0-9]{10}$/.test(String(value))) throw new Error(`${item.label}必须是 10 位 ASIN`);
    if (item.format === "asins") {
      const invalid = value.filter((asin) => !/^[A-Za-z0-9]{10}$/.test(asin));
      if (invalid.length) throw new Error(`${item.label}包含无效 ASIN：${invalid[0]}`);
    }
    params[item.key] = value;
  }
  if (advancedJson.trim()) {
    let advanced;
    try { advanced = JSON.parse(advancedJson); } catch { throw new Error("高级参数不是有效 JSON"); }
    if (!advanced || typeof advanced !== "object" || Array.isArray(advanced)) throw new Error("高级参数必须是 JSON 对象");
    Object.assign(params, advanced);
  }
  for (const key of definition.required || []) {
    if (!hasValue(params[key])) throw new Error(`${fieldList(definition).find((item) => item.key === key)?.label || key}为必填项`);
  }
  if (definition.requiredAny && !definition.requiredAny.some((key) => hasValue(params[key]))) throw new Error("请至少填写一个主要查询条件");
  for (const key of Object.keys(params).filter((name) => name.startsWith("min"))) {
    const maximumKey = `max${key.slice(3)}`;
    if (typeof params[key] === "number" && typeof params[maximumKey] === "number" && params[key] > params[maximumKey]) throw new Error(`${key}不能大于${maximumKey}`);
  }
  return params;
}
