import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { getOpsAppDeployBase, loadOpsAppConfig } from "./ops-app-config.mjs";

const [configPath, templatePath, outputPath] = process.argv.slice(2);

if (!configPath || !templatePath || !outputPath) {
  throw new Error(
    "用法: node render-nginx-config.mjs <ops-app.config> <nginx.conf.template> <output>",
  );
}

// 生产 Nginx 配置不接受空应用 ID。
const config = loadOpsAppConfig(configPath, { requireAppId: true });
const template = readFileSync(resolve(templatePath), "utf8");
const rendered = template
  .replaceAll("${OPS_APP_ID}", config.appId)
  .replaceAll("${OPS_APP_NAME}", config.appName);

if (/\$\{OPS_[A-Z_]+\}/.test(rendered)) {
  throw new Error("Nginx 模板包含未解析的 OPS 变量");
}

const absoluteOutput = resolve(outputPath);
mkdirSync(dirname(absoluteOutput), { recursive: true });
writeFileSync(absoluteOutput, rendered, "utf8");

console.log(
  JSON.stringify({
    success: true,
    output: absoluteOutput,
    deployBase: getOpsAppDeployBase(config),
  }),
);
