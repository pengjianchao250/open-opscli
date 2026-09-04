import assert from "node:assert/strict";
import test from "node:test";

import { formatMatrixValue, matrixCsv, resultSheets, visibleMatrixRows } from "../result-utils.js";

const workbook = {
  schema_version: "2.0",
  sheet_name: "Main",
  columns: ["关键词", "流量占比", "搜索量"],
  number_formats: [null, "0.00%", "#,##0"],
  rows: [["charger", 0.125, 12000], ["cable", 0.08, 24000]],
  additional_sheets: [{ name: "Unique Words", columns: ["词根"], rows: [["charger"]], number_formats: [null] }],
};

test("JSON v2 会保留主表与辅助工作表的矩阵合同", () => {
  const sheets = resultSheets(workbook);
  assert.equal(sheets.length, 2);
  assert.deepEqual(sheets[0].columns, ["关键词", "流量占比", "搜索量"]);
  assert.deepEqual(sheets[1].rows, [["charger"]]);
});

test("普通对象数组仍可转换为表格", () => {
  const [sheet] = resultSheets([{ asin: "B012345678", sales: 100 }]);
  assert.deepEqual(sheet.columns, ["asin", "sales"]);
  assert.deepEqual(sheet.rows, [["B012345678", 100]]);
});

test("矩阵筛选排序和 CSV 导出保持重复表头能力", () => {
  const [sheet] = resultSheets(workbook);
  const visible = visibleMatrixRows(sheet, "a", 2, -1);
  assert.deepEqual(visible.map(({ row }) => row[0]), ["cable", "charger"]);
  const csv = matrixCsv({ ...sheet, columns: ["关键词", "关键词", "搜索量"] }, visible.map(({ row }) => row));
  assert.match(csv, /^\uFEFF"关键词","关键词","搜索量"/);
});

test("数字格式用于百分比和千分位显示", () => {
  assert.equal(formatMatrixValue(0.125, "0.00%"), "12.5%");
  assert.equal(formatMatrixValue(12000, "#,##0"), "12,000");
});
