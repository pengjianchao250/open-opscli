# CLI 升级指南

> 适用版本：aukeys-opscli >= 0.0.140
> 文档日期：2026-07-16

## 一键升级（推荐）

```bash
opscli self-update
```

该命令自动完成三件事：

1. 识别当前安装方式（uv tool / pipx / pip），执行对应升级命令
2. 升级完成后自动执行 `opscli skills install --force`（刷新内置 Skill 模板）
3. 自动执行 `opscli skills upgrade`（拉取远端最新 Skill 数据）

已是最新版本时输出 `√ 已是最新版本` 并直接退出，可放心重复执行。

## 手动升级（备用）

按你的安装方式选择其一：

| 安装方式 | 升级命令 |
|---|---|
| uv tool | `uv tool upgrade aukeys-opscli` |
| pipx | `pipx upgrade aukeys-opscli` |
| pip | `pip install --upgrade --only-binary :all: aukeys-opscli` |

手动升级后必须补两条命令：

```bash
opscli skills install --force
opscli skills upgrade
```

## 常见问题

### 提示找不到二进制包（no matching distribution / wheel）

opscli 以预编译二进制 wheel 分发（不支持源码编译安装）。出现该提示说明
当前平台或 Python 版本暂未提供预编译包，请将 `opscli self-update` 输出的
平台信息（系统 / 架构 / Python 版本）反馈给维护者。

### 升级成功但 skills 同步失败

CLI 本体已是新版本，只需手动重试失败的那条命令：

```bash
opscli skills install --force   # 或 opscli skills upgrade
```

### 如何确认升级成功

```bash
opscli --version
```
