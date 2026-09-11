(() => {
  const model = {
    planRanges: (plan) => Array.isArray(plan?.edl?.ranges) ? plan.edl.ranges : [],
    jobKey: (job) => job ? `${job.id}:${job.status}:${job.updatedAt}` : "",
    shouldProcessJob: (job, lastKey) => Boolean(job) && model.jobKey(job) !== lastKey,
    latestJobForProject: (jobs, projectId) => jobs.find((item) => item.kind === "pipeline" && item.projectId === projectId),
  };
  if (typeof module !== "undefined" && module.exports) module.exports = model;
  if (typeof window === "undefined") return;
  const phase = { plan: null, approved: false, busy: false, lastJob: null };

  function sourcePath() { return $("media-path").value.trim(); }
  function setBusy(value) {
    phase.busy = value;
    for (const id of ["pipeline-save-brief", "pipeline-transcribe", "pipeline-propose", "pipeline-approve",
                      "pipeline-render", "pipeline-apply-preview", "pipeline-undo", "pipeline-redo"]) $(id).disabled = value;
    updateControls();
  }
  function updateControls() {
    const hasSource = Boolean(state.current && sourcePath());
    $("pipeline-transcribe").disabled = phase.busy || !hasSource;
    $("pipeline-propose").disabled = phase.busy || !hasSource;
    $("pipeline-save-brief").disabled = phase.busy || !state.current || !$("pipeline-script").value.trim();
    $("pipeline-approve").disabled = phase.busy || !phase.plan || !$("pipeline-approve-check").checked;
    $("pipeline-render").disabled = phase.busy || !phase.plan || !phase.approved;
    $("pipeline-source").textContent = hasSource ? `Fonte: ${sourcePath()}` : "Fonte: escolha um vídeo acima.";
  }
  async function dispatch(action, extra = {}) {
    if (!state.current || phase.busy) return;
    $("pipeline-error").textContent = "";
    setBusy(true);
    try {
      await api("/api/jobs", {method: "POST", body: JSON.stringify({projectId: state.current.id, kind: "pipeline", action, ...extra})});
      state.jobsSignature = null;
      await loadJobs();
    } catch (error) { $("pipeline-error").textContent = error.message; }
    finally { setBusy(false); }
  }
  async function showPlan(result) {
    const projectId = state.current?.id;
    phase.plan = {revision: result.revision, planHash: result.planHash, path: result.plan, projectId};
    phase.approved = false;
    $("pipeline-approve-check").checked = false;
    $("pipeline-plan").hidden = false;
    $("pipeline-plan-id").textContent = `revisão ${result.revision}`;
    const knownRanges = Number.isInteger(result.ranges) ? `${result.ranges} blocos` : "carregando blocos";
    const knownDuration = Number.isFinite(Number(result.totalDuration)) ? ` · ${Number(result.totalDuration).toLocaleString("pt-BR", {maximumFractionDigits: 1})} s` : "";
    $("pipeline-plan-summary").textContent = `${knownRanges}${knownDuration}`;
    $("pipeline-ranges").replaceChildren();
    if (result.plan && state.current) {
      try {
        const path = `${state.current.path}/${result.plan}`;
        const response = await fetch(`/project-media/${state.current.id}?path=${encodeURIComponent(path)}`);
        const plan = await response.json();
        if (state.current?.id !== projectId || phase.plan?.projectId !== projectId || phase.plan?.planHash !== result.planHash) return;
        const ranges = model.planRanges(plan);
        const duration = Number(plan?.edl?.total_duration_s);
        $("pipeline-plan-summary").textContent = `${ranges.length} blocos${Number.isFinite(duration) ? ` · ${duration.toLocaleString("pt-BR", {maximumFractionDigits: 1})} s` : ""}`;
        for (const item of ranges) {
          const row = document.createElement("p");
          row.textContent = `${Number(item.start).toFixed(2)}–${Number(item.end).toFixed(2)} s · ${item.transcript || item.beat || "bloco de fala"}`;
          $("pipeline-ranges").append(row);
        }
      } catch (_) { /* O resumo da proposta continua disponível. */ }
    }
    updateControls();
  }
  window.renderPipelineJobs = (jobs) => {
    const job = model.latestJobForProject(jobs, state.current?.id);
    const jobKey = model.jobKey(job);
    if (!model.shouldProcessJob(job, phase.lastJob)) return;
    phase.lastJob = jobKey;
    if (job.status === "failed") $("pipeline-error").textContent = job.error || "A ação da Fase 1 falhou.";
    if (job.status !== "completed") return;
    const result = job.result || {};
    if (job.action === "propose-cut") showPlan(result);
    if (job.action === "approve-plan" && phase.plan && result.revision === phase.plan.revision && result.planHash === phase.plan.planHash) {
      phase.approved = true; updateControls();
    }
    if (["apply-preview-edits", "undo", "redo"].includes(job.action)) {
      if (result.requiresApproval && result.plan) showPlan(result);
      else {
        phase.plan = null; phase.approved = false; $("pipeline-plan").hidden = true;
        $("pipeline-approve-check").checked = false; updateControls();
      }
    }
    $("pipeline-state").textContent = `${job.action} · concluído`;
  };
  window.loadPipeline = async () => {
    const projectId = state.current?.id;
    phase.plan = null; phase.approved = false; phase.lastJob = null;
    $("pipeline-plan").hidden = true; $("pipeline-error").textContent = "";
    if (!state.current) return updateControls();
    try {
      const result = await api(`/api/pipeline/${state.current.id}`);
      if (state.current?.id !== projectId) return;
      const last = result.state?.lastCommand;
      $("pipeline-state").textContent = last ? `${last.action} · ${last.ok ? "concluído" : "falhou"}` : "sem ações";
      const history = result.state?.history || [];
      const proposal = [...history].reverse().find((item) => item.ok && item.plan
        && (item.action === "propose-cut" || item.requiresApproval));
      if (proposal) {
        await showPlan(proposal);
        const proposalIndex = history.lastIndexOf(proposal);
        const later = history.slice(proposalIndex + 1);
        phase.approved = later.some((item) => item.action === "approve-plan" && item.ok
          && item.revision === proposal.revision && item.planHash === proposal.planHash)
          && !later.some((item) => ["apply-preview-edits", "undo", "redo"].includes(item.action));
      }
    } catch (error) { $("pipeline-error").textContent = error.message; }
    updateControls();
  };

  $("pipeline-script").addEventListener("input", updateControls);
  $("media-path").addEventListener("input", updateControls);
  $("media-path").addEventListener("change", updateControls);
  $("pipeline-approve-check").addEventListener("change", updateControls);
  $("pipeline-save-brief").addEventListener("click", () => dispatch("save-brief", {script: $("pipeline-script").value}));
  $("pipeline-transcribe").addEventListener("click", () => dispatch("transcribe", {source: sourcePath(), language: $("pipeline-language").value}));
  $("pipeline-propose").addEventListener("click", () => dispatch("propose-cut", {source: sourcePath()}));
  $("pipeline-approve").addEventListener("click", () => phase.plan && dispatch("approve-plan", {revision: phase.plan.revision, planHash: phase.plan.planHash, approve: true}));
  $("pipeline-render").addEventListener("click", () => phase.plan && phase.approved && dispatch("render-cut", {revision: phase.plan.revision, planHash: phase.plan.planHash}));
  $("pipeline-apply-preview").addEventListener("click", () => dispatch("apply-preview-edits", {previewEdits: "edit/preview_edits.json"}));
  $("pipeline-undo").addEventListener("click", () => dispatch("undo"));
  $("pipeline-redo").addEventListener("click", () => dispatch("redo"));
  updateControls();
})();
