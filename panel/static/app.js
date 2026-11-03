"use strict";
/* Management Memory — READ-ONLY control panel.
   All dynamic content is inserted with textContent (never innerHTML). */

const $ = (s) => document.querySelector(s);
const SVGNS = "http://www.w3.org/2000/svg";
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "data") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
};
const api = async (path, opts) => {
  const r = await fetch("/api" + path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
};

/* ── formatting ── */
const bytes = (n) => {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0, v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${u[i]}`;
};
const num = (n) => (n == null ? "—" : Number(n).toLocaleString("es-CO"));
const usd = (n) => (n == null ? "—" : `$${Number(n).toFixed(4)}`);
const ago = (iso) => {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now"; if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`; return `${Math.round(s / 86400)} d ago`;
};

/* ── icons (stroke, 24×24) ── */
const ICON = {
  home: "M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z",
  book: "M4 4h12a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3zM4 17a3 3 0 0 1 3-3h12",
  cube: "M12 2l9 5v10l-9 5-9-5V7zM12 22V12M3 7l9 5 9-5",
  graph: "M6 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18 8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18 20.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM8.2 10.8l7.6-3.6M8.2 13.2l7.6 3.6",
  db: "M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.5-4.5",
  zap: "M13 2L4 14h7l-1 8 9-12h-7z",
  pulse: "M22 12h-4l-3 9L9 3l-3 9H2",
  sync: "M21 12a9 9 0 0 1-15.5 6.2M3 12A9 9 0 0 1 18.5 5.8M21 4v5h-5M3 20v-5h5",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  check: "M20 6L9 17l-5-5",
  alert: "M12 3l10 18H2zM12 10v5M12 18h.01",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  layers: "M12 2l10 5-10 5L2 7zM2 12l10 5 10-5M2 17l10 5 10-5",
  refresh: "M21 12a9 9 0 1 1-3-6.7M21 3v6h-6",
};
const icon = (name, size = 18) => {
  const s = document.createElementNS(SVGNS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) s.setAttribute(k, v);
  const p = document.createElementNS(SVGNS, "path"); p.setAttribute("d", ICON[name] || ICON.info); s.append(p); return s;
};

/* ── components ── */
const help = (text) => h("span", { class: "help", "data-tip": text, tabindex: "0", role: "note", "aria-label": text }, "?");
const pill = (text, kind = "") => h("span", { class: `pill ${kind}` }, text);
const intro = (title, text, more) => h("div", { class: "callout" }, icon("info", 20),
  h("div", {}, h("b", {}, title), h("p", {}, text), more ? h("details", {}, h("summary", {}, "Learn more"), h("p", {}, more)) : null));
function sparkline(vals) {
  const w = 84, hgt = 30, max = Math.max(1, ...vals), min = Math.min(...vals);
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${hgt - 3 - ((v - min) / (max - min || 1)) * (hgt - 6)}`).join(" ");
  const s = document.createElementNS(SVGNS, "svg"); s.setAttribute("class", "spark"); s.setAttribute("width", w); s.setAttribute("height", hgt); s.setAttribute("viewBox", `0 0 ${w} ${hgt}`);
  const pl = document.createElementNS(SVGNS, "polyline"); pl.setAttribute("points", pts); pl.setAttribute("fill", "none"); pl.setAttribute("stroke", "var(--brand)"); pl.setAttribute("stroke-width", 2); pl.setAttribute("stroke-linecap", "round"); pl.setAttribute("stroke-linejoin", "round");
  s.append(pl); return s;
}
const kpi = ({ label, value, meta, tip, spark }) => h("div", { class: "card kpi" },
  h("div", { class: "lbl" }, label, tip ? help(tip) : null), h("div", { class: "val" }, value), meta ? h("div", { class: "meta" }, meta) : null,
  spark && spark.length > 1 ? sparkline(spark) : null);
const tile = ({ ic, name, state, tone, what, data }) => h("div", { class: `card tile ${tone}` }, h("div", { class: "ic" }, icon(ic, 20)),
  h("div", {}, h("div", { class: "name" }, name), h("div", { class: "state" }, state), h("div", { class: "what" }, what), data ? h("div", { class: "data" }, data) : null));
function table(cols, rows, opts = {}) {
  if (!rows || !rows.length) return h("div", { class: "tbl" }, h("div", { class: "empty" }, opts.empty || "No data yet."));
  return h("div", { class: "tbl" }, h("div", { class: "scroll" }, h("table", {},
    h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.n ? "n" : "" }, c.t, c.tip ? help(c.tip) : null)))),
    h("tbody", {}, rows.map((r) => h("tr", { class: opts.onrow ? "click" : "", onclick: opts.onrow ? (e) => opts.onrow(r, e.currentTarget) : null },
      cols.map((c) => { const v = c.f ? c.f(r) : r[c.k]; return h("td", { class: c.n ? "n" : "" }, v?.nodeType ? v : (v ?? "—")); })))))));
}
function barChart(points, { label = (p) => p.k, value = (p) => p.v, fmt = num } = {}) {
  if (!points.length) return h("div", { class: "empty" }, "No data in this period.");
  const max = Math.max(1, ...points.map(value));
  return h("div", {}, h("div", { class: "bars" }, points.map((p) => h("div", { style: `height:${Math.max(3, (100 * value(p)) / max)}%`, data: { t: `${label(p)}: ${fmt(value(p))}` } }))),
    h("div", { class: "axis" }, h("span", {}, label(points[0])), h("span", {}, label(points[points.length - 1]))));
}
function hbars(items, fmt = num) {
  const max = Math.max(1, ...items.map((i) => i.v));
  return h("div", {}, items.map((i) => h("div", { class: "hb" }, h("span", { class: "l", title: i.l }, i.l), h("span", { class: "t" }, h("i", { style: `width:${Math.max(2, (100 * i.v) / max)}%` })), h("span", { class: "v" }, fmt(i.v)))));
}
const loading = () => h("div", { class: "empty" }, "Loading…");
const fail = (e) => h("div", { class: "callout", style: "background:var(--bad-soft)" }, icon("alert", 20), h("div", {}, h("b", {}, "Could not load"), h("p", {}, e.message)));
async function render(fn) {
  const v = $("#view"); v.replaceChildren(loading());
  try { v.replaceChildren(await fn()); } catch (e) { v.replaceChildren(fail(e)); }
}
const section = (title, hint) => [h("h2", {}, title), hint ? h("p", { class: "hint" }, hint) : null];

/* ── plain language: names and explanations ── */
const COLLECTION = {
  DocumentChunk_text: ["Fragments of your documents", "Each document is cut into pieces; this is the collection that search uses."],
  TextSummary_text: ["Summaries of each fragment", "A short summary per fragment, generated by Claude at indexing time."],
  TextDocument_name: ["Document names", "One vector per document."],
  Entity_name: ["Detected concepts", "Modules, rules, decisions… that Claude extracted from the texts (graph nodes)."],
  EntityType_name: ["Concept categories", "The types the concepts belong to (e.g. «module», «rule»)."],
  EdgeType_relationship_name: ["Descriptions of graph connections", "One vector per connection between concepts, with a phrase that describes it («X mentions Y», «X is part of Z»). They are only useful for graph searches, not for fragment search."],
  SessionQAVector_text: ["Session questions and answers", "Conversations saved in the graph."],
};
const ADVICE = {
  edges_dominate: ["Graph relationships take up almost all of the vector space", "Each graph connection stores its own descriptive phrase as a vector (they are all different, no duplicates). They are not your documents, and fragment search (CHUNKS, the one we use) does not query them. If you ever need to save space, this is the first place to look, but today it is only a few MB."],
  no_ann: ["No fast-search index (ANN)", "Search compares against all vectors (exact). With hundreds or thousands of rows it is instantaneous. An index would only be needed with tens of thousands. Not a problem today."],
  sessions: ["Session history", "Each session close stores a summary with ~3 calls to Claude. Check «Tokens and cost» to see whether what you spend is worth what it gives you."],
  empty: ["Empty dataset", "It contains no documents: you can delete it without losing anything."],
  empty_code: ["Empty code dataset", "The plugin creates it even if code indexing is turned off. It consumes nothing."],
  not_indexed: ["Documents pending indexing", "They are in the registry but their indexing was not confirmed. They are retried on the next sync."],
  missing_in_cognee: ["Documents that disappeared from Cognee", "They exist in the registry but no longer in memory. A new sync is needed."],
  orphans: ["Documents without a registry entry", "They are in Cognee but are not managed by the synchronizer (loaded by hand?)."],
  heavy_docs: ["Documents that cost a lot", "They have many more fragments than the rest. Each fragment costs ~2 calls to Claude when reindexing: consider splitting or shortening them."],
};
const GLOSSARY = [
  ["Memory / knowledge base", "What the AI «remembers» about a project: your documents turned into data that can be searched by meaning."],
  ["Dataset", "An independent «drawer» of memory. Each project has one for knowledge (its documents) and another for sessions (conversations)."],
  ["Document", "A text file (usually Markdown) that was saved in memory."],
  ["Chunk (fragment)", "A piece of a document. It is cut this way to search precisely and give Claude only what is relevant."],
  ["Vector (embedding)", "The numeric «fingerprint» of a text: 768 numbers that represent its meaning. Similar texts have close fingerprints; that is how search works. It is computed locally."],
  ["Dimension", "How many numbers each vector has (here 768). More dimensions = more detail, more space."],
  ["ANN index", "A shortcut for finding similar vectors without comparing against all of them. Useful from tens of thousands of rows onward."],
  ["Knowledge graph", "A map of concepts (nodes) joined by relationships (edges), which Claude extracts from the texts when indexing."],
  ["Node / Edge", "Node = a concept or document. Edge = a named connection between two nodes (contains, is_a…)."],
  ["Observer", "A bridge on your Mac that uses your Claude subscription so Cognee can summarize and extract concepts. Each call counts tokens."],
  ["Token", "The unit in which the text an AI processes is measured (~3-4 characters). More tokens = more consumption."],
  ["Token cache", "Text that Claude has already seen and reuses more cheaply. It appears as «cache read»."],
  ["Reingestion", "Indexing a document again. It costs about 2 calls to Claude per fragment. Used to estimate what rebuilding the memory would cost."],
  ["OpenTelemetry (OTel)", "A standard for measuring what a program does. Claude Code uses it to report each call and its tokens to the collector."],
  ["Collector", "The service that receives that telemetry and stores it in files that this screen reads."],
  ["MCP", "The local «plug» through which Claude Code queries the memory with tools (recall, remember…)."],
  ["Session", "A conversation with Claude Code. Cognee can save its history to remember it later."],
  ["Briefing", "Automatic summary (goal, decisions, rules, pending items) that is loaded when a session opens without querying Cognee. Costs ~1 000 tokens."],
  ["Swarm", "A team of specialised Claude agents that implement approved OpenSpec changes in isolated worktrees, on your subscription."],
  ["Change (OpenSpec)", "A reviewed plan: proposal, spec scenarios, design and tasks. Nothing is implemented until you approve it."],
  ["Scenario", "A WHEN/THEN example in a spec. The reviewer must find a test or evidence for every one."],
  ["Worktree", "A separate checkout of the repo on its own branch, so each change is isolated."],
  ["Verdict", "The reviewer's structured result per change. Only a script, after a passing verdict, marks a change done."],
  ["Swap", "Memory borrowed from disk when RAM fills up; if it grows a lot, the Mac is running tight."],
  ["Footprint (space)", "Everything a dataset occupies: database + graph + raw text."],
];

/* ── pages ── */
const pages = {};

pages.overview = { title: "Overview", sub: "The state of your memory at a glance.", icon: "home", run: async () => {
  const [o, kb] = await Promise.all([api("/overview"), api("/kb")]);
  const reg = o.registry.states || {}, pending = Object.entries(reg).filter(([k]) => k !== "indexed").reduce((s, [, v]) => s + v, 0);
  const issues = [];
  [["Cognee (API)", o.cognee], ["MCP", o.mcp], ["PostgreSQL", o.postgres], ["Observer", o.observer]].forEach(([n, s]) => { if (!s.ok) issues.push(`${n} is not responding.`); });
  if (!o.collector.ok) issues.push("The telemetry collector has no files.");
  if (pending) issues.push(`${pending} document(s) not indexed correctly (see «Synchronization»).`);
  kb.datasets.forEach((d) => d.flags.filter((f) => f.level === "warn").forEach((f) => issues.push(`${d.name}: ${f.text}`)));
  const root = h("div", {});
  root.append(issues.length
    ? h("div", { class: "attention warn" }, icon("alert", 22), h("div", {}, h("h2", {}, `${issues.length} ${issues.length === 1 ? "thing needs" : "things need"} your attention`), h("ul", {}, issues.map((i) => h("li", {}, i)))))
    : h("div", { class: "attention ok" }, icon("check", 22), h("div", {}, h("h2", {}, "All good"), h("span", { class: "muted" }, "The services are responding, all documents are indexed and there are no warnings."))));
  const t = (ok, ic, name, what, data) => tile({ ic, name, tone: ok ? "ok" : "bad", state: ok ? "Running" : "Not responding", what, data });
  root.append(...section("Service health", "Each piece of the system and what it is for. Everything runs on your Mac."));
  root.append(h("div", { class: "grid" },
    t(o.cognee.ok, "layers", "Cognee", "The local service that stores and searches the memory.", o.cognee.version && `Version ${o.cognee.version}`),
    t(o.postgres.ok, "db", "Database", "Where the vectors and data live.", o.postgres.ok && `${bytes(o.postgres.size_bytes)} · ${o.postgres.connections} connections`),
    t(o.observer.ok, "zap", "Observer (Claude)", "Lets Cognee use your Claude subscription when indexing.", o.observer.ok && `${num(o.observer.calls)} calls since it started`),
    t(o.mcp.ok, "search", "MCP", "How Claude Code queries the memory (local).", "Port 45873"),
    t(o.collector.ok, "pulse", "Telemetry (OTel)", "Collects how many tokens Claude Code uses.", `${o.collector.files} file(s) · ${bytes(o.collector.bytes)} · ${ago(o.collector.latest_file)}`),
    t(pending === 0, "sync", "Synchronization", "Keeps the memory identical to your documents.", `${reg.indexed || 0} of ${o.registry.total} indexed`)));
  const obs = o.observer_usage, ot = o.otel_usage.total;
  root.append(...section("How much memory there is and what it costs", "Hover over «?» to see what each number means."));
  const totalFoot = kb.datasets.reduce((s, d) => s + (d.footprint_bytes || 0), 0), docs = kb.datasets.reduce((s, d) => s + (d.documents || 0), 0), vec = kb.datasets.reduce((s, d) => s + (d.vector_rows || 0), 0);
  root.append(h("div", { class: "grid" },
    kpi({ label: "Total space", value: bytes(totalFoot), meta: `${kb.projects.length} project(s) · ${kb.datasets.length} datasets`, tip: "Everything the memory occupies: database + graph + text." }),
    kpi({ label: "Documents", value: num(docs), meta: `${num(kb.datasets.reduce((s, d) => s + d.chunks, 0))} fragments`, tip: "Saved files and the pieces they were cut into for searching." }),
    kpi({ label: "Vectors", value: num(vec), meta: "768 numbers each", tip: "The numeric fingerprint of each text, concept and relationship. It is computed locally and allows searching by meaning." }),
    kpi({ label: "Calls to Claude", value: num(obs.total.calls), meta: `${num(obs.total.tokens)} tokens`, tip: "Times Cognee used your subscription to index. Measured at the observer.", spark: obs.by_day.map((d) => d.calls) }),
    kpi({ label: "Measured sessions", value: num(ot.sessions), meta: `${num(ot.total)} tokens`, tip: "Claude Code sessions with telemetry enabled. Only those launched with «claude-memory» count.", spark: o.otel_usage.by_day.map((d) => d.total) })));
  root.append(h("div", { class: "grid two", style: "margin-top:14px" },
    h("div", { class: "card" }, h("h3", {}, "Calls to Claude per day"), barChart(obs.by_day, { label: (p) => p.day, value: (p) => p.calls }), h("p", { class: "hint small" }, "Each bar is a day. Each call is an indexing or summarization step.")),
    h("div", { class: "card" }, h("h3", {}, "What takes up the most space"), hbars(kb.datasets.filter((d) => d.footprint_bytes).sort((a, b) => b.footprint_bytes - a.footprint_bytes).map((d) => ({ l: d.name, v: d.footprint_bytes })), bytes), h("p", { class: "hint small" }, "By dataset. Go to «Knowledge bases» to see the breakdown."))));
  return root;
} };

pages.knowledge = { title: "Knowledge bases", sub: "How much memory each project has, how much it weighs and what it costs to rebuild.", icon: "book", run: async () => {
  const o = await api("/kb");
  const root = h("div", {});
  root.append(intro("What am I looking at?", "Each project has its own knowledge base: its documents turned into data that the AI can query. Here you see how much there is, how much space it takes and how much it would cost to rebuild, to decide whether it is worth compacting or deleting something.",
    "«Rebuild» is the cost of indexing everything again: ~2 calls to Claude per fragment. It is calculated with the real average measured by the observer."));
  const totalFoot = o.datasets.reduce((s, d) => s + (d.footprint_bytes || 0), 0), reingest = o.projects.reduce((s, p) => s + p.est_reingest_tokens, 0);
  root.append(h("div", { class: "grid" },
    kpi({ label: "Projects with memory", value: num(o.projects.length), meta: o.projects.map((p) => p.project).join(", ") }),
    kpi({ label: "Total space", value: bytes(totalFoot), meta: `Database ${bytes(o.pg.size_bytes)} · graph and files ${bytes(o.storage.total_bytes)}`, tip: "What everything takes up on disk." }),
    kpi({ label: "Cost to rebuild everything", value: `${num(reingest)} tokens`, meta: `≈ ${num(o.avg_tokens_per_call)} per call`, tip: "Estimate: fragments × 2 calls × average tokens per call." })));
  root.append(...section("By project", "The datasets of the same project (knowledge, sessions, code) are summed."));
  root.append(table([
    { t: "Project", f: (r) => h("strong", {}, r.project) }, { t: "Contains", f: (r) => r.datasets.map((d) => d.kind).join(" · ") },
    { t: "Documents", n: 1, f: (r) => num(r.documents) }, { t: "Fragments", n: 1, f: (r) => num(r.chunks), tip: "Pieces the documents are cut into." }, { t: "Vectors", n: 1, f: (r) => num(r.vector_rows) },
    { t: "Space", n: 1, f: (r) => bytes(r.footprint_bytes) }, { t: "Rebuild", n: 1, f: (r) => `${num(r.est_reingest_tokens)} tok`, tip: "Tokens it would cost to index it again." }], o.projects));
  root.append(...section("By dataset", "Click a row to see the detail, the documents that cost the most and what to do."));
  const box = h("div", {});
  root.append(table([
    { t: "Dataset", f: (r) => h("span", {}, h("strong", {}, r.name), " ", pill(r.kind, "brand")) }, { t: "Docs", n: 1, f: (r) => num(r.documents) },
    { t: "Text", n: 1, f: (r) => `${num(r.est_tokens)} tok`, tip: "Size of the original text, in approximate tokens." }, { t: "Concepts", n: 1, f: (r) => num(r.nodes), tip: "Graph nodes." }, { t: "Connections", n: 1, f: (r) => num(r.edges), tip: "Graph edges." },
    { t: "Vectors", n: 1, f: (r) => num(r.vector_rows) }, { t: "Space", n: 1, f: (r) => bytes(r.footprint_bytes) },
    { t: "Warnings", f: (r) => { const n = r.flags.filter((f) => f.level !== "info").length; return n ? pill(`${n} ${n === 1 ? "warning" : "warnings"}`, "warn") : pill("no warnings", "ok"); } }],
    o.datasets, { onrow: (r, tr) => { document.querySelectorAll("tr.sel").forEach((x) => x.classList.remove("sel")); tr.classList.add("sel"); detail(r.id, box); } }));
  root.append(box);
  return root;
} };
async function detail(id, box) {
  box.replaceChildren(loading());
  try {
    const d = await api(`/kb/${id}`);
    box.replaceChildren(...section(`Detail of ${d.name}`, null),
      h("div", { class: "grid" }, kpi({ label: "Documents", value: num(d.documents), meta: `${bytes(d.raw_bytes)} of text` }), kpi({ label: "Fragments", value: num(d.chunks), meta: `≈ ${num(d.est_tokens)} tokens` }),
        kpi({ label: "Rebuild", value: `${num(d.est_reingest_calls)} calls`, meta: `≈ ${num(d.est_reingest_tokens)} tokens`, tip: "Fragments × 2 calls to Claude." }),
        kpi({ label: "Space", value: bytes(d.footprint_bytes), meta: `Postgres ${bytes(d.pg_bytes)} · graph ${bytes(d.graph_bytes)}` })),
      ...section("What it means and what you can do", "Warnings and data that help decide whether to compact or clean up."),
      ...(d.flags.length ? d.flags.map((f) => { const a = ADVICE[f.code]; return h("div", { class: `advice ${f.level}` }, icon(f.level === "warn" ? "alert" : "info", 18), h("div", {}, h("b", {}, a ? a[0] : f.code), h("span", {}, a ? a[1] : f.text), a ? h("div", { class: "small muted", style: "margin-top:4px" }, "Data: " + f.text) : null)); }) : [h("div", { class: "empty" }, "No warnings for this dataset.")]),
      ...section("Documents, from most to least costly", "Fragments determine the cost of reindexing. A document with many fragments is a candidate for splitting or shortening."),
      table([{ t: "Document", f: (r) => r.path || r.name }, { t: "Status", f: (r) => (r.status ? pill(r.status === "indexed" ? "indexed" : r.status, r.status === "indexed" ? "ok" : "warn") : pill("no registry entry", "warn")) },
        { t: "Fragments", n: 1, f: (r) => num(r.chunks) }, { t: "Text", n: 1, f: (r) => `${num(r.est_tokens)} tok` }, { t: "Reindex", n: 1, f: (r) => `${num(r.est_reingest_tokens)} tok` }, { t: "Updated", f: (r) => ago(r.updated || r.created) }], d.docs),
      ...section("Where the vectors are", "One collection per type of text, stored in the database for searching by meaning."), vectorTable(d.collections));
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) { box.replaceChildren(fail(e)); }
}
function vectorTable(cols) {
  return table([
    { t: "What it stores", f: (r) => { const c = COLLECTION[r.table]; return h("div", {}, h("strong", {}, c ? c[0] : r.table), c ? h("div", { class: "muted small" }, c[1]) : null, h("code", {}, r.table)); } },
    { t: "Vectors", n: 1, f: (r) => num(r.rows) }, { t: "Dimension", n: 1, f: (r) => r.dim, tip: "How many numbers each vector has." },
    { t: "Space", n: 1, f: (r) => bytes(r.bytes_total) }, { t: "Fast index", f: (r) => (r.has_ann_index ? pill("yes", "ok") : pill("no (exact search)")), tip: "Search shortcut (ANN). Without it, it compares against all of them: perfect for small amounts of data." },
    { t: "Example", f: (r) => (r.sample ? h("div", {}, h("div", { class: "mono muted" }, `[${r.sample.first_components.slice(0, 4).join(", ")} …]`), h("div", { class: "small" }, r.sample.item.slice(0, 60))) : "—") }], cols);
}

pages.vectors = { title: "Vectors", sub: "Which numeric fingerprints are created, where they are stored and how much they weigh.", icon: "cube", run: async () => {
  const all = await api("/vectors");
  const root = h("div", {});
  root.append(intro("What is a vector and where is it created?", "To search by meaning (not by exact words), each text is converted into a list of 768 numbers: its «fingerprint». Two texts with similar meaning have close fingerprints. They are computed inside your Mac, in the Cognee container, and stored in PostgreSQL (one schema per dataset).",
    "The model is jina-embeddings-v2-base-es: it was downloaded once, runs locally, does not use your subscription or the internet, and understands Spanish and English."));
  for (const d of all) root.append(...section(d.dataset, `${num(d.rows)} vectors · ${bytes(d.bytes)} on disk · schema ${d.schema}`), d.collections.length ? vectorTable(d.collections) : h("div", { class: "empty" }, "This dataset has no vectors."));
  return root;
} };

const TYPE_COLORS = { Entity: "#0e7c86", EntityType: "#c2650c", DocumentChunk: "#4f7cc4", TextSummary: "#8a63b5", TextDocument: "#12805c", Timestamp: "#98a2b3", default: "#667085" };
const TYPE_NAMES = { Entity: "Concepts", EntityType: "Categories", DocumentChunk: "Fragments", TextSummary: "Summaries", TextDocument: "Documents", Timestamp: "Dates" };
pages.graph = { title: "Graph", sub: "The map of concepts that Claude extracted from your documents.", icon: "graph", run: async () => {
  const ds = (await api("/datasets")).filter((d) => d.nodes);
  if (!ds.length) return h("div", {}, intro("There is no graph yet", "Once documents are indexed, the concept map will appear here."));
  const sel = h("select", {}, ds.map((d) => h("option", { value: d.id }, `${d.name} (${num(d.nodes)} nodes)`)));
  const max = h("input", { type: "number", value: 300, min: 20, max: 3000, style: "width:90px" });
  const chips = h("div", { class: "row" }), info = h("p", { class: "hint" });
  const panel = h("div", { class: "card" }, h("h3", {}, "Detail"), h("p", { class: "muted" }, "Click a point to see what it is and its properties."));
  const cyBox = h("div", { id: "cy" }); let cy = null, stats = null; const active = new Set();
  const load = async () => {
    info.textContent = "Loading graph…";
    try {
      const types = active.size ? [...active].join(",") : "";
      const g = await api(`/datasets/${sel.value}/graph?max_nodes=${max.value}&types=${encodeURIComponent(types)}`);
      if (!stats) { stats = g.stats; chips.replaceChildren(...Object.entries(stats.types).map(([t, c]) => { active.add(t); return h("span", { class: "pill chip", style: `box-shadow:inset 0 0 0 2px ${TYPE_COLORS[t] || TYPE_COLORS.default}`, title: "Show/hide", onclick: (e) => { active.has(t) ? active.delete(t) : active.add(t); e.currentTarget.classList.toggle("off"); load(); } }, `${TYPE_NAMES[t] || t} · ${c}`); })); }
      info.textContent = `Showing ${g.stats.shown_nodes} of ${g.stats.nodes} points and ${g.stats.shown_edges} of ${g.stats.edges} connections${g.stats.truncated ? " (the most connected)" : ""}.`;
      if (cy) cy.destroy();
      cy = cytoscape({ container: cyBox, elements: [...g.nodes.map((n) => ({ data: { id: n.id, label: n.label, type: n.type, degree: n.degree, props: n.props } })), ...g.edges.map((e, i) => ({ data: { id: "e" + i, source: e.source, target: e.target, label: e.label } }))],
        style: [{ selector: "node", style: { "background-color": (n) => TYPE_COLORS[n.data("type")] || TYPE_COLORS.default, label: "data(label)", "font-size": 9, color: "#667085", "min-zoomed-font-size": 10, "text-wrap": "ellipsis", "text-max-width": 90, width: "mapData(degree,0,40,8,34)", height: "mapData(degree,0,40,8,34)" } },
          { selector: "edge", style: { width: 0.6, "line-color": "#b8c0cc", "curve-style": "haystack", opacity: 0.5 } }, { selector: "node:selected", style: { "border-width": 3, "border-color": "#c2650c" } }],
        layout: { name: "cose", animate: false, nodeRepulsion: 9000, idealEdgeLength: 60 } });
      cy.on("tap", "node", (ev) => { const n = ev.target.data(); panel.replaceChildren(h("h3", {}, TYPE_NAMES[n.type] || n.type), h("strong", {}, n.label), h("p", { class: "muted" }, `${n.degree} connections`), h("pre", {}, JSON.stringify(n.props, null, 2))); });
    } catch (e) { info.textContent = ""; cyBox.replaceChildren(fail(e)); }
  };
  sel.onchange = () => { stats = null; active.clear(); load(); }; max.onchange = load;
  setTimeout(async () => { await load(); if (stats) $("#rels").replaceChildren(hbars(Object.entries(stats.relations).sort((a, b) => b[1] - a[1]).map(([l, v]) => ({ l, v })))); }, 0);
  return h("div", {}, intro("What is the graph?", "When a document is indexed, Claude identifies the concepts that appear in it (modules, rules, decisions…) and how they relate. Each point is a concept, fragment or document; each line is a named relationship. The large points are the most connected."),
    h("div", { class: "row" }, sel, h("span", { class: "muted" }, "max. points"), max, h("button", { onclick: load }, "Load")), h("div", { style: "margin:10px 0" }, chips), info,
    h("div", { class: "split" }, cyBox, panel), ...section("Relationship types", "How many connections there are of each kind."), h("div", { class: "card", id: "rels" }));
} };

pages.postgres = { title: "PostgreSQL", sub: "Explore the database where the vectors live (read-only).", icon: "db", run: async () => {
  const schemas = await api("/pg/schemas");
  const right = h("div", {}, h("div", { class: "empty" }, "Choose a schema on the left to see its tables."));
  const showTable = async (schema, tbl, offset = 0) => {
    right.replaceChildren(loading());
    try {
      const d = await api(`/pg/table?schema=${encodeURIComponent(schema)}&table=${encodeURIComponent(tbl)}&limit=25&offset=${offset}`);
      right.replaceChildren(...section(`${tbl}`, schema), table([{ t: "Column", k: "name" }, { t: "Type", k: "type" }, { t: "Nullable", f: (c) => (c.nullable ? "yes" : "no") }], d.columns),
        ...section(`Rows ${offset + 1}–${offset + d.rows.length}`, "Vectors and long texts are shown abbreviated."), table(d.columns.map((c, i) => ({ t: c.name, f: (r) => h("span", { class: "mono" }, String(r[i] ?? "NULL")) })), d.rows),
        h("div", { class: "row", style: "margin-top:10px" }, offset ? h("button", { class: "ghost", onclick: () => showTable(schema, tbl, Math.max(0, offset - 25)) }, "← Previous") : null, d.rows.length === 25 ? h("button", { class: "ghost", onclick: () => showTable(schema, tbl, offset + 25) }, "Next →") : null));
    } catch (e) { right.replaceChildren(fail(e)); }
  };
  const showSchema = async (s) => {
    right.replaceChildren(loading());
    try {
      const t = await api(`/pg/tables?schema=${encodeURIComponent(s.schema)}`);
      right.replaceChildren(...section(s.dataset ? `Dataset ${s.dataset}` : `Schema ${s.schema}`, s.schema), table([{ t: "Table", f: (r) => h("code", {}, r.table) }, { t: "Rows", n: 1, f: (r) => num(r.rows) }, { t: "Space", n: 1, f: (r) => bytes(r.bytes) }], t, { onrow: (r) => showTable(s.schema, r.table) }));
    } catch (e) { right.replaceChildren(fail(e)); }
  };
  const left = table([{ t: "Schema", f: (s) => h("div", {}, h("strong", {}, s.dataset || s.schema), s.dataset ? h("div", { class: "muted small mono" }, s.schema.slice(0, 18) + "…") : null) }, { t: "Tables", n: 1, k: "tables" }, { t: "Space", n: 1, f: (s) => bytes(s.bytes) }], schemas, { onrow: showSchema });
  const sql = h("textarea", {}, "select count(*) as fragmentos from \"ds_<id_del_dataset>\".\"DocumentChunk_text\""), out = h("div", {});
  const run = async () => {
    out.replaceChildren(loading());
    try {
      const r = await api("/pg/query", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sql: sql.value }) });
      out.replaceChildren(table(r.columns.map((c, i) => ({ t: c, f: (row) => h("span", { class: "mono" }, String(row[i] ?? "NULL")) })), r.rows), r.truncated ? h("p", { class: "hint" }, "Result truncated to 500 rows.") : null);
    } catch (e) { out.replaceChildren(fail(e)); }
  };
  return h("div", {}, intro("What is this?", "PostgreSQL is the database where Cognee stores the vectors. Each dataset has its own schema (ds_…) with one table per type of text. This view is read-only: you cannot change anything from here, not even with the SQL console.", "The connection uses a dedicated role (mm_reader) with read-only permissions, read-only transactions and a limit of 15 seconds per query."),
    h("div", { class: "split", style: "grid-template-columns:380px minmax(0,1fr)" }, left, right), ...section("SQL console", "A single read query (SELECT, WITH, EXPLAIN, SHOW)."), sql, h("div", { class: "row", style: "margin:10px 0" }, h("button", { onclick: run }, "Run")), out);
} };

pages.search = { title: "Search", sub: "Test how the memory retrieves what you ask it.", icon: "search", run: async () => {
  const ds = await api("/datasets");
  const sel = h("select", {}, ds.filter((d) => d.documents).map((d) => h("option", { value: d.name }, d.name)));
  const q = h("input", { placeholder: "Type a question, e.g. «what thresholds does the scoring use?»", style: "flex:1;min-width:300px" }), k = h("input", { type: "number", value: 5, min: 1, max: 20, style: "width:70px" });
  const out = h("div", {});
  const go = async () => {
    if (!q.value.trim()) return; out.replaceChildren(loading()); const t0 = performance.now();
    try {
      const r = await api("/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataset: sel.value, query: q.value, top_k: Number(k.value) }) });
      out.replaceChildren(h("p", { class: "hint" }, `${r.results.length} results in ${Math.round(performance.now() - t0)} ms · no calls to Claude · smaller distance = more similar`),
        ...r.results.map((x, i) => h("div", { class: "card", style: "margin:10px 0" }, h("div", { class: "row" }, pill(`#${i + 1}`, "brand"), h("strong", {}, x.path || x.document_id || "?"), h("span", { class: "spacer" }), pill(`distance ${x.score?.toFixed?.(3) ?? x.score}`), x.status ? pill(x.status === "indexed" ? "indexed" : x.status, x.status === "indexed" ? "ok" : "warn") : null), h("p", { style: "white-space:pre-wrap;margin:10px 0 0" }, (x.text || "").slice(0, 900)))));
    } catch (e) { out.replaceChildren(fail(e)); }
  };
  q.addEventListener("keydown", (e) => e.key === "Enter" && go());
  return h("div", {}, intro("What is it for?", "It is the same mechanism Claude uses when it queries the memory. You type a question, it is converted into a vector (locally) and the closest fragments are returned. It is useful for checking whether the memory «understands» what you ask it. It does not spend tokens from your subscription.", "Use the CHUNKS (fragments) mode: it is the cheapest, with no calls to Claude."),
    h("div", { class: "row" }, sel, q, h("span", { class: "muted" }, "results"), k, h("button", { onclick: go }, "Search")), out);
} };

pages.tokens = { title: "Tokens and cost", sub: "How much text the AI processes and where that consumption comes from.", icon: "zap", run: async () => {
  const [t, otel] = await Promise.all([api("/tokens?days=30"), api("/otel")]);
  const root = h("div", {});
  const o = t.observer.total || {}, c = t.claude_code.total, s = t.cognee_sessions.stats || {};
  root.append(intro("What is a token and what does this screen measure?", "A token is the unit in which the text an AI processes is measured (~3-4 characters). Tokens are counted here, not money: your Claude subscription does not charge per token and its remaining quota cannot be queried from outside. There are three different sources, each measuring something different.",
    "For a Claude Code session to appear in source 2, it must be opened with «scripts/claude-memory <project>» (or by defining the OTEL_* variables in the terminal). The «env» block of the project settings does not work for this. Normal sessions are not measured."));
  root.append(...section("1 · What Cognee spends on indexing (the observer)", "Each time Cognee summarizes or extracts concepts, it calls Claude through the observer. This source is complete: no call escapes it."));
  root.append(h("div", { class: "grid" }, kpi({ label: "Calls", value: num(o.calls), spark: t.observer.by_day.map((d) => d.calls) }), kpi({ label: "Tokens", value: num(o.tokens), meta: `${num(o.avg_tokens)} per call`, spark: t.observer.by_day.map((d) => d.tokens) }),
    kpi({ label: "Speed (median)", value: `${num(o.p50_ms)} ms`, meta: `p95: ${num(o.p95_ms)} ms`, tip: "p95: 95 % of calls take less than this." })));
  root.append(h("div", { class: "grid two", style: "margin-top:14px" }, h("div", { class: "card" }, h("h3", {}, "Tokens per day"), barChart(t.observer.by_day, { label: (p) => p.day, value: (p) => p.tokens })),
    h("div", { class: "card" }, h("h3", {}, "Latest calls"), table([{ t: "Time", f: (r) => (r.ts || "").slice(5, 16).replace("T", " ") }, { t: "Tokens", n: 1, f: (r) => num(r.tokens) }, { t: "Duration", n: 1, f: (r) => `${num(r.duration_ms)} ms` }], (t.observer.recent || []).slice(0, 8)))));
  root.append(...section("2 · What Claude Code spends (telemetry)", "Each Claude response in the measured sessions: input, output and cache tokens. The cost is the API equivalent, not what your subscription charges."));
  root.append(h("div", { class: "grid" }, kpi({ label: "Calls", value: num(c.calls), meta: `${c.sessions} sessions` }), kpi({ label: "Total tokens", value: num(c.total), meta: `input ${num(c.input)} · output ${num(c.output)}` }),
    kpi({ label: "Cache", value: num(c.cache_read), meta: `write ${num(c.cache_creation)}`, tip: "Text that Claude had already seen and reuses more cheaply." }), kpi({ label: "API-equivalent cost", value: usd(c.cost), tip: "Reference: how much it would cost if you paid per use instead of a subscription." })));
  root.append(h("h3", { style: "margin-top:18px" }, "By run"), table([{ t: "Project", f: (r) => r.project || "—" }, { t: "Run", f: (r) => r.run || "(no run_id)" }, { t: "Var.", f: (r) => r.variant || "—", tip: "A = without memory, B = with memory (comparisons)." }, { t: "Calls", n: 1, k: "calls" }, { t: "Tokens", n: 1, f: (r) => num(r.total) }, { t: "Cost", n: 1, f: (r) => usd(r.cost) }, { t: "Median", n: 1, f: (r) => `${num(r.p50_ms)} ms` }], t.claude_code.by_run));
  root.append(h("h3", { style: "margin-top:18px" }, "By model"), table([{ t: "Model", k: "model" }, { t: "Calls", n: 1, k: "calls" }, { t: "Tokens", n: 1, f: (r) => num(r.total) }, { t: "Cost", n: 1, f: (r) => usd(r.cost) }], t.claude_code.by_model));
  root.append(...section("3 · What Cognee records per session", "The sessions saved on the server. It is usually zero because the observer uses the subscription."));
  root.append(h("div", { class: "grid" }, kpi({ label: "Sessions (30 days)", value: num(s.sessions), meta: `${s.abandoned ?? 0} abandoned` }), kpi({ label: "Tokens", value: num(s.tokens_total), meta: `input ${num(s.tokens_in)} · output ${num(s.tokens_out)}` }), kpi({ label: "Recorded spend", value: usd(s.total_spend_usd) })));
  root.append(...section("Measurement health", "Checks to know whether the numbers are reliable."));
  root.append(h("div", { class: "grid two" }, h("div", {}, h("h3", {}, "Events received"), table([{ t: "Event", f: (r) => h("code", {}, r.name) }, { t: "Count", n: 1, f: (r) => num(r.count) }], otel.events)),
    h("div", {}, h("h3", {}, "Reconciliation: logs vs. metrics"), table([{ t: "Run", f: (r) => r.run }, { t: "Type", k: "kind" }, { t: "Logs", n: 1, f: (r) => num(r.logs) }, { t: "Metrics", n: 1, f: (r) => num(r.metrics) }, { t: "Diff.", n: 1, f: (r) => (r.diff_pct == null ? "—" : `${r.diff_pct}%`), tip: "Metrics tend to fall short in brief sessions; logs are the reliable source." }], otel.reconciliation))));
  return root;
} };

pages.calls = { title: "API and containers", sub: "Who talks to Cognee, how often and whether the services are healthy.", icon: "pulse", run: async () => {
  const hours = h("select", {}, [1, 6, 24, 72, 168].map((x) => h("option", { value: x, selected: x === 24 }, `last ${x} h`)));
  const body = h("div", {});
  const load = async () => {
    body.replaceChildren(loading());
    try {
      const [c, a] = await Promise.all([api("/containers"), api(`/api-calls?hours=${hours.value}`)]);
      const parts = [...section("Containers", "The programs that make up the system. If one restarts a lot or runs out of memory, it will show up here.")];
      parts.push(c.available ? table([{ t: "Service", f: (r) => h("strong", {}, r.service) },
        { t: "Status", f: (r) => (r.state === "exited" && r.exit_code === 0 ? pill("completed", "ok") : pill(`${r.state === "running" ? "active" : r.state}${r.health ? " · " + r.health : ""}`, r.state === "running" && r.health !== "unhealthy" ? "ok" : "bad")) },
        { t: "CPU", n: 1, f: (r) => (r.cpu_pct == null ? "—" : `${r.cpu_pct}%`) }, { t: "Memory", n: 1, f: (r) => (r.mem_bytes == null ? "—" : bytes(r.mem_bytes)) }, { t: "Restarts", n: 1, k: "restarts", tip: "Times Docker restarted it because of a failure." }, { t: "Active since", f: (r) => ago(r.started) }], c.containers)
        : h("div", { class: "empty" }, "No access to Docker (proxy not configured)."));
      if (a.available === false || a.ok === false) parts.push(...section("API calls"), h("div", { class: "empty" }, a.error || "Docker not available."));
      else {
        parts.push(...section(`Cognee API calls · ${num(a.total)} in ${a.hours} h`, a.note),
          h("div", { class: "grid" }, kpi({ label: "Calls", value: num(a.total), meta: `${num(a.health_checks)} health checks separately` }), kpi({ label: "Errors", value: num((a.status["4xx"] || 0) + (a.status["5xx"] || 0)), meta: "4xx/5xx responses", tip: "A 404 is usually a nonexistent dataset; a 5xx, a server failure." }), ...a.callers.slice(0, 3).map((x) => kpi({ label: "Source", value: num(x.count), meta: x.caller }))),
          h("div", { class: "card", style: "margin:14px 0" }, h("h3", {}, "Calls per hour"), barChart(a.per_hour, { label: (p) => p.hour.replace("T", " "), value: (p) => p.count })),
          h("h3", {}, "By endpoint"), table([{ t: "What it does", f: (r) => h("code", {}, `${r.method} ${r.path}`) }, { t: "Calls", n: 1, f: (r) => num(r.count) }, { t: "Errors", n: 1, f: (r) => (r.errors ? pill(r.errors, "bad") : "0") },
            { t: "Spends tokens?", f: (r) => (r.llm ? pill("may use Claude", "warn") : "no"), tip: "The cognify, improve, remember and memify endpoints call Claude." }, { t: "Who calls", f: (r) => Object.entries(r.callers).map(([k, v]) => `${k} (${v})`).join(", ") }], a.endpoints));
      }
      body.replaceChildren(...parts);
    } catch (e) { body.replaceChildren(fail(e)); }
  };
  hours.onchange = load; setTimeout(load, 0);
  return h("div", {}, intro("What am I looking at?", "Each time a program uses the memory (the Claude Code hooks, the MCP, your scripts) it makes a call to the Cognee API, which runs on your Mac. Here they are counted, grouped by endpoint, and it shows who made them. Useful for detecting unnecessary calls, errors and abnormal consumption."), h("div", { class: "row" }, h("span", { class: "muted" }, "Period"), hours), body);
} };

pages.sync = { title: "Synchronization", sub: "Which documents are indexed and what their last status was.", icon: "sync", run: async () => {
  const rows = await api("/registry");
  const bad = rows.filter((r) => r.status !== "indexed").length;
  return h("div", {}, intro("What is synchronization?", "Your Markdown documents are the source of truth. Synchronization copies them to the memory only when they change (by comparing a «hash», the file's fingerprint) and checks that they can be retrieved before marking them as indexed.", "It is launched by hand with «memctl.sh sync <repo> --apply», once per work milestone, not after every edit."),
    h("div", { class: "grid" }, kpi({ label: "Registered documents", value: num(rows.length) }), kpi({ label: "Indexed", value: num(rows.length - bad), meta: bad ? `${bad} pending` : "all" })),
    ...section("Registry", "A document appears as «indexed» only if a search retrieved it."), table([{ t: "Project", k: "project" }, { t: "Document", k: "path" }, { t: "Status", f: (r) => pill(r.status === "indexed" ? "indexed" : r.status, r.status === "indexed" ? "ok" : "warn") }, { t: "Hash", f: (r) => h("code", {}, r.hash), tip: "File fingerprint: if it changes, it is reindexed." }, { t: "Commit", k: "commit" }, { t: "Updated", f: (r) => ago(r.updated) }, { t: "Error", f: (r) => r.last_error || "—" }], rows));
} };

const meter = (pct, label, detail) => h("div", { class: "meter" }, h("div", { class: "meter-top" }, h("span", {}, label), h("b", {}, pct == null ? "—" : `${Math.round(pct)}%`)),
  h("div", { class: "meter-bar" }, h("i", { class: pct >= 90 ? "bad" : pct >= 75 ? "warn" : "", style: `width:${Math.min(100, Math.max(0, pct || 0))}%` })), detail ? h("div", { class: "muted small" }, detail) : null);
const lineChart = (vals, { max, fmt = (v) => `${Math.round(v)}%`, label = "" } = {}) => {
  if (vals.length < 2) return h("div", { class: "empty" }, "Not enough samples yet.");
  const w = 600, hg = 110, mx = max || Math.max(1, ...vals);
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${hg - 4 - (Math.min(v, mx) / mx) * (hg - 8)}`).join(" ");
  const s = document.createElementNS(SVGNS, "svg"); s.setAttribute("viewBox", `0 0 ${w} ${hg}`); s.setAttribute("preserveAspectRatio", "none"); s.setAttribute("class", "line"); s.setAttribute("role", "img"); s.setAttribute("aria-label", label);
  const pl = document.createElementNS(SVGNS, "polyline"); pl.setAttribute("points", pts); pl.setAttribute("fill", "none"); pl.setAttribute("stroke", "var(--brand)"); pl.setAttribute("stroke-width", 2); pl.setAttribute("vector-effect", "non-scaling-stroke"); pl.setAttribute("stroke-linejoin", "round");
  s.append(pl);
  return h("div", {}, s, h("div", { class: "axis" }, h("span", {}, "oldest"), h("span", {}, `now: ${fmt(vals[vals.length - 1])} · max. ${fmt(Math.max(...vals))}`)));
};

pages.usage = { title: "Memory usage", sub: "When the memory is queried and how the system uses it.", icon: "search", run: async () => {
  const days = h("select", {}, [1, 7, 14, 30].map((x) => h("option", { value: x, selected: x === 14 }, `last ${x} d`)));
  const body = h("div", {});
  const load = async () => {
    body.replaceChildren(loading());
    try {
      const u = await api(`/usage?days=${days.value}`);
      if (!u.file_present) { body.replaceChildren(h("div", { class: "callout" }, icon("alert", 20), h("div", {}, h("b", {}, "There is no usage record yet"), h("p", {}, "It is generated by scripts/usage_scan.py (it updates itself when each session closes). Run it once: python3 -I <KIT>/scripts/usage_scan.py")))); return; }
      const r = u.recall, s = u.sessions, pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
      const verdict = [];
      verdict.push(s.total ? [s.with_briefing >= s.total * 0.8 ? "ok" : "warn", `When opening a session, the briefing was injected in ${s.with_briefing} of ${s.total} sessions (${pct(s.with_briefing, s.total)} %). ${s.with_briefing >= s.total * 0.8 ? "The continuity system is working." : "Some sessions started without a briefing: check the hooks of that project."}`] : ["warn", "There are no sessions in this period."]);
      verdict.push(r.total ? ["ok", `Claude queried the memory ${r.total} ${r.total === 1 ? "time" : "times"} (${r.via_mcp} via MCP tool, ${r.via_skill} via the skill). Queries happen when the briefing is not enough.`] : ["warn", "Nobody has queried the memory in this period. This is normal if the briefing was enough, but if it always happens, the deep memory is not being used."]);
      if (r.answered) verdict.push([r.errors ? "warn" : "ok", `${r.ok} of ${r.answered} MCP queries returned content${r.errors ? `; ${r.errors} failed (see the table: ‘with error’)` : ""}.${r.avg_chars ? ` Average response size: ${num(r.avg_chars)} characters.` : ""} Median time: ${r.p50_s ?? "—"} s.`]);
      if (u.plugin.asked) verdict.push([u.plugin.hits ? "ok" : "warn", `The plugin measured that in ${u.plugin.hits} of ${u.plugin.asked} queries from its hooks there was a useful result (${pct(u.plugin.hits, u.plugin.asked)} %).`]);
      verdict.push(["info", "Note: this record proves that the memory IS USED and that it responds. Whether it really helps is checked with the evaluation (memctl.sh eval) and by comparing cost with and without memory."]);
      body.replaceChildren(
        h("div", { class: "grid" },
          kpi({ label: "Briefings injected", value: num(u.briefing.count), meta: `≈ ${num(u.briefing.avg_chars)} characters each`, tip: "Automatic summary (decisions, rules, pending items) that is loaded when a session opens, without querying Cognee." }),
          kpi({ label: "Memory queries", value: num(r.total), meta: `${r.via_mcp} MCP · ${r.via_skill} skill`, tip: "Times Claude searched the deep memory (Cognee) because the briefing was not enough." }),
          kpi({ label: "Queries with a result", value: r.answered ? `${pct(r.ok, r.answered)} %` : "—", meta: `${r.ok} of ${r.answered}`, tip: "MCP queries that returned content without an error." }),
          kpi({ label: "Sessions with a query", value: `${s.with_recall} / ${s.total}`, meta: "of the sessions in the period" }),
          kpi({ label: "Writes to memory", value: num(u.counts.write || 0), meta: "handoff / document / remember" })),
        ...section("Is it working?", "Automatic reading of the data, in simple words."),
        h("div", {}, verdict.map(([k, t]) => h("div", { class: `advice ${k === "ok" ? "tip" : k === "warn" ? "warn" : ""}` }, icon(k === "warn" ? "alert" : k === "ok" ? "check" : "info", 18), h("div", {}, t)))),
        ...section("Activity per day", "Bars: memory queries. The briefing is injected once per session."),
        h("div", { class: "grid two" }, h("div", { class: "card" }, h("h3", {}, "Queries per day"), barChart(u.per_day, { label: (p) => p.day, value: (p) => p.recall || 0 })),
          h("div", { class: "card" }, h("h3", {}, "Briefings per day"), barChart(u.per_day, { label: (p) => p.day, value: (p) => p.briefing || 0 }))),
        ...section("Latest events", "What was asked and what happened. Only the truncated question and the size of the response are stored, never the returned text."),
        table([{ t: "When", f: (e) => ago(e.when) }, { t: "Project", k: "project" },
          { t: "What", f: (e) => ({ recall: pill("query", "brand"), write: pill("write", "warn"), briefing: pill("briefing") })[e.kind] },
          { t: "Via", f: (e) => (e.via || "hook").replace("skill:project-memory-", "skill ") },
          { t: "Question", f: (e) => (e.kind === "briefing" ? `${num(e.chars)} characters injected` : e.query || "—") },
          { t: "Result", f: (e) => (e.kind !== "recall" || !("ok" in e) ? "—" : e.ok ? pill(`${num(e.chars)} chars.`, "ok") : pill("with error", "bad")) },
          { t: "Time", n: 1, f: (e) => (e.latency_s != null ? `${e.latency_s} s` : "—") }], u.recent, { empty: "No events in this period." }));
    } catch (e) { body.replaceChildren(fail(e)); }
  };
  days.onchange = load; setTimeout(load, 0);
  return h("div", {}, intro("What am I looking at?", "To know whether the memory is useful, you have to see whether it is used. This page reads the Claude Code sessions and counts when the briefing was injected at the start, when Claude searched the deep memory and with what result. It does not store the responses, only when, what was asked (truncated) and how much was returned.",
    "The data is generated by scripts/usage_scan.py reading ~/.claude/projects (read-only) and refreshes itself when each session closes. All your Claude Code sessions appear here, not just those launched with the telemetry launcher."),
    h("div", { class: "row" }, h("span", { class: "muted" }, "Period"), days), body);
} };

pages.resources = { title: "System resources", sub: "How much load your Mac and Docker have right now.", icon: "layers", run: async () => {
  const body = h("div", {});
  const load = async () => {
    try {
      const r = await api("/resources"), hs = r.host, dk = r.docker, parts = [];
      if (!hs.available) parts.push(...section("Your Mac", "It is only measured when you ask: there is no process measuring in the background."), h("div", { class: "card row" }, h("div", {}, h("b", {}, "No measurement yet"), h("div", { class: "muted small" }, "Press the button to take a snapshot of CPU, memory, disk and programs (takes ~2 s).")), h("span", { class: "spacer" }), measureBtn()));
      else {
        const L = hs.latest, m = L.memory, cpu = L.cpu ? L.cpu.used : null;
        parts.push(h("div", { class: "row", style: "margin-top:26px" }, h("div", {}, h("h2", { style: "margin:0" }, `Your Mac · ${L.model} · macOS ${L.os}`), h("p", { class: "hint", style: "margin:2px 0 0" }, `Measured ${hs.age_s < 90 ? "just now" : `${Math.round(hs.age_s / 60)} min ago`} (point-in-time snapshot, not live) · up for ${Math.round((L.uptime_s || 0) / 3600)} h${L.battery ? ` · battery ${L.battery.pct} % (${L.battery.on_ac ? "plugged in" : "on battery"})` : ""}`)), h("span", { class: "spacer" }), measureBtn()));
        parts.push(h("div", { class: "grid" },
          h("div", { class: "card" }, meter(cpu, "Processor (CPU)", `${L.cpu_count} cores · user ${L.cpu?.user ?? "—"} % · system ${L.cpu?.sys ?? "—"} %`)),
          h("div", { class: "card" }, meter((100 * m.used) / m.total, "Memory (RAM)", `${bytes(m.used)} of ${bytes(m.total)} · compressed ${bytes(m.compressed)}`)),
          h("div", { class: "card" }, meter(m.swap_total ? (100 * m.swap_used) / m.swap_total : 0, "Swap (memory on disk)", `${bytes(m.swap_used)} of ${bytes(m.swap_total)}`)),
          h("div", { class: "card" }, meter((100 * L.disk.used) / L.disk.total, "Disk", `${bytes(L.disk.free)} free of ${bytes(L.disk.total)}`)),
          kpi({ label: "System load", value: L.load[0].toFixed(2), meta: `5 min ${L.load[1].toFixed(2)} · 15 min ${L.load[2].toFixed(2)}`, tip: "Processes waiting for CPU. If it is consistently greater than the number of cores, the Mac is saturated." }),
          kpi({ label: "Memory pressure", value: m.free_pct == null ? "—" : `${m.free_pct} % free`, meta: m.free_pct != null && m.free_pct < 20 ? "High: the Mac is running tight on memory" : "Normal", tip: "macOS measure: the more free memory, the better." })));
        parts.push(h("div", { class: "grid two", style: "margin-top:14px" },
          h("div", { class: "card" }, h("h3", {}, "CPU in your measurements"), lineChart(hs.history.map((x) => x.cpu ?? 0), { max: 100, label: "CPU" })),
          h("div", { class: "card" }, h("h3", {}, "Memory in your measurements"), lineChart(hs.history.map((x) => (100 * x.mem_used) / m.total), { max: 100, label: "Memory" }))));
        parts.push(h("div", { class: "grid two", style: "margin-top:14px" },
          h("div", {}, h("h3", {}, "Who uses the most CPU"), table([{ t: "Program", k: "name" }, { t: "CPU", n: 1, f: (p) => `${p.cpu.toFixed(1)} %` }, { t: "Processes", n: 1, k: "n" }], L.procs.by_cpu)),
          h("div", {}, h("h3", {}, "Who uses the most memory"), table([{ t: "Program", k: "name" }, { t: "Memory", n: 1, f: (p) => bytes(p.rss) }, { t: "Processes", n: 1, k: "n" }], L.procs.by_mem))));
      }
      if (!dk.available) parts.push(...section("Docker"), h("div", { class: "empty" }, dk.error || "No access to Docker."));
      else {
        const e = dk.engine, u = dk.usage, d = dk.disk;
        parts.push(...section(`Docker · engine ${e.version}`, `The Docker virtual machine has ${e.cpus} CPUs and ${bytes(e.mem_total)} of memory. ${e.running} of ${e.containers} containers running.`));
        parts.push(h("div", { class: "grid" },
          h("div", { class: "card" }, meter((100 * u.mem_used) / e.mem_total, "Docker VM memory", `${bytes(u.mem_used)} of ${bytes(e.mem_total)} used by the containers`)),
          h("div", { class: "card" }, meter(u.cpu_pct_sum / e.cpus, "Docker VM CPU", `${u.cpu_pct_sum} % of one core summed (${e.cpus} cores)`)),
          kpi({ label: "Images", value: bytes(d.images_bytes), meta: `${d.images} images`, tip: "Downloaded or built programs. They can be rebuilt." }),
          kpi({ label: "Volumes (your data)", value: bytes(d.volumes_bytes), meta: "Postgres, graphs, models", tip: "The memory's data lives here. Do not delete it." }),
          kpi({ label: "Build cache", value: bytes(d.build_cache_bytes), meta: "can be cleaned without losing data", tip: "Leftovers from building images. docker builder prune frees it." })));
        parts.push(h("h3", { style: "margin-top:18px" }, "Containers"), table([{ t: "Container", f: (c) => h("strong", {}, c.service || c.name) }, { t: "Status", f: (c) => pill(`${c.state === "running" ? "active" : c.state}${c.health ? " · " + c.health : ""}`, c.state === "running" && c.health !== "unhealthy" ? "ok" : "") },
          { t: "CPU", n: 1, f: (c) => (c.cpu_pct == null ? "—" : `${c.cpu_pct} %`) }, { t: "Memory", n: 1, f: (c) => (c.mem_bytes == null ? "—" : `${bytes(c.mem_bytes)}${c.mem_limit && c.mem_limit < e.mem_total ? " / " + bytes(c.mem_limit) : ""}`) }, { t: "Restarts", n: 1, f: (c) => c.restarts ?? "—" }], dk.containers));
        parts.push(h("h3", { style: "margin-top:18px" }, "Largest volumes"), table([{ t: "Volume", f: (v) => h("code", {}, v.name.length > 46 ? v.name.slice(0, 46) + "…" : v.name) }, { t: "Size", n: 1, f: (v) => (v.bytes < 0 ? "—" : bytes(v.bytes)) }], d.volumes));
      }
      body.replaceChildren(...parts);
    } catch (e) { body.replaceChildren(fail(e)); }
  };
  const measureBtn = () => h("button", { onclick: async (e) => { const b = e.currentTarget; b.disabled = true; b.textContent = "Measuring…"; try { await api("/resources/host", { method: "POST" }); } catch (x) { alert(x.message); } load(); } }, "Measure the Mac now");
  body.replaceChildren(loading()); setTimeout(load, 0);
  return h("div", {}, intro("What am I looking at?", "The real load of the machine where everything runs: your Mac (processor, memory, disk) and Docker (the mini‑machine that runs the memory and its containers). It is useful for knowing whether there is headroom, whether something is saturating the machine and how much space the data takes up. Docker is read when the page is opened; the Mac is only measured when you press «Measure the Mac now». Nothing is measuring in the background, so it does not slow down your machine.",
    "A container cannot see the Mac, so when you press the button the panel asks launchd to run host_stats.py just once (~2 s) and exit. At rest there is no process or consumption. The Docker data comes from the engine itself, through a read-only proxy."), body);
} };

pages.guide = { title: "Guide and glossary", sub: "Everything you need to read this panel.", icon: "info", run: async () => h("div", {},
  intro("What is Management Memory?", "A read-only control panel to understand and monitor the memory your AI uses: how much knowledge there is per project, how much space it takes, what it costs to maintain and whether everything works. It does not modify anything: it is for making decisions."),
  ...section("What is local and what leaves your Mac?", "Everything runs on your Mac. Only one step uses an external service."),
  h("div", { class: "grid two" }, h("div", { class: "card" }, h("h3", {}, "Local (does not leave your Mac)"), h("ul", {}, h("li", {}, "Cognee, the database, the MCP and this panel."), h("li", {}, "Creating the vectors (embeddings): done by a local model."), h("li", {}, "Searching: your question is converted into a vector and compared in PostgreSQL."))),
    h("div", { class: "card" }, h("h3", {}, "Goes out to Claude (Anthropic)"), h("ul", {}, h("li", {}, "When indexing: the fragments are sent to Claude (via the observer) to summarize them and extract concepts. It spends tokens."), h("li", {}, "When asking: the retrieved text is included in your conversation with Claude Code.")))),
  ...section("How it all connects", "From your document to an answer."), h("div", { class: "card" }, h("ol", { class: "steps" },
    h("li", {}, h("b", {}, "You write a document "), "(Markdown) in your project."),
    h("li", {}, h("b", {}, "Synchronization sends it to Cognee "), "only if it changed."),
    h("li", {}, h("b", {}, "Cognee cuts it into fragments, "), "computes their vectors locally and asks Claude (via the observer) for summaries and concepts: this is where tokens are spent."),
    h("li", {}, h("b", {}, "The vectors are stored "), "in PostgreSQL and the graph in its own file."),
    h("li", {}, h("b", {}, "When Claude Code asks something, "), "the question is converted into a vector and the closest fragments are returned (without spending tokens)."))),
  ...section("What each section does"), h("div", { class: "grid two" }, [["Overview", "Health and key numbers."], ["Knowledge bases", "Size and cost per project; warnings to decide what to compact."], ["Vectors", "Which fingerprints are stored and how much they weigh."], ["Graph", "The concept map."], ["PostgreSQL", "The database, read-only."], ["Search", "Test retrieval."], ["Memory usage", "When it is queried and whether it responds: proof that it works."], ["System resources", "Snapshot of the Mac's load (on demand) and of Docker."], ["Tokens and cost", "AI consumption, from three sources."], ["API and containers", "Who calls Cognee and the health of the services."]].map(([a, b]) => h("div", { class: "card" }, h("b", {}, a), h("div", { class: "muted" }, b)))),
  ...section("Glossary"), h("div", { class: "card" }, h("dl", { class: "gloss" }, GLOSSARY.flatMap(([t, d]) => [h("dt", {}, t), h("dd", {}, d)])))) };


/* ── Swarm: agents, assigned tasks, pending work, board, verdicts, efficiency (read-only) ── */
const STATE_TONE = { running: "ok", queued: "brand", succeeded: "ok", failed: "bad", timeout: "warn", parked: "bad", cancelled: "", awaiting_approval: "warn", approved: "brand", in_progress: "ok", review: "brand", done: "ok", needs_attention: "warn", draft: "" };
const sp = (v) => pill(String(v || "—").replace(/_/g, " "), STATE_TONE[v] || "");
const dur = (a, b) => { if (!a) return "—"; const s = ((b ? new Date(b) : new Date()) - new Date(a)) / 1000; return s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`; };
const SWARM_TABS = [["agents", "Agents and tasks"], ["pending", "Pending work"], ["board", "Change board"], ["verdicts", "Verdicts and health"], ["efficiency", "Efficiency"]];
let swarmTab = "agents";

async function swarmAgents() {
  const o = await api("/swarm/agents"), root = h("div", {});
  const risk = { low: "ok", medium: "warn", high: "bad", unknown: "" }[o.quota_risk];
  root.append(h("div", { class: "grid" },
    kpi({ label: "Active agents", value: num(o.active.length), meta: "running or queued now", tip: "One row per job the dispatcher is running. Concurrency is capped (default 2)." }),
    kpi({ label: "Quota risk (5 h window)", value: h("span", {}, sp(o.quota_risk)), meta: o.quota_utilization == null ? "no reading yet" : `${(o.quota_utilization * 100).toFixed(0)}% of the subscription window`, tip: "Taken from the utilisation figure Claude Code reports for your subscription. Above 85% pause the swarm (swarm pause)." }),
    kpi({ label: "Recent runs", value: num(o.recent.length), meta: `${o.recent.filter((r) => r.state === "succeeded").length} succeeded` })));
  root.append(...section("Who is doing what right now", "Each active agent with the task it is assigned to."));
  root.append(table([
    { t: "Run", f: (r) => `#${r.id}` }, { t: "Project", k: "project_id" }, { t: "Agent", f: (r) => h("span", {}, h("b", {}, r.role), " ", pill(`${r.model || "?"}${r.effort ? " · " + r.effort : ""}`)) },
    { t: "Change", k: "change_id" }, { t: "Assigned task", f: (r) => r.task_id ? `${r.task_id} — ${r.task_title || ""}` : r.kind }, { t: "State", f: (r) => sp(r.state) },
    { t: "Running", f: (r) => dur(r.started_at) }, { t: "Turns", n: 1, f: (r) => num(r.turns) }], o.active, { empty: "No agent is running. Start one with `swarm implement <change>`.", onrow: (r) => runDetail(r.id) }));
  root.append(...section("Recent runs", "Click a row for its events, health checks and memory recalls."));
  root.append(table([
    { t: "Run", f: (r) => `#${r.id}` }, { t: "Project", k: "project_id" }, { t: "Agent", f: (r) => `${r.role} · ${r.model || "?"}` }, { t: "Change", k: "change_id" }, { t: "Task", k: "task_id" },
    { t: "Result", f: (r) => sp(r.state) }, { t: "Took", f: (r) => dur(r.started_at, r.ended_at) }, { t: "Tokens in/out", n: 1, f: (r) => `${num(r.input_tokens)} / ${num(r.output_tokens)}` }], o.recent, { onrow: (r) => runDetail(r.id) }));
  root.append(h("div", { id: "runBox" }));
  return root;
}
async function runDetail(id) {
  const d = await api(`/swarm/runs/${id}`), box = $("#runBox"); if (!box) return;
  box.replaceChildren(h("div", { class: "card", style: "margin-top:14px" }, h("h3", {}, `Run #${id} — ${d.run.role} (${d.run.state})`),
    h("p", { class: "hint" }, d.run.summary || d.run.progress || "No summary recorded."),
    h("h4", {}, "Events"), table([{ t: "When", f: (e) => ago(e.ts) }, { t: "Type", k: "type" }, { t: "Tool", k: "tool" }, { t: "OK", f: (e) => e.ok == null ? "—" : e.ok ? pill("ok", "ok") : pill("blocked/failed", "bad") }, { t: "Detail", f: (e) => h("code", {}, JSON.stringify(e.detail).slice(0, 140)) }], d.events),
    h("h4", {}, "Memory recalls"), table([{ t: "Dataset", k: "dataset" }, { t: "Results", n: 1, k: "results" }, { t: "Used", f: (r) => r.rejected ? pill("rejected (cross-project)", "bad") : r.used ? pill("used", "ok") : pill("not used", "warn") }], d.recalls, { empty: "No recalls in this run." }),
    h("h4", {}, "Health checks"), table([{ t: "When", f: (e) => ago(e.ts) }, { t: "Result", f: (e) => e.ok ? pill("pass", "ok") : pill("fail", "bad") }, { t: "Output (tail)", f: (e) => h("code", {}, (e.output_tail || "").slice(-160)) }], d.health, { empty: "No health checks." })));
  box.scrollIntoView({ behavior: "smooth" });
}
async function swarmPending() {
  const rows = await api("/swarm/pending"), root = h("div", {});
  const byChange = {}; rows.forEach((r) => (byChange[`${r.project_id} / ${r.change_id}`] ||= []).push(r));
  root.append(intro("Pending work", "Every unchecked task of every OpenSpec change, in the order the swarm will execute them. Tasks of one change run in sequence; different changes can run in parallel.", "A task is ticked only after its own verification (and the health script) passed. Awaiting approval means nothing runs until you run `swarm approve <change>`."));
  root.append(h("div", { class: "grid" }, kpi({ label: "Pending tasks", value: num(rows.length) }), kpi({ label: "Changes with work left", value: num(Object.keys(byChange).length) }),
    kpi({ label: "Assigned right now", value: num(rows.filter((r) => r.assigned_run).length), meta: "being worked by an agent" })));
  for (const [k, items] of Object.entries(byChange)) {
    root.append(h("h2", {}, k, " ", sp(items[0].change_status)));
    root.append(table([{ t: "Task", k: "task_id" }, { t: "Group", k: "group_title" }, { t: "What", k: "title" }, { t: "Verification", f: (r) => h("code", {}, r.verification || "health script") },
      { t: "Assigned", f: (r) => r.assigned_run ? pill(`${r.assigned_role} · run #${r.assigned_run}`, "ok") : pill("not started") }], items));
  }
  if (!rows.length) root.append(h("div", { class: "empty" }, "Nothing pending. Run `swarm sync-state` in a project to load its changes."));
  return root;
}
async function swarmBoard() {
  const o = await api("/swarm/board"), root = h("div", {});
  root.append(intro("Change board", "Each OpenSpec change moves left to right: awaiting approval → approved → in progress → review → done. Parked means two failed reviews: it needs you."));
  const cols = ["awaiting_approval", "approved", "in_progress", "review", "done", "parked", "needs_attention"];
  root.append(h("div", { class: "board" }, cols.map((c) => h("div", { class: "card col" }, h("h3", {}, c.replace(/_/g, " "), " ", pill(String((o.columns[c] || []).length))),
    (o.columns[c] || []).map((x) => h("div", { class: "chg" }, h("b", {}, x.change_id), h("div", { class: "muted small" }, x.project_id), h("div", { class: "small" }, `${x.tasks_done}/${x.tasks_total} tasks · ${x.scenarios} scenarios`)))))));
  return root;
}
async function swarmVerdicts() {
  const o = await api("/swarm/verdicts"), root = h("div", {});
  root.append(...section("Reviewer verdicts", "A change is done only when every scenario has evidence and the health script passes."));
  root.append(table([{ t: "When", f: (r) => ago(r.created_at) }, { t: "Project", k: "project_id" }, { t: "Change", k: "change_id" }, { t: "Verdict", f: (r) => r.passed ? pill("pass", "ok") : pill("fail", "bad") },
    { t: "Scenarios", f: (r) => { const s = JSON.parse(r.scenarios || "[]"); return `${s.filter((x) => x.status === "pass").length}/${s.length} pass`; } },
    { t: "Findings", f: (r) => JSON.parse(r.findings || "[]").slice(0, 2).join(" · ") || "—" }], o.verdicts, { empty: "No verdicts yet." }));
  root.append(...section("Health-script history"));
  root.append(table([{ t: "When", f: (r) => ago(r.ts) }, { t: "Project", k: "project_id" }, { t: "Change", k: "change_id" }, { t: "Result", f: (r) => r.ok ? pill("pass", "ok") : pill("fail", "bad") }, { t: "Run", f: (r) => r.run_id ? `#${r.run_id}` : "—" }], o.health, { empty: "No health runs yet." }));
  return root;
}
async function swarmEfficiency() {
  const o = await api("/swarm/efficiency"), root = h("div", {});
  root.append(intro("Token efficiency", "Where the subscription quota goes: per role, how many tokens, how much was served from cache, turns and how full the context got. Defaults change only after a before/after comparison.", "Cache share = cache-read tokens / all input tokens. Context at end = size of the last request. Policy thresholds from outside sources are hypotheses until this page confirms them."));
  root.append(...section("By role"));
  root.append(table([{ t: "Role", k: "role" }, { t: "Runs", n: 1, k: "runs" }, { t: "Input", n: 1, f: (r) => num(r.input_tokens) }, { t: "Output", n: 1, f: (r) => num(r.output_tokens) },
    { t: "Cache share", n: 1, f: (r) => `${(r.cache_read_share * 100).toFixed(0)}%`, tip: "Higher is cheaper: stable prompts get reused." }, { t: "Avg turns", n: 1, k: "avg_turns" }, { t: "Context at end", n: 1, f: (r) => num(r.avg_context_end) },
    { t: "Retries", n: 1, k: "retries" }, { t: "Failed", n: 1, k: "bad" }], o.by_role, { empty: "No finished runs yet." }));
  root.append(h("div", { class: "grid two", style: "margin-top:14px" },
    h("div", { class: "card" }, h("h3", {}, "Model mix"), hbars(o.models.map((m) => ({ l: m.model, v: m.runs })))),
    h("div", { class: "card" }, h("h3", {}, "Memory usefulness"), table([{ t: "Run", f: (r) => `#${r.run_id}` }, { t: "Recalls", n: 1, k: "recalls" }, { t: "Used", n: 1, k: "used" }, { t: "Flag", f: (r) => r.flag === "unused" ? pill("unused recalls", "warn") : pill("ok", "ok") }], o.recalls, { empty: "No recalls logged." }))));
  root.append(...section("Compare two runs", "Pick two runs of the same task under different policies."));
  const a = h("input", { type: "number", placeholder: "run A" }), b = h("input", { type: "number", placeholder: "run B" }), out = h("div", {});
  root.append(h("div", { class: "row" }, a, b, h("button", { onclick: async () => { try { const c = await api(`/swarm/compare?a=${a.value}&b=${b.value}`);
    const f = [["role"], ["model"], ["effort"], ["state"], ["turns"], ["input_tokens"], ["output_tokens"], ["cache_read_tokens"], ["policy_hash"]];
    out.replaceChildren(table([{ t: "Metric", f: (r) => r[0] }, { t: `Run #${c.a.id}`, f: (r) => String(c.a[r[0]] ?? "—") }, { t: `Run #${c.b.id}`, f: (r) => String(c.b[r[0]] ?? "—") }], f)); } catch (e) { out.replaceChildren(fail(e)); } } }, "Compare")), out);
  root.append(...section("Finished runs"));
  root.append(table([{ t: "Run", f: (r) => `#${r.id}` }, { t: "Role", k: "role" }, { t: "Model", f: (r) => `${r.model || "?"}${r.effort ? " · " + r.effort : ""}` }, { t: "State", f: (r) => sp(r.state) }, { t: "Turns", n: 1, k: "turns" },
    { t: "In", n: 1, f: (r) => num(r.input_tokens) }, { t: "Out", n: 1, f: (r) => num(r.output_tokens) }, { t: "Cache read", n: 1, f: (r) => num(r.cache_read_tokens) }, { t: "Policy", f: (r) => h("code", {}, r.policy_hash || "—") }], o.runs));
  return root;
}
pages.swarm = { title: "Swarm", sub: "What the agents are doing, what is assigned to them and what is still pending.", icon: "layers", run: async () => {
  const body = h("div", {}), tabs = h("div", { class: "tabs" }, SWARM_TABS.map(([k, n]) => h("button", { class: "tab" + (k === swarmTab ? " on" : ""), onclick: async (e) => { swarmTab = k; tabs.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x === e.currentTarget)); await load(); } }, n)));
  const fns = { agents: swarmAgents, pending: swarmPending, board: swarmBoard, verdicts: swarmVerdicts, efficiency: swarmEfficiency };
  const load = async () => { body.replaceChildren(loading()); try { body.replaceChildren(await fns[swarmTab]()); } catch (e) { body.replaceChildren(fail(e)); } };
  await load();
  return h("div", {}, h("div", { class: "callout", style: "margin-bottom:12px" }, icon("info", 20), h("div", {}, h("b", {}, "Read-only"), h("p", {}, "This page cannot start, stop or approve anything. Use the `swarm` command; the panel only shows the database."))), tabs, body);
} };

/* ── navigation and theme ── */
const NAV = [["General", ["overview"]], ["Knowledge", ["knowledge", "vectors", "graph", "search"]], ["Data", ["postgres", "sync"]], ["Agents", ["swarm"]], ["Consumption and health", ["usage", "resources", "tokens", "calls"]], ["Help", ["guide"]]];
const NAMES = { overview: "Overview", knowledge: "Knowledge bases", vectors: "Vectors", graph: "Graph", search: "Search", postgres: "PostgreSQL", sync: "Synchronization", usage: "Memory usage", resources: "System resources", tokens: "Tokens and cost", calls: "API and containers", guide: "Guide and glossary", swarm: "Swarm" };
function themeBtn() {
  const dark = document.documentElement.dataset.theme === "dark";
  return h("button", { class: "ghost", id: "themeBtn", title: "Change theme", "aria-label": "Change theme", onclick: () => { const d = document.documentElement.dataset.theme !== "dark"; document.documentElement.dataset.theme = d ? "dark" : "light"; try { localStorage.setItem("mm-theme", d ? "dark" : "light"); } catch (_) { /* no storage */ } $("#themeBtn").replaceWith(themeBtn()); } }, icon(dark ? "sun" : "moon", 15));
}
function route() {
  const key = (location.hash || "#overview").slice(1), p = pages[key] || pages.overview;
  document.querySelectorAll("#menu a").forEach((a) => a.classList.toggle("on", a.dataset.k === (pages[key] ? key : "overview")));
  $("#title").textContent = p.title; $("#subtitle").textContent = p.sub; document.title = `${p.title} · Management Memory`; $("#side").classList.remove("open");
  $("#actions").replaceChildren(h("button", { class: "ghost", onclick: route, title: "Reload the data" }, icon("refresh", 15), " Refresh"), themeBtn());
  render(p.run);
}
try { const t = localStorage.getItem("mm-theme") || (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light"); document.documentElement.dataset.theme = t; } catch (_) { /* default theme */ }
$("#menu").append(...NAV.flatMap(([g, keys]) => [h("div", { class: "group" }, g), ...keys.map((k) => h("a", { data: { k }, href: "#" + k }, icon(pages[k].icon, 18), NAMES[k]))]));
$("#menuBtn").onclick = () => $("#side").classList.toggle("open");
addEventListener("hashchange", route); route();
setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString("es-CO"); }, 1000);
