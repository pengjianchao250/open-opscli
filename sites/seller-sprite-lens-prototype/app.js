import { formatMatrixValue, matrixCsv, resultSheets, visibleMatrixRows } from "./result-utils.js";
import { buildScenarioParams, periodOptionsForScenario, scenarioDefaults, scenarioPeriod, SCENARIO_GROUPS, SCENARIOS, SITE_OPTIONS } from "./scenarios.js";

const JOB_STORAGE_KEY = "seller-sprite-lens-jobs";
const PREFERENCE_STORAGE_KEY = "seller-sprite-lens-preferences";
const JOB_LIMIT = 30;
const SELLER_SPRITE_API_PATH = "./api/v1/seller-sprite";

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function createJobId(scenario, cryptoValue = globalThis.crypto) {
  const token = typeof cryptoValue?.randomUUID === "function"
    ? cryptoValue.randomUUID().slice(0, 8)
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const stamp = new Date().toISOString().replaceAll(/[-:TZ.]/g, "").slice(0, 14);
  return `web-${scenario}-${stamp}-${token}`;
}

function loadJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

function normalizeJobs(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((job) => isRecord(job) && typeof job.jobId === "string" && SCENARIOS[job.scenario]).slice(0, JOB_LIMIT);
}

function saveJobs(jobs) {
  localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(jobs.slice(0, JOB_LIMIT)));
}

function taskPending(task) {
  const state = String(task?.state || "").toLowerCase();
  return state === "queued" || state === "running" || task?.ready === false;
}

function taskFailed(task) {
  const state = String(task?.state || "").toLowerCase();
  return state === "failed" || state === "cancelled" || task?.failed === true;
}

function taskLabel(state) {
  return ({ queued: "排队中", running: "执行中", succeeded: "已完成", failed: "失败", cancelled: "已取消" })[state] || state || "未知";
}

function taskTone(state) {
  if (state === "succeeded") return "success";
  if (state === "failed" || state === "cancelled") return "danger";
  if (state === "running") return "info";
  return "warning";
}

function daisyTone(tone) {
  return tone === "danger" ? "error" : tone;
}

function responseError(payload, status) {
  const error = payload?.error;
  return error?.message || payload?.message || (typeof error === "string" ? error : "") || `HTTP ${status}`;
}

function sampleWorkbook() {
  return {
    schema_version: "2.0",
    sheet_name: "US-B0TEST1234-Keywords",
    columns: ["关键词", "流量占比", "月搜索量", "自然排名", "PPC价格"],
    number_formats: [null, "0.00%", "#,##0", "#,##0", "#,##0.00"],
    row_count: 4,
    rows: [
      ["usb c charger", 0.1842, 61800, 8, 1.34],
      ["fast charger", 0.126, 42300, 17, 1.72],
      ["phone charger", 0.091, 112000, 34, 1.16],
      ["type c charger", 0.074, 33700, 12, 1.28],
    ],
    additional_sheets: [{
      name: "Unique Words",
      columns: ["词根", "频次"],
      number_formats: [null, "#,##0"],
      row_count: 4,
      rows: [["charger", 4], ["usb", 1], ["fast", 1], ["phone", 1]],
    }],
  };
}

function summarizeParams(params) {
  const entries = Object.entries(params || {}).filter(([, value]) => value !== "" && value !== false && value !== undefined);
  if (!entries.length) return "默认条件";
  return entries.slice(0, 3).map(([key, value]) => {
    const text = Array.isArray(value) ? value.join(", ") : String(value);
    return `${key}: ${text.length > 24 ? `${text.slice(0, 24)}...` : text}`;
  }).join(" · ");
}

class SellerSpriteLens extends HTMLElement {
  constructor() {
    super();
    const preferences = loadJson(PREFERENCE_STORAGE_KEY, {});
    const scenario = SCENARIOS[preferences.scenario] ? preferences.scenario : "keyword-reverse";
    this.state = {
      theme: ["dark", "business"].includes(preferences.theme) ? "business" : "corporate",
      scenario,
      site: preferences.site || "US",
      period: scenarioPeriod(scenario, preferences.period),
      pageSize: 100,
      params: scenarioDefaults(scenario),
      paramsByScenario: {},
      advancedJson: "",
      jobs: normalizeJobs(loadJson(JOB_STORAGE_KEY, [])),
      activeJobId: "",
      task: null,
      result: sampleWorkbook(),
      sheets: resultSheets(sampleWorkbook()),
      activeSheet: 0,
      view: "table",
      filter: "",
      sortIndex: -1,
      sortDirection: 1,
      page: 1,
      pageSizeView: 100,
      quota: null,
      remoteScenarios: null,
      status: "已载入 JSON v2 样例数据。",
      tone: "success",
      busy: false,
      sidebarOpen: false,
    };
    document.documentElement.dataset.theme = this.state.theme;
  }

  connectedCallback() {
    this.render();
    this.addEventListener("click", (event) => this.handleClick(event));
    this.addEventListener("input", (event) => this.handleInput(event));
    this.addEventListener("change", (event) => this.handleInput(event));
    this.addEventListener("submit", (event) => this.handleSubmit(event));
  }

  savePreferences() {
    localStorage.setItem(PREFERENCE_STORAGE_KEY, JSON.stringify({
      theme: this.state.theme,
      scenario: this.state.scenario,
      site: this.state.site,
      period: this.state.period,
    }));
  }

  async request(path, options = {}) {
    const response = await fetch(`${SELLER_SPRITE_API_PATH}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      credentials: "same-origin",
    });
    const text = await response.text();
    let payload;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      throw new Error(response.headers.get("content-type")?.includes("text/html")
        ? "站点 API 返回了网页，请检查 AppHub 路由配置。"
        : "接口返回内容不是有效 JSON。");
    }
    if (!response.ok || payload?.success === false) throw new Error(responseError(payload, response.status));
    return { payload, status: response.status };
  }

  setStatus(message, tone = "info") {
    this.state.status = message;
    this.state.tone = tone;
  }

  handleInput(event) {
    const target = event.target;
    if (target.dataset.param) {
      this.state.params[target.dataset.param] = target.type === "checkbox" ? target.checked : target.value;
      return;
    }
    const field = target.dataset.field;
    if (!field) return;
    if (field === "scenario") return this.selectScenario(target.value);
    if (field === "theme") {
      this.state.theme = target.checked ? "business" : "corporate";
      document.documentElement.dataset.theme = this.state.theme;
      this.savePreferences();
      this.render();
      return;
    }
    this.state[field] = target.type === "checkbox" ? target.checked : target.value;
    if (["site", "period"].includes(field)) this.savePreferences();
    if (field === "filter") {
      this.state.page = 1;
      queueMicrotask(() => this.render());
    }
  }

  handleClick(event) {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.scenario) return this.selectScenario(button.dataset.scenario);
    if (button.dataset.view) {
      this.state.view = button.dataset.view;
      this.render();
      return;
    }
    if (button.dataset.sheet !== undefined) {
      this.state.activeSheet = Number(button.dataset.sheet);
      this.state.filter = "";
      this.state.sortIndex = -1;
      this.state.page = 1;
      this.render();
      return;
    }
    if (button.dataset.sort !== undefined) {
      const index = Number(button.dataset.sort);
      this.state.sortDirection = this.state.sortIndex === index ? this.state.sortDirection * -1 : 1;
      this.state.sortIndex = index;
      this.state.page = 1;
      this.render();
      return;
    }
    if (button.dataset.page) {
      this.state.page += Number(button.dataset.page);
      this.render();
      return;
    }
    if (button.dataset.jobId) return this.openJob(button.dataset.jobId);
    if (button.dataset.refreshJob) return this.refreshJob(button.dataset.refreshJob);
    if (button.dataset.deleteJob) return this.deleteJob(button.dataset.deleteJob);
    if (button.dataset.connect !== undefined) return this.checkConnection();
    if (button.dataset.sample !== undefined) return this.loadSample();
    if (button.dataset.download !== undefined) return this.downloadCsv();
    if (button.dataset.sidebar !== undefined) {
      this.state.sidebarOpen = !this.state.sidebarOpen;
      this.render();
    }
  }

  selectScenario(scenario) {
    if (!SCENARIOS[scenario] || scenario === this.state.scenario) return;
    this.state.paramsByScenario[this.state.scenario] = { ...this.state.params, __advanced: this.state.advancedJson };
    const saved = this.state.paramsByScenario[scenario];
    this.state.scenario = scenario;
    this.state.params = saved ? Object.fromEntries(Object.entries(saved).filter(([key]) => key !== "__advanced")) : scenarioDefaults(scenario);
    this.state.advancedJson = saved?.__advanced || "";
    this.state.period = scenarioPeriod(scenario);
    this.state.sidebarOpen = false;
    this.setStatus(`已切换到${SCENARIOS[scenario].title}。`, "info");
    this.savePreferences();
    this.render();
  }

  async checkConnection() {
    this.state.busy = true;
    this.setStatus("正在验证连接并读取额度...", "info");
    this.render();
    try {
      const [scenarioResponse, quotaResponse] = await Promise.all([
        this.request("/scenarios"),
        this.request("/quota"),
      ]);
      this.state.remoteScenarios = scenarioResponse.payload?.data || [];
      this.state.quota = quotaResponse.payload?.data || quotaResponse.payload?.quota || null;
      this.setStatus(`连接正常，服务端开放 ${this.state.remoteScenarios.length} 个场景。`, "success");
    } catch (error) {
      this.setStatus(`连接失败：${error.message}`, "danger");
    } finally {
      this.state.busy = false;
      this.render();
    }
  }

  handleSubmit(event) {
    event.preventDefault();
    if (event.target.dataset.action === "submit") this.submitTask();
  }

  async submitTask() {
    let params;
    try {
      params = buildScenarioParams(this.state.scenario, this.state.params, this.state.advancedJson);
    } catch (error) {
      this.setStatus(error.message, "danger");
      this.render();
      return;
    }
    const jobId = createJobId(this.state.scenario);
    const requestBody = {
      scenario: this.state.scenario,
      params,
      site: this.state.site,
      period: this.state.period,
      page_size: Number(this.state.pageSize),
      export_format: "json",
      job_id: jobId,
    };
    this.state.busy = true;
    this.setStatus("正在提交采集任务...", "info");
    this.render();
    try {
      const { payload } = await this.request("/jobs", { method: "POST", body: JSON.stringify(requestBody) });
      const task = payload?.data || {};
      const realJobId = task.job_id || jobId;
      this.state.task = task;
      this.state.activeJobId = realJobId;
      this.upsertJob({
        jobId: realJobId,
        scenario: this.state.scenario,
        site: this.state.site,
        period: this.state.period,
        params,
        createdAt: new Date().toISOString(),
        state: task.state || "queued",
        stage: task.stage || "queued",
      });
      if (payload?.quota) this.state.quota = payload.quota;
      this.setStatus(`任务已提交：${realJobId}`, "success");
      this.render();
      await this.refreshJob(realJobId, true);
    } catch (error) {
      this.setStatus(`提交失败：${error.message}`, "danger");
    } finally {
      this.state.busy = false;
      this.render();
    }
  }

  upsertJob(job) {
    const existing = this.state.jobs.find((item) => item.jobId === job.jobId);
    this.state.jobs = [existing ? { ...existing, ...job } : job, ...this.state.jobs.filter((item) => item.jobId !== job.jobId)].slice(0, JOB_LIMIT);
    saveJobs(this.state.jobs);
  }

  async refreshJob(jobId, afterSubmit = false) {
    if (!jobId) return;
    this.state.busy = true;
    this.state.activeJobId = jobId;
    this.setStatus(afterSubmit ? "任务已进入队列，正在等待第一轮结果..." : "正在读取任务状态...", "info");
    this.render();
    try {
      const { payload, status } = await this.request(`/jobs/${encodeURIComponent(jobId)}/result?wait_seconds=30`);
      const task = payload?.data || {};
      this.state.task = task;
      this.upsertJob({ jobId, state: task.state || "unknown", stage: task.stage || "", rowCount: task.row_count ?? null, updatedAt: new Date().toISOString() });
      if (status === 202 || taskPending(task)) {
        this.setStatus(`任务${taskLabel(task.state)}，可稍后继续刷新。`, "warning");
      } else if (taskFailed(task)) {
        this.setStatus(`任务失败：${task.error?.message || task.message || "请查看原始状态"}`, "danger");
      } else {
        const result = task.result ?? task.data ?? task;
        this.state.result = result;
        this.state.sheets = resultSheets(result);
        this.state.activeSheet = 0;
        this.state.view = this.state.sheets.length ? "table" : "raw";
        this.state.filter = "";
        this.state.sortIndex = -1;
        this.state.page = 1;
        this.setStatus(`任务完成，返回 ${task.row_count ?? this.state.sheets[0]?.rows.length ?? 0} 行。`, "success");
      }
    } catch (error) {
      this.setStatus(`状态查询失败：${error.message}`, "danger");
    } finally {
      this.state.busy = false;
      this.render();
    }
  }

  openJob(jobId) {
    const job = this.state.jobs.find((item) => item.jobId === jobId);
    if (!job) return;
    this.state.activeJobId = jobId;
    this.state.scenario = job.scenario;
    this.state.site = job.site;
    this.state.period = job.period;
    this.state.params = { ...(job.params || {}) };
    this.state.task = job;
    this.setStatus(`已载入任务 ${jobId}。`, "info");
    this.savePreferences();
    this.render();
  }

  deleteJob(jobId) {
    this.state.jobs = this.state.jobs.filter((job) => job.jobId !== jobId);
    if (this.state.activeJobId === jobId) {
      this.state.activeJobId = "";
      this.state.task = null;
    }
    saveJobs(this.state.jobs);
    this.render();
  }

  loadSample() {
    const sample = sampleWorkbook();
    this.state.result = sample;
    this.state.sheets = resultSheets(sample);
    this.state.activeSheet = 0;
    this.state.view = "table";
    this.state.filter = "";
    this.state.sortIndex = -1;
    this.state.page = 1;
    this.setStatus("已载入 JSON v2 样例数据。", "success");
    this.render();
  }

  downloadCsv() {
    const sheet = this.state.sheets[this.state.activeSheet];
    if (!sheet?.rows.length) return;
    const rows = visibleMatrixRows(sheet, this.state.filter, this.state.sortIndex, this.state.sortDirection).map(({ row }) => row);
    if (!rows.length) return;
    const url = URL.createObjectURL(new Blob([matrixCsv(sheet, rows)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `seller-sprite-${this.state.scenario}-${this.state.site}-${sheet.name}-${new Date().toISOString().slice(0, 10)}.csv`.replaceAll(/[\\/:*?"<>|]/g, "-");
    link.click();
    URL.revokeObjectURL(url);
  }

  renderField(item) {
    const value = this.state.params[item.key] ?? "";
    const required = (SCENARIOS[this.state.scenario].required || []).includes(item.key);
    const label = `${escapeHtml(item.label)}${required ? '<span class="required">必填</span>' : ""}`;
    if (item.type === "checkbox") {
      return `<label class="check-field"><input class="checkbox checkbox-primary checkbox-sm" type="checkbox" data-param="${escapeHtml(item.key)}" ${value ? "checked" : ""}><span>${label}</span></label>`;
    }
    if (item.type === "select") {
      return `<label class="form-field"><span>${label}</span><select class="select select-bordered select-sm w-full" data-param="${escapeHtml(item.key)}">${item.options.map(([option, optionLabel]) => `<option value="${escapeHtml(option)}" ${String(value) === String(option) ? "selected" : ""}>${escapeHtml(optionLabel)}</option>`).join("")}</select></label>`;
    }
    if (item.type === "multi" || item.type === "multiline") {
      const rows = item.type === "multiline" ? 5 : 3;
      const text = Array.isArray(value) ? value.join(item.type === "multiline" ? "\n" : ", ") : value;
      return `<label class="form-field ${item.type === "multiline" ? "field-wide" : ""}"><span>${label}</span><textarea class="textarea textarea-bordered textarea-sm w-full" rows="${rows}" data-param="${escapeHtml(item.key)}" placeholder="${escapeHtml(item.placeholder || "多个值用逗号或换行分隔")}">${escapeHtml(text)}</textarea></label>`;
    }
    const attributes = [item.min !== undefined && `min="${item.min}"`, item.max !== undefined && `max="${item.max}"`, item.step && `step="${item.step}"`, item.placeholder && `placeholder="${escapeHtml(item.placeholder)}"`].filter(Boolean).join(" ");
    return `<label class="form-field"><span>${label}</span><input class="input input-bordered input-sm w-full" type="${item.type === "number" ? "number" : "text"}" data-param="${escapeHtml(item.key)}" value="${escapeHtml(value)}" ${attributes}></label>`;
  }

  renderSidebar() {
    return `<aside class="sidebar ${this.state.sidebarOpen ? "open" : ""}">
      <div class="brand"><span class="brand-mark">SS</span><div><strong>SellerSprite Lens</strong><span>场景数据工作台</span></div></div>
      <nav aria-label="卖家精灵场景">${SCENARIO_GROUPS.map((group) => `<section class="nav-group"><h2>${escapeHtml(group.label)}</h2>${group.scenarios.map((id) => `<button type="button" class="nav-item btn btn-ghost ${id === this.state.scenario ? "active btn-active" : ""}" data-scenario="${id}"><span>${escapeHtml(SCENARIOS[id].title)}</span><small>${escapeHtml(id)}</small></button>`).join("")}</section>`).join("")}</nav>
      <div class="sidebar-note"><strong>一期范围</strong><span>13 个 JSON 场景</span><span>Listing Analysis 与文件型场景暂不开放</span></div>
    </aside>`;
  }

  renderQuota() {
    const quota = this.state.quota;
    if (!quota) return `<div class="quota"><span>额度</span><strong>未读取</strong></div>`;
    if (quota.unlimited) return `<div class="quota success"><span>额度</span><strong>专属账号</strong></div>`;
    const remaining = quota.remaining ?? "-";
    const limit = quota.limit ?? "-";
    return `<div class="quota"><span>今日额度</span><strong>${escapeHtml(remaining)} / ${escapeHtml(limit)}</strong></div>`;
  }

  renderHeader() {
    return `<header class="topbar navbar bg-base-100"><div class="topbar-left"><button type="button" class="icon-button mobile-menu btn btn-square btn-ghost btn-sm" data-sidebar aria-label="打开场景导航">菜单</button><div><span class="eyebrow">SELLERSPRITE DATA WORKSPACE</span><h1>${escapeHtml(SCENARIOS[this.state.scenario].title)}</h1></div></div><div class="topbar-actions">${this.renderQuota()}<label class="theme-toggle"><span>暗色</span><input class="toggle toggle-primary toggle-sm" type="checkbox" data-field="theme" ${this.state.theme === "business" ? "checked" : ""}></label></div></header>`;
  }

  renderRequestPanel() {
    const definition = SCENARIOS[this.state.scenario];
    const periodOptions = periodOptionsForScenario(this.state.scenario);
    const periodField = periodOptions.length ? `<label class="form-field"><span>${definition.periodMode === "monthly" ? "月份" : "周期"}<span class="required">必填</span></span><select class="select select-bordered select-sm w-full" data-field="period">${periodOptions.map(([value, label]) => `<option value="${value}" ${String(this.state.period) === value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select></label>` : "";
    return `<section class="request-panel card bg-base-100"><div class="section-heading"><div><span class="eyebrow">QUERY BUILDER</span><h2>查询条件</h2><p>${escapeHtml(definition.description)}</p></div><span class="scenario-code badge badge-outline badge-sm">${escapeHtml(this.state.scenario)}</span></div>
      <form data-action="submit">
        <div class="common-grid bg-base-200"><label class="form-field"><span>站点<span class="required">必填</span></span><select class="select select-bordered select-sm w-full" data-field="site">${SITE_OPTIONS.map(([code, label]) => `<option value="${code}" ${this.state.site === code ? "selected" : ""}>${code} · ${label}</option>`).join("")}</select></label>${periodField}<label class="form-field"><span>返回数量</span><select class="select select-bordered select-sm w-full" data-field="pageSize"><option value="100" selected>100 条</option></select></label></div>
        <div class="form-groups">${definition.groups.map((group) => `<details class="form-group bg-base-100" ${group.open ? "open" : ""}><summary><span>${escapeHtml(group.label)}</span><small>${group.fields.length} 项</small></summary><div class="field-grid">${group.fields.map((item) => this.renderField(item)).join("")}</div></details>`).join("")}</div>
        <details class="form-group advanced bg-base-100"><summary><span>高级参数 JSON</span><small>覆盖或补充表单</small></summary><label class="form-field"><textarea class="textarea textarea-bordered textarea-sm w-full" rows="5" data-field="advancedJson" placeholder='例如 {"orderField":"searches"}'>${escapeHtml(this.state.advancedJson)}</textarea></label></details>
        <div class="form-actions"><button class="primary-button btn btn-primary btn-sm" type="submit" ${this.state.busy ? "disabled" : ""}>${this.state.busy ? "处理中..." : "提交 JSON 任务"}</button><button class="secondary-button btn btn-outline btn-sm" type="button" data-connect ${this.state.busy ? "disabled" : ""}>验证连接</button><button class="secondary-button btn btn-outline btn-sm" type="button" data-sample>载入样例</button></div>
        <div class="status-message alert alert-soft alert-${daisyTone(this.state.tone)}" role="status">${escapeHtml(this.state.status)}</div>
      </form></section>`;
  }

  renderTaskPanel() {
    if (!this.state.task) return `<section class="task-panel card bg-base-100 empty"><div><span class="eyebrow">TASK STATUS</span><h2>尚未提交任务</h2><p>提交后可在这里查看排队位置、执行阶段和结果状态。</p></div></section>`;
    const task = this.state.task;
    const state = String(task.state || "unknown").toLowerCase();
    return `<section class="task-panel card bg-base-100"><div class="task-main"><div><span class="eyebrow">TASK STATUS</span><div class="task-title"><h2>${escapeHtml(taskLabel(state))}</h2><span class="state-badge badge badge-${daisyTone(taskTone(state))} badge-sm ${taskTone(state)}">${escapeHtml(state)}</span></div></div><button type="button" class="secondary-button btn btn-outline btn-sm" data-refresh-job="${escapeHtml(this.state.activeJobId || task.job_id)}" ${this.state.busy ? "disabled" : ""}>刷新状态</button></div><dl class="task-metrics stats"><div class="stat"><dt class="stat-title">任务编号</dt><dd class="stat-value" title="${escapeHtml(this.state.activeJobId || task.job_id)}">${escapeHtml(this.state.activeJobId || task.job_id)}</dd></div><div class="stat"><dt class="stat-title">执行阶段</dt><dd class="stat-value">${escapeHtml(task.stage || "-")}</dd></div><div class="stat"><dt class="stat-title">排队位置</dt><dd class="stat-value">${escapeHtml(task.position ?? "-")}</dd></div><div class="stat"><dt class="stat-title">结果行数</dt><dd class="stat-value">${escapeHtml(task.row_count ?? task.rowCount ?? "-")}</dd></div></dl></section>`;
  }

  renderTable() {
    const sheet = this.state.sheets[this.state.activeSheet];
    if (!sheet || !sheet.rows.length) return `<div class="empty-result">当前结果没有可显示的表格数据。</div>`;
    const visible = visibleMatrixRows(sheet, this.state.filter, this.state.sortIndex, this.state.sortDirection);
    if (!visible.length) return `<div class="empty-result">没有匹配当前筛选的数据。</div>`;
    const pageCount = Math.max(1, Math.ceil(visible.length / this.state.pageSizeView));
    const currentPage = Math.min(this.state.page, pageCount);
    const pageRows = visible.slice((currentPage - 1) * this.state.pageSizeView, currentPage * this.state.pageSizeView);
    const head = sheet.columns.map((column, index) => `<th><button type="button" data-sort="${index}">${escapeHtml(column)}${this.state.sortIndex === index ? (this.state.sortDirection === 1 ? " ↑" : " ↓") : ""}</button></th>`).join("");
    const body = pageRows.map(({ row, index }) => `<tr><td class="row-number">${index + 1}</td>${sheet.columns.map((_, columnIndex) => { const raw = row[columnIndex]; const formatted = formatMatrixValue(raw, sheet.numberFormats[columnIndex]); return `<td title="${escapeHtml(typeof raw === "object" ? JSON.stringify(raw) : formatted)}">${raw && typeof raw === "object" ? `<details><summary>查看数据</summary><pre>${escapeHtml(JSON.stringify(raw, null, 2))}</pre></details>` : escapeHtml(formatted) || '<span class="muted">-</span>'}</td>`; }).join("")}</tr>`).join("");
    return `<div class="table-scroll"><table class="table table-zebra table-pin-rows"><thead><tr><th>#</th>${head}</tr></thead><tbody>${body}</tbody></table></div>${pageCount > 1 ? `<div class="pagination"><span>第 ${currentPage} / ${pageCount} 页 · ${visible.length} 条</span><div class="join"><button type="button" class="secondary-button btn btn-outline btn-sm join-item" data-page="-1" ${currentPage === 1 ? "disabled" : ""}>上一页</button><button type="button" class="secondary-button btn btn-outline btn-sm join-item" data-page="1" ${currentPage === pageCount ? "disabled" : ""}>下一页</button></div></div>` : ""}`;
  }

  renderResultPanel() {
    const sheet = this.state.sheets[this.state.activeSheet];
    const content = this.state.view === "raw"
      ? `<pre class="raw-json">${escapeHtml(JSON.stringify(this.state.result, null, 2))}</pre>`
      : this.state.view === "tree"
        ? this.renderTree(this.state.result)
        : this.renderTable();
    return `<section class="result-panel card bg-base-100"><div class="result-header"><div><span class="eyebrow">JSON RESULT</span><h2>查询结果</h2></div><div class="result-tools"><input class="input input-bordered input-sm" data-field="filter" value="${escapeHtml(this.state.filter)}" placeholder="筛选当前工作表" aria-label="筛选当前工作表"><div class="segmented tabs tabs-box tabs-sm"><button type="button" data-view="table" class="tab ${this.state.view === "table" ? "active tab-active" : ""}">表格</button><button type="button" data-view="tree" class="tab ${this.state.view === "tree" ? "active tab-active" : ""}">树形</button><button type="button" data-view="raw" class="tab ${this.state.view === "raw" ? "active tab-active" : ""}">原始</button></div><button type="button" class="secondary-button btn btn-outline btn-sm" data-download ${!sheet?.rows.length || this.state.view !== "table" ? "disabled" : ""}>下载 CSV</button></div></div>
      <div class="summary-strip stats"><div class="stat"><span class="stat-title">工作表</span><strong class="stat-value">${this.state.sheets.length}</strong></div><div class="stat"><span class="stat-title">当前行数</span><strong class="stat-value">${sheet?.rows.length ?? 0}</strong></div><div class="stat"><span class="stat-title">字段数</span><strong class="stat-value">${sheet?.columns.length ?? 0}</strong></div><div class="stat"><span class="stat-title">数据格式</span><strong class="stat-value">${this.state.result?.schema_version ? `JSON v${escapeHtml(this.state.result.schema_version)}` : "JSON"}</strong></div></div>
      ${this.state.sheets.length > 1 ? `<div class="sheet-tabs tabs tabs-border">${this.state.sheets.map((item, index) => `<button type="button" data-sheet="${index}" class="tab ${index === this.state.activeSheet ? "active tab-active" : ""}">${escapeHtml(item.name)} <span>${item.rows.length}</span></button>`).join("")}</div>` : ""}
      <div class="result-content">${content}</div></section>`;
  }

  renderTree(value, key = "root") {
    if (value === null || typeof value !== "object") return `<span class="tree-value">${escapeHtml(String(value))}</span>`;
    const entries = Array.isArray(value) ? value.map((item, index) => [index, item]) : Object.entries(value);
    return `<ul class="tree"><li><details open><summary><strong>${escapeHtml(key)}</strong><span>${Array.isArray(value) ? "array" : "object"} · ${entries.length}</span></summary><ul>${entries.map(([childKey, childValue]) => `<li><span class="tree-key">${escapeHtml(childKey)}</span>${childValue !== null && typeof childValue === "object" ? this.renderTree(childValue, childKey) : `<span class="tree-value">${escapeHtml(JSON.stringify(childValue))}</span>`}</li>`).join("")}</ul></details></li></ul>`;
  }

  renderJobs() {
    return `<section class="jobs-panel card bg-base-100"><div class="section-heading compact"><div><span class="eyebrow">RECENT TASKS</span><h2>最近任务</h2></div><span class="count-badge badge badge-ghost badge-sm">${this.state.jobs.length}</span></div>${this.state.jobs.length ? `<div class="job-list">${this.state.jobs.map((job) => `<article class="job-item ${job.jobId === this.state.activeJobId ? "active" : ""}"><button type="button" class="job-open" data-job-id="${escapeHtml(job.jobId)}"><span><strong>${escapeHtml(SCENARIOS[job.scenario].title)}</strong><small>${escapeHtml(job.site)} · ${escapeHtml(job.period)}</small></span><span class="state-badge badge badge-${daisyTone(taskTone(job.state))} badge-sm ${taskTone(job.state)}">${escapeHtml(taskLabel(job.state))}</span><p>${escapeHtml(summarizeParams(job.params))}</p><time>${escapeHtml(new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(job.createdAt || job.updatedAt || Date.now())))}</time></button><button type="button" class="job-delete btn btn-ghost btn-square btn-xs" data-delete-job="${escapeHtml(job.jobId)}" aria-label="删除任务记录">×</button></article>`).join("")}</div>` : `<div class="jobs-empty">暂无本地任务记录</div>`}</section>`;
  }

  render() {
    this.innerHTML = `<div class="app-shell bg-base-200">${this.renderSidebar()}<div class="main-shell">${this.renderHeader()}<main><div class="primary-column">${this.renderRequestPanel()}${this.renderTaskPanel()}${this.renderResultPanel()}</div>${this.renderJobs()}</main></div>${this.state.sidebarOpen ? '<button type="button" class="sidebar-backdrop" data-sidebar aria-label="关闭场景导航"></button>' : ""}</div>`;
  }
}

customElements.define("seller-sprite-lens", SellerSpriteLens);
