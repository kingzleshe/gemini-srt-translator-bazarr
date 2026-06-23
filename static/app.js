const state = {
  view: "dashboard",
  settings: null,
  languages: [],
  selectedSources: [],
  selectedTargets: [],
  scanItems: [],
  models: [],
};

const SECRET_MASK = "**********";

const titles = {
  dashboard: ["Dashboard", "Bazarr subtitles to Gemini translated targets."],
  wanted: ["Wanted", "Bazarr missing subtitles that can be translated from configured sources."],
  scan: ["Scan", "Find local source subtitles missing configured targets."],
  queue: ["Queue", "Translation jobs by state."],
  settings: ["Settings", "Bazarr connection, languages, and scan behavior."],
  system: ["System", "Backups and service maintenance."],
  logs: ["Logs", "Recent worker output."],
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2600);
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.id === view));
  document.querySelectorAll(".nav").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  document.getElementById("view-title").textContent = titles[view][0];
  document.getElementById("view-subtitle").textContent = titles[view][1];
  refresh();
}

async function loadLanguages() {
  const data = await api("/api/languages");
  state.languages = data.items || [];
  renderLanguageSelect("source");
  renderLanguageSelect("target");
}

async function loadModels() {
  const data = await api("/api/gemini-models");
  state.models = data.items || [];
}

async function loadStatus() {
  const status = await api("/api/status");
  const queue = status.queue || {};
  document.getElementById("metric-pending").textContent = queue.pending || 0;
  document.getElementById("metric-processing").textContent = queue.processing || 0;
  document.getElementById("metric-done").textContent = queue.done || 0;
  document.getElementById("metric-failed").textContent = queue.failed || 0;
  state.settings = status.settings;
  fillSettings(status.settings);
  renderDashboardLanguages();
}

function languageByCode(code) {
  return state.languages.find((language) => language.code === code);
}

function displayLanguage(item) {
  const match = languageByCode(item.code);
  const name = match ? match.name : item.language;
  return `${item.code} - ${name}`;
}

function renderChipList(id, items) {
  const el = document.getElementById(id);
  el.innerHTML = "";
  items.forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = displayLanguage(item);
    el.appendChild(chip);
  });
}

function renderDashboardLanguages() {
  renderChipList("source-list", state.selectedSources);
  renderChipList("target-list", state.selectedTargets);
}

function renderModelSelect(selectedModel) {
  const select = document.getElementById("gst-model-select");
  if (!select) return;
  const selected = selectedModel || "gemini-flash-latest";
  const models = [...state.models];
  if (!models.some((model) => model.id === selected)) {
    models.unshift({ id: selected, name: selected });
  }
  select.innerHTML = "";
  models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.name;
    select.appendChild(option);
  });
  select.value = selected;
}

function selectedList(kind) {
  return kind === "source" ? state.selectedSources : state.selectedTargets;
}

function setSelectedList(kind, list) {
  if (kind === "source") state.selectedSources = list;
  else state.selectedTargets = list;
}

function renderLanguageSelect(kind) {
  const select = document.getElementById(`${kind}-language-select`);
  if (!select) return;
  const selectedCodes = new Set(selectedList(kind).map((item) => item.code));
  const options = state.languages.filter((language) => !selectedCodes.has(language.code));
  select.innerHTML = "";
  if (!options.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No languages available";
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  select.disabled = false;
  options.forEach((language) => {
    const option = document.createElement("option");
    option.value = language.code;
    option.textContent = `${language.code} - ${language.name}${language.enabled_in_bazarr ? " *" : ""}`;
    select.appendChild(option);
  });
}

function renderSelectedLanguages(kind) {
  const container = document.getElementById(`selected-${kind}-languages`);
  const items = selectedList(kind);
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "No languages selected";
    container.appendChild(empty);
    renderLanguageSelect(kind);
    return;
  }

  items.forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "language-chip";
    chip.appendChild(document.createTextNode(displayLanguage(item)));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.onclick = () => {
      setSelectedList(kind, items.filter((candidate) => candidate.code !== item.code));
      renderSelectedLanguages(kind);
      renderDashboardLanguages();
    };
    chip.appendChild(remove);
    container.appendChild(chip);
  });
  renderLanguageSelect(kind);
}

function addLanguage(kind) {
  const select = document.getElementById(`${kind}-language-select`);
  const language = languageByCode(select.value);
  if (!language) return;
  const items = selectedList(kind);
  if (items.some((item) => item.code === language.code)) return;
  setSelectedList(kind, [
    ...items,
    {
      code: language.code,
      language: language.language,
      enabled: true,
    },
  ]);
  renderSelectedLanguages(kind);
  renderDashboardLanguages();
}

function fillSettings(settings) {
  if (!settings) return;
  state.selectedSources = (settings.source_languages || []).map((item) => ({
    code: item.code,
    language: item.language,
    enabled: item.enabled !== false,
  }));
  state.selectedTargets = (settings.target_languages || []).map((item) => ({
    code: item.code,
    language: item.language,
    enabled: item.enabled !== false,
  }));
  document.getElementById("bazarr-url-input").value = settings.bazarr_url || "";
  document.getElementById("bazarr-api-key-input").value = settings.bazarr_api_key || "";
  document.getElementById("gemini-api-key-input").value = settings.gemini_api_key || "";
  document.getElementById("gemini-api-key2-input").value = settings.gemini_api_key2 || "";
  document.getElementById("tmdb-api-key-input").value = settings.tmdb_api_key || "";
  document.getElementById("bazarr-key-status").textContent = settings.bazarr_api_key_configured
    ? "API key is configured."
    : "No API key configured.";
  document.getElementById("gemini-key-status").textContent = settings.gemini_api_key_configured
    ? "API key 1 is configured."
    : "No Gemini API key 1 configured.";
  document.getElementById("gemini-key2-status").textContent = settings.gemini_api_key2_configured
    ? "API key 2 is configured."
    : "No Gemini API key 2 configured.";
  document.getElementById("tmdb-key-status").textContent = settings.tmdb_api_key_configured
    ? "TMDB API key is configured."
    : "No TMDB API key configured.";
  renderModelSelect(settings.gst_model);
  document.getElementById("gst-batch-size-input").value = settings.gst_batch_size || 1000;
  document.getElementById("job-settle-seconds-input").value = settings.job_settle_seconds ?? 600;
  document.getElementById("gst-paid-quota-input").checked = Boolean(settings.gst_paid_quota);
  document.getElementById("gst-skip-upgrade-input").checked = settings.gst_skip_upgrade !== false;
  document.getElementById("gst-quiet-input").checked = settings.gst_quiet !== false;
  document.getElementById("gst-progress-log-input").checked = Boolean(settings.gst_progress_log);
  document.getElementById("gst-thoughts-log-input").checked = Boolean(settings.gst_thoughts_log);
  document.getElementById("gst-temperature-input").value = settings.gst_temperature || "";
  document.getElementById("gst-top-p-input").value = settings.gst_top_p || "";
  document.getElementById("gst-top-k-input").value = settings.gst_top_k || "";
  document.getElementById("gst-thinking-budget-input").value = settings.gst_thinking_budget || "";
  document.getElementById("gst-thinking-level-select").value = settings.gst_thinking_level || "";
  document.getElementById("gst-no-streaming-input").checked = Boolean(settings.gst_no_streaming);
  document.getElementById("gst-no-thinking-input").checked = Boolean(settings.gst_no_thinking);
  document.getElementById("gst-no-context-input").checked = Boolean(settings.gst_no_context);
  document.getElementById("roots-input").value = (settings.media_roots || []).join("\n");
  document.getElementById("scan-limit-input").value = settings.scan_limit || 200;
  renderSelectedLanguages("source");
  renderSelectedLanguages("target");
}

function parseSettings() {
  const roots = document.getElementById("roots-input").value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return {
    bazarr_url: document.getElementById("bazarr-url-input").value.trim(),
    bazarr_api_key: document.getElementById("bazarr-api-key-input").value.trim(),
    gemini_api_key: document.getElementById("gemini-api-key-input").value.trim(),
    gemini_api_key2: document.getElementById("gemini-api-key2-input").value.trim(),
    tmdb_api_key: document.getElementById("tmdb-api-key-input").value.trim(),
    gst_model: document.getElementById("gst-model-select").value,
    gst_batch_size: Number(document.getElementById("gst-batch-size-input").value || 1000),
    job_settle_seconds: Number(document.getElementById("job-settle-seconds-input").value || 0),
    gst_paid_quota: document.getElementById("gst-paid-quota-input").checked,
    gst_skip_upgrade: document.getElementById("gst-skip-upgrade-input").checked,
    gst_quiet: document.getElementById("gst-quiet-input").checked,
    gst_progress_log: document.getElementById("gst-progress-log-input").checked,
    gst_thoughts_log: document.getElementById("gst-thoughts-log-input").checked,
    gst_temperature: document.getElementById("gst-temperature-input").value.trim(),
    gst_top_p: document.getElementById("gst-top-p-input").value.trim(),
    gst_top_k: document.getElementById("gst-top-k-input").value.trim(),
    gst_thinking_budget: document.getElementById("gst-thinking-budget-input").value.trim(),
    gst_thinking_level: document.getElementById("gst-thinking-level-select").value,
    gst_no_streaming: document.getElementById("gst-no-streaming-input").checked,
    gst_no_thinking: document.getElementById("gst-no-thinking-input").checked,
    gst_no_context: document.getElementById("gst-no-context-input").checked,
    source_languages: state.selectedSources,
    target_languages: state.selectedTargets,
    media_roots: roots,
    scan_limit: Number(document.getElementById("scan-limit-input").value || 200),
  };
}

async function saveSettings() {
  const saved = await api("/api/settings", { method: "POST", body: JSON.stringify(parseSettings()) });
  state.settings = saved;
  fillSettings(saved);
  renderDashboardLanguages();
  toast("Settings saved");
  if (state.view === "system") await loadBackups();
}

async function testConnection(kind, statusId) {
  const status = document.getElementById(statusId);
  status.textContent = "Testing...";
  const data = await api("/api/test-connection", {
    method: "POST",
    body: JSON.stringify({ ...parseSettings(), kind }),
  });
  status.textContent = data.message || (data.ok ? "OK" : "Failed");
  status.classList.toggle("status-ok", Boolean(data.ok));
  status.classList.toggle("status-warn", !data.ok);
  toast(data.message || (data.ok ? "Connection OK" : "Connection failed"));
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(epochSeconds) {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleString();
}

function renderBackups(items) {
  const el = document.getElementById("backup-list");
  if (!el) return;
  el.innerHTML = "";
  if (!items.length) {
    el.innerHTML = `<div class="muted">No backups</div>`;
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "backup-row";
    row.innerHTML = `
      <div>
        <strong>${item.name}</strong>
        <div class="muted">${item.path}</div>
      </div>
      <div>${formatBytes(item.size)}</div>
      <div>${formatDate(item.created_at)}</div>
    `;
    const actions = document.createElement("div");
    const download = document.createElement("button");
    download.type = "button";
    download.textContent = "Download";
    download.onclick = () => downloadBackup(item.name);
    actions.appendChild(download);
    row.appendChild(actions);
    el.appendChild(row);
  });
}

async function loadBackups() {
  const data = await api("/api/backups");
  renderBackups(data.items || []);
}

async function createBackup() {
  const data = await api("/api/backups", { method: "POST", body: "{}" });
  toast(`Backup created: ${data.backup.name}`);
  await loadBackups();
}

function downloadBackup(name) {
  window.location.href = `/api/backups/download?name=${encodeURIComponent(name)}`;
}

async function importBackup() {
  const input = document.getElementById("backup-file-input");
  const file = input.files && input.files[0];
  if (!file) {
    toast("Choose a backup zip first");
    return;
  }
  if (!window.confirm("Import this backup? Current settings and post-processing targets will be replaced after a pre-import backup is created.")) {
    return;
  }
  const response = await fetch("/api/backups/import", {
    method: "POST",
    headers: { "Content-Type": "application/zip" },
    body: file,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  input.value = "";
  toast(`Backup imported. Pre-import backup: ${payload.pre_import_backup.name}`);
  await loadStatus();
  await loadBackups();
}

async function loadQueue() {
  const snapshot = await api("/api/queue");
  const el = document.getElementById("queue-list");
  el.innerHTML = "";
  ["pending", "processing", "done", "failed"].forEach((name) => {
    const col = document.createElement("div");
    col.className = "queue-col";
    col.innerHTML = `<h3>${name} (${snapshot.counts[name] || 0})</h3>`;
    (snapshot[name] || []).forEach((job) => {
      const card = document.createElement("div");
      card.className = "job";
      card.innerHTML = `
        <div class="job-title">${job.source_code || "?"} -> ${job.target_code || "?"}</div>
        <div class="muted">${job.subtitle_path || job.job_id}</div>
        ${job.error ? `<div class="status-warn">${job.error}</div>` : ""}
      `;
      if (name === "failed") {
        const retry = document.createElement("button");
        retry.textContent = "Retry";
        retry.onclick = async () => {
          await api("/api/queue/retry", { method: "POST", body: JSON.stringify({ job_id: job.job_id }) });
          await refresh();
        };
        card.appendChild(retry);
      }
      col.appendChild(card);
    });
    el.appendChild(col);
  });
}

function renderItems(containerId, items) {
  const el = document.getElementById(containerId);
  el.innerHTML = "";
  if (!items.length) {
    el.innerHTML = `<div class="row"><div class="muted">No items</div></div>`;
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "row";
    const targets = (item.missing_targets || []).map((target) => target.code).join(", ");
    const source = item.source_code ? `${item.source_code} ->` : "";
    row.innerHTML = `
      <div class="row-title">
        <strong>${item.title || item.subtitle_path}</strong>
        <div class="muted">${item.subtitle_path || "No configured source subtitle found"}</div>
      </div>
      <div>${source} ${targets}</div>
      <div>${item.can_enqueue === false ? '<span class="status-warn">No source</span>' : '<span class="status-ok">Ready</span>'}</div>
    `;
    const btn = document.createElement("button");
    btn.textContent = "Enqueue";
    btn.disabled = item.can_enqueue === false;
    btn.onclick = async () => {
      const payload = {
        ...item,
        media_type: item.type || item.media_type || "movie",
        target_codes: (item.missing_targets || []).map((target) => target.code),
      };
      await api("/api/enqueue", { method: "POST", body: JSON.stringify(payload) });
      toast("Queued");
      await loadQueue();
    };
    row.children[2].appendChild(document.createTextNode(" "));
    row.children[2].appendChild(btn);
    el.appendChild(row);
  });
}

async function loadWanted() {
  const data = await api("/api/wanted");
  renderItems("wanted-list", data.items || []);
}

async function loadScan() {
  const data = await api("/api/scan");
  state.scanItems = data.items || [];
  renderItems("scan-list", state.scanItems.map((item) => ({ ...item, can_enqueue: true })));
}

async function enqueueScan() {
  const data = await api("/api/enqueue-scan", { method: "POST", body: "{}" });
  toast(`Queued ${data.count} jobs`);
  await loadQueue();
}

async function loadLogs() {
  const data = await api("/api/logs");
  document.getElementById("log-output").textContent = (data.lines || []).join("\n");
}

async function clearLogs() {
  await api("/api/logs/clear", { method: "POST", body: "{}" });
  document.getElementById("log-output").textContent = "";
  toast("Logs cleared");
}

async function refresh() {
  try {
    await loadLanguages();
    await loadModels();
    await loadStatus();
    if (state.view === "queue") await loadQueue();
    if (state.view === "wanted") await loadWanted();
    if (state.view === "scan") await loadScan();
    if (state.view === "system") await loadBackups();
    if (state.view === "logs") await loadLogs();
  } catch (error) {
    toast(error.message);
  }
}

document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("save-settings").addEventListener("click", saveSettings);
document.getElementById("create-backup").addEventListener("click", createBackup);
document.getElementById("import-backup").addEventListener("click", importBackup);
document.getElementById("clear-logs").addEventListener("click", clearLogs);
document.getElementById("test-bazarr-key").addEventListener("click", () => testConnection("bazarr", "bazarr-key-status"));
document.getElementById("test-gemini-key").addEventListener("click", () => testConnection("gemini_api_key", "gemini-key-status"));
document.getElementById("test-gemini-key2").addEventListener("click", () => testConnection("gemini_api_key2", "gemini-key2-status"));
document.getElementById("test-tmdb-key").addEventListener("click", () => testConnection("tmdb_api_key", "tmdb-key-status"));
document.getElementById("add-source-language").addEventListener("click", () => addLanguage("source"));
document.getElementById("add-target-language").addEventListener("click", () => addLanguage("target"));
document.getElementById("load-wanted").addEventListener("click", loadWanted);
document.getElementById("load-scan").addEventListener("click", loadScan);
document.getElementById("enqueue-scan").addEventListener("click", enqueueScan);

refresh();
