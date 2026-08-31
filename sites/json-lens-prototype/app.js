import { buildRequestHeaders } from "./request-contract.js";
import { tableCsv, tableKeys, tableValue, visibleTableRows } from "./table-utils.js";

const HISTORY_STORAGE_KEY = "json-lens-query-history";
const HISTORY_LIMIT = 20;

const SAMPLE_DATA = [
  {
    asin: "B0A1LAMP01",
    title: "Rechargeable Work Light",
    price: 29.99,
    currency: "USD",
    inStock: true,
    tags: ["usb-c", "magnetic"],
    metrics: { salesRank: 1240, rating: 4.6, reviewCount: 1820 },
  },
  {
    asin: "B0A1LAMP02",
    title: "Compact Camping Lantern",
    price: 22.5,
    currency: "USD",
    inStock: false,
    tags: ["camping"],
    metrics: { salesRank: 3860, rating: 4.3, reviewCount: 742 },
  },
  {
    asin: "B0A1LAMP03",
    title: "Motion Sensor Night Light",
    price: 16.8,
    currency: "USD",
    inStock: true,
    tags: ["motion", "indoor"],
    metrics: { salesRank: 512, rating: 4.7, reviewCount: 3298 },
  },
];

const SCENARIO_SAMPLE_DATA = {
  product: [{ asin: "B0A1LAMP01", title: "Rechargeable Work Light", brand: "AUKEY", price: 29.99, currency: "USD", offers: 18 }],
  "product-search": SAMPLE_DATA,
  "product-finder": [
    { asin: "B0A1LAMP01", title: "Rechargeable Work Light", brand: "AUKEY", current_NEW: 2999, monthlySold: 420, hasReviews: true },
    { asin: "B0A1LAMP03", title: "Motion Sensor Night Light", brand: "AUKEY", current_NEW: 1680, monthlySold: 275, hasReviews: true },
  ],
  "category-search": [{ categoryId: 172282, name: "Home Office", parent: "Home & Kitchen" }],
  "category-lookup": [{ categoryId: 172282, name: "Home Office", parent: "Office Products" }],
  seller: [{ sellerId: "A1AUKEYSELLER", sellerName: "AUKEY Direct", currentRating: 98, storefrontAsins: 126 }],
  "seller-finder": [
    { sellerId: "A1AUKEYSELLER", sellerName: "AUKEY Direct", currentRating: 98, hasFBA: true },
    { sellerId: "A1LIGHTSELLER", sellerName: "Bright Supply", currentRating: 94, hasFBA: true },
  ],
  "top-seller": [{ sellerId: "A1TOPSELLER01", sellerName: "Top Home Store", feedbackCount: 18500 }],
  bestsellers: [{ asin: "B0A1LAMP01", title: "Rechargeable Work Light", salesRank: 512 }, { asin: "B0A1LAMP03", title: "Motion Sensor Night Light", salesRank: 1240 }],
  deals: [{ asin: "B0A1LAMP01", title: "Rechargeable Work Light", currentPrice: 2499, deltaPercent: 18, isLowest: true }],
  "lightning-deals": [{ asin: "B0A1LAMP03", title: "Motion Sensor Night Light", state: "AVAILABLE", discountPercent: 25 }],
};

function scenarioSample(scenario) {
  return SCENARIO_SAMPLE_DATA[scenario] || [{ scenario, message: "暂无样例数据，请运行查询。" }];
}

const VARIANTS = {
  a: "Split workspace",
  b: "Result-first",
  c: "Inspector",
};

const SCENARIOS = {
  product: {
    title: "商品详情",
    description: "按 ASIN 或 UPC/EAN/ISBN-13 获取商品对象和价格历史。",
    required: [{ key: "identifier", label: "ASIN 或商品编码", type: "text", placeholder: "例如 B0A1LAMP01" }],
    optional: [
      { key: "offers", label: "Offer 数量", type: "number", min: 20, max: 100 },
      { key: "days", label: "历史天数", type: "number", min: 1 },
      { key: "stats", label: "统计区间（天）", type: "number", min: 0 },
      { key: "rating", label: "包含评分", type: "checkbox" },
      { key: "buybox", label: "包含 Buy Box", type: "checkbox" },
      { key: "stock", label: "包含库存", type: "checkbox" },
      { key: "history", label: "包含价格历史", type: "checkbox" },
    ],
    defaults: { identifierType: "asin", history: false, stats: 30 },
  },
  "product-search": {
    title: "商品关键词搜索",
    description: "按关键词搜索 Amazon 商品，可返回商品对象或 ASIN 列表。",
    required: [{ key: "keyword", label: "搜索关键词", type: "text", placeholder: "例如 flashlight" }],
    optional: [
      { key: "asinsOnly", label: "仅返回 ASIN", type: "checkbox" },
      { key: "stats", label: "统计区间（天）", type: "number", min: 0 },
      { key: "rating", label: "包含评分", type: "checkbox" },
      { key: "history", label: "包含价格历史", type: "checkbox" },
    ],
    defaults: { keyword: "flashlight" },
  },
  "product-finder": {
    title: "Product Finder",
    description: "按 Product Finder 条件筛选商品库。",
    selectionFields: [
      { key: "title", label: "标题包含", type: "text", placeholder: "例如 rechargeable lamp" },
      { key: "brand", label: "品牌", type: "csv", placeholder: "多个品牌用逗号分隔" },
      { key: "manufacturer", label: "制造商", type: "csv", placeholder: "多个制造商用逗号分隔" },
      { key: "productGroup", label: "产品组", type: "text" },
      { key: "rootCategory", label: "根类目 ID", type: "csv", placeholder: "多个 ID 用逗号分隔（最多 50 个）", valueKind: "number" },
      { key: "categories_include", label: "包含子类目", type: "csv", placeholder: "多个 ID 用逗号分隔", valueKind: "number" },
      { key: "categories_exclude", label: "排除子类目", type: "csv", placeholder: "多个 ID 用逗号分隔", valueKind: "number" },
      { key: "current_NEW_gte", label: "新品价不低于", type: "number", min: 0 },
      { key: "current_NEW_lte", label: "新品价不高于", type: "number", min: 0 },
      { key: "monthlySold_gte", label: "月销量不低于", type: "number", min: 0 },
      { key: "monthlySold_lte", label: "月销量不高于", type: "number", min: 0 },
      { key: "current_SALES_lte", label: "Sales Rank 不高于", type: "number", min: 1 },
      { key: "hasReviews", label: "必须有评论", type: "checkbox" },
      { key: "hasAPlus", label: "必须有 A+", type: "checkbox" },
      { key: "isPrimeExclusive", label: "Prime 专享", type: "checkbox" },
    ],
    optional: [
      { key: "singleVariation", label: "仅单变体商品", type: "checkbox" },
      { key: "hasParentASIN", label: "必须有父 ASIN", type: "checkbox" },
      { key: "perPage", label: "返回数量", type: "select", options: [["50", "50 条"], ["100", "100 条"], ["500", "500 条"], ["1000", "1000 条"]] },
      { key: "page", label: "页码", type: "number", min: 0 },
      { key: "stats", label: "返回统计数据", type: "checkbox" },
      { key: "customSelection", label: "自定义筛选 JSON", type: "json", placeholder: '{"variationCount": {"gte": 2}}' },
    ],
    defaults: {},
  },
  "category-search": {
    title: "类目搜索",
    description: "按关键词搜索 Keepa 类目。",
    required: [{ key: "keyword", label: "类目关键词", type: "text", placeholder: "例如 home office" }],
  },
  "category-lookup": {
    title: "类目详情",
    description: "按 category id 查询类目详情，最多 10 个。",
    required: [{ key: "categories", label: "类目 ID", type: "text", placeholder: "例如 172282" }],
    optional: [{ key: "parents", label: "包含父级类目", type: "checkbox" }],
  },
  seller: {
    title: "卖家详情",
    description: "按 seller id 查询卖家指标，最多 100 个。",
    required: [{ key: "sellers", label: "Seller ID", type: "text", placeholder: "例如 A1ABCDEF123" }],
    optional: [{ key: "storefront", label: "读取店铺 ASIN", type: "checkbox" }],
  },
  "seller-finder": {
    title: "Seller Finder",
    description: "按筛选条件查找卖家，返回 sellerIdList。",
    selectionFields: [
      { key: "search", label: "搜索关键词", type: "text", placeholder: "卖家名、公司名或地址" },
      { key: "sellerName", label: "卖家名称", type: "text" },
      { key: "businessName", label: "企业名称", type: "text" },
      { key: "sellerId", label: "Seller ID", type: "csv", placeholder: "多个 Seller ID 用逗号分隔" },
      { key: "address", label: "地址关键词", type: "text", placeholder: "例如 California" },
      { key: "activeOnly", label: "仅活跃卖家", type: "checkbox" },
      { key: "isAmazon", label: "Amazon 自营", type: "checkbox" },
      { key: "hasFBA", label: "使用 FBA", type: "checkbox" },
      { key: "hasBusinessDetails", label: "有企业资料", type: "checkbox" },
      { key: "currentRating_gte", label: "好评率不低于 (%)", type: "number", min: 0, max: 100 },
      { key: "currentRatingCount_gte", label: "评分数不低于", type: "number", min: 0 },
    ],
    optional: [
      { key: "totalStorefrontAsins_gte", label: "店铺商品数不低于", type: "number", min: 0 },
      { key: "perPage", label: "返回数量", type: "select", options: [["50", "50 条"], ["100", "100 条"], ["500", "500 条"], ["1000", "1000 条"]] },
      { key: "page", label: "页码", type: "number", min: 0 },
      { key: "customSelection", label: "自定义筛选 JSON", type: "json", placeholder: '{"ratingCount": {"gte": 100}}' },
    ],
    defaults: {},
  },
  "top-seller": {
    title: "Top Sellers",
    description: "获取指定站点评分最多的 marketplace sellers。",
    required: [],
    primitiveResultKey: "sellerId",
  },
  bestsellers: {
    title: "Best Sellers",
    description: "按 category node 或 productGroup 获取热销 ASIN 列表。",
    primitiveResultKey: "asin",
    required: [{ key: "category", label: "类目 ID / Product Group", type: "text", placeholder: "例如 172282" }],
    optional: [
      { key: "range", label: "历史范围", type: "select", options: [["", "当前榜单"], ["30", "近 30 天"], ["90", "近 90 天"], ["180", "近 180 天"]] },
      { key: "month", label: "历史月份", type: "number", min: 1, max: 12 },
      { key: "year", label: "历史年份", type: "number", min: 2000, max: 9999 },
      { key: "variations", label: "包含变体", type: "checkbox" },
      { key: "sublist", label: "返回子榜单", type: "checkbox" },
    ],
  },
  deals: {
    title: "Deals",
    description: "按筛选条件查询最近变动和折扣商品。",
    selectionFields: [
      { key: "priceTypes", label: "价格类型", type: "select", options: [["0", "Amazon 售价"], ["1", "新品售价"], ["2", "二手售价"], ["3", "销售排名"], ["8", "Lightning Deal"], ["16", "评分"], ["17", "评论数"]] },
      { key: "dateRange", label: "变化时间范围", type: "select", options: [["", "不限"], ["0", "今天"], ["1", "近 7 天"], ["2", "近 30 天"], ["3", "近 90 天"]] },
      { key: "includeCategories", label: "包含类目 ID", type: "csv", placeholder: "多个 ID 用逗号分隔", valueKind: "number" },
      { key: "excludeCategories", label: "排除类目 ID", type: "csv", placeholder: "多个 ID 用逗号分隔", valueKind: "number" },
      { key: "isLowest", label: "当前为历史最低", type: "checkbox" },
      { key: "isRisers", label: "价格上涨", type: "checkbox" },
      { key: "isDrop", label: "价格下降", type: "checkbox" },
      { key: "mustHaveAmazonOffer", label: "必须有 Amazon Offer", type: "checkbox" },
      { key: "mustNotHaveAmazonOffer", label: "不能有 Amazon Offer", type: "checkbox" },
    ],
    optional: [{ key: "customSelection", label: "自定义筛选 JSON", type: "json", placeholder: '{"current_NEW_gte": 10}' }],
    defaults: { priceTypes: "0" },
  },
  "lightning-deals": {
    title: "Lightning Deals",
    description: "查询当前和即将开始的秒杀。",
    required: [],
    optional: [
      { key: "asin", label: "ASIN（可选）", type: "text", placeholder: "留空查询全部" },
      { key: "state", label: "状态", type: "select", options: [["", "全部状态"], ["AVAILABLE", "可用"], ["UPCOMING", "即将开始"]] },
    ],
  },
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function loadQueryHistory() {
  try {
    const records = JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || "[]");
    if (!Array.isArray(records)) return [];
    return records.filter((record) => isRecord(record) && SCENARIOS[record.scenario] && isRecord(record.params)).slice(0, HISTORY_LIMIT);
  } catch {
    return [];
  }
}

function storeQueryHistory(records) {
  try {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(records));
  } catch {
    return false;
  }
  return true;
}

function summarizeHistoryParams(params) {
  const entries = Object.entries(params).filter(([key, value]) => key !== "identifierType" && value !== "" && value !== false && value !== undefined);
  if (!entries.length) return "无额外参数";
  return entries.slice(0, 2).map(([key, value]) => {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return `${key}: ${text.length > 28 ? `${text.slice(0, 28)}...` : text}`;
  }).join(" · ");
}

function extractRows(data) {
  if (Array.isArray(data)) return data;
  if (isRecord(data)) {
    for (const key of ["data", "rows", "items", "results"]) {
      if (Array.isArray(data[key])) return data[key];
    }
  }
  return null;
}

function unionKeys(rows, primitiveKey = "value") {
  return tableKeys(rows, primitiveKey);
}

function typeName(value) {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function scenarioSupportsBrazil(scenario) {
  return !["seller-finder", "top-seller", "bestsellers"].includes(scenario);
}

function formatScalar(value) {
  if (value === null) return '<span class="tree-null">null</span>';
  if (typeof value === "boolean") return `<span class="tree-boolean">${value}</span>`;
  if (typeof value === "number") return `<span class="tree-number">${escapeHtml(value)}</span>`;
  return `<span class="tree-string">${escapeHtml(value)}</span>`;
}

function renderTreeNode(value, key = null) {
  const label = key === null ? "value" : escapeHtml(key);
  if (!isRecord(value) && !Array.isArray(value)) {
    return `<li><span class="tree-key">${label}:</span> <span class="tree-value">${formatScalar(value)}</span></li>`;
  }
  const entries = Array.isArray(value) ? value.map((item, index) => [index, item]) : Object.entries(value);
  const kind = Array.isArray(value) ? "array" : "object";
  const summary = `${label} <span class="tree-${kind}">${kind} · ${entries.length}</span>`;
  return `<li><details open><summary>${summary}</summary><ul class="tree">${entries.map(([childKey, childValue]) => renderTreeNode(childValue, childKey)).join("")}</ul></details></li>`;
}

function renderTree(data) {
  return `<ul class="tree">${renderTreeNode(data)}</ul>`;
}

function cellHtml(value, rowIndex, key) {
  if (isRecord(value) || Array.isArray(value)) {
    const label = Array.isArray(value) ? `array · ${value.length}` : `object · ${Object.keys(value).length}`;
    return `<details class="cell-detail"><summary><span class="badge badge-soft badge-info badge-xs">${escapeHtml(label)}</span><span class="cell-detail-action">查看</span></summary><pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre></details>`;
  }
  if (value === undefined) return '<span class="muted">—</span>';
  if (typeof value === "boolean") return `<span class="badge badge-soft badge-info badge-xs">${value ? "true" : "false"}</span>`;
  return `<span class="cell-value" title="${escapeHtml(value)}">${formatScalar(value)}</span>`;
}

function renderTable(rows, filter, sortKey, sortDir, primitiveKey, page, pageSize) {
  const keys = unionKeys(rows, primitiveKey);
  const visibleRows = filter || sortKey ? visibleTableRows(rows, filter, sortKey, sortDir, primitiveKey) : null;
  const visibleCount = visibleRows ? visibleRows.length : rows.length;
  if (!visibleCount) return '<div class="empty-state">没有匹配的数据。<br>可以清空筛选，或切换到 JSON 视图。</div>';
  const pageCount = Math.ceil(visibleCount / pageSize);
  const currentPage = Math.min(Math.max(page, 1), pageCount);
  const pageStart = (currentPage - 1) * pageSize;
  const pageRows = visibleRows
    ? visibleRows.slice(pageStart, pageStart + pageSize)
    : rows.slice(pageStart, pageStart + pageSize).map((row, offset) => ({ row, index: pageStart + offset }));
  const head = keys.map((key) => `<th><button class="btn btn-ghost btn-xs sort-button" type="button" data-sort-key="${escapeHtml(key)}">${escapeHtml(key)} ↕</button></th>`).join("");
  const table = `<div class="table-scroll"><table class="table table-zebra table-pin-rows"><thead><tr><th>#</th>${head}</tr></thead><tbody>${pageRows.map(({ row, index }) => `<tr><td class="tiny">${index + 1}</td>${keys.map((key) => `<td>${cellHtml(tableValue(row, key, primitiveKey), index, key)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  if (pageCount === 1) return table;
  return `${table}<div class="table-pagination"><span>第 ${currentPage.toLocaleString("zh-CN")} / ${pageCount.toLocaleString("zh-CN")} 页 · ${visibleCount.toLocaleString("zh-CN")} 条</span><div class="join"><button class="btn btn-outline btn-sm join-item" type="button" data-table-page="-1" ${currentPage === 1 ? "disabled" : ""}>上一页</button><button class="btn btn-outline btn-sm join-item" type="button" data-table-page="1" ${currentPage === pageCount ? "disabled" : ""}>下一页</button></div></div>`;
}

class JsonLensApp extends HTMLElement {
  constructor() {
    super();
    const requestedVariant = new URLSearchParams(location.search).get("variant");
    const savedTheme = localStorage.getItem("json-lens-theme");
    this.state = {
      variant: VARIANTS[requestedVariant] ? requestedVariant : "a",
      theme: savedTheme === "business" ? "business" : "corporate",
      history: loadQueryHistory(),
      historyOpen: false,
      scenario: "product-search",
      site: "US",
      wait: true,
      endpoint: "http://127.0.0.1:8765/api/v1/keepa/run",
      apiKey: "",
      params: { keyword: "flashlight" },
      paramsByScenario: { "product-search": { keyword: "flashlight" } },
      advancedOpen: false,
      data: scenarioSample("product-search"),
      view: "table",
      filter: "",
      sortKey: "",
      sortDir: 1,
      tablePage: 1,
      tablePageSize: 100,
      status: "样例数据已加载。",
      tone: "ok",
      loading: false,
    };
    document.documentElement.dataset.theme = this.state.theme;
  }

  connectedCallback() {
    this.render();
    this.addEventListener("click", (event) => this.handleClick(event));
    this.addEventListener("submit", (event) => this.handleSubmit(event));
    this.addEventListener("input", (event) => this.handleInput(event));
    window.addEventListener("keydown", (event) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        this.switchVariant(event.key === "ArrowRight" ? 1 : -1);
      }
    });
  }

  updateUrl() {
    const url = new URL(location.href);
    url.searchParams.set("variant", this.state.variant);
    history.replaceState({}, "", url);
  }

  switchVariant(direction) {
    const keys = Object.keys(VARIANTS);
    const current = keys.indexOf(this.state.variant);
    this.state.variant = keys[(current + direction + keys.length) % keys.length];
    this.updateUrl();
    this.render();
  }

  handleInput(event) {
    const field = event.target?.dataset?.field;
    if (field === "theme") {
      this.state.theme = event.target.checked ? "business" : "corporate";
      document.documentElement.dataset.theme = this.state.theme;
      localStorage.setItem("json-lens-theme", this.state.theme);
      return;
    }
    if (field === "scenario") {
      this.selectScenario(event.target.value);
      return;
    }
    if (field) this.state[field] = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    const param = event.target?.dataset?.param;
    if (param) this.state.params[param] = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    if (event.target?.dataset?.filter !== undefined) {
      this.state.filter = event.target.value;
      this.state.tablePage = 1;
      this.render();
    }
  }

  handleClick(event) {
    const summary = event.target.closest("summary");
    if (summary?.parentElement?.classList.contains("advanced-options")) {
      setTimeout(() => { this.state.advancedOpen = summary.parentElement.open; }, 0);
      return;
    }
    const target = event.target.closest("button");
    if (!target) return;
    if (target.dataset.historyToggle !== undefined) {
      this.state.historyOpen = !this.state.historyOpen;
      this.render();
      return;
    }
    if (target.dataset.historyId) {
      this.applyHistory(target.dataset.historyId);
      return;
    }
    if (target.dataset.historyClear !== undefined) {
      this.state.history = [];
      this.state.historyOpen = true;
      localStorage.removeItem(HISTORY_STORAGE_KEY);
      this.render();
      return;
    }
    if (target.dataset.variantDirection) return this.switchVariant(Number(target.dataset.variantDirection));
    if (target.dataset.sample !== undefined) {
      this.state.data = scenarioSample(this.state.scenario);
      this.state.status = `已载入${SCENARIOS[this.state.scenario].title}样例。`;
      this.state.tone = "ok";
      this.state.filter = "";
      this.state.tablePage = 1;
      this.render();
      return;
    }
    if (target.dataset.downloadTable !== undefined) {
      this.downloadTable();
      return;
    }
    if (target.dataset.tablePage) {
      this.state.tablePage += Number(target.dataset.tablePage);
      this.render();
      return;
    }
    if (target.dataset.scenario) {
      this.selectScenario(target.dataset.scenario);
      return;
    }
    if (target.dataset.identifierType) {
      this.state.params.identifierType = target.dataset.identifierType;
      this.render();
      return;
    }
    if (target.dataset.advanced !== undefined) {
      this.state.advancedOpen = !this.state.advancedOpen;
      this.render();
      return;
    }
    if (target.dataset.view) {
      this.state.view = target.dataset.view;
      this.render();
      return;
    }
    if (target.dataset.sortKey) {
      this.state.sortDir = this.state.sortKey === target.dataset.sortKey ? this.state.sortDir * -1 : 1;
      this.state.sortKey = target.dataset.sortKey;
      this.state.tablePage = 1;
      this.render();
      return;
    }
  }

  selectScenario(nextScenario) {
    if (!SCENARIOS[nextScenario] || nextScenario === this.state.scenario) return;
    const pageScrollY = window.scrollY;
    this.state.paramsByScenario[this.state.scenario] = { ...this.state.params };
    this.state.scenario = nextScenario;
    if (!scenarioSupportsBrazil(this.state.scenario) && this.state.site === "BR") this.state.site = "US";
    this.state.params = { ...(this.state.paramsByScenario[this.state.scenario] || SCENARIOS[this.state.scenario].defaults || {}) };
    this.state.advancedOpen = false;
    this.state.data = scenarioSample(this.state.scenario);
    this.state.view = "table";
    this.state.filter = "";
    this.state.sortKey = "";
    this.state.tablePage = 1;
    this.state.status = `已切换到${SCENARIOS[this.state.scenario].title}。`;
    this.state.tone = "ok";
    this.render();
    window.scrollTo(0, pageScrollY);
  }

  recordHistory() {
    const record = {
      id: crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      scenario: this.state.scenario,
      site: this.state.site,
      wait: this.state.wait,
      params: JSON.parse(JSON.stringify(this.state.params)),
    };
    this.state.history = [record, ...this.state.history].slice(0, HISTORY_LIMIT);
    storeQueryHistory(this.state.history);
  }

  applyHistory(historyId) {
    const record = this.state.history.find((item) => item.id === historyId);
    if (!record) return;
    this.state.paramsByScenario[this.state.scenario] = { ...this.state.params };
    this.state.scenario = record.scenario;
    this.state.site = record.site;
    this.state.wait = record.wait;
    this.state.params = JSON.parse(JSON.stringify(record.params));
    this.state.paramsByScenario[record.scenario] = { ...this.state.params };
    this.state.advancedOpen = false;
    this.state.data = scenarioSample(record.scenario);
    this.state.view = "table";
    this.state.filter = "";
    this.state.sortKey = "";
    this.state.tablePage = 1;
    this.state.historyOpen = true;
    this.state.status = `已载入${SCENARIOS[record.scenario].title}历史查询条件。`;
    this.state.tone = "ok";
    this.render();
  }

  downloadTable() {
    const rows = extractRows(this.state.data);
    if (!rows?.length) return;
    const primitiveKey = SCENARIOS[this.state.scenario].primitiveResultKey || "value";
    const visibleRows = this.state.filter || this.state.sortKey
      ? visibleTableRows(rows, this.state.filter, this.state.sortKey, this.state.sortDir, primitiveKey).map(({ row }) => row)
      : rows;
    if (!visibleRows.length) return;
    const csv = tableCsv(visibleRows, unionKeys(rows, primitiveKey), primitiveKey);
    const blobUrl = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = `keepa-${this.state.scenario}-${this.state.site}-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(blobUrl);
  }

  async handleSubmit(event) {
    event.preventDefault();
    const form = event.target;
    if (form.dataset.action !== "request") return;
    const definition = SCENARIOS[this.state.scenario];
    let params = { ...this.state.params };
    const jsonFields = new Set((definition.required || []).concat(definition.selectionFields || [], definition.optional || []).filter((field) => field.type === "json").map((field) => field.key));
    try {
      for (const key of jsonFields) {
        if (typeof params[key] === "string" && params[key].trim()) params[key] = JSON.parse(params[key]);
      }
    } catch {
      this.state.status = "筛选条件不是有效 JSON。";
      this.state.tone = "error";
      this.render();
      return;
    }
    for (const field of (definition.selectionFields || []).concat(definition.required || [], definition.optional || [])) {
      if (field.type === "number" && params[field.key] !== "" && params[field.key] !== undefined) params[field.key] = Number(params[field.key]);
    }
    if (definition.selectionFields) {
      const selectionKeys = new Set(definition.selectionFields.map((field) => field.key));
      const selection = {};
      for (const field of definition.selectionFields) {
        const value = params[field.key];
        if (field.key === "priceTypes" && value !== "" && value !== undefined) selection.priceTypes = [Number(value)];
        else if (field.type === "csv" && typeof value === "string" && value.trim()) {
          const items = value.split(",").map((item) => item.trim()).filter(Boolean);
          if (field.valueKind === "number") {
            const numbers = items.map((item) => Number(item));
            if (numbers.some((item) => !Number.isInteger(item) || item < 1)) {
              this.state.status = `${field.label}必须是用逗号分隔的正整数。`;
              this.state.tone = "error";
              this.render();
              return;
            }
            selection[field.key] = numbers;
          } else selection[field.key] = items;
        }
        else if (field.type === "checkbox" ? value === true : value !== "" && value !== undefined) selection[field.key] = value;
      }
      const customSelection = params.customSelection;
      delete params.customSelection;
      if (isRecord(customSelection)) Object.assign(selection, customSelection);
      if (!Object.keys(selection).length || (this.state.scenario === "deals" && !selection.priceTypes?.length)) {
        this.state.status = "请至少填写一项筛选条件。";
        this.state.tone = "error";
        this.render();
        return;
      }
      if (this.state.scenario === "deals" && Object.keys(selection).length > 1) selection.isFilterEnabled = true;
      params = { ...Object.fromEntries(Object.entries(params).filter(([key]) => !selectionKeys.has(key))), selection };
    }
    if (this.state.scenario === "product") {
      const identifier = String(params.identifier || "").trim();
      delete params.identifier;
      params[this.state.params.identifierType === "code" ? "code" : "asin"] = identifier;
      delete params.identifierType;
    }
    const body = { scenario: this.state.scenario, site: this.state.site, params, export_format: "json", wait: this.state.wait };
    this.recordHistory();
    this.state.loading = true;
    this.state.status = "请求中...";
    this.state.tone = "";
    this.render();
    try {
      const headers = buildRequestHeaders(this.state.apiKey);
      const response = await fetch(this.state.endpoint, { method: "POST", headers, body: JSON.stringify(body) });
      const contentType = response.headers.get("content-type") || "";
      const responseText = await response.text();
      let payload = null;
      try {
        payload = responseText ? JSON.parse(responseText) : null;
      } catch {
        const hint = contentType.includes("text/html")
          ? "接口地址返回了网页而不是 JSON，请在连接设置中填写后端 API 地址。"
          : "接口返回内容不是有效 JSON，请检查后端响应。";
        throw new Error(`HTTP ${response.status}：${hint}`);
      }
      if (!response.ok) {
        const message = payload?.error?.message || payload?.message || payload?.error;
        throw new Error(message || `HTTP ${response.status}`);
      }
      this.state.data = payload?.data ?? payload;
      this.state.status = `请求成功 · HTTP ${response.status}`;
      this.state.tone = "ok";
      this.state.view = extractRows(this.state.data) ? "table" : "tree";
      this.state.tablePage = 1;
    } catch (error) {
      this.state.status = `请求失败：${error.message}`;
      this.state.tone = "error";
    } finally {
      this.state.loading = false;
      this.render();
    }
  }

  renderField(field, required = false) {
    const value = this.state.params[field.key] ?? "";
    const requiredMark = required ? '<span class="required-mark">必填</span>' : '';
    const requiredAttr = required ? "required" : "";
    if (field.type === "checkbox") {
      return `<label class="check-field"><input class="checkbox checkbox-primary checkbox-sm" type="checkbox" data-param="${escapeHtml(field.key)}" ${value ? "checked" : ""} ${requiredAttr}><span>${escapeHtml(field.label)}${requiredMark}</span></label>`;
    }
    if (field.type === "select") {
      return `<label>${escapeHtml(field.label)}${requiredMark}<select class="select select-bordered select-sm w-full" data-param="${escapeHtml(field.key)}" ${requiredAttr}>${field.options.map(([option, label]) => `<option value="${escapeHtml(option)}" ${String(value) === String(option) ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select></label>`;
    }
    if (field.type === "json") {
      return `<label class="field-wide">${escapeHtml(field.label)}${requiredMark}<textarea class="textarea textarea-bordered textarea-sm w-full" data-param="${escapeHtml(field.key)}" spellcheck="false" placeholder="${escapeHtml(field.placeholder || "")}" ${requiredAttr}>${escapeHtml(value)}</textarea></label>`;
    }
    const attrs = [field.placeholder && `placeholder="${escapeHtml(field.placeholder)}"`, field.min !== undefined && `min="${field.min}"`, field.max !== undefined && `max="${field.max}"`].filter(Boolean).join(" ");
    return `<label>${escapeHtml(field.label)}${requiredMark}<input class="input input-bordered input-sm w-full" type="${field.type === "csv" ? "text" : field.type || "text"}" data-param="${escapeHtml(field.key)}" value="${escapeHtml(value)}" ${attrs} ${requiredAttr}></label>`;
  }

  renderScenarioForm() {
    const definition = SCENARIOS[this.state.scenario];
    const required = definition.required || [];
    const primary = definition.selectionFields || required;
    const optional = definition.optional || [];
    const identifierToggle = this.state.scenario === "product" ? `<div class="identifier-toggle"><span class="tiny">输入类型</span><div class="join">${[["asin", "ASIN"], ["code", "UPC/EAN/ISBN"]].map(([value, label]) => `<button type="button" class="btn btn-sm join-item ${this.state.params.identifierType === value ? "btn-active" : ""}" data-identifier-type="${value}">${label}</button>`).join("")}</div></div>` : "";
    return `<div class="scenario-intro"><div><h3>${escapeHtml(definition.title)}</h3><p>${escapeHtml(definition.description)}</p></div><span class="badge badge-outline badge-info badge-sm">${escapeHtml(this.state.scenario)}</span></div>
      ${identifierToggle}
      ${definition.selectionFields ? '<p class="field-hint alert alert-soft alert-info">至少填写一项筛选条件；同一字段多个值默认匹配任一项，勾选项只会在开启时提交。</p>' : ""}
      <div class="field-grid">${primary.map((field) => this.renderField(field, !definition.selectionFields)).join("") || '<p class="field-empty">这个场景没有必填业务参数，直接执行即可。</p>'}</div>
      ${optional.length ? `<details class="advanced-options details-box" ${this.state.advancedOpen ? "open" : ""}><summary class="details-title"><span>高级参数</span><span class="tiny">${optional.length} 项可选</span></summary><div class="details-content field-grid">${optional.map((field) => this.renderField(field)).join("")}</div></details>` : ""}`;
  }

  renderScenarioSelector() {
    return `<label class="scenario-selector">查询场景<select class="select select-bordered select-sm w-full" data-field="scenario" aria-label="查询场景">${Object.entries(SCENARIOS).map(([key, item]) => `<option value="${escapeHtml(key)}" ${key === this.state.scenario ? "selected" : ""}>${escapeHtml(item.title)}</option>`).join("")}</select></label>`;
  }

  renderRequestForm(compact = false) {
    return `<form class="flow-stack" data-action="request">
      ${this.renderScenarioSelector()}
      <label class="site-selector"><span>站点 <span class="required-mark">必填</span></span><select class="select select-bordered select-sm w-full" data-field="site">${[["US", "美国"], ["GB", "英国"], ["DE", "德国"], ["FR", "法国"], ["JP", "日本"], ["CA", "加拿大"], ["IT", "意大利"], ["ES", "西班牙"], ["IN", "印度"], ["MX", "墨西哥"], ["BR", "巴西"]].map(([site, label]) => `<option value="${site}" ${this.state.site === site ? "selected" : ""} ${site === "BR" && !scenarioSupportsBrazil(this.state.scenario) ? "disabled" : ""}>${site} · ${label}</option>`).join("")}</select></label>
      ${this.renderScenarioForm()}
      <details class="connection-options details-box"><summary class="details-title">连接设置 <span class="tiny">API 地址与鉴权</span></summary><div class="details-content flow-stack connection-body"><label>API Key <input class="input input-bordered input-sm w-full" type="password" data-field="apiKey" value="${escapeHtml(this.state.apiKey)}" placeholder="支持纯 Key 或 Bearer Key" autocomplete="off"></label><label>API 地址 <input class="input input-bordered input-sm w-full" data-field="endpoint" value="${escapeHtml(this.state.endpoint)}" aria-label="接口地址"></label></div></details>
      <details class="common-options details-box"><summary class="details-title">执行设置 <span class="tiny">等待策略</span></summary><div class="details-content field-grid"><label class="check-field"><input class="toggle toggle-primary toggle-sm" type="checkbox" data-field="wait" ${this.state.wait ? "checked" : ""}><span>等待任务完成</span></label></div></details>
      <div class="row"><button class="btn btn-primary" type="submit" ${this.state.loading ? "disabled" : ""}>${this.state.loading ? "请求中..." : "运行" + escapeHtml(SCENARIOS[this.state.scenario].title)}</button><button class="btn btn-outline" type="button" data-sample>载入样例</button></div>
      <div class="status-line ${this.state.tone ? `alert alert-soft ${this.state.tone === "error" ? "alert-error" : "alert-success"}` : ""}" data-tone="${this.state.tone}">${escapeHtml(this.state.status)}</div>
    </form>`;
  }

  renderSummary() {
    const rows = extractRows(this.state.data);
    const primitiveKey = SCENARIOS[this.state.scenario].primitiveResultKey || "value";
    const keys = rows ? unionKeys(rows, primitiveKey).length : isRecord(this.state.data) ? Object.keys(this.state.data).length : 1;
    const shape = rows ? (isRecord(rows.find((row) => row !== undefined && row !== null)) ? "对象数组" : "值列表") : Array.isArray(this.state.data) ? "数组" : isRecord(this.state.data) ? "对象" : typeName(this.state.data);
    return `<div class="stats summary-strip"><div class="stat metric"><span class="stat-title">结构</span><strong class="stat-value">${shape}</strong></div><div class="stat metric"><span class="stat-title">记录</span><strong class="stat-value">${rows ? rows.length : "—"}</strong></div><div class="stat metric"><span class="stat-title">字段</span><strong class="stat-value">${keys}</strong></div><div class="stat metric"><span class="stat-title">视图</span><strong class="stat-value">${this.state.view}</strong></div></div>`;
  }

  renderResultPanel() {
    const rows = extractRows(this.state.data);
    const primitiveKey = SCENARIOS[this.state.scenario].primitiveResultKey || "value";
    const downloadable = rows && (this.state.filter || this.state.sortKey
      ? visibleTableRows(rows, this.state.filter, this.state.sortKey, this.state.sortDir, primitiveKey).length > 0
      : rows.length > 0);
    let content = "";
    if (this.state.view === "table" && rows) content = renderTable(rows, this.state.filter, this.state.sortKey, this.state.sortDir, primitiveKey, this.state.tablePage, this.state.tablePageSize);
    else if (this.state.view === "tree") content = `<div class="panel-body">${renderTree(this.state.data)}</div>`;
    else content = `<pre class="raw-json">${escapeHtml(JSON.stringify(this.state.data, null, 2))}</pre>`;
    return `<section class="panel card bg-base-100 result-panel"><div class="panel-header"><div><p class="eyebrow">adaptive result</p><h2>查询结果</h2></div><div class="result-toolbar"><input class="input input-bordered input-sm" data-filter placeholder="筛选当前结果" value="${escapeHtml(this.state.filter)}"><div class="view-tabs tabs tabs-box tabs-sm" role="tablist">${["table", "tree", "raw"].map((view) => `<button class="view-tab tab ${this.state.view === view ? "tab-active" : ""}" type="button" data-view="${view}" aria-selected="${this.state.view === view}">${view === "table" ? "表格" : view === "tree" ? "树形" : "原始"}</button>`).join("")}</div>${downloadable ? '<button class="btn btn-outline btn-sm download-table" type="button" data-download-table title="下载当前筛选和排序后的 CSV 表格">下载 CSV</button>' : ""}</div></div>${this.renderSummary()}${content}</section>`;
  }

  renderHistory() {
    const records = this.state.history.map((record) => {
      const title = SCENARIOS[record.scenario].title;
      const time = new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(record.createdAt));
      const summary = summarizeHistoryParams(record.params);
      return `<button class="history-item" type="button" data-history-id="${escapeHtml(record.id)}" aria-label="重新载入 ${escapeHtml(title)} ${escapeHtml(record.site)}"><span class="history-item-head"><strong>${escapeHtml(title)}</strong><span class="tiny">${escapeHtml(record.site)} · ${escapeHtml(time)}</span></span><span class="history-summary" title="${escapeHtml(summary)}">${escapeHtml(summary)}</span></button>`;
    }).join("");
    return `<section class="history-panel" data-history-panel data-open="${this.state.historyOpen}"><button class="history-toggle btn btn-ghost" type="button" data-history-toggle aria-expanded="${this.state.historyOpen}"><span>历史查询 <span class="badge badge-sm">${this.state.history.length}</span></span><span aria-hidden="true">${this.state.historyOpen ? "-" : "+"}</span></button><div class="history-content" data-history-content>${records ? `<div class="history-list">${records}</div><button class="btn btn-ghost btn-xs history-clear" type="button" data-history-clear>清空历史</button>` : '<p class="history-empty">暂无查询记录</p>'}</div></section>`;
  }

  render() {
    const v = this.state.variant;
    let layout;
    if (v === "a") {
      layout = `<div class="variant-layout variant-a"><aside class="panel card bg-base-100 request-panel"><div class="panel-header"><div><p class="eyebrow">scenario & filters</p><h2>查询场景</h2></div><span class="badge badge-outline badge-sm">prototype</span></div><div class="panel-body">${this.renderRequestForm()}</div>${this.renderHistory()}</aside>${this.renderResultPanel()}</div>`;
    } else if (v === "b") {
      layout = `<div class="variant-layout variant-b"><section class="hero-strip"><div><p class="eyebrow">result-first workspace</p><h2>先看数据，再决定下一步。</h2><p>适合运营场景：查询配置收进顶部工具栏，结果占据主区域。</p></div><div class="hero-actions"><button class="btn btn-outline" type="button" data-sample>样例数据</button><button class="btn btn-primary" type="button" data-view="table">打开表格</button></div></section><section class="panel card bg-base-100"><div class="panel-body">${this.renderRequestForm(true)}</div>${this.renderHistory()}</section>${this.renderResultPanel()}</div>`;
    } else {
      const sourceRows = extractRows(this.state.data);
      const primitiveKey = SCENARIOS[this.state.scenario].primitiveResultKey || "value";
      const keys = isRecord(this.state.data) ? Object.keys(this.state.data) : unionKeys(sourceRows || [], primitiveKey);
      const fieldType = (key) => {
        if (isRecord(this.state.data)) return typeName(this.state.data[key]);
        const row = sourceRows?.find((item) => isRecord(item) ? key in item : key === primitiveKey);
        return typeName(tableValue(row, key, primitiveKey));
      };
      layout = `<div class="variant-layout variant-c"><section class="panel card bg-base-100 result-panel"><div class="panel-header"><div><p class="eyebrow">inspector view</p><h2>数据检查器</h2></div><div class="result-toolbar"><button class="btn btn-outline btn-sm" type="button" data-view="tree">展开树</button><button class="btn btn-outline btn-sm" type="button" data-view="raw">原始 JSON</button></div></div>${this.renderSummary()}<div class="panel-body">${this.state.view === "tree" ? renderTree(this.state.data) : this.state.view === "raw" ? `<pre class="raw-json">${escapeHtml(JSON.stringify(this.state.data, null, 2))}</pre>` : (sourceRows ? renderTable(sourceRows, this.state.filter, this.state.sortKey, this.state.sortDir, primitiveKey, this.state.tablePage, this.state.tablePageSize) : renderTree(this.state.data))}</div></section><aside class="flow-stack"><section class="panel card bg-base-100"><div class="panel-header"><div><p class="eyebrow">scenario & filters</p><h2>查询场景</h2></div></div><div class="panel-body">${this.renderRequestForm(true)}</div>${this.renderHistory()}</section><section class="panel card bg-base-100"><div class="panel-header"><h2>顶层字段</h2></div><div class="panel-body"><ul class="key-list">${keys.slice(0, 18).map((key) => `<li><span>${escapeHtml(key)}</span><strong>${escapeHtml(fieldType(key))}</strong></li>`).join("") || '<li>暂无字段</li>'}</ul></div></section></aside></div>`;
    }
    this.innerHTML = `<div class="shell"><header class="topbar navbar bg-base-100"><div class="brand"><div class="brand-mark">{ }</div><div><p class="eyebrow">HTML-first API explorer</p><h1>JSON Lens <span class="badge badge-outline badge-sm">prototype</span></h1></div></div><div class="header-tools"><div class="header-note">动态 JSON 结果 · 原生 Web Components<br>Variant ${v.toUpperCase()} · ${VARIANTS[v]}</div><label class="theme-switcher"><span>明亮</span><input class="toggle toggle-primary toggle-sm" type="checkbox" role="switch" aria-label="切换明暗主题" data-field="theme" ${this.state.theme === "business" ? "checked" : ""}><span>暗色</span></label></div></header><main class="workspace">${layout}</main><nav class="prototype-switcher join" aria-label="原型布局切换"><button class="btn btn-square btn-sm join-item" type="button" data-variant-direction="-1" title="上一个布局">←</button><span class="switcher-label join-item">${v.toUpperCase()} · ${VARIANTS[v]}</span><button class="btn btn-square btn-sm join-item" type="button" data-variant-direction="1" title="下一个布局">→</button></nav></div>`;
  }
}

customElements.define("json-lens-app", JsonLensApp);
