import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { getOpsAppDeployBase, loadOpsAppConfig } from "./ops-app-config.mjs";

const [configPath, templatePath, outputPath] = process.argv.slice(2);

if (!configPath || !templatePath || !outputPath) {
  throw new Error(
    "用法: node render-nginx-config.mjs <ops-app.config> <nginx.conf.template> <output>",
  );
}

// 生产构建仍需校验应用身份，但 Nginx 不消费公开路径。
const config = loadOpsAppConfig(configPath, { requireAppId: true });
const rendered = readFileSync(resolve(templatePath), "utf8");

if (/\$\{OPS_[A-Z_]+\}/.test(rendered)) {
  throw new Error("根路径 Nginx 模板不得包含 OPS 变量");
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
