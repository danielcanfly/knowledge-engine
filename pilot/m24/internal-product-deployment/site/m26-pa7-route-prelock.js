(function () {
  const MARKER = "m26-pa7-route-prelock";

  function isFullGraphUrl() {
    try {
      const url = new URL(location.href);
      return (
        (url.pathname === "/ask" || url.pathname === "/ask/") &&
        url.searchParams.get("surface") === "full-graph"
      );
    } catch (_error) {
      return false;
    }
  }

  function prelockFullGraphRoute() {
    if (!isFullGraphUrl()) return;
    document.documentElement.setAttribute("data-m26-pa7-route-prelock", "true");
    document.documentElement.setAttribute("data-m26-pa7-full-graph-route", "true");
    if (location.hash) {
      const nextUrl = `${location.pathname}${location.search}`;
      history.replaceState(null, "", nextUrl);
    }
    window.__M26_PA7_FULL_GRAPH_ROUTE_PRELOCK__ = {
      marker: MARKER,
      active: true,
      pathname: location.pathname,
      search: location.search,
      hash_cleared: !location.hash,
    };
  }

  prelockFullGraphRoute();
})();
