import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const APP_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const PROJECT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;

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

  const projectId = config.projectId;
  if (projectId == null && !options.requireProjectId) {
    return Object.freeze({ schemaVersion: 1, projectId: null, appName: config.appName });
  }
  if (typeof projectId !== "string" || !PROJECT_ID_PATTERN.test(projectId)) {
    throw new Error("ops-app.config projectId 必须是非空 URL 安全单路径段");
  }

  return Object.freeze({ schemaVersion: 1, projectId, appName: config.appName });
}

/** 从已校验配置派生唯一部署前缀。 */
export function getOpsAppDeployBase(config) {
  if (!config.projectId) {
    throw new Error("生产构建前必须取得 projectId");
  }
  return `/ops-app/${config.projectId}/${config.appName}/`;
}
