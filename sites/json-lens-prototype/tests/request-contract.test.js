import assert from "node:assert/strict";
import test from "node:test";

import { buildRequestHeaders } from "../request-contract.js";

test("纯 API Key 会生成 Bearer Authorization", () => {
  assert.deepEqual(buildRequestHeaders("opscli-mcp-test-key"), {
    "Content-Type": "application/json",
    Authorization: "Bearer opscli-mcp-test-key",
  });
});

test("完整 Bearer 值不会被重复拼接", () => {
  assert.equal(
    buildRequestHeaders("Bearer opscli-mcp-test-key").Authorization,
    "Bearer opscli-mcp-test-key",
  );
});

test("完整 Authorization 头文本会被归一化", () => {
  assert.equal(
    buildRequestHeaders("Authorization: Bearer opscli-mcp-test-key").Authorization,
    "Bearer opscli-mcp-test-key",
  );
});

test("空 API Key 不发送 Authorization", () => {
  assert.deepEqual(buildRequestHeaders("  "), {
    "Content-Type": "application/json",
  });
});
