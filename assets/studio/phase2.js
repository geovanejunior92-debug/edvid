(() => {
  const model = {
    jobKey: (job) => job ? `${job.id}:${job.status}:${job.updatedAt}` : "",
    latestJobForProject: (jobs, projectId) => jobs.find((item) => item.kind === "phase2" && item.projectId === projectId),
  };
  if (typeof module !== "undefined" && module.exports) module.exports = model;
  if (typeof window === "undefined") return;

  const phase = {
    revision: null,
    dataHash: null,
    approved: false,
    busy: false,
    lastJob: null,
    render: null,
    outputHash: null,
    delivery: null,
  };

  function updateControls() {
    const ready = Boolean(state.current && phase.revision && phase.dataHash);
    $("phase2-scaffold").disabled = phase.busy || !state.current;
    $("phase2-save").disabled = phase.busy || !state.current || !$("phase2-edit-data").value.trim();
    $("phase2-approve").disabled = phase.busy || !ready || !$("phase2-approve-check").checked;
    $("phase2-render").disabled = phase.busy || !ready || !phase.approved;
    $("phase2-review-approve").disabled = phase.busy || !phase.outputHash
      || Boolean(phase.delivery) || !$("phase2-review-check").checked;
  }

  function setBusy(value) {
    phase.busy = value;
    updateControls();
  }

  function showRevision(revision, dataHash, approval = null, render = null, delivery = null) {
    phase.revision = Number(revision) || null;
    phase.dataHash = typeof dataHash === "string" ? dataHash : null;
    phase.approved = Boolean(approval && approval.revision === phase.revision && approval.dataHash === phase.dataHash);
    phase.render = render?.output ? render : null;
    phase.outputHash = render?.fingerprint?.sha256 || null;
    phase.delivery = delivery?.outputHash === phase.outputHash ? delivery : null;
    $("phase2-approval").hidden = !phase.revision;
    $("phase2-revision").textContent = phase.revision ? `revisão ${phase.revision}` : "";
    $("phase2-summary").textContent = phase.delivery
      ? `Render revisado e aprovado para entrega em ${render.output}.`
      : (phase.render
        ? `Render concluído em ${render.output}. Assista ao arquivo inteiro antes de liberar.`
        : (phase.approved ? "Efeitos aprovados para o corte atual." : "Confira os efeitos no editor antes de aprovar."));
    $("phase2-approve-check").checked = false;
    $("phase2-review").hidden = !phase.render;
    $("phase2-review-check").checked = false;
    $("phase2-output-hash").textContent = phase.outputHash ? `Arquivo ${phase.outputHash.slice(0, 12)}…` : "";
    $("phase2-delivery-status").textContent = phase.delivery ? "aprovado para entrega" : "aguardando revisão integral";
    const player = $("phase2-output");
    if (phase.render && state.current) {
      player.src = `/project-media/${state.current.id}?path=${encodeURIComponent(`${state.current.path}/${phase.render.output}`)}`;
      player.load();
    } else {
      player.pause();
      player.removeAttribute("src");
      player.load();
    }
    $("phase2-state").textContent = phase.delivery ? "pronta para entrega"
      : (phase.render ? "aguardando revisão integral"
        : (phase.approved ? "aprovada" : (phase.revision ? "aguardando aprovação" : "sem estado")));
    updateControls();
  }

  async function dispatch(action, extra = {}) {
    if (!state.current || phase.busy) return;
    $("phase2-error").textContent = "";
    setBusy(true);
    try {
      await api("/api/jobs", { method: "POST", body: JSON.stringify({ projectId: state.current.id, kind: "phase2", action, ...extra }) });
      state.jobsSignature = null;
      await loadJobs();
    } catch (error) {
      $("phase2-error").textContent = error.message;
    } finally {
      setBusy(false);
    }
  }

  window.renderPhase2Jobs = (jobs) => {
    const job = model.latestJobForProject(jobs, state.current?.id);
    const key = model.jobKey(job);
    if (!job || key === phase.lastJob) return;
    phase.lastJob = key;
    if (job.status === "failed") {
      $("phase2-state").textContent = "falhou";
      $("phase2-error").textContent = job.error || "A Fase 2 falhou.";
      return;
    }
    if (job.status !== "completed") {
      $("phase2-state").textContent = job.status === "running" ? "em andamento" : "na fila";
      return;
    }
    const result = job.result || {};
    if (job.action === "save") showRevision(result.revision, result.dataHash);
    if (job.action === "approve" && result.revision === phase.revision && result.dataHash === phase.dataHash) {
      phase.approved = true;
      showRevision(phase.revision, phase.dataHash, result);
    }
    if (job.action === "render") {
      showRevision(phase.revision, phase.dataHash, { revision: phase.revision, dataHash: phase.dataHash }, result);
      const frame = $("editor-frame");
      if (frame.src) frame.src = frame.src;
    }
    if (job.action === "review-approve") {
      showRevision(phase.revision, phase.dataHash,
        { revision: phase.revision, dataHash: phase.dataHash }, phase.render, result);
    }
    if (job.action === "scaffold") $("phase2-state").textContent = "preparada";
  };

  window.loadPhase2 = async () => {
    const projectId = state.current?.id;
    phase.revision = null; phase.dataHash = null; phase.approved = false; phase.lastJob = null;
    phase.render = null; phase.outputHash = null; phase.delivery = null;
    $("phase2-error").textContent = "";
    $("phase2-approval").hidden = true;
    $("phase2-review").hidden = true;
    if (!state.current) return updateControls();
    try {
      const result = await api(`/api/phase2/${state.current.id}`);
      if (state.current?.id !== projectId) return;
      const saved = result.state || {};
      showRevision(saved.revision, saved.dataHash, saved.approval, saved.render, saved.delivery);
      if (!saved.revision && saved.scaffold) $("phase2-state").textContent = "preparada";
    } catch (error) {
      $("phase2-error").textContent = error.message;
    }
    updateControls();
  };

  $("phase2-edit-data").addEventListener("input", updateControls);
  $("phase2-approve-check").addEventListener("change", updateControls);
  $("phase2-review-check").addEventListener("change", updateControls);
  $("phase2-scaffold").addEventListener("click", () => dispatch("scaffold"));
  $("phase2-save").addEventListener("click", () => dispatch("save", { editData: $("phase2-edit-data").value.trim() }));
  $("phase2-approve").addEventListener("click", () => dispatch("approve", { revision: phase.revision, dataHash: phase.dataHash, approve: true }));
  $("phase2-render").addEventListener("click", () => dispatch("render", { revision: phase.revision, dataHash: phase.dataHash }));
  $("phase2-review-approve").addEventListener("click", () => dispatch("review-approve", {
    outputHash: phase.outputHash,
    fullReview: true,
  }));
  updateControls();
})();
