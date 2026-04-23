# 通用 Skill 版本控制架构

> **定位：** 可复用的架构模式文档。描述"本地缓存 + 显式版本发布 + 多层级更新触发"的通用设计，供后续同类 Skill 快速落地。

---

## 核心思想

> **不追求实时，追求可控；不只被动等待，也能主动触发。**

当 AI/Skill 需要检索结构化业务数据时，在本地维护有版本号的数据快照，配合显式发布机制，通过三层更新触发机制（自动静默 / CLI 主动 / 脚本直接）实现**离线可用 + 受控同步 + 随时可刷新**的平衡。

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                       服务端（Server）                         │
│                                                              │
│  GET  /{resource}/skill/manifest   版本元数据（轻量）          │
│  GET  /{resource}/skill/export     流式下载数据文件            │
│  POST /{resource}/skill/publish    管理员发布新版本             │
│                                                              │
│  版本存储：system_constant 表                                  │
│  key: SKILL_{RESOURCE}_MANIFEST                              │
│  value: {"version":"vX.Y.Z","field_count":N,...}             │
└──────────────────────────┬───────────────────────────────────┘
                           │  HTTP（JWT Bearer）
              ┌────────────┴────────────┐
              │                         │
┌─────────────▼──────┐    ┌─────────────▼──────────────────────┐
│   opscli 工具       │    │        客户端 Skill（Python）         │
│                    │    │                                     │
│  skills list       │    │  updater.py   版本检查 + 下载         │
│  skills status     │    │  core.py      索引 + 自动更新         │
│  skills upgrade    │    │  search.py    CLI 搜索入口            │
│                    │    │                                     │
│  扫描 .claude/skills│    │  data/VERSION.json  本地版本         │
│  并行触发批量更新    │    │  data/{name}.csv    数据缓存          │
└────────────────────┘    └─────────────────────────────────────┘
```

---

## 三层更新机制

```
┌────────────────────────────────────────────────────────────────┐
│  Layer 1   自动静默更新                                          │
│            触发：Skill 被调用时（import core 时）                 │
│            特点：完全无感知，失败降级本地缓存                       │
│            场景：日常使用                                        │
├────────────────────────────────────────────────────────────────┤
│  Layer 2   opscli 主动更新                                      │
│            触发：opscli skills upgrade                          │
│            特点：格式化进度输出，批量管理，可集成 CI/CD            │
│            场景：版本发布后需立即同步；多 Skill 统一维护            │
├────────────────────────────────────────────────────────────────┤
│  Layer 3   updater.py 直接更新                                  │
│            触发：python3 scripts/updater.py                     │
│            特点：单个 Skill 精细控制，支持 --force                │
│            场景：开发调试；修复损坏 CSV                           │
└────────────────────────────────────────────────────────────────┘
```

---

## 关键设计决策

### 决策 1：Pull 模式 + 显式版本发布

**DB 变更不自动触发更新**，由管理员主动执行 `POST /skill/publish`，客户端通过 Pull 主动拉取。

- **为什么：** 避免高频小改动引发频繁全量同步；发布时机人工可控，更稳定
- **权衡：** 管理员需要额外一步操作；版本略滞后于实际数据

### 决策 2：CLI 工具（opscli）而非 Push/Webhook

用 `opscli skills upgrade` 替代推送通知，充当 Skills 的本地包管理器。

- **为什么：** 无需额外基础设施（Redis/MQ/Webhook）；与现有 `opscli` 工具链集成；用户有明确操作感知
- **权衡：** 需要主动执行，不能完全自动化（配合 Layer 1 静默更新互补）

### 决策 3：语义化版本 + 防降级

版本号格式 `vX.Y.Z`，发布时强校验新版本必须大于当前版本。

- **为什么：** 防止误操作回滚；版本历史可追溯（manifest 中记录 `previous`）
- **实现：** 三元组字典序比较 `(major, minor, patch)`

### 决策 4：原子替换保证数据完整性

下载到临时文件后 `shutil.move()` 原子替换，下载中断不破坏已有缓存。

- **为什么：** 搜索服务永远有完整可用的数据，不会出现"下载一半"的损坏状态

### 决策 5：静默降级优先于报错

Layer 1 自动更新的所有异常均被捕获，降级使用本地缓存。

- **为什么：** Skill 的核心价值是搜索，更新失败不能阻断搜索；网络抖动不应影响业务

---

## 服务端实现模板

### Controller 骨架（PHP/Laravel）

```php
class {Resource}SkillController extends Controller
{
    const MANIFEST_KEY = 'SKILL_{RESOURCE}_MANIFEST';

    // 轻量：仅返回元数据，不含数据内容
    public function manifest(): JsonResponse
    {
        $manifest = $this->loadManifest();
        if (!$manifest) return ApiResponse::error('尚未发布', 404);
        return ApiResponse::success($manifest);
    }

    // 流式 CSV：避免大文件占内存
    public function export(Request $request)
    {
        $manifest = $this->loadManifest();
        $version  = $manifest['version'] ?? 'v0.0.0';
        $rows     = (new {Resource}ExportService())->getData();

        return response()->streamDownload(function () use ($rows) {
            $handle = fopen('php://output', 'w');
            fwrite($handle, "\xEF\xBB\xBF");           // UTF-8 BOM
            fputcsv($handle, [/* 列头 */]);
            foreach ($rows as $row) {
                fputcsv($handle, [/* 行数据，含 keywords 合并列 */]);
            }
            fclose($handle);
        }, "skill_{$version}.csv", ['Content-Type' => 'text/csv; charset=UTF-8']);
    }

    // 管理员发布：校验 + 防降级 + 写入
    public function publish(Request $request): JsonResponse
    {
        $request->validate(['version' => ['required', 'regex:/^v\d+\.\d+\.\d+$/']]);
        $newVersion = $request->input('version');

        $current = $this->loadManifest();
        if ($current && !$this->isNewerVersion($newVersion, $current['version'])) {
            return ApiResponse::error("版本号 {$newVersion} 不高于当前版本 {$current['version']}");
        }

        $manifest = [
            'version'      => $newVersion,
            'released_at'  => now()->toISOString(),
            'field_count'  => count((new {Resource}ExportService())->getData()),
            'published_by' => auth()->user()?->email ?? 'system',
            'previous'     => $current['version'] ?? null,
        ];
        $this->saveManifest($manifest);
        return ApiResponse::success($manifest);
    }

    private function loadManifest(): ?array
    {
        $row = DB::table('system_constant')->where('name', self::MANIFEST_KEY)->first();
        if (!$row || empty($row->value)) return null;
        $data = json_decode($row->value, true);
        return is_array($data) ? $data : null;
    }

    private function saveManifest(array $manifest): void
    {
        $value = json_encode($manifest, JSON_UNESCAPED_UNICODE);
        DB::table('system_constant')->updateOrInsert(
            ['name' => self::MANIFEST_KEY],
            ['value' => $value, 'updated_at' => time()]
        );
    }

    private function isNewerVersion(string $new, string $current): bool
    {
        $toInts = fn($v) => array_map('intval', explode('.', ltrim($v, 'v')));
        return $toInts($new) > $toInts($current);
    }
}
```

**路由注册（静态路由必须置于动态参数路由之前）：**

```php
Route::prefix('{resource}')->group(function () {
    // ✅ 静态路由（Skill）— 必须先于 /{id}
    Route::get('/skill/manifest', [{Resource}SkillController::class, 'manifest']);
    Route::get('/skill/export',   [{Resource}SkillController::class, 'export']);
    Route::post('/skill/publish', [{Resource}SkillController::class, 'publish']);

    // 动态路由（通配）
    Route::get('/{id}', [...]);
});
```

---

## 客户端实现模板

### updater.py 骨架

```python
MANIFEST_URL = f"{OPS_BASE_URL}/v1/{resource}/skill/manifest"
EXPORT_URL   = f"{OPS_BASE_URL}/v1/{resource}/skill/export"

def update(force: bool = False) -> bool:
    token  = AuthClient().get_token("ops")
    remote = fetch_manifest(token)["version"]
    local  = load_local_version()                    # 读 data/VERSION.json

    if not force and _version_tuple(remote) <= _version_tuple(local):
        return False                                 # 已是最新

    download_csv(token, CSV_FILE)                    # 临时文件 → 原子替换
    VERSION_FILE.write_text(json.dumps({"version": remote}))
    return True

def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split("."))
```

### core.py 骨架

```python
def _auto_update_silent() -> None:
    """Layer 1：import 时静默触发，任何异常均降级"""
    try:
        from updater import update
        import sys, io
        sys.stdout, old = io.StringIO(), sys.stdout
        try:
            update()
        finally:
            sys.stdout = old
    except Exception:
        pass

_index = None

def get_index(auto_update: bool = True):
    global _index
    if _index is None:
        if auto_update:
            _auto_update_silent()
        _index = YourIndex()
        _index.load()           # 读 CSV + 建 BM25 索引
    return _index
```

### opscli skills manager 骨架

```python
class SkillsManager:
    def __init__(self, skills_dir=None):
        self.root = self._resolve_dir(skills_dir)  # 参数 > 环境变量 > 默认

    def discover(self) -> list:
        return [d for d in self.root.iterdir()
                if (d / "data" / "VERSION.json").exists()]

    def upgrade(self, skill_name=None, force=False):
        skills = self.discover()
        if skill_name:
            skills = [s for s in skills if s.name == skill_name]

        # 并行检查版本，串行下载（避免带宽竞争）
        with ThreadPoolExecutor() as ex:
            manifests = list(ex.map(self._fetch_manifest, skills))

        for skill, remote in zip(skills, manifests):
            local = self._local_version(skill)
            if force or _version_tuple(remote["version"]) > _version_tuple(local):
                self._download_and_replace(skill, remote)
```

---

## 客户端目录规范

```
.claude/skills/{skill-name}/
├── SKILL.md                   Skill 元信息（Claude 读取）
├── data/
│   ├── VERSION.json           {"version": "vX.Y.Z"}
│   └── {name}.csv             数据缓存（含 keywords 合并列）
└── scripts/
    ├── updater.py             更新引擎（Layer 3 入口 + Layer 1/2 复用）
    ├── core.py                索引 + 搜索（Layer 1 在此触发）
    └── search.py              Claude 调用入口
```

**初始化：** `data/VERSION.json` 写入 `{"version": "v0.0.0"}`，CSV 为只含表头的空文件。首次 `opscli skills upgrade` 后填充真实数据。

---

## 快速复用清单

新增一个 Skill 的完整工作量约 **3~4 小时**：

**服务端（~2h）：**
- [ ] 创建 `{Resource}ExportService`（数据查询 + 组装，含 keywords 合并列）
- [ ] 复制 `DatasetSkillController` → `{Resource}SkillController`，改 `MANIFEST_KEY` 和 CSV 列定义
- [ ] 在 `routes/api.php` 注册 3 条静态路由（置于动态路由之前）

**客户端（~1h）：**
- [ ] 复制 `scripts/updater.py`，改 `MANIFEST_URL` / `EXPORT_URL`
- [ ] 复制 `scripts/core.py`，改 `COLUMNS` 列表和 `keywords` 取法
- [ ] 复制 `scripts/search.py`，调整输出格式
- [ ] 创建 `data/VERSION.json` → `{"version": "v0.0.0"}`
- [ ] 创建 `data/{name}.csv`（只含表头的空文件）

**opscli 集成（~0.5h，仅首次）：**
- [ ] 在 `opscli/skills/services/manager.py` 中 Skill 路径无需额外注册（目录扫描自动发现）

---

## 适用场景评估

| 场景特征 | 是否适用 | 说明 |
|---------|---------|------|
| 数据变更频率：周/月级 | ✅ 最佳 | 三层机制完全满足 |
| 数据变更频率：日级 | ✅ 可用 | Layer 1 静默更新覆盖 |
| 数据变更频率：小时级 | ⚠️ 勉强 | 建议结合 cron 定时运行 opscli |
| 数据变更频率：分钟级 | ❌ 不适用 | 改用 Redis Pub/Sub 或 SSE |
| 数据量：百~百万条 | ✅ 推荐 | CSV 轻量，BM25 内存索引 |
| 需要本地语义搜索 | ✅ 推荐 | BM25 开箱即用 |
| 需要实时最新数据 | ❌ 不适用 | 改用实时 API 查询 |

---

## 可扩展点

| 扩展点 | 当前实现 | 可选升级 |
|-------|---------|---------|
| **目标工具** | Claude Code 单工具 | + OpenClaw（Tier 1）/ OpenCode、Cursor、Windsurf（Tier 2 适配） |
| 更新触发 | 启动时 Pull + opscli | + cron 定时 / Redis Pub/Sub |
| 搜索算法 | BM25 | + Embedding + FAISS（向量搜索）|
| 数据格式 | CSV（轻量） | SQLite（支持复杂过滤条件） |
| 数据压缩 | 无 | gzip（百万行级别场景） |
| 认证方式 | JWT（opscli） | + API Key（外部系统对接） |
| 版本存储 | system_constant 表 | 独立版本管理表（多 Skill 统一管理）|

> 多工具支持的详细路径调研与分阶段实现规划，见 [opscli多工具Skills支持调研规划.md](opscli多工具Skills支持调研规划.md)。
