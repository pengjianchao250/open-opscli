import assert from "node:assert/strict";
import test from "node:test";

import { buildRequestHeaders } from "../request-contract.js";

test("API Key 会被归一化为 Bearer Authorization", () => {
  assert.equal(buildRequestHeaders("Authorization: Bearer test-key").Authorization, "Bearer test-key");
  assert.equal(buildRequestHeaders("Bearer test-key").Authorization, "Bearer test-key");
  assert.equal(buildRequestHeaders("test-key").Authorization, "Bearer test-key");
});

test("空 API Key 不发送 Authorization", () => {
  assert.deepEqual(buildRequestHeaders(""), { "Content-Type": "application/json" });
});
