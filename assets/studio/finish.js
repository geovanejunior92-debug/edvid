(() => {
  const model = {
    latestJobForProject: (jobs, projectId) => jobs.find((item) => item.kind === "finish" && item.projectId === projectId),
    jobKey: (job) => job ? `${job.id}:${job.status}:${job.updatedAt}` : "",
    qcPassed: (qc) => Boolean(qc && Array.isArray(qc.fails) && qc.fails.length === 0),
    canUseRevision: ({latest, approved, dirty}) => Boolean(latest && approved && !dirty),
    draftFromSettings: (saved) => {
      const captions = saved?.captions || {mode: "none"};
      const importedAsCues = captions.mode === "import" && Array.isArray(captions.cues);
      const headline = saved?.headline || {enabled: false};
      const insert = Array.isArray(saved?.inserts) ? saved.inserts[0] : null;
      const music = saved?.music || {enabled: false};
      return {
        "finish-platform": saved?.platform || "reels",
        "finish-caption-mode": importedAsCues ? "manual" : (captions.mode || "none"),
        "finish-caption-cues": captions.cues || [],
        "finish-caption-file": captions.file || "", "finish-caption-burn": captions.burn !== false,
        "finish-caption-size": captions.fontSize ?? 48, "finish-headline-enabled": Boolean(headline.enabled),
        "finish-headline-text": headline.text || "", "finish-headline-start": headline.start ?? 0,
        "finish-headline-end": headline.end ?? 3, "finish-insert-file": insert?.file || "",
        "finish-insert-start": insert?.start ?? 0, "finish-insert-end": insert?.end ?? 3,
        "finish-insert-layout": insert?.layout || "fullscreen", "finish-music-enabled": Boolean(music.enabled),
        "finish-music-file": music.file || "", "finish-music-gain": music.gainDb ?? -18,
        "finish-music-fade-in": music.fadeIn ?? 1, "finish-music-fade-out": music.fadeOut ?? 1,
        "finish-music-ducking": music.duckingDb ?? -10,
      };
    },
  };
  if (typeof module !== "undefined" && module.exports) module.exports = model;
  if (typeof window === "undefined") return;

  const finish = { busy: false, projectId: null, latest: null, approved: false, render: null,
                   review: null, lastJob: null, dirty: false, editSequence: 0,
                   pendingSaveSequence: null, drafts: new Map(), dirtyDrafts: new Map() };
  const ids = ["finish-platform", "finish-caption-mode", "finish-caption-file",
    "finish-caption-burn", "finish-caption-size", "finish-headline-enabled", "finish-headline-text",
    "finish-headline-start", "finish-headline-end", "finish-insert-file", "finish-insert-start",
    "finish-insert-end", "finish-insert-layout", "finish-music-enabled", "finish-music-file",
    "finish-music-gain", "finish-music-fade-in", "finish-music-fade-out", "finish-music-ducking"];

  function readForm() {
    const values = Object.fromEntries(ids.map((id) => {
      const field = $(id); return [id, field.type === "checkbox" ? field.checked : field.value];
    }));
    values["finish-caption-cues"] = [...$("finish-caption-cues").querySelectorAll(".caption-cue")].map((row) => ({
      start: Number(row.querySelector("[data-cue=start]").value), end: Number(row.querySelector("[data-cue=end]").value),
      text: row.querySelector("[data-cue=text]").value.trim(),
    }));
    return values;
  }
  function renderCues(cues) {
    const root = $("finish-caption-cues"); root.replaceChildren();
    for (const cue of cues || []) {
      const row = document.createElement("div"); row.className = "caption-cue";
      row.innerHTML = '<label>Início (s)<input data-cue="start" type="number" min="0" step="0.1"></label><label>Fim (s)<input data-cue="end" type="number" min="0" step="0.1"></label><label class="cue-text">Texto<input data-cue="text" maxlength="500"></label><button class="text-button danger" type="button" aria-label="Remover trecho">Remover</button>';
      row.querySelector("[data-cue=start]").value = cue.start ?? 0;
      row.querySelector("[data-cue=end]").value = cue.end ?? 1;
      row.querySelector("[data-cue=text]").value = cue.text || "";
      row.querySelectorAll("input").forEach((input) => input.addEventListener("input", markDirty));
      row.querySelector("button").addEventListener("click", () => { row.remove(); markDirty(); });
      root.append(row);
    }
  }
  function writeForm(values) {
    if (!values) return;
    for (const [id, value] of Object.entries(values)) {
      if (id === "finish-caption-cues") continue;
      const field = $(id); if (!field) continue;
      if (field.type === "checkbox") field.checked = Boolean(value); else field.value = value ?? "";
    }
    renderCues(values["finish-caption-cues"] || []);
    captionMode();
  }
  const defaultForm = readForm();
  function draftFromSettings(saved) {
    return model.draftFromSettings(saved);
  }
  window.beforeProjectChange = () => {
    if (finish.projectId) {
      finish.drafts.set(finish.projectId, readForm());
      finish.dirtyDrafts.set(finish.projectId, finish.dirty);
    }
  };
  function number(id) { return Number($(id).value); }
  function settings() {
    const mode = $("finish-caption-mode").value;
    const captions = {mode, burn: $("finish-caption-burn").checked, fontSize: number("finish-caption-size")};
    if (mode === "manual") {
      captions.cues = readForm()["finish-caption-cues"];
    }
    if (mode === "import") captions.file = $("finish-caption-file").value.trim();
    const headline = {enabled: $("finish-headline-enabled").checked, text: $("finish-headline-text").value.trim(),
                      start: number("finish-headline-start"), end: number("finish-headline-end")};
    const insertFile = $("finish-insert-file").value.trim();
    const inserts = insertFile ? [{file: insertFile, start: number("finish-insert-start"),
      end: number("finish-insert-end"), layout: $("finish-insert-layout").value}] : [];
    const music = {enabled: $("finish-music-enabled").checked, file: $("finish-music-file").value.trim(),
      gainDb: number("finish-music-gain"), fadeIn: number("finish-music-fade-in"),
      fadeOut: number("finish-music-fade-out"), duckingDb: number("finish-music-ducking")};
    return {version: 1, platform: $("finish-platform").value, captions, headline, inserts, music};
  }
  function captionMode() {
    const mode = $("finish-caption-mode").value;
    $("finish-caption-manual").hidden = mode !== "manual";
    $("finish-caption-import").hidden = mode !== "import";
  }
  function pathForProject(path) {
    if (!path || !state.current) return "";
    return path.startsWith("/") ? path : `${state.current.path}/${path}`;
  }
  function setBusy(value) {
    finish.busy = value;
    updateControls();
  }
  function updateControls() {
    const exactApproval = model.canUseRevision(finish);
    $("finish-save").disabled = finish.busy || !state.current;
    $("finish-approve").disabled = finish.busy || finish.dirty || !finish.latest || !$("finish-approve-check").checked;
    $("finish-render").disabled = finish.busy || !exactApproval;
    const qcPassed = model.qcPassed(finish.render?.qc);
    const awaitsReview = finish.render?.deliveryStatus === "awaiting-visual-review";
    $("finish-review-check").disabled = !qcPassed || !awaitsReview;
    $("finish-review-approve").disabled = finish.busy || !qcPassed || !awaitsReview || !$("finish-review-check").checked;
  }
  async function dispatch(action, extra = {}) {
    if (!state.current || finish.busy) return;
    const projectId = state.current.id;
    $("finish-error").textContent = ""; setBusy(true);
    if (action === "save") finish.pendingSaveSequence = finish.editSequence;
    try {
      await api("/api/jobs", {method: "POST", body: JSON.stringify({projectId, kind: "finish", action, ...extra})});
      state.jobsSignature = null; await loadJobs();
    } catch (error) { if (state.current?.id === projectId) $("finish-error").textContent = error.message; }
    finally { if (state.current?.id === projectId) setBusy(false); }
  }
  function showLatest(value) {
    finish.latest = value || null; finish.approved = false;
    finish.render = null; finish.review = null;
    $("finish-review").hidden = true;
    $("finish-preview").pause(); $("finish-preview").removeAttribute("src"); $("finish-preview").load();
    $("finish-review-check").checked = false;
    $("finish-approve-check").checked = false;
    $("finish-approval").hidden = !value;
    if (!value) return updateControls();
    $("finish-revision").textContent = `revisão ${value.revision}`;
    const fingerprint = value.cutFingerprint || {};
    $("finish-fingerprint").textContent = fingerprint.sha256
      ? `Corte ${fingerprint.sha256.slice(0, 12)}… · ${Number(fingerprint.size || 0).toLocaleString("pt-BR")} bytes`
      : "Aprovação vinculada ao corte atual e ao hash destas configurações.";
    $("finish-state").textContent = `revisão ${value.revision} pendente`;
    updateControls();
  }
  async function hydrateLatest(value, projectId) {
    if (!value?.settings || !state.current || state.current.id !== projectId) return;
    const editSequence = finish.editSequence;
    finish.dirty = true; updateControls();
    const path = pathForProject(value.settings);
    const response = await fetch(`/project-media/${projectId}?path=${encodeURIComponent(path)}`);
    if (!response.ok) throw new Error("Não foi possível carregar as configurações salvas.");
    const doc = await response.json();
    if (state.current?.id !== projectId || finish.projectId !== projectId
        || finish.latest?.settingsHash !== value.settingsHash || finish.editSequence !== editSequence) return;
    const hydrated = draftFromSettings(doc.settings);
    writeForm(hydrated); finish.drafts.set(projectId, hydrated); finish.dirtyDrafts.set(projectId, false); finish.dirty = false; updateControls();
  }
  function showRender(value, review) {
    finish.render = value || null; finish.review = review || null;
    $("finish-review").hidden = !value;
    if (!value) return updateControls();
    const approved = review?.deliveryStatus === "approved" || value.deliveryStatus === "approved";
    $("finish-delivery-status").textContent = approved ? "revisão visual aprovada" : "aguardando revisão visual";
    const passed = model.qcPassed(value.qc);
    $("finish-qc-summary").textContent = passed ? "Os gates automáticos passaram. A revisão visual integral ainda é obrigatória."
      : "A entrega permanece bloqueada porque os gates automáticos não passaram.";
    const reports = $("finish-qc-reports"); reports.replaceChildren();
    const sheets = Array.isArray(value.reviewSheets) ? value.reviewSheets : [];
    for (const path of sheets) {
      const link = document.createElement("a"); link.textContent = path.split("/").pop(); link.target = "_blank";
      link.href = `/project-media/${state.current.id}?path=${encodeURIComponent(pathForProject(path))}`; reports.append(link);
    }
    const output = value.output;
    const video = $("finish-preview");
    if (output) video.src = `/project-media/${state.current.id}?path=${encodeURIComponent(pathForProject(output))}`;
    else video.removeAttribute("src");
    $("finish-output-hash").textContent = value.outputHash ? `Arquivo ${value.outputHash}` : "";
    $("finish-review-check").checked = approved;
    $("finish-state").textContent = approved ? "entrega aprovada" : (passed ? "revisão visual pendente" : "QC bloqueou entrega");
    updateControls();
  }
  window.renderFinishJobs = (jobs) => {
    const job = model.latestJobForProject(jobs, state.current?.id);
    const key = model.jobKey(job);
    if (!job || key === finish.lastJob) return;
    finish.lastJob = key;
    if (job.status === "failed") $("finish-error").textContent = job.error || "A finalização falhou.";
    if (job.status !== "completed") return;
    const result = job.result || {};
    if (job.action === "save") {
      const unchangedSinceSubmit = finish.pendingSaveSequence === finish.editSequence;
      showLatest(result); finish.dirty = !unchangedSinceSubmit;
      if (unchangedSinceSubmit) hydrateLatest(result, state.current.id).catch((error) => { $("finish-error").textContent = error.message; });
      finish.pendingSaveSequence = null;
    }
    if (job.action === "approve" && finish.latest && result.revision === finish.latest.revision
        && result.settingsHash === finish.latest.settingsHash) {
      finish.approved = true; finish.render = null; finish.review = null; $("finish-review").hidden = true;
      $("finish-review-check").checked = false; $("finish-state").textContent = `revisão ${result.revision} aprovada`; updateControls();
    }
    if (job.action === "render") showRender(result, null);
    if (job.action === "review-approve") showRender(finish.render, result);
  };
  window.loadFinish = async () => {
    const projectId = state.current?.id; finish.projectId = projectId; finish.lastJob = null;
    finish.latest = null; finish.approved = false; finish.render = null; finish.review = null;
    finish.dirty = Boolean(finish.dirtyDrafts.get(projectId)); finish.editSequence = 0; finish.pendingSaveSequence = null;
    $("finish-approval").hidden = true; $("finish-review").hidden = true; $("finish-error").textContent = "";
    writeForm(finish.drafts.get(projectId) || defaultForm);
    if (!projectId) return updateControls();
    try {
      const result = await api(`/api/finish/${projectId}`);
      if (state.current?.id !== projectId) return;
      const saved = result.state || {};
      if (saved.latest) { showLatest(saved.latest); if (!finish.dirty) await hydrateLatest(saved.latest, projectId); }
      if (state.current?.id !== projectId || finish.projectId !== projectId) return;
      finish.approved = Boolean(saved.approval && saved.latest && saved.approval.revision === saved.latest.revision
        && saved.approval.settingsHash === saved.latest.settingsHash);
      if (saved.render) showRender(saved.render, saved.review);
    } catch (error) { if (state.current?.id === projectId) $("finish-error").textContent = error.message; }
    updateControls();
  };

  $("finish-caption-mode").addEventListener("change", captionMode);
  $("finish-caption-add").addEventListener("click", () => {
    renderCues([...readForm()["finish-caption-cues"], {start: 0, end: 1, text: ""}]); markDirty();
  });
  function markDirty() {
    if (!finish.projectId) return;
    finish.editSequence += 1; finish.dirty = true; finish.approved = false; $("finish-approve-check").checked = false;
    $("finish-state").textContent = "alterações não salvas"; updateControls();
  }
  for (const id of ids) $(id).addEventListener("input", markDirty);
  $("finish-approve-check").addEventListener("change", updateControls);
  $("finish-review-check").addEventListener("change", updateControls);
  $("finish-save").addEventListener("click", () => { try { dispatch("save", {settings: settings()}); } catch (error) { $("finish-error").textContent = error.message; } });
  $("finish-approve").addEventListener("click", () => dispatch("approve", {revision: finish.latest.revision,
    settingsHash: finish.latest.settingsHash, approve: $("finish-approve-check").checked}));
  $("finish-render").addEventListener("click", () => dispatch("render", {revision: finish.latest.revision,
    settingsHash: finish.latest.settingsHash}));
  $("finish-review-approve").addEventListener("click", () => dispatch("review-approve", {
    outputHash: finish.render.outputHash, fullReview: $("finish-review-check").checked}));
  document.querySelectorAll(".finish-picker").forEach((button) => {
    if (window.webkit?.messageHandlers?.chooseMedia) {
      button.hidden = false; button.addEventListener("click", () => window.webkit.messageHandlers.chooseMedia.postMessage({
        projectPath: state.current?.path || "", target: button.dataset.target}));
    }
  });
  window.addEventListener("edvid-finish-media", (event) => {
    const targets = {"finish-music": "finish-music-file", "finish-insert": "finish-insert-file", "finish-captions": "finish-caption-file"};
    const field = targets[event.detail?.target];
    if (field && typeof event.detail?.path === "string") { $(field).value = event.detail.path; markDirty(); }
  });
  captionMode(); updateControls();
})();
