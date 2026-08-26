export interface OpsAppConfig {
  readonly schemaVersion: 1;
  readonly projectId: string | null;
  readonly appName: string;
}

export interface LoadOpsAppConfigOptions {
  readonly requireProjectId?: boolean;
}

/** 读取并校验唯一的 OPS 应用配置。 */
export function loadOpsAppConfig(
  configPath: string,
  options?: LoadOpsAppConfigOptions,
): OpsAppConfig;

/** 从已校验配置派生唯一部署前缀。 */
export function getOpsAppDeployBase(config: OpsAppConfig): string;

/** 派生前后端镜像名；仓库部分统一转为小写。 */
export function getOpsAppImageName(
  config: OpsAppConfig,
  service: "frontend" | "backend",
  tag?: string,
): string;
