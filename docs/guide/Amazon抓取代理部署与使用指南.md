# Amazon 抓取代理部署与使用指南

> 适用模块：`opscli/amazon`（`opscli amazon scrape / search / payload`）
> 适用版本：v0.0.108+（含代理注入、反检测重试、扩展字段采集）
> 面向读者：运维部署人员、opscli 使用方

---

## 一、为什么需要代理（问题背景）

`opscli amazon` 通过 Playwright 驱动 Chromium 抓取 Amazon 商品页。抓取服务当前部署在**阿里云服务器**上，而阿里云对外出口是**数据中心 IP 段（Datacenter IP）**。

Amazon 的 Bot 检测体系中，**来源 IP 的信誉是第一权重**：

- 数据中心 IP（阿里云、腾讯云、AWS、GCP 等）被 Amazon 标记为高风险；
- 命中后表现为：跳转到 `Continue shopping` 中间验证页、重定向到首页、`Sorry` 拒绝页、或返回空白商品数据；
- **浏览器指纹伪装（UA、stealth）无法解决 IP 层的封禁** —— 指纹做得再真，机房 IP 一旦被判定为高风险，依然被拦。

因此，绕过拦截的**根因手段只有一个方向：把抓取请求的出口 IP 从"数据中心"换成"住宅 / 移动 IP"（Residential / Mobile IP）**。这正是代理要解决的问题。

> 结论先行：**代理服务端必须以住宅 / 移动 IP 作为最终出口，抓取才有效。** 单纯再买一台海外 VPS 做代理没用 —— 那仍然是数据中心 IP，Amazon 照样封。

---

## 二、整体链路

```
                          ┌─────────────────────────────┐
                          │   opscli amazon (阿里云服务器)  │
                          │   Chromium + Playwright      │
                          └──────────────┬──────────────┘
                                         │  ① 请求经代理转发
                                         │  （config.ini / 环境变量指定）
                                         ▼
                          ┌─────────────────────────────┐
                          │      代理服务端 (Proxy)        │
                          │  HTTP(S) 代理，带账号密码鉴权   │
                          └──────────────┬──────────────┘
                                         │  ② 从住宅 / 移动 IP 出口
                                         ▼
                          ┌─────────────────────────────┐
                          │        住宅 / 移动 出口 IP      │
                          │  （家宽 / 4G / 商业住宅代理池）  │
                          └──────────────┬──────────────┘
                                         │  ③ 以"真实用户 IP"访问
                                         ▼
                          ┌─────────────────────────────┐
                          │          amazon.com          │
                          └─────────────────────────────┘
```

opscli 侧只关心 **①**：把 `proxy_server / proxy_username / proxy_password` 配好即可。
出口是不是住宅 IP，取决于你在 **②③** 采用哪种代理方案（见第三节）。

---

## 三、代理方案选型（服务端形态）

按落地成本与稳定性，从推荐到不推荐排列：

| 方案 | 是否需自建服务端 | 出口 IP 类型 | 稳定性 | 成本 | 说明 |
| ---- | ---- | ---- | ---- | ---- | ---- |
| **A. 商业住宅代理** | 否（供应商已托管） | 住宅 / 移动 | 高 | 按流量/IP 计费 | **最省事、最推荐**。直接拿到网关地址即可用 |
| **B. 自建转发 + 住宅出口** | 是 | 取决于出口线路 | 中 | 低（有现成住宅线路时） | 你有家宽 / 海外住宅节点 / 4G 卡池时才有意义 |
| **C. 官方 PA-API（非代理）** | 否 | 无（走官方接口） | 最高 | 需卖家/联盟资质 | 最合规、无封禁，但不是网页抓取，字段口径不同 |

> ❗ 不推荐的做法：买一台普通海外 VPS（DigitalOcean / Vultr / 阿里云香港等）自己搭 HTTP 代理。VPS 出口仍是**数据中心 IP**，Amazon 一样封，白费功夫。

---

## 四、方案 A：商业住宅代理（推荐，无需自建）

### 4.1 选择供应商

主流商业住宅 / 移动代理供应商（自行评估合规与预算）：

- Bright Data（亮数据）、Oxylabs、Decodo（原 Smartproxy）、IPRoyal、Soax 等。

> 注意：很多国内"高匿代理""IP 池"卖的是**数据中心 IP**，对 Amazon 无效。选购时务必确认是 **Residential / Mobile** 类型。

### 4.2 拿到网关信息

商业住宅代理通常给你一个**统一网关（gateway）地址 + 账号密码**，由供应商负责在后端轮换真实住宅出口。你会拿到类似：

```
入口地址(host):   gate.provider.com
端口(port):        8000
用户名(username):  brd-customer-xxx-zone-residential
密码(password):    xxxxxxxx
```

两种出口策略（供应商侧配置，通常体现在用户名或端口上）：

- **Rotating（轮换）**：每次请求换一个出口 IP —— 适合大批量、彼此独立的抓取。
- **Sticky（会话保持）**：同一会话固定一个出口 IP 几分钟 —— 适合需要设邮编、翻页等有状态流程。

opscli 单次抓商品是完整的一个浏览器上下文，两种都可用；**建议优先 Sticky**，避免设邮编后 IP 变化导致价格口径漂移。

### 4.3 填入 opscli（见第六节）

把 host/port/username/password 填进 `config.ini` 或环境变量即可，无需任何服务端部署。

---

## 五、方案 B：自建转发代理服务端

**前提：你必须已经拥有一个住宅 / 移动出口线路**，例如：

- 公司/家里的家宽路由器（可做端口转发或反向隧道）；
- 海外住宅宽带上的一台小主机；
- 4G/5G 上网卡组成的卡池主机。

自建的本质是：在**住宅出口机器**上跑一个带鉴权的 HTTP 代理，opscli 连它。下面给两种常见实现。

> ⚠️ 协议限制：opscli 底层是 Chromium，**Chromium 不支持 SOCKS5 的用户名/密码鉴权**。因此自建代理请用 **HTTP(S) 代理 + Basic Auth**，不要用带账号密码的 socks5。

### 5.1 用 3proxy 部署（轻量，推荐）

在**住宅出口主机**上安装 3proxy：

```bash
# Debian/Ubuntu 示例
sudo apt update && sudo apt install -y 3proxy || {
  # 无仓库时源码编译
  git clone https://github.com/3proxy/3proxy.git
  cd 3proxy && make -f Makefile.Linux && sudo make -f Makefile.Linux install
}
```

配置文件 `/etc/3proxy/3proxy.cfg`：

```conf
# 日志与 DNS
nserver 8.8.8.8
nscache 65536
timeouts 1 5 30 60 180 1800 15 60

# 鉴权：用户名 opscli / 密码 ChangeMe_Strong#2026（务必改成强密码）
users opscli:CL:ChangeMe_Strong#2026
auth strong

# 仅允许上面的用户使用，禁止匿名
allow opscli

# HTTP 代理，监听 8000 端口
proxy -n -a -p8000

# 关闭其它服务
flush
```

用 systemd 托管 `/etc/systemd/system/3proxy.service`：

```ini
[Unit]
Description=3proxy residential HTTP proxy
After=network-online.target

[Service]
ExecStart=/usr/local/bin/3proxy /etc/3proxy/3proxy.cfg
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now 3proxy
sudo systemctl status 3proxy
```

### 5.2 用 Gost 部署（可选，一行起服务）

Gost（GO Simple Tunnel）适合快速起代理：

```bash
# 下载对应平台二进制后
# v2 语法：HTTP 代理 + Basic Auth，监听 8000
gost -L "http://opscli:ChangeMe_Strong#2026@:8000"
```

systemd 版 `/etc/systemd/system/gost.service`：

```ini
[Unit]
Description=gost residential HTTP proxy
After=network-online.target

[Service]
ExecStart=/usr/local/bin/gost -L "http://opscli:ChangeMe_Strong#2026@:8000"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### 5.3 防火墙与安全

代理端口**绝不能对公网裸奔**（会被扫描滥用）。二选一：

- **白名单放行**：只允许阿里云抓取服务器的公网 IP 访问代理端口：

  ```bash
  # 以 ufw 为例，仅放行抓取服务器 IP <OPSCLI_SERVER_IP>
  sudo ufw allow from <OPSCLI_SERVER_IP> to any port 8000 proto tcp
  sudo ufw deny 8000
  ```

- **走内网隧道**：用 WireGuard / SSH 隧道把代理端口只暴露在私有网络里，opscli 连隧道内地址。

务必：① 强密码；② 只放行需要的来源 IP；③ 定期查代理访问日志。

### 5.4 专题：买了"家庭 IP VPS"自建代理，到底有没有意义？

很多人会买号称"家庭 IP / 住宅 IP"的 VPS 来自建代理。**结论：只要那台 VPS 的 IP 确实是住宅 ISP 类型，就是有效的**——因为 Amazon 判风险看的是"这个 IP 是不是住宅"，而不看这台机器是云服务器还是家用电脑。但它相比商业住宅代理池有本质短板：**单一静态 IP、没有轮换**。

#### 5.4.1 前提：先验证它是不是"真住宅 IP"

市面上大量"住宅 VPS"其实是**机房 IP 套了个住宅样子的反向 DNS**，或早已被风控库（MaxMind、IPQualityScore 等）标记为 hosting 的 IP 段。买之前 / 到手后**必须验证**：

```bash
# 在这台 VPS 上执行，查它出口 IP 的类型
curl https://ipinfo.io/json
# 重点看 org / 类型：应是某个 ISP / 电信运营商（residential），
# 而不是 Alibaba / Amazon / DigitalOcean / Hosting / Datacenter
```

再用 `scamalytics.com` 或 `ipqualityscore.com` 查该 IP 的 fraud score、是否被标记为 proxy / datacenter。**只要显示 datacenter / hosting，就等于白买，Amazon 照封。**

#### 5.4.2 它的上限：单 IP，不耐"量"

| 维度 | 家庭 IP VPS（单 IP） | 商业住宅代理池 |
| ---- | ---- | ---- |
| IP 数量 | 1 个静态 | 成千上万，自动轮换 |
| 低频抓取（每天几十~几百次） | 够用 | 够用 |
| 高频 / 批量抓取 | 单 IP 很快被盯上、限流甚至封 | 轮换分摊风险，抗封 |
| 成本 | 固定月租，量稳定时更划算 | 按流量 / IP 计费，量大更贵 |
| IP 是否可能被前住户用脏 | 有风险（共享 / 回收 IP） | 供应商管理，相对干净 |

一句话：**低频、稳定量的抓取用它划算；一旦要上量，单 IP 扛不住，仍需住宅代理池。**

#### 5.4.3 更省事的用法：能直接跑就别搭代理

如果这台住宅 VPS 性能够跑 Chromium（约需 1GB+ 内存），**你不一定需要搭代理**：

- **方案 A（最简，推荐）**：把 opscli 抓取服务**直接部署在这台住宅 VPS 上**运行。它自身出口就是住宅 IP，`[amazon]` 段**无需配置 proxy**——链路最短、少一层故障点、也不用管防火墙鉴权。
- **方案 B（分离）**：抓取算力仍留在阿里云，住宅 VPS 只当代理出口——这时才需要按 5.1~5.3 在 VPS 上搭 3proxy / gost，阿里云的 opscli 连它。

**决策：能在这台 VPS 上直接跑抓取，就选方案 A**；只有当算力必须集中在阿里云（与其它服务耦合、资源不够等）时，才用方案 B 把它当纯代理。

#### 5.4.4 落地建议（顺序执行）

1. 按 5.4.1 验证 IP **确为住宅类型**，是脏 IP 或机房 IP 就别买；
2. 确认后，**能直接在 VPS 上跑 opscli 就走方案 A**（不配代理）；
3. 控制频率（单 IP 别猛抓），配合内置的退避重试（`max_retries`）；
4. 抓取量要上规模时，再升级到商业住宅代理池。

---

## 六、客户端（opscli）配置

opscli 侧读取优先级：**环境变量 `OPSCLI_AMAZON_*` > `~/.config/opscli/config.ini [amazon]` 段 > 内置默认（不使用代理）**。

### 6.1 方式一：config.ini（推荐用于服务器常驻）

编辑 `~/.config/opscli/config.ini`（没有就新建），加入 `[amazon]` 段：

```ini
[amazon]
; 代理入口地址，必须带协议头；Chromium 支持 http/https，socks5 不支持账号密码
proxy_server = http://gate.provider.com:8000
; 代理鉴权账号密码（无鉴权代理可留空/删除这两行）
proxy_username = opscli
proxy_password = ChangeMe_Strong#2026
; 命中拦截时的最大尝试次数（含首次），范围 1~6，默认 3
max_retries = 3
; 是否无头模式，服务器无显示器保持 true
headless = true
```

> 安全建议：`chmod 600 ~/.config/opscli/config.ini`，避免密码被同机其他用户读取；该文件**不要提交到 git**。

### 6.2 方式二：环境变量（推荐用于容器 / CI）

```bash
export OPSCLI_AMAZON_PROXY_SERVER="http://gate.provider.com:8000"
export OPSCLI_AMAZON_PROXY_USERNAME="opscli"
export OPSCLI_AMAZON_PROXY_PASSWORD="ChangeMe_Strong#2026"
export OPSCLI_AMAZON_MAX_RETRIES="3"
export OPSCLI_AMAZON_HEADLESS="true"
```

### 6.3 配置项对照表

| config.ini `[amazon]` | 环境变量 | 默认值 | 说明 |
| ---- | ---- | ---- | ---- |
| `proxy_server` | `OPSCLI_AMAZON_PROXY_SERVER` | 空（不使用代理） | 代理入口，如 `http://host:8000`。**为空则走本机出口** |
| `proxy_username` | `OPSCLI_AMAZON_PROXY_USERNAME` | 空 | 代理账号；为空表示免鉴权代理 |
| `proxy_password` | `OPSCLI_AMAZON_PROXY_PASSWORD` | 空 | 代理密码 |
| `max_retries` | `OPSCLI_AMAZON_MAX_RETRIES` | 3 | 命中拦截时换指纹重试次数，1~6 |
| `headless` | `OPSCLI_AMAZON_HEADLESS` | true | 无头模式；服务器保持 true |

> `proxy_server` 为空时，opscli **默认不使用代理**（即走阿里云本机出口）——这也是不配置时会被封的原因。

---

## 七、验证与使用

### 7.1 先验证代理本身可用

在抓取服务器上，用 curl 直连代理确认出口 IP 已是住宅/非机房：

```bash
# 通过代理查询出口 IP
curl -x http://opscli:ChangeMe_Strong#2026@gate.provider.com:8000 https://api.ipify.org
# 再查这个 IP 的类型（应为 ISP/住宅，而非 Datacenter/Hosting）
curl https://ipinfo.io/<上一步返回的IP>/json
```

### 7.2 用 opscli 抓取验证

```bash
# 安装抓取依赖（首次）
pip install "aukeys-opscli[amazon]"
playwright install chromium

# 抓取单个商品（含扩展字段）
opscli amazon scrape --asin B08N5WRWNW --include-raw --pretty
```

期望：返回 `"valid": true`，且包含 `brand / bullet_points / images / best_sellers_rank / categories` 等扩展字段。

若返回 `"valid": false` 且 `error` 含"Bot 检测/首页/人机验证"，说明仍被拦，转第八节排查。

### 7.3 采集到的完整字段

v0.0.108 起，`opscli amazon scrape` 在原有标题/价格/评分/评论数/位置基础上，新增：

| 字段 | 含义 |
| ---- | ---- |
| `brand` | 品牌 |
| `availability` | 库存状态（In Stock / Only N left 等） |
| `bullet_points` | 五点描述（feature bullets 列表） |
| `description` | 商品文字描述 |
| `images` | 商品图片 URL 列表（主图 + 缩略图，已还原大图） |
| `best_sellers_rank` | Best Sellers Rank 原始文本 |
| `categories` | 面包屑类目路径 |
| `delivery_info` | 配送信息 |
| `ships_from` | 发货方 |
| `sold_by` | 卖家 |
| `coupon` | 优惠券文案 |

完整结构可用 `opscli amazon schema --pretty` 查看。

---

## 八、排错清单

| 现象 | 可能原因 | 处理 |
| ---- | ---- | ---- |
| `error` 含"Bot 检测/重定向到首页" | 出口仍是机房 IP，或该住宅 IP 已被封 | 确认代理出口为住宅（7.1）；启用 Rotating 或换 IP 池；提高 `max_retries` |
| curl 走代理超时 | 代理端口未放行 / 服务未启动 | 检查 3proxy/gost 状态、防火墙白名单是否含抓取服务器 IP |
| 代理 407 Proxy Authentication Required | 账号密码错 / 用了 socks5 带鉴权 | 核对账号密码；改用 http(s) 代理（Chromium 不支持 socks5 鉴权） |
| 价格/邮编口径漂移 | Rotating 代理每请求换 IP | 改用 Sticky 会话保持代理 |
| `ScraperDependencyError` | 未装 playwright / chromium | `pip install "aukeys-opscli[amazon]" && playwright install chromium` |
| 扩展字段大量为空但 valid=true | 页面版式差异 / A+ 懒加载 | 属正常，扩展字段为尽力采集；核心字段有效即算成功 |

---

## 九、合规与运维注意

- **遵守 Amazon 服务条款与当地法律**：仅抓取公开商品信息，控制频率，不做高并发压测式抓取。
- **限速**：为出口 IP 保寿命，控制单位时间抓取量；`max_retries` 不宜设过大。
- **凭证保护**：代理账号密码只存 `config.ini`（600 权限）或密钥管理，禁止入库、禁止硬编码。
- **长期方案建议**：若为长期、稳定、大规模需求，优先评估 **Amazon 官方 PA-API**（合规、无封禁、结构化字段），网页抓取作为兜底通道。

---

## 附：与代码的对应关系

| 能力 | 代码位置 |
| ---- | ---- |
| 代理 / 反检测配置读取 | `opscli/amazon/config.py` |
| 代理注入、随机指纹、stealth、退避重试 | `opscli/amazon/scraping/scraper.py`（`AmazonScraper`） |
| 扩展字段模型 | `opscli/amazon/domain/models.py`（`AmazonProductSnapshot`） |
| CLI 命令 | `opscli/amazon/commands/cli.py`（`scrape / search / payload / schema / history`） |
