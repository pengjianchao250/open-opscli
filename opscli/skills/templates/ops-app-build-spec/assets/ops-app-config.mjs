import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const APP_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const APP_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
const IMAGE_SERVICE_PATTERN = /^(frontend|backend)$/;
const IMAGE_TAG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

/** 读取并校验唯一的 OPS 应用配置。 */
export function loadOpsAppConfig(configPath, options = {}) {
  const absolutePath = resolve(configPath);
  const config = JSON.parse(readFileSync(absolutePath, "utf8"));

  if (config.schemaVersion !== 1) {
    throw new Error("ops-app.config schemaVersion 必须为 1");
  }
  if (!APP_NAME_PATTERN.test(config.appName ?? "")) {
    throw new Error("ops-app.config appName 必须是小写字母、数字和连字符组成的 URL 安全名称");
  }

  const appId = config.appId;
  if (appId == null && !options.requireAppId) {
    return Object.freeze({ schemaVersion: 1, appId: null, appName: config.appName });
  }
  if (typeof appId !== "string" || !APP_ID_PATTERN.test(appId)) {
    throw new Error("ops-app.config appId 必须是非空 URL 安全单路径段");
  }

  return Object.freeze({ schemaVersion: 1, appId, appName: config.appName });
}

/** 从已校验配置派生唯一公开 URL 前缀。 */
export function getOpsAppDeployBase(config) {
  if (!config.appId) {
    throw new Error("生成公开 URL 前必须取得 appId");
  }
  return `/ops-app/${config.appId}/${config.appName}/`;
}

/** 派生前后端镜像名；仓库部分统一转为小写。 */
export function getOpsAppImageName(config, service, tag = "latest") {
  if (!config.appId) {
    throw new Error("生成镜像名之前必须取得 appId");
  }
  if (!IMAGE_SERVICE_PATTERN.test(service)) {
    throw new Error("镜像服务只能是 frontend 或 backend");
  }
  if (!IMAGE_TAG_PATTERN.test(tag)) {
    throw new Error("镜像 tag 不是合法格式");
  }

  const repository = `${config.appId}-${config.appName}-${service}`.toLowerCase();
  return `${repository}:${tag}`;
}
