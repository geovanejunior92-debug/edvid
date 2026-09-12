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

const PROJECT_ICONS = {
  pin: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.3l1.9 4 4.4.6-3.2 3.1.8 4.4L8 11.3l-3.9 2.1.8-4.4L1.7 5.9l4.4-.6z"/></svg>',
  rename: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11.6 1.9l2.5 2.5-8 8L3 13l.6-3.1zM2 14.6h12v1.1H2z"/></svg>',
  archive: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.6 2.6h12.8v2.6H1.6zM2.8 6.4h10.4v7H2.8zm2.6 2.1h5.2v1.2H5.4z"/></svg>',
  restore: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.6a5.4 5.4 0 105.1 7.1h-1.7A3.8 3.8 0 118 4.2v2.1l3-2.8L8 .6z"/></svg>',
};

function projectAction(label, icon, handler, pressed) {
  const button = document.createElement("button");
  button.type = "button"; button.className = "project-action"; button.innerHTML = icon;
  button.title = label; button.setAttribute("aria-label", label);
  if (pressed !== undefined) button.setAttribute("aria-pressed", String(Boolean(pressed)));
  button.addEventListener("click", (event) => { event.stopPropagation(); handler(); });
  return button;
}

async function updateProject(project, patch) {
  try {
    const updated = await api("/api/projects/update", {
      method: "POST", body: JSON.stringify({ projectId: project.id, ...patch }),
    });
    Object.assign(project, updated);
    await loadProjects();
    return true;
  } catch (error) {
    $("project-notice").textContent = error.message;
    return false;
  }
}

function startProjectRename(card, project) {
  const heading = card.querySelector(".project-card-body strong");
  const input = document.createElement("input");
  input.className = "project-rename"; input.value = project.name; input.maxLength = 100;
  const finish = async (commit) => {
    if (!input.isConnected) return;
    const name = input.value.trim(); input.replaceWith(heading);
    if (commit && name && name !== project.name) await updateProject(project, { name });
  };
  input.addEventListener("click", (event) => event.stopPropagation());
  input.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Enter") { event.preventDefault(); finish(true); }
    if (event.key === "Escape") { event.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
  heading.replaceWith(input); input.focus(); input.select();
}

function projectCard(project) {
  const card = document.createElement("article");
  card.className = `project-card ${project.pinned ? "pinned" : ""} ${state.current?.id === project.id ? "active" : ""}`;
  card.tabIndex = 0; card.setAttribute("role", "button"); card.setAttribute("aria-label", `Abrir ${project.name}`);
  card.innerHTML = '<span class="project-poster" aria-hidden="true"></span><span class="project-card-body"><em></em><strong></strong><span></span><small></small><span class="project-actions"></span></span>';
  const poster = card.querySelector(".project-poster");
  if (project.thumbnail) {
    const image = document.createElement("img"); image.alt = ""; image.loading = "lazy";
    image.src = `/project-media/${project.id}?path=${encodeURIComponent(project.thumbnail)}`;
    poster.append(image);
  } else {
    poster.textContent = (project.name.trim()[0] || "E").toLocaleUpperCase("pt-BR");
  }
  card.querySelector("em").textContent = project.available ? "CONTINUAR EDIÇÃO" : "LOCALIZAR PASTA";
  card.querySelector("strong").textContent = project.name;
  card.querySelector(".project-card-body > span:not(.project-actions)").textContent = project.path;
  card.querySelector("small").textContent = project.available ? `Atualizado ${formatTime(project.updatedAt)}` : "Pasta indisponível";
  const actions = card.querySelector(".project-actions");
  if (project.archived) {
    actions.append(projectAction("Tirar do arquivo", PROJECT_ICONS.restore,
      () => updateProject(project, { archived: false })));
  } else {
    actions.append(
      projectAction(project.pinned ? "Desafixar projeto" : "Fixar projeto no topo", PROJECT_ICONS.pin,
        () => updateProject(project, { pinned: !project.pinned }), project.pinned),
      projectAction("Renomear projeto", PROJECT_ICONS.rename, () => startProjectRename(card, project)),
      projectAction("Arquivar projeto sem apagar arquivos", PROJECT_ICONS.archive, async () => {
        if (!await updateProject(project, { archived: true })) return;
        const notice = $("project-notice");
        notice.replaceChildren(document.createTextNode(`“${project.name}” foi arquivado. Nenhum arquivo foi apagado. `));
        const undo = document.createElement("button"); undo.type = "button"; undo.className = "text-button"; undo.textContent = "Desfazer";
        undo.addEventListener("click", () => updateProject(project, { archived: false })); notice.append(undo);
      }),
    );
  }
  card.addEventListener("click", (event) => {
    if (!event.target.closest(".project-action, .project-rename")) selectProject(project);
  });
  card.addEventListener("keydown", (event) => {
    if (event.target !== card || !["Enter", " "].includes(event.key)) return;
    event.preventDefault(); selectProject(project);
  });
  return card;
}

function renderProjects() {
  const list = $("project-list");
  list.replaceChildren();
  const query = $("project-search").value.trim().toLocaleLowerCase("pt-BR");
  const matches = state.projects.filter((project) => !query
    || `${project.name} ${project.path}`.toLocaleLowerCase("pt-BR").includes(query));
  const visible = matches.filter((project) => !project.archived);
  const archived = matches.filter((project) => project.archived);
  $("project-notice").textContent = visible.length
    ? `${visible.length} projeto(s)`
    : (state.projects.some((project) => project.archived) ? "Nenhum projeto ativo encontrado." : "A biblioteca está vazia.");
  if (!visible.length) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = query ? "Tente outro nome ou caminho." : "Adicione uma pasta para começar.";
    list.append(p);
  }
  visible.forEach((project) => list.append(projectCard(project)));
  const archivedBox = $("archived-projects");
  archivedBox.hidden = !archived.length;
  $("archived-count").textContent = `Arquivados (${archived.length})`;
  const archivedList = $("archived-list"); archivedList.replaceChildren();
  archived.forEach((project) => archivedList.append(projectCard(project)));
}

function setStudioTab(name, { toggle = false } = {}) {
  const toolbox = document.querySelector(".toolbox");
  const isOpen = toolbox.classList.contains("drawer-open");
  const isSame = document.querySelector(`[data-studio-tab="${name}"]`)?.classList.contains("active");
  document.querySelectorAll("[data-studio-tab]").forEach((button) => {
    const active = button.dataset.studioTab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-studio-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.studioPanel !== name;
  });
  toolbox.classList.toggle("drawer-open", !(toggle && isSame && isOpen));
}

function showLibrary() {
  window.beforeProjectChange?.();
  const video = $("raw-preview");
  video.pause(); video.removeAttribute("src"); video.load(); video.hidden = true;
  state.current = null;
  document.body.classList.remove("has-project");
  $("top-project").hidden = true;
  $("project").hidden = true;
  $("editor-frame").removeAttribute("src");
  renderProjects();
}

function selectProject(project) {
  window.beforeProjectChange?.();
  const video = $("raw-preview");
  video.pause(); video.removeAttribute("src"); video.load(); video.hidden = true;
  state.current = project;
  document.body.classList.add("has-project");
  $("empty").hidden = true; $("project").hidden = false; $("top-project").hidden = false;
  $("project-name").textContent = project.name;
  $("project-location").textContent = project.path;
  $("top-project-name").textContent = project.name;
  $("top-project-path").textContent = project.path;
  $("editor-frame").src = `/editor/${project.id}/?embedded=1`;
  $("media-path").value = "";
  $("music-confirm").checked = false;
  updateMusicButton();
  setStudioTab("project");
  document.querySelector(".toolbox").classList.remove("drawer-open");
  renderProjects();
  window.loadPipeline?.();
  window.loadPhase2?.();
  window.loadFinish?.();
}

async function loadProjects() {
  const data = await api("/api/projects"); state.projects = data.projects;
  if (state.current) state.current = state.projects.find((x) => x.id === state.current.id) || null;
  renderProjects();
}

async function loadJobs() {
  const { jobs } = await api("/api/jobs");
  window.renderPipelineJobs?.(jobs);
  window.renderPhase2Jobs?.(jobs);
  window.renderFinishJobs?.(jobs);
  const signature = JSON.stringify(jobs);
  if (signature === state.jobsSignature) return;
  state.jobsSignature = signature;
  const root = $("jobs"); root.replaceChildren();
  if (!jobs.length) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "Nenhuma tarefa registrada."; root.append(p); return; }
  jobs.forEach((job) => {
    const row = document.createElement("article"); row.className = "job";
    const names = { probe: "Análise", proxy: "Proxy", music: "Música Treblo", pipeline: "Fase 1", phase2: "Fase 2 Remotion", finish: "Finalização manual" };
    row.innerHTML = `<div><strong></strong><span class="pill"></span></div><p></p><small></small>`;
    row.querySelector("strong").textContent = names[job.kind] || job.kind;
    row.querySelector(".pill").textContent = ({queued:"na fila",running:"em andamento",completed:"concluída",failed:"falhou",cancelled:"cancelada",interrupted:"interrompida"})[job.status] || job.status;
    const format = job.result?.format;
    let summary = job.error || job.output || job.input;
    if (job.kind === "pipeline") summary = job.error || job.action;
    if (job.kind === "finish") summary = job.error || job.action;
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
$("project-search").addEventListener("input", renderProjects);
$("back-library").addEventListener("click", showLibrary);
document.querySelectorAll("[data-studio-tab]").forEach((button) => button.addEventListener("click", () => setStudioTab(button.dataset.studioTab, { toggle: true })));
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
