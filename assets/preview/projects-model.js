(function (global) {
  'use strict';
  const model = {
    automaticRequest(sources, idempotencyKey) {
      if (!Array.isArray(sources) || sources.length !== 1 || typeof sources[0]?.id !== 'string') return null;
      return {mode: 'automatic', text: 'corte automático', sources: [sources[0].id], idempotencyKey};
    },
    // The shelf, split and ordered. Archived projects are never mixed into the
    // main list — they are still there, behind their own disclosure, because
    // archiving hides a card and deletes nothing.
    libraryView(items, query) {
      const term = String(query || '').trim().toLocaleLowerCase();
      const matches = (p) => !term || String(p.name || '').toLocaleLowerCase().includes(term);
      const rank = (a, b) => (Number(!!b.pinned) - Number(!!a.pinned)) || ((b.updatedAt || 0) - (a.updatedAt || 0));
      const list = (Array.isArray(items) ? items : []).filter(matches);
      return {
        visible: list.filter((p) => !p.archived).sort(rank),
        archived: list.filter((p) => p.archived).sort(rank),
      };
    },
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = model;
  if (global) global.EdvidProjectsModel = model;
})(typeof globalThis !== 'undefined' ? globalThis : this);
