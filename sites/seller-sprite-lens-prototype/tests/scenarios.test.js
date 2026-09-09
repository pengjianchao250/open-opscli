import assert from "node:assert/strict";
import test from "node:test";

import { buildScenarioParams, monthlyPeriodOptions, periodOptionsForScenario, scenarioPeriod, SCENARIO_GROUPS, SCENARIOS } from "../scenarios.js";

test("一期导航只开放 13 个 JSON 场景", () => {
  const exposed = SCENARIO_GROUPS.flatMap((group) => group.scenarios);
  assert.equal(exposed.length, 13);
  assert.ok(!exposed.includes("listing-analysis"));
  assert.ok(!exposed.includes("branddb"));
  assert.ok(!exposed.includes("aba-reverse"));
  assert.ok(exposed.every((scenario) => SCENARIOS[scenario]));
});

test("月份型周期从最近30天开始并列出官网最近 25 个已发布月份", () => {
  const options = monthlyPeriodOptions(new Date(2026, 8, 4));
  assert.deepEqual(options.slice(0, 4), [
    ["30d", "最近30天"],
    ["2026-07", "2026-07"],
    ["2026-06", "2026-06"],
    ["2026-05", "2026-05"],
  ]);
  assert.equal(options.length, 26);
  assert.deepEqual(options.at(-1), ["2024-07", "2024-07"]);
});

test("场景周期遵循官网支持范围", () => {
  const now = new Date(2026, 8, 4);
  assert.deepEqual(periodOptionsForScenario("product-research", now).slice(0, 2), [
    ["30d", "最近30天"],
    ["2026-07", "2026-07"],
  ]);
  assert.deepEqual(periodOptionsForScenario("aba-research", now).slice(0, 2), [
    ["30d", "最近完整周"],
    ["2026-07", "2026-07"],
  ]);
  assert.deepEqual(periodOptionsForScenario("keyword-conversion-rate", now), [["W", "按周"], ["90D", "近 90 天"]]);
  assert.deepEqual(periodOptionsForScenario("real-time-bidding", now), []);
  assert.equal(scenarioPeriod("product-research", "2026-07", now), "2026-07");
  assert.equal(scenarioPeriod("product-research", "2020-01", now), "30d");
});

test("关键词反查校验 ASIN 并构造布尔参数", () => {
  assert.throws(() => buildScenarioParams("keyword-reverse", { asin: "bad" }), /10 位 ASIN/);
  assert.deepEqual(buildScenarioParams("keyword-reverse", {
    asin: "B012345678",
    includeHighFrequency: true,
    exactly: "false",
  }), {
    asin: "B012345678",
    exactly: false,
    includeHighFrequency: true,
  });
});

test("选产品支持官网筛选和高级 JSON 覆盖", () => {
  assert.deepEqual(buildScenarioParams("product-research", {
    recommendationMode: "新手推荐",
    sellerTypes: "FBA, FBM",
    minPrice: "15",
    maxPrice: "60",
  }, '{"maxReviews":50}'), {
    recommendationMode: "新手推荐",
    sellerTypes: ["FBA", "FBM"],
    minPrice: 15,
    maxPrice: 60,
    maxReviews: 50,
  });
});

test("多 ASIN 场景限制数量和格式", () => {
  assert.deepEqual(buildScenarioParams("traffic-extend", {
    asins: "B012345678\nB087654321",
    variantSelection: "all",
  }), {
    asins: ["B012345678", "B087654321"],
    variantSelection: "all",
  });
  assert.throws(() => buildScenarioParams("keyword-comparison", {
    ownAsin: "B012345678",
    competitorAsins: "invalid",
  }), /无效 ASIN/);
});

test("13 个公开场景都能构造最小合法参数", () => {
  const cases = {
    "product-research": {},
    "market-research": {},
    "competitor-lookup": { keyword: "charger" },
    "aba-research": { q: "charger" },
    "keyword-miner": { keyword: "charger" },
    "keyword-research": {},
    "keyword-reverse": { asin: "B012345678" },
    "traffic-source": { keywordOrAsin: "charger" },
    "traffic-extend": { asins: "B012345678" },
    "association-traffic": { asins: "B012345678" },
    "keyword-comparison": { ownAsin: "B012345678", competitorAsins: "B087654321" },
    "keyword-conversion-rate": { keywords: "usb c charger\nphone charger" },
    "real-time-bidding": { asin: "B012345678" },
  };
  const exposed = SCENARIO_GROUPS.flatMap((group) => group.scenarios);
  assert.deepEqual(Object.keys(cases).sort(), exposed.toSorted());
  for (const scenario of exposed) assert.doesNotThrow(() => buildScenarioParams(scenario, cases[scenario]));
});
