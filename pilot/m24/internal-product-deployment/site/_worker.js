export default {
  async fetch(request, env) {
    const host = new URL(request.url).host;
    if (
      host === "llm-wiki-m24-internal.pages.dev" ||
      host.endsWith(".llm-wiki-m24-internal.pages.dev")
    ) {
      return new Response("Forbidden", {
        status: 403,
        headers: {
          "cache-control": "no-store",
          "content-type": "text/plain; charset=utf-8",
        },
      });
    }

    return env.ASSETS.fetch(request);
  },
};
