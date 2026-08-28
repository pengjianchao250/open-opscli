import assert from "node:assert/strict";
import test from "node:test";

import { tableCsv, tableKeys, visibleTableRows } from "../table-utils.js";

const rows = [
  { asin: "B02", title: "很长的商品名称", tags: ["usb-c", "charger"] },
  { asin: "B01", title: "Short", tags: [] },
];

test("表格字段按首次出现顺序合并", () => {
  assert.deepEqual(tableKeys(rows), ["asin", "title", "tags"]);
});

test("字符串数组可映射为指定业务字段", () => {
  assert.deepEqual(tableKeys(["APZB0IDP1EYQW", "A2BA4D4U3M3NVW"], "sellerId"), ["sellerId"]);
});

test("下载数据沿用当前筛选和排序", () => {
  const visible = visibleTableRows(rows, "B0", "asin", 1).map(({ row }) => row.asin);
  assert.deepEqual(visible, ["B01", "B02"]);
});

test("CSV 保留中文并序列化复杂字段", () => {
  const csv = tableCsv(rows);
  assert.ok(csv.startsWith("\uFEFF"));
  assert.match(csv, /很长的商品名称/);
  assert.match(csv, /""usb-c"",""charger""/);
});

test("字符串列表按业务字段导出 CSV", () => {
  const csv = tableCsv(["APZB0IDP1EYQW", "A2BA4D4U3M3NVW"], ["sellerId"], "sellerId");
  assert.match(csv, /^\uFEFF"sellerId"/);
  assert.match(csv, /"APZB0IDP1EYQW"/);
});

test("CSV 防止单元格公式注入", () => {
  assert.match(tableCsv([{ value: "=1+1" }]), /"'=1\+1"/);
});
