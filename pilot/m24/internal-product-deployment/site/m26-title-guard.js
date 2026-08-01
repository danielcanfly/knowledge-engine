(function () {
  const FULL_GRAPH_TITLE = "Full Knowledge Graph";

  function isFullGraphSurface() {
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

  function enforceTitle() {
    if (!isFullGraphSurface()) return;
    const routeTitle = document.querySelector("#route-title");
    if (routeTitle && routeTitle.textContent !== FULL_GRAPH_TITLE) {
      routeTitle.textContent = FULL_GRAPH_TITLE;
      routeTitle.setAttribute("data-pa7-full-graph-title", "true");
    }
    if (document.title !== FULL_GRAPH_TITLE) {
      document.title = FULL_GRAPH_TITLE;
    }
  }

  enforceTitle();
  document.addEventListener("DOMContentLoaded", enforceTitle);
  window.addEventListener("popstate", enforceTitle);
  window.addEventListener("hashchange", enforceTitle);
  const observer = new MutationObserver(enforceTitle);
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
  });
  window.setInterval(enforceTitle, 250);
})();
