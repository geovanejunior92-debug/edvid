const state = { projects: [], current: null, jobsSignature: null, musicSubmitting: false };
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Erro ${response.status}`);
  return data;
}

function formatTime(value) {
  return value ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value * 1000)) : "—";
}

function renderProjects() {
  const list = $("project-list");
  list.replaceChildren();
  if (!state.projects.length) {
    const p = document.createElement("p"); p.className = "muted"; p.textContent = "A biblioteca está vazia."; list.append(p); return;
  }
  state.projects.forEach((project) => {
    const button = document.createElement("button");
    button.className = `project-card ${state.current?.id === project.id ? "active" : ""}`;
    button.innerHTML = `<strong></strong><span></span><small></small>`;
    button.querySelector("strong").textContent = project.name;
    button.querySelector("span").textContent = project.path;
    button.querySelector("small").textContent = project.available ? `Atualizado ${formatTime(project.updatedAt)}` : "Pasta indisponível";
    button.addEventListener("click", () => selectProject(project));
    list.append(button);
  });
}

function selectProject(project) {
  const video = $("raw-preview");
  video.pause(); video.removeAttribute("src"); video.load(); video.hidden = true;
  state.current = project;
  $("empty").hidden = true; $("project").hidden = false;
  $("project-name").textContent = project.name;
  $("project-location").textContent = project.path;
  $("media-path").value = "";
  $("music-confirm").checked = false;
  updateMusicButton();
  renderProjects();
  window.loadPipeline?.();
}

async function loadProjects() {
  const data = await api("/api/projects"); state.projects = data.projects;
  if (state.current) state.current = state.projects.find((x) => x.id === state.current.id) || null;
  renderProjects();
}

async function loadJobs() {
  const { jobs } = await api("/api/jobs");
  window.renderPipelineJobs?.(jobs);
  const signature = JSON.stringify(jobs);
  if (signature === state.jobsSignature) return;
  state.jobsSignature = signature;
  const root = $("jobs"); root.replaceChildren();
  if (!jobs.length) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "Nenhuma tarefa registrada."; root.append(p); return; }
  jobs.forEach((job) => {
    const row = document.createElement("article"); row.className = "job";
    const names = { probe: "Análise", proxy: "Proxy", music: "Música Treblo", pipeline: "Fase 1" };
    row.innerHTML = `<div><strong></strong><span class="pill"></span></div><p></p><small></small>`;
    row.querySelector("strong").textContent = names[job.kind] || job.kind;
    row.querySelector(".pill").textContent = ({queued:"na fila",running:"em andamento",completed:"concluída",failed:"falhou",cancelled:"cancelada",interrupted:"interrompida"})[job.status] || job.status;
    const format = job.result?.format;
    let summary = job.error || job.output || job.input;
    if (job.kind === "pipeline") summary = job.error || job.action;
    if (job.status === "completed" && format) {
      const seconds = Number(format.duration || 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
      const megabytes = (Number(format.size || 0) / 1048576).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
      summary = `${seconds} s · ${megabytes} MB · ${format.format_name || "formato não identificado"}`;
    }
    row.querySelector("p").textContent = summary;
    row.querySelector("small").textContent = formatTime(job.updatedAt);
    if (job.kind === "music" && job.provider?.taskId) {
      const remote = document.createElement("span");
      remote.className = "remote-task";
      remote.textContent = `Tarefa Treblo: ${job.provider.taskId}${job.provider.status ? ` · ${job.provider.status}` : ""}`;
      row.append(remote);
    }
    if (job.kind === "music" && job.output && (job.status === "completed" || job.provider?.status === "downloaded")) {
      const player = document.createElement("audio");
      player.controls = true;
      player.preload = "metadata";
      player.src = `/project-media/${job.projectId}?path=${encodeURIComponent(job.output)}`;
      row.append(player);
    }
    if (["queued", "running"].includes(job.status)) {
      const cancel = document.createElement("button"); cancel.className = "text-button danger"; cancel.textContent = "Cancelar";
      cancel.addEventListener("click", async () => { await api(`/api/jobs/${job.id}/cancel`, { method: "POST", body: "{}" }); await loadJobs(); });
      row.firstChild.append(cancel);
    }
    root.append(row);
  });
}

async function loadDiagnostics() {
  const data = await api("/api/diagnostics");
  const labels = { python: "Python", ffmpeg: "FFmpeg", ffprobe: "FFprobe", dataDir: "Dados locais", queueRunning: "Tarefa ativa" };
  const dl = $("diagnostics"); dl.replaceChildren();
  Object.entries(data).forEach(([key, value]) => { const dt=document.createElement("dt"), dd=document.createElement("dd"); dt.textContent=labels[key]||key; dd.textContent=value||(key === "queueRunning" ? "Nenhuma" : "indisponível"); dl.append(dt,dd); });
}

$("project-form").addEventListener("submit", async (event) => {
  event.preventDefault(); $("project-error").textContent = "";
  try {
    const item = await api("/api/projects", { method: "POST", body: JSON.stringify({ path: $("project-path").value, create: $("create-project").checked }) });
    await loadProjects(); selectProject(item); $("project-path").value = "";
  } catch (error) { $("project-error").textContent = error.message; }
});

async function enqueue(kind) {
  $("job-error").textContent = "";
  if (!state.current) return;
  try { await api("/api/jobs", { method: "POST", body: JSON.stringify({ projectId: state.current.id, kind, input: $("media-path").value }) }); await loadJobs(); }
  catch (error) { $("job-error").textContent = error.message; }
}
function updateMusicButton() {
  $("generate-music").disabled = state.musicSubmitting || !state.current || !$("music-confirm").checked || !$("music-prompt").value.trim();
}
async function loadTrebloProvider() {
  const provider = await api("/api/providers/treblo");
  $("treblo-config").textContent = provider.configured ? "configurada" : "não configurada";
  $("treblo-config").classList.toggle("bad", !provider.configured);
}
async function checkTrebloConnection() {
  $("music-error").textContent = "";
  $("music-status").textContent = "Testando conexão…";
  try {
    const result = await api("/api/providers/treblo/check", { method: "POST", body: "{}" });
    const credits = result.balance?.num_credits;
    const payg = result.balance?.num_credits_payg;
    const values = [credits != null ? `${credits} créditos` : "", payg != null ? `${payg} avulsos` : ""].filter(Boolean);
    $("music-status").textContent = `Autenticada${values.length ? ` · ${values.join(" · ")}` : ""}`;
  } catch (error) {
    $("music-status").textContent = "Conexão não autenticada.";
    $("music-error").textContent = error.message;
  }
}
async function enqueueMusic() {
  $("music-error").textContent = "";
  if (!state.current || state.musicSubmitting) return;
  state.musicSubmitting = true;
  const confirmed = $("music-confirm").checked;
  $("music-confirm").checked = false;
  updateMusicButton();
  try {
    await api("/api/jobs", { method: "POST", body: JSON.stringify({
      projectId: state.current.id, kind: "music", prompt: $("music-prompt").value,
      lengthMin: Number($("music-min").value), lengthMax: Number($("music-max").value),
      confirmed,
    }) });
    await loadJobs();
  } catch (error) { $("music-error").textContent = error.message; }
  finally { state.musicSubmitting = false; updateMusicButton(); }
}
function previewMedia() {
  if (!state.current || !$("media-path").value.trim()) return;
  const video = $("raw-preview");
  video.src = `/project-media/${state.current.id}?path=${encodeURIComponent($("media-path").value.trim())}`;
  video.hidden = false;
}
$("probe").addEventListener("click", () => enqueue("probe"));
$("proxy").addEventListener("click", () => enqueue("proxy"));
$("media-path").addEventListener("change", previewMedia);
$("refresh").addEventListener("click", loadDiagnostics);
$("music-confirm").addEventListener("change", updateMusicButton);
$("music-prompt").addEventListener("input", updateMusicButton);
$("generate-music").addEventListener("click", enqueueMusic);
$("treblo-check").addEventListener("click", checkTrebloConnection);
$("open-editor").addEventListener("click", () => { window.location.href = `/editor/${state.current.id}/`; });

const nativeFolder = window.webkit?.messageHandlers?.chooseFolder;
const nativeMedia = window.webkit?.messageHandlers?.chooseMedia;
if (nativeFolder) { $("choose-folder").hidden=false; $("choose-folder").addEventListener("click", () => nativeFolder.postMessage(null)); }
if (nativeMedia) { $("choose-media").hidden=false; $("choose-media").addEventListener("click", () => nativeMedia.postMessage({ projectPath: state.current?.path || "" })); }
window.addEventListener("edvid-folder", (event) => { if (typeof event.detail === "string") $("project-path").value=event.detail; });
window.addEventListener("edvid-media", (event) => { if (typeof event.detail === "string") { $("media-path").value=event.detail; previewMedia(); } });

Promise.all([loadProjects(), loadJobs(), loadDiagnostics(), loadTrebloProvider()]).catch((error) => { $("service-status").textContent = error.message; $("service-status").classList.add("bad"); });
setInterval(() => loadJobs().catch(() => {}), 1200);
