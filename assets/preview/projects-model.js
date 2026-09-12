(function (global) {
  'use strict';
  const model = {
    automaticRequest(sources, idempotencyKey) {
      if (!Array.isArray(sources) || sources.length !== 1 || typeof sources[0]?.id !== 'string') return null;
      return {mode: 'automatic', text: 'corte automático', sources: [sources[0].id], idempotencyKey};
    },
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = model;
  if (global) global.EdvidProjectsModel = model;
})(typeof globalThis !== 'undefined' ? globalThis : this);
