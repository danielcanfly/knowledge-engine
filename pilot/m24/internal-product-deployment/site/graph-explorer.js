(function () {
  "use strict";

  const NODE_COLORS = {
    architecture: "#0f766e",
    component: "#1d4ed8",
    concept: "#0f766e",
    contract: "#7c3aed",
    decision: "#b45309",
    process: "#be123c",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function normalize(value) {
    return String(value ?? "").normalize("NFKC").trim().toLocaleLowerCase("en-US");
  }

  function stableHash(value) {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function positionFor(nodeId, index, count) {
    const phase = (stableHash(nodeId) / 0xffffffff) * Math.PI * 2;
    const angle = phase + (index / Math.max(count, 1)) * Math.PI * 2;
    const radius = 5 + (stableHash(`${nodeId}:radius`) % 1000) / 140;
    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
  }

  function nodeIdOf(node) {
    return node.concept_id || node.id || node.node_id;
  }

  function nodeTitle(node) {
    return node.title || node.label || nodeIdOf(node);
  }

  function stringList(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
  }

  function buildGraphologyGraph(payload) {
    const Graphology = window.graphology;
    if (typeof Graphology !== "function") {
      throw new Error("graphology browser runtime unavailable");
    }
    const graph = new Graphology({ allowSelfLoops: false, multi: true, type: "mixed" });
    const nodes = [...(payload.nodes || [])].sort((left, right) =>
      nodeIdOf(left).localeCompare(nodeIdOf(right)),
    );
    nodes.forEach((node, index) => {
      const nodeId = nodeIdOf(node);
      const position = positionFor(nodeId, index, nodes.length);
      const semanticType = node.type || node.concept_type || "concept";
      const semanticTypeKey = normalize(semanticType || "concept");
      graph.addNode(nodeId, {
        ...node,
        color: NODE_COLORS[semanticTypeKey] || "#64748b",
        label: nodeTitle(node),
        semanticType,
        semanticTypeKey,
        size: node.focus_node ? 9 : 6,
        title: nodeTitle(node),
        type: "circle",
        x: position.x,
        y: position.y,
      });
    });
    for (const edge of [...(payload.edges || [])].sort((left, right) =>
      left.edge_id.localeCompare(right.edge_id),
    )) {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
      const attrs = {
        ...edge,
        color: edge.focus_edge ? "#0f766e" : "#94a3b8",
        label: edge.relation_type || "related",
        relationType: edge.relation_type || "related",
        size: edge.focus_edge ? 2 : 1,
      };
      if (edge.directed === false) {
        graph.addUndirectedEdgeWithKey(edge.edge_id, edge.source, edge.target, attrs);
      } else {
        graph.addDirectedEdgeWithKey(edge.edge_id, edge.source, edge.target, attrs);
      }
    }
    graph.setAttribute("readOnly", true);
    graph.setAttribute("releaseId", payload.release_id);
    return graph;
  }

  function selection(graph, nodeId, sourceCountsByConcept) {
    const attrs = graph.getNodeAttributes(nodeId);
    return {
      id: nodeId,
      title: attrs.title || nodeId,
      type: attrs.semanticType || "concept",
      description: attrs.description || attrs.summary || "",
      sourcePath: attrs.source_path || attrs.path || "",
      sourceCount: Number(sourceCountsByConcept?.[nodeId] || 0),
      tags: stringList(attrs.tags),
    };
  }

  function searchMatches(graph, query) {
    const normalizedQuery = normalize(query);
    if (!normalizedQuery) return [];
    return graph
      .nodes()
      .map((nodeId) => {
        const attrs = graph.getNodeAttributes(nodeId);
        const title = normalize(attrs.title || nodeId);
        const aliases = stringList(attrs.aliases).map(normalize);
        const tags = stringList(attrs.tags).map(normalize);
        const description = normalize(attrs.description || attrs.summary || "");
        let score = null;
        if (title === normalizedQuery) score = 0;
        else if (aliases.includes(normalizedQuery)) score = 1;
        else if (title.startsWith(normalizedQuery)) score = 2;
        else if (aliases.some((alias) => alias.startsWith(normalizedQuery))) score = 3;
        else if (title.includes(normalizedQuery)) score = 4;
        else if (aliases.some((alias) => alias.includes(normalizedQuery))) score = 5;
        else if (tags.some((tag) => tag.includes(normalizedQuery))) score = 6;
        else if (description.includes(normalizedQuery)) score = 7;
        else if (normalize(nodeId).includes(normalizedQuery)) score = 8;
        return score === null ? null : { id: nodeId, score, title: attrs.title || nodeId };
      })
      .filter(Boolean)
      .sort((left, right) => left.score - right.score || left.id.localeCompare(right.id))
      .slice(0, 20);
  }

  function relationTypes(payload) {
    return [
      ...new Set((payload.edges || []).map((edge) => edge.relation_type || "related")),
    ].sort();
  }

  window.createM24GraphExplorer = function createM24GraphExplorer(options) {
    const root = options.root;
    const stage = root.querySelector("[data-sigma-stage]");
    const details = root.querySelector("[data-graph-details]");
    const results = root.querySelector("[data-graph-results]");
    const search = root.querySelector("[data-graph-search]");
    const relation = root.querySelector("[data-graph-relation]");
    const reset = root.querySelector("[data-graph-reset]");
    const clear = root.querySelector("[data-graph-clear]");
    const oneHop = root.querySelector("[data-graph-neighbor='1']");
    const twoHop = root.querySelector("[data-graph-neighbor='2']");
    const showOrphans = root.querySelector("[data-graph-orphans]");
    const Sigma = window.Sigma;
    if (typeof Sigma !== "function") {
      throw new Error("Sigma.js browser runtime unavailable");
    }

    const graph = buildGraphologyGraph(options.payload);
    let selectedNodeId = graph.hasNode(options.selectedNodeId) ? options.selectedNodeId : null;
    let focusDepth = 0;
    let visibleNodes = new Set(graph.nodes());
    let visibleEdges = new Set(graph.edges());
    let searchResultIds = new Set();

    for (const type of relationTypes(options.payload)) {
      const option = document.createElement("option");
      option.value = type;
      option.textContent = type;
      relation.append(option);
    }

    function adjacentWithinDepth(nodeId, depth) {
      const seen = new Set([nodeId]);
      let frontier = [nodeId];
      for (let level = 0; level < depth; level += 1) {
        const next = [];
        for (const id of frontier) {
          for (const neighbor of graph.neighbors(id).sort()) {
            if (!seen.has(neighbor)) {
              seen.add(neighbor);
              next.push(neighbor);
            }
          }
        }
        frontier = next;
      }
      return seen;
    }

    function recompute() {
      const relationFilter = relation.value;
      let nodes = new Set(graph.nodes());
      let edges = graph.edges().filter((edgeId) => {
        if (!relationFilter) return true;
        return graph.getEdgeAttribute(edgeId, "relationType") === relationFilter;
      });
      if (selectedNodeId && focusDepth > 0) {
        nodes = adjacentWithinDepth(selectedNodeId, focusDepth);
        edges = edges.filter((edgeId) =>
          nodes.has(graph.source(edgeId)) && nodes.has(graph.target(edgeId)),
        );
      }
      if (!showOrphans.checked) {
        const connected = new Set();
        for (const edgeId of edges) {
          connected.add(graph.source(edgeId));
          connected.add(graph.target(edgeId));
        }
        if (selectedNodeId) connected.add(selectedNodeId);
        nodes = new Set([...nodes].filter((nodeId) => connected.has(nodeId)));
        edges = edges.filter((edgeId) =>
          nodes.has(graph.source(edgeId)) && nodes.has(graph.target(edgeId)),
        );
      }
      visibleNodes = nodes;
      visibleEdges = new Set(edges);
      const matches = searchMatches(graph, search.value).filter((match) => nodes.has(match.id));
      searchResultIds = new Set(matches.map((match) => match.id));
      renderResults(matches);
      renderDetails();
      stage.dataset.state = nodes.size === 0 ? "empty" : "ready";
      stage.dataset.message = nodes.size === 0 ? "No graph nodes match the current filters." : "";
      renderer.refresh();
      options.onStatus?.(
        `Sigma.js canvas ready: ${nodes.size} visible nodes, ${edges.length} visible edges.`,
      );
    }

    function renderResults(matches) {
      if (!search.value.trim()) {
        results.innerHTML = "<p>Search graph nodes by title, aliases, tags, or source path.</p>";
        return;
      }
      if (matches.length === 0) {
        results.innerHTML = '<p data-state="no-match">No matching graph nodes.</p>';
        return;
      }
      results.innerHTML = matches
        .map((match) => `
          <button
            class="graph-result-button"
            data-node-id="${escapeHtml(match.id)}"
            aria-current="${match.id === selectedNodeId ? "true" : "false"}"
          >${escapeHtml(match.title)}</button>
        `)
        .join("");
      for (const button of results.querySelectorAll("[data-node-id]")) {
        button.addEventListener("click", () => selectNode(button.dataset.nodeId));
      }
    }

    function renderDetails() {
      if (!selectedNodeId) {
        details.innerHTML = "<p>Select a node to inspect provenance and relationships.</p>";
        return;
      }
      const selected = selection(graph, selectedNodeId, options.sourceCountsByConcept || {});
      const neighbors = graph.neighbors(selectedNodeId).sort();
      details.innerHTML = `
        <div class="detail-actions graph-selection-actions">
          <button
            class="inline-action"
            type="button"
            data-graph-open-wiki="${escapeHtml(selected.id)}"
          >Open Wiki</button>
          ${selected.sourceCount > 0 ? `
            <button
              class="inline-action"
              type="button"
              data-graph-view-sources="${escapeHtml(selected.id)}"
            >View sources</button>
          ` : ""}
          <button
            class="inline-action"
            type="button"
            data-graph-copy-concept="${escapeHtml(selected.id)}"
          >Copy concept ID</button>
        </div>
        <dl>
          <div><dt>Title</dt><dd>${escapeHtml(selected.title)}</dd></div>
          <div><dt>Type</dt><dd>${escapeHtml(selected.type)}</dd></div>
          <div>
            <dt>Source</dt>
            <dd>${escapeHtml(selected.sourcePath || "release artifact")}</dd>
          </div>
          <div><dt>Tags</dt><dd>${escapeHtml(selected.tags.join(", ") || "none")}</dd></div>
          <div><dt>Neighbors</dt><dd>${escapeHtml(neighbors.length)}</dd></div>
          <div><dt>Source handoffs</dt><dd>${escapeHtml(selected.sourceCount)}</dd></div>
          <div>
            <dt>Description</dt>
            <dd>${escapeHtml(selected.description || "No description")}</dd>
          </div>
        </dl>
      `;
      const wikiButton = details.querySelector("[data-graph-open-wiki]");
      if (wikiButton) {
        wikiButton.addEventListener("click", () => options.onOpenWiki?.(selected));
      }
      const sourcesButton = details.querySelector("[data-graph-view-sources]");
      if (sourcesButton) {
        sourcesButton.addEventListener("click", () => options.onViewSources?.(selected));
      }
      const copyButton = details.querySelector("[data-graph-copy-concept]");
      if (copyButton) {
        copyButton.addEventListener("click", async () => {
          try {
            await navigator.clipboard?.writeText(selected.id);
            options.onStatus?.(`Copied ${selected.id}.`);
          } catch (_error) {
            options.onStatus?.(selected.id);
          }
        });
      }
      options.onSelection?.(selected);
    }

    function selectNode(nodeId) {
      if (!graph.hasNode(nodeId)) return;
      selectedNodeId = nodeId;
      focusDepth = Math.max(focusDepth, 0);
      recompute();
    }

    const renderer = new Sigma(graph, stage, {
      allowInvalidContainer: false,
      defaultEdgeColor: "#94a3b8",
      defaultNodeColor: "#64748b",
      edgeReducer: (edgeId, data) =>
        visibleEdges.has(edgeId) ? data : { ...data, hidden: true },
      enableEdgeEvents: true,
      hideEdgesOnMove: true,
      hideLabelsOnMove: true,
      labelDensity: 0.08,
      labelRenderedSizeThreshold: 8,
      nodeReducer: (nodeId, data) => {
        if (!visibleNodes.has(nodeId)) return { ...data, hidden: true };
        if (nodeId === selectedNodeId) {
          return {
            ...data,
            color: "#0f766e",
            forceLabel: true,
            highlighted: true,
            size: 10,
            zIndex: 2,
          };
        }
        if (searchResultIds.has(nodeId)) {
          return { ...data, forceLabel: true, highlighted: true, size: 8, zIndex: 1 };
        }
        return data;
      },
      renderLabels: true,
      zIndex: true,
    });

    renderer.on("clickNode", ({ node }) => selectNode(node));
    renderer.on("clickStage", () => {
      selectedNodeId = null;
      focusDepth = 0;
      recompute();
    });
    search.addEventListener("input", recompute);
    relation.addEventListener("change", recompute);
    showOrphans.addEventListener("change", recompute);
    reset.addEventListener("click", () => renderer.getCamera().animatedReset({ duration: 200 }));
    clear.addEventListener("click", () => {
      selectedNodeId = null;
      focusDepth = 0;
      search.value = "";
      relation.value = "";
      showOrphans.checked = true;
      recompute();
    });
    oneHop.addEventListener("click", () => {
      if (selectedNodeId) {
        focusDepth = 1;
        recompute();
      }
    });
    twoHop.addEventListener("click", () => {
      if (selectedNodeId) {
        focusDepth = 2;
        recompute();
      }
    });

    if (selectedNodeId) focusDepth = 1;
    recompute();
    return {
      destroy() {
        renderer.kill();
      },
    };
  };
})();
