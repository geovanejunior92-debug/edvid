(function (root, factory) {
  const model = factory();
  if (typeof module === 'object' && module.exports) module.exports = model;
  root.EdvidRequestsModel = model;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  return {
    shouldRefreshSources(search, pendingRequest) {
      return new URLSearchParams(search).get('sources') === '1' || Boolean(pendingRequest?.payload);
    },
  };
});
