"""Collector Monitor 无外部资源的嵌入式只读仪表盘。"""

DASHBOARD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Collector Monitor</title>
  <style>
    :root { color-scheme: light; --ink:#17212b; --muted:#66727f; --line:#d9e0e6; --paper:#ffffff; --canvas:#f3f6f8; --blue:#1769aa; --red:#b42318; --amber:#a15c00; --green:#18794e; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--canvas); color:var(--ink); font:14px/1.5 "Segoe UI Variable","Microsoft YaHei UI","Segoe UI",sans-serif; }
    header { background:#102a43; color:white; padding:22px max(24px,calc((100vw - 1400px)/2)); display:flex; justify-content:space-between; align-items:end; }
    h1 { margin:0; font-size:25px; letter-spacing:0; }
    header p { margin:4px 0 0; color:#c9d8e6; }
    #updated { color:#dce7f0; font-variant-numeric:tabular-nums; }
    main { max-width:1400px; margin:0 auto; padding:24px; }
    .cards { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:18px; }
    .card,.panel { background:var(--paper); border:1px solid var(--line); border-radius:8px; box-shadow:0 2px 8px rgba(16,42,67,.05); }
    .card { padding:17px; }
    .card span { display:block; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:0; }
    .card strong { display:block; margin-top:5px; font-size:28px; font-variant-numeric:tabular-nums; }
    .tabs { display:flex; gap:4px; margin-bottom:14px; padding:4px; overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:#e8edf1; scrollbar-width:thin; }
    .tab { flex:0 0 auto; min-width:112px; border-color:transparent; background:transparent; color:#526272; }
    .tab:hover { background:#f4f7f9; }
    .tab[aria-selected="true"] { border-color:#b8c9d6; background:var(--paper); color:#123f60; box-shadow:0 1px 3px rgba(16,42,67,.08); }
    .tab-panel[hidden] { display:none; }
    .view-grid { display:grid; grid-template-columns:minmax(0,2.2fr) minmax(320px,.8fr); gap:18px; align-items:start; }
    .task-table-wrap { min-height:420px; max-height:calc(100vh - 330px); overflow:auto; }
    .task-table-wrap thead { position:sticky; top:0; z-index:1; }
    .detail-panel { position:sticky; top:24px; }
    .stack { display:grid; gap:18px; }
    .panel { overflow:hidden; }
    .panel h2 { font-size:16px; margin:0; padding:15px 17px; border-bottom:1px solid var(--line); }
    .panel-title { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 14px 11px 17px; border-bottom:1px solid var(--line); }
    .panel-title h2 { padding:0; border:0; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
    button { min-height:34px; padding:6px 11px; border:1px solid #8aa8bf; border-radius:6px; background:#f7fbfe; color:#174f78; font:600 13px/1.2 inherit; cursor:pointer; }
    button:hover { background:#e8f3fa; }
    button:focus-visible { outline:2px solid var(--blue); outline-offset:2px; }
    button:disabled { cursor:wait; opacity:.6; }
    .credential-row { display:flex; align-items:end; gap:10px; padding:14px 16px; border-bottom:1px solid var(--line); background:#fbfcfd; }
    .credential-field { display:grid; gap:5px; width:min(520px,100%); }
    .credential-field label { color:var(--muted); font-size:12px; font-weight:650; }
    .credential-field input { width:100%; height:36px; padding:7px 10px; border:1px solid #aebdca; border-radius:6px; background:var(--paper); color:var(--ink); font:14px/1.2 inherit; }
    .credential-field input:focus { outline:2px solid var(--blue); outline-offset:1px; border-color:transparent; }
    .credential-save { display:flex; align-items:center; gap:7px; min-height:36px; color:var(--muted); font-size:13px; cursor:pointer; }
    .credential-save input { width:16px; height:16px; margin:0; accent-color:var(--blue); }
    .credential-save input:focus-visible { outline:2px solid var(--blue); outline-offset:2px; }
    .scenario-summary { display:grid; grid-template-columns:minmax(180px,.8fr) minmax(0,1.2fr); gap:12px 24px; padding:16px; border-bottom:1px solid var(--line); background:#f8fafb; }
    .scenario-summary strong { font-size:16px; }
    .scenario-summary code { color:#31556f; overflow-wrap:anywhere; }
    .scenario-form { padding:16px; }
    .form-grid { display:grid; grid-template-columns:minmax(220px,1.4fr) repeat(3,minmax(120px,.6fr)); gap:14px; }
    .field { display:grid; gap:5px; min-width:0; }
    .field label { color:var(--muted); font-size:12px; font-weight:650; }
    .field input { width:100%; height:38px; padding:7px 10px; border:1px solid #aebdca; border-radius:6px; background:var(--paper); color:var(--ink); font:14px/1.2 inherit; }
    .field input:focus { outline:2px solid var(--blue); outline-offset:1px; border-color:transparent; }
    .confirm-row { display:flex; align-items:flex-start; gap:8px; margin:16px 0; color:#713f00; }
    .confirm-row input { flex:0 0 auto; width:16px; height:16px; margin-top:2px; accent-color:var(--amber); }
    .submit-row { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
    .submit-row button { min-width:172px; }
    .scenario-result { min-height:38px; margin-top:14px; padding:9px 11px; border:1px solid var(--line); border-radius:6px; background:#f8fafb; overflow-wrap:anywhere; }
    .panel-body { padding:16px; }
    table { width:100%; border-collapse:collapse; }
    th,td { padding:10px 12px; border-bottom:1px solid #edf1f4; text-align:left; vertical-align:top; }
    th { color:var(--muted); font-size:12px; font-weight:600; background:#f8fafb; }
    tbody tr[data-job] { cursor:pointer; }
    tbody tr[data-job]:hover,tbody tr[data-job]:focus { background:#edf6fc; outline:none; }
    .badge { display:inline-block; padding:2px 8px; border-radius:999px; background:#e8eef3; font-size:12px; font-weight:650; }
    .healthy,.succeeded { color:var(--green); background:#e8f5ef; }
    .slow,.queue_starved { color:var(--amber); background:#fff3dd; }
    .stalled,.orphaned,.worker_unavailable,.failed { color:var(--red); background:#fdecea; }
    .incident { padding:12px 0; border-bottom:1px solid #edf1f4; }
    .incident:last-child { border-bottom:0; }
    .incident strong { display:flex; justify-content:space-between; gap:12px; }
    .resolved { color:var(--muted); background:#edf1f4; }
    .muted,.empty { color:var(--muted); }
    .runtime { display:grid; grid-template-columns:1fr auto; gap:6px 14px; padding:10px 0; border-bottom:1px solid #edf1f4; }
    .runtime:last-child { border-bottom:0; }
    .timeline { list-style:none; padding:0; margin:0; }
    .timeline li { border-left:2px solid #9fbfd7; padding:0 0 16px 14px; margin-left:5px; }
    .timeline time { display:block; color:var(--muted); font-size:12px; }
    .source-error { display:none; margin-bottom:16px; padding:12px 14px; border:1px solid #f2b8b5; background:#fff0ef; color:var(--red); border-radius:7px; }
    @media (max-width:900px) { .cards { grid-template-columns:repeat(2,1fr); } .view-grid { grid-template-columns:1fr; } .task-table-wrap { min-height:0; max-height:none; } .detail-panel { position:static; } .form-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
    @media (max-width:540px) { main { padding:14px; } header { padding:18px 14px; align-items:start; flex-direction:column; gap:8px; } .cards { grid-template-columns:repeat(2,minmax(0,1fr)); } .card { padding:14px; } .card strong { font-size:24px; } .tabs { margin-left:-14px; margin-right:-14px; padding-left:14px; padding-right:14px; border-left:0; border-right:0; border-radius:0; } .tab { min-width:96px; } .panel-title { align-items:flex-start; flex-direction:column; } .actions { width:100%; justify-content:flex-start; } .credential-row { align-items:stretch; flex-direction:column; } .scenario-summary,.form-grid { grid-template-columns:1fr; } th:nth-child(2),td:nth-child(2) { display:none; } }
  </style>
</head>
<body>
<header><div><h1>Collector Monitor</h1><p>SellerSprite 采集队列只读监督台</p></div><div id="updated">等待首次刷新</div></header>
<main>
  <div id="source-error" class="source-error"></div>
  <section class="cards" aria-label="任务总览">
    <div class="card"><span>任务总览</span><strong id="total">0</strong></div>
    <div class="card"><span>运行中</span><strong id="running">0</strong></div>
    <div class="card"><span>异常任务</span><strong id="unhealthy">0</strong></div>
    <div class="card"><span>活动事故</span><strong id="incident-count">0</strong></div>
  </section>
  <nav class="tabs" role="tablist" aria-label="监控视图">
    <button class="tab" id="tab-tasks" type="button" role="tab" aria-controls="panel-tasks" aria-selected="true" tabindex="0" data-tab="tasks">任务</button>
    <button class="tab" id="tab-collector" type="button" role="tab" aria-controls="panel-collector" aria-selected="false" tabindex="-1" data-tab="collector">Collector</button>
    <button class="tab" id="tab-scenario" type="button" role="tab" aria-controls="panel-scenario" aria-selected="false" tabindex="-1" data-tab="scenario">场景测试</button>
    <button class="tab" id="tab-runtimes" type="button" role="tab" aria-controls="panel-runtimes" aria-selected="false" tabindex="-1" data-tab="runtimes">运行时</button>
    <button class="tab" id="tab-incidents" type="button" role="tab" aria-controls="panel-incidents" aria-selected="false" tabindex="-1" data-tab="incidents">事故</button>
  </nav>
  <section class="tab-panel" id="panel-tasks" role="tabpanel" aria-labelledby="tab-tasks">
    <div class="view-grid">
      <section class="panel"><h2>任务列表</h2><div class="task-table-wrap"><table><thead><tr><th>任务</th><th>队列 / 类型</th><th>生命周期</th><th>健康</th><th>阶段</th><th>最近进度</th></tr></thead><tbody id="tasks"></tbody></table></div></section>
      <section class="panel detail-panel"><h2>进度时间线</h2><div id="detail" class="panel-body"><p class="empty">选择一条任务查看时间线。</p></div></section>
    </div>
  </section>
  <section class="tab-panel" id="panel-collector" role="tabpanel" aria-labelledby="tab-collector" hidden>
    <section class="panel"><div class="panel-title"><h2>Collector 状态</h2><div class="actions"><button type="button" data-probe="collector" data-endpoint="/api/v1/probes/collector" title="只执行健康检查，不会提交真实任务">立即探测 Collector</button><button type="button" data-probe="queue-source" data-endpoint="/api/v1/probes/queue-source" title="只读检查队列源，不会提交真实任务">立即探测队列源</button></div></div><div class="credential-row"><div class="credential-field"><label for="collector-api-key">API Key</label><input id="collector-api-key" type="password" maxlength="512" autocomplete="new-password" autocapitalize="off" spellcheck="false" title="未选择保存时，仅用于下一次 Collector 探测"></div><label class="credential-save" for="collector-api-key-save" title="API Key 将以明文保存在当前浏览器的 localStorage 中"><input id="collector-api-key-save" type="checkbox"><span>保存到此浏览器</span></label></div><div id="probe-result" class="panel-body muted" aria-live="polite">尚未执行手动探测。</div><div id="collector" class="panel-body"></div></section>
  </section>
  <section class="tab-panel" id="panel-scenario" role="tabpanel" aria-labelledby="tab-scenario" hidden>
    <section class="panel">
      <div class="panel-title"><h2>场景测试</h2></div>
      <div class="scenario-summary"><strong>关键词反查</strong><code>keyword-reverse</code><span class="muted">导出格式</span><span>JSON</span></div>
      <div class="credential-row"><div class="credential-field"><label for="scenario-api-key">API Key</label><input id="scenario-api-key" type="password" maxlength="512" autocomplete="new-password" autocapitalize="off" spellcheck="false" required title="未选择保存时，仅用于本次关键词反查提交"></div><label class="credential-save" for="scenario-api-key-save" title="API Key 将以明文保存在当前浏览器的 localStorage 中"><input id="scenario-api-key-save" type="checkbox"><span>保存到此浏览器</span></label></div>
      <form id="scenario-form" class="scenario-form" autocomplete="off">
        <div class="form-grid">
          <div class="field"><label for="scenario-asin">ASIN</label><input id="scenario-asin" maxlength="10" required autocapitalize="characters" spellcheck="false"></div>
          <div class="field"><label for="scenario-site">站点</label><input id="scenario-site" value="US" maxlength="2" required autocapitalize="characters" spellcheck="false"></div>
          <div class="field"><label for="scenario-period">周期</label><input id="scenario-period" value="30d" maxlength="7" required spellcheck="false"></div>
          <div class="field"><label for="scenario-page-size">每页数量</label><input id="scenario-page-size" type="number" min="1" max="100" value="100" required></div>
        </div>
        <label class="confirm-row" for="scenario-confirmed"><input id="scenario-confirmed" type="checkbox"><span>我确认该操作会创建真实任务并消耗额度</span></label>
        <div class="submit-row"><button id="scenario-submit" type="submit" disabled>提交关键词反查任务</button><span id="scenario-availability" class="muted">正在读取场景配置...</span></div>
        <div id="scenario-result" class="scenario-result muted" aria-live="polite">尚未提交场景测试。</div>
      </form>
    </section>
  </section>
  <section class="tab-panel" id="panel-runtimes" role="tabpanel" aria-labelledby="tab-runtimes" hidden>
    <section class="panel"><h2>运行时状态</h2><div id="runtimes" class="panel-body"></div></section>
  </section>
  <section class="tab-panel" id="panel-incidents" role="tabpanel" aria-labelledby="tab-incidents" hidden>
    <section class="panel"><h2>事故历史</h2><div id="incidents" class="panel-body"></div></section>
  </section>
</main>
<script>
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const age=v=>v?new Date(v).toLocaleString():"—";
async function json(url){const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();}
function badge(v){return `<span class="badge ${esc(v)}">${esc(v)}</span>`;}
function render(data){
  const life=data.summary?.by_lifecycle||{}, health=data.summary?.by_health||{};
  document.querySelector("#total").textContent=data.summary?.total||0;
  document.querySelector("#running").textContent=life.running||0;
  document.querySelector("#unhealthy").textContent=Object.entries(health).filter(([k])=>!["healthy"].includes(k)).reduce((n,[,v])=>n+v,0);
  document.querySelector("#incident-count").textContent=data.summary?.active_incident_count||0;
  document.querySelector("#updated").textContent=`更新于 ${age(data.generated_at)}`;
  const error=document.querySelector("#source-error");
  if(data.source?.ready){error.style.display="none";}else{error.style.display="block";error.textContent=data.source?.error?.message||"队列数据源未就绪";}
  document.querySelector("#tasks").innerHTML=(data.tasks||[]).map(t=>`<tr data-job="${esc(t.job_id)}" tabindex="0"><td><strong>${esc(t.job_id)}</strong></td><td>${esc(t.queue_scope)}<br><span class="muted">${esc(t.task_kind)}</span></td><td>${badge(t.lifecycle)}</td><td>${badge(t.health)}</td><td>${esc(t.progress_stage||"—")}</td><td>${age(t.progress_at)}</td></tr>`).join("")||'<tr><td colspan="6" class="empty">当前没有任务。</td></tr>';
  document.querySelectorAll("tr[data-job]").forEach(row=>{const open=()=>showDetail(row.dataset.job);row.addEventListener("click",open);row.addEventListener("keydown",e=>{if(e.key==="Enter")open();});});
  const incidents=data.incidents||[];
  document.querySelector("#incidents").innerHTML=incidents.map(i=>`<article class="incident"><strong><span>${esc(i.rule)}</span>${badge(i.status==="resolved"?"resolved":i.severity)}</strong><div>${esc(i.subject)}</div><div class="muted">${esc(i.message)} · ${i.status==="resolved"?"已恢复":"活动中"}</div></article>`).join("")||'<p class="empty">没有事故记录。</p>';
  const collector=data.collector||{}, modules=collector.modules||[];
  document.querySelector("#collector").innerHTML=`<div class="runtime"><strong>Collector MCP</strong>${badge(collector.status||"unknown")}<span class="muted">探测</span><span>${collector.enabled?"已配置":"未配置"}</span></div>`+modules.map(m=>`<div class="runtime"><strong>${esc(m.bundle_id)}</strong>${badge(m.status)}<span class="muted">队列 / 调度器</span><span>${esc(m.checks?.queue||"—")} / ${esc(m.checks?.scheduler||"—")}</span>${m.error_code?`<span class="muted">错误码</span><span>${esc(m.error_code)} (${esc(m.error_class||"unknown")})</span>`:""}</div>`).join("");
  document.querySelector("#runtimes").innerHTML=(data.runtimes||[]).map(r=>`<div class="runtime"><strong>${esc(r.execution_owner)}</strong>${badge(r.lifecycle_state)}<span class="muted">心跳</span><span>${age(r.heartbeat_at)}</span><span class="muted">通用 / Listing / 备用容量</span><span>${esc(r.generic_available_capacity)} / ${esc(r.listing_available_capacity)} / ${esc(r.standby_capacity)}</span></div>`).join("")||'<p class="empty">没有运行时心跳。</p>';
}
async function showDetail(job){try{const d=await json(`/api/v1/tasks/${encodeURIComponent(job)}`);document.querySelector("#detail").innerHTML=`<strong>${esc(d.job_id)}</strong><p>${badge(d.health)} ${esc(d.progress_stage||"")}</p><ol class="timeline">${(d.timeline||[]).map(e=>`<li><strong>${esc(e.progress_stage)}</strong><time>${age(e.progress_at)} · #${esc(e.progress_sequence)}</time></li>`).join("")||'<li class="empty">没有进度事件。</li>'}</ol>`;}catch(e){document.querySelector("#detail").innerHTML='<p class="empty">详情暂不可用。</p>';}}
const collectorKeyStorageKey="opscli.collector_monitor.collector_api_key";
const collectorKeyInput=document.querySelector("#collector-api-key");
const collectorKeySave=document.querySelector("#collector-api-key-save");
const probeOutput=document.querySelector("#probe-result");
const scenarioKeyInput=document.querySelector("#scenario-api-key");
const scenarioKeySave=document.querySelector("#scenario-api-key-save");
const scenarioOutput=document.querySelector("#scenario-result");
function removeStoredCollectorKey(){try{localStorage.removeItem(collectorKeyStorageKey);}catch{}}
function readStoredCollectorKey(){try{const value=localStorage.getItem(collectorKeyStorageKey)||"";if(!value||value.length>512||[...value].some(character=>character.charCodeAt(0)<32||character.charCodeAt(0)===127)){removeStoredCollectorKey();return "";}return value;}catch{return "";}}
function writeStoredCollectorKey(value){try{localStorage.setItem(collectorKeyStorageKey,value);return true;}catch{return false;}}
function clearStoredKeyState(){removeStoredCollectorKey();collectorKeySave.checked=false;scenarioKeySave.checked=false;}
function syncStoredCollectorKey(){if(!collectorKeySave.checked){clearStoredKeyState();return;}const value=collectorKeyInput.value.trim();if(!value){clearStoredKeyState();return;}if(writeStoredCollectorKey(value)){scenarioKeyInput.value=value;scenarioKeySave.checked=true;}else{clearStoredKeyState();probeOutput.textContent="浏览器禁止本地存储，API Key 未保存。";}}
function syncStoredScenarioKey(){if(!scenarioKeySave.checked){clearStoredKeyState();return;}const value=scenarioKeyInput.value.trim();if(!value){clearStoredKeyState();return;}if(writeStoredCollectorKey(value)){collectorKeyInput.value=value;collectorKeySave.checked=true;}else{clearStoredKeyState();scenarioOutput.textContent="浏览器禁止本地存储，API Key 未保存。";}}
async function probe(target,endpoint,button){button.disabled=true;let body="{}";const apiKey=collectorKeyInput.value.trim();if(target==="collector"&&apiKey){body=JSON.stringify({api_key:apiKey});if(collectorKeySave.checked){syncStoredCollectorKey();}else{collectorKeyInput.value="";}}probeOutput.textContent="探测中...";try{const r=await fetch(endpoint,{method:"POST",cache:"no-store",headers:{"Content-Type":"application/json"},body});body="{}";const d=await r.json();if(!r.ok){const wait=d.error?.retry_after?`，${d.error.retry_after} 秒后可再次探测`:"";throw new Error((d.error?.message||`HTTP ${r.status}`)+wait);}const diagnostic=d.error_code?`，${d.error_code} (${d.error_class||"unknown"})`:"";probeOutput.textContent=`${target}：${d.state} / ${d.status}${diagnostic}，${age(d.probed_at)}`;await refresh();}catch(e){probeOutput.textContent=`探测失败：${e.message}`;}finally{body="{}";button.disabled=false;}}
document.querySelectorAll("button[data-probe]").forEach(button=>button.addEventListener("click",()=>probe(button.dataset.probe,button.dataset.endpoint,button)));
const storedCollectorKey=readStoredCollectorKey();
collectorKeyInput.value=storedCollectorKey;
collectorKeySave.checked=Boolean(storedCollectorKey);
scenarioKeyInput.value=storedCollectorKey;
scenarioKeySave.checked=Boolean(storedCollectorKey);
collectorKeySave.addEventListener("change",syncStoredCollectorKey);
collectorKeyInput.addEventListener("input",()=>{if(collectorKeySave.checked)syncStoredCollectorKey();});
collectorKeyInput.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();document.querySelector('button[data-probe="collector"]').click();}});
scenarioKeySave.addEventListener("change",syncStoredScenarioKey);
scenarioKeyInput.addEventListener("input",()=>{if(scenarioKeySave.checked)syncStoredScenarioKey();});
async function loadScenarioContract(){const availability=document.querySelector("#scenario-availability"),button=document.querySelector("#scenario-submit");try{const data=await json("/api/v1/commands/scenario-test");const ready=data.enabled&&data.configured;button.disabled=!ready;availability.textContent=ready?"场景测试已启用":"场景测试未启用";if(data.defaults){document.querySelector("#scenario-site").value=data.defaults.site||"US";document.querySelector("#scenario-period").value=data.defaults.period||"30d";document.querySelector("#scenario-page-size").value=data.defaults.page_size||100;}}catch(e){button.disabled=true;availability.textContent="场景配置暂不可用";}}
async function submitScenario(event){event.preventDefault();const button=document.querySelector("#scenario-submit"),confirmed=document.querySelector("#scenario-confirmed");button.disabled=true;let payload={confirmed:confirmed.checked,asin:document.querySelector("#scenario-asin").value,site:document.querySelector("#scenario-site").value,period:document.querySelector("#scenario-period").value,page_size:Number(document.querySelector("#scenario-page-size").value)};const apiKey=scenarioKeyInput.value.trim();if(apiKey){payload.api_key=apiKey;if(scenarioKeySave.checked){syncStoredScenarioKey();}else{scenarioKeyInput.value="";}}scenarioOutput.textContent="正在提交...";try{const response=await fetch("/api/v1/commands/scenario-test",{method:"POST",cache:"no-store",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});payload={};const data=await response.json();if(!response.ok){const code=data.error?.code?` [${data.error.code}]`:"";throw new Error((data.error?.message||`HTTP ${response.status}`)+code);}scenarioOutput.textContent=`任务已排队：${data.job_id}（${data.state}）`;confirmed.checked=false;await refresh();}catch(e){scenarioOutput.textContent=`提交失败：${e.message}`;}finally{payload={};button.disabled=false;}}
document.querySelector("#scenario-form").addEventListener("submit",submitScenario);
const tabs=[...document.querySelectorAll('[role="tab"]')];
function selectTab(selected,{focus=true}={}){
  tabs.forEach(tab=>{
    const active=tab===selected;
    tab.setAttribute("aria-selected",String(active));
    tab.tabIndex=active?0:-1;
    document.querySelector(`#${tab.getAttribute("aria-controls")}`).hidden=!active;
  });
  if(focus)selected.focus();
}
tabs.forEach((tab,index)=>{
  tab.addEventListener("click",()=>selectTab(tab,{focus:false}));
  tab.addEventListener("keydown",event=>{
    let next=null;
    if(event.key==="ArrowRight")next=tabs[(index+1)%tabs.length];
    if(event.key==="ArrowLeft")next=tabs[(index-1+tabs.length)%tabs.length];
    if(event.key==="Home")next=tabs[0];
    if(event.key==="End")next=tabs[tabs.length-1];
    if(next){event.preventDefault();selectTab(next);}
  });
});
async function refresh(){try{render(await json("/api/v1/status"));}catch(e){const el=document.querySelector("#source-error");el.style.display="block";el.textContent="监控服务暂不可达";}}
loadScenarioContract(); refresh(); setInterval(refresh, 7000);
</script>
</body>
</html>"""
