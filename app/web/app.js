"use strict";
// Frontend for the AI Act assistant. All model output is HTML-escaped before rendering;
// citation links are built here from server-provided URLs, never from model text.

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ tabs
const TAB_TITLES = { chat: "Chat", scheme: "Scheme", source: "Source code", evaluation: "Evaluation", agentic: "Agentic usage" };
document.querySelectorAll(".tabs button[data-tab]").forEach((b) =>
  b.addEventListener("click", () => { showTab(b.dataset.tab); closeMobileSidebar(); }));
const loaded = {};
function showTab(name) {
  document.querySelectorAll(".tabs button[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  $("#crumb").textContent = TAB_TITLES[name] || "";
  if (!loaded[name]) { loaded[name] = true; ({ scheme: loadScheme, source: loadSource, evaluation: loadEvals, agentic: () => loadDoc("log") })[name]?.(); }
  try { history.replaceState(null, "", `#${name}`); } catch {}
}

// ------------------------------------------------------------------ citations (mirror of app/chat/citations.py norm)
function norm(label) {
  let s = label.trim().toLowerCase();
  s = s.replace(/\barticles?\b\.?/g, "art.").replace(/\bart\b\.?/g, "art.").replace(/\brecitals?\b/g, "recital");
  s = s.replace(/[–—‑]/g, "-").replace(/\s*-\s*/g, "-").replace(/\s*\(\s*/g, "(").replace(/\s*\)/g, ")");
  s = s.replace(/\s*,\s*/g, ", ").replace(/\s+/g, " ").replace(/art\.\s*/g, "art. ");
  return s;
}
// a citation narrowing a retrieved excerpt ("Annex III, point 1(c)") links to that excerpt
function lookup(n, cmap) {
  while (n) {
    if (cmap.has(n)) return cmap.get(n);
    const m = n.match(/\([a-z0-9]{1,4}\)$/);
    if (!m) return null;
    n = n.slice(0, m.index).trimEnd();
  }
  return null;
}
const isCite = (s) => /^\s*(art\.?|article|annex|recital)\b/i.test(s);

// ------------------------------------------------------------------ minimal, safe markdown
const unesc = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const BAD_TIP = "Not among the provisions this answer was based on: check it on EUR-Lex before relying on it";
const chip = (label, url, header) => `<a class="cite" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(header || "")}">${esc(label)}</a>`;

// br: the server's verdict per bracket (final answers). null while streaming: unknown forms are then drawn neutral,
// not red, because only the server's check is authoritative.
function inline(raw, cmap, br = null) {
  // raw is unescaped text; escape first, then add our own markup
  let s = esc(raw);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:]|$)/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\[\]\n]{2,80})\]/g, (m, inner) => {
    const decided = br && br[unesc(inner)];
    if (decided) {
      return decided.map((c) => (c.valid ? chip(c.label, c.url, c.header)
        : `<span class="cite bad" title="${BAD_TIP}">${esc(c.label)}</span>`)).join(" ");
    }
    const parts = inner.split(";").map((p) => p.trim()).filter(Boolean);
    if (!parts.every((p) => isCite(unesc(p)))) return m;
    return parts.map((p) => {
      const hit = lookup(norm(unesc(p)), cmap);
      if (hit) return `<a class="cite" href="${esc(hit.url)}" target="_blank" rel="noopener" title="${esc(hit.header || "")}">${p}</a>`;
      return br ? `<span class="cite bad" title="${BAD_TIP}">${p}</span>` : `<span class="cite">${p}</span>`;
    }).join(" ");
  });
  return s;
}

function renderMarkdown(text, cmap, br = null) {
  const lines = text.replace(/\r/g, "").split("\n");
  let html = "", list = null, para = [];
  const flushPara = () => { if (para.length) { html += `<p>${para.map((l) => inline(l, cmap, br)).join("<br>")}</p>`; para = []; } };
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const line of lines) {
    const ul = line.match(/^\s*[-*•]\s+(.*)$/), ol = line.match(/^\s*\d+[.)]\s+(.*)$/), h = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const want = ul ? "ul" : "ol";
      if (list !== want) { closeList(); html += `<${want}>`; list = want; }
      html += `<li>${inline((ul || ol)[1], cmap, br)}</li>`;
    } else if (h) { flushPara(); closeList(); html += `<h4>${inline(h[1], cmap, br)}</h4>`; }
    else if (!line.trim()) { flushPara(); closeList(); }
    else { closeList(); para.push(line); }
  }
  flushPara(); closeList();
  return html;
}

// ------------------------------------------------------------------ chat
const SKEY = "aiact.session", STYLE_KEY = "aiact.style";
let session = null;
try { session = localStorage.getItem(SKEY); } catch {}

// answer style toggle: legal | plain (sent with every question; the server validates it)
let style = "legal";
try { if (localStorage.getItem(STYLE_KEY) === "plain") style = "plain"; } catch {}
function setStyle(s) {
  style = s;
  document.querySelectorAll(".style-toggle button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.style === s)));
  try { localStorage.setItem(STYLE_KEY, s); } catch {}
}
document.querySelectorAll(".style-toggle button").forEach((b) => b.addEventListener("click", () => setStyle(b.dataset.style)));
setStyle(style);
let busy = false;

const messagesEl = $("#messages"), q = $("#q"), send = $("#send");

function addMsg(cls, html) {
  $("#empty")?.remove();
  const d = document.createElement("div");
  d.className = `msg ${cls}`;
  d.innerHTML = html;
  messagesEl.appendChild(d);
  d.scrollIntoView({ block: "end", behavior: "smooth" });
  return d;
}

function sourcesMap(sources) {
  const m = new Map();
  (sources || []).forEach((s) => { if (!m.has(norm(s.label))) m.set(norm(s.label), s); });
  return m;
}

function showSources(sources, citedIds) {
  const list = $("#sources-list");
  list.innerHTML = "";
  $("#sources-empty").style.display = sources?.length ? "none" : "";
  const cited = new Set(citedIds || []);
  (sources || []).forEach((s) => {
    const li = document.createElement("li");
    if (cited.has(s.id)) li.className = "cited";
    li.innerHTML = `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a><span class="hdr">${esc(s.header)}</span>`;
    list.appendChild(li);
  });
}

function metaLine(ev) {
  const bits = [];
  const ans = (ev.usage || []).find((u) => !u.model.includes("lite")) || (ev.usage || [])[0];
  if (ans) bits.push(esc(ans.model));
  if (ev.style && ev.kind === "answer") bits.push(ev.style === "plain" ? "explanatory" : "legal detail");
  if (ev.latency_s != null) bits.push(`${ev.latency_s.toFixed(1)} s`);
  if (ev.cost_usd != null) bits.push(`$${ev.cost_usd.toFixed(4)}`);
  if (ev.citations) bits.push(`${ev.citations.filter((c) => c.valid).length} citation(s)`);
  if (ev.stage) bits.push(`decided by: ${esc(ev.stage)}`);
  const issues = (ev.issues || []).map((i) => `<span class="badge">${esc(i.replace(/_/g, " "))}</span>`).join("");
  return `<div class="meta">${bits.map((b) => `<span>${b}</span>`).join("")}${issues}</div>`;
}

async function ask(text) {
  if (busy || !text.trim()) return;
  busy = true; send.disabled = true;
  addMsg("user", esc(text));
  const bot = addMsg("bot", `<div class="body thinking">Checking the question…</div>`);
  const body = $(".body", bot);
  let acc = "", cmap = new Map(), standalone = "";

  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: session, message: text, style }),
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data: ")) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "session") { session = ev.session_id; try { localStorage.setItem(SKEY, session); } catch {} enableExport(); }
        else if (ev.type === "meta") {
          cmap = sourcesMap(ev.sources); standalone = ev.standalone; showSources(ev.sources, []);
          body.className = "body cursor"; body.innerHTML = "";
          if (standalone && standalone.trim().toLowerCase() !== text.trim().toLowerCase())
            bot.insertAdjacentHTML("afterbegin", `<div class="interp">Interpreted as: ${esc(standalone)}</div>`);
        } else if (ev.type === "delta") {
          acc += ev.text; body.innerHTML = renderMarkdown(acc, cmap);
        } else if (ev.type === "done") {
          body.className = "body";
          const finalMap = new Map(cmap);
          (ev.citations || []).forEach((c) => { if (c.valid) finalMap.set(norm(c.label), { url: c.url, header: "" }); });
          body.innerHTML = renderMarkdown(ev.text, finalMap, ev.brackets || {});
          showSources(ev.sources, (ev.citations || []).filter((c) => c.valid).map((c) => c.chunk_id));
          bot.insertAdjacentHTML("beforeend", metaLine(ev));
        } else if (ev.type === "final") {
          bot.classList.add(ev.kind); body.className = "body"; body.innerHTML = renderMarkdown(ev.text, new Map());
          bot.insertAdjacentHTML("beforeend", metaLine(ev));
          if (ev.kind !== "answer") showSources([], []);
        } else if (ev.type === "error") {
          bot.classList.add("error"); body.className = "body"; body.textContent = ev.text;
        }
        bot.scrollIntoView({ block: "end" });
      }
    }
  } catch (e) {
    bot.classList.add("error"); body.className = "body"; body.textContent = "Connection problem. Please try again.";
  } finally {
    busy = false; send.disabled = false; q.focus();
  }
}

$("#ask").addEventListener("submit", (e) => {
  e.preventDefault();
  if (busy || !q.value.trim()) return; // keep the text in the box until the previous answer has finished
  const t = q.value; q.value = ""; autosize(); ask(t);
});
q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask").requestSubmit(); } });
const autosize = () => { q.style.height = "auto"; q.style.height = `${Math.min(q.scrollHeight, 160)}px`; };
q.addEventListener("input", autosize);
document.querySelectorAll(".ex").forEach((b) => b.addEventListener("click", () => ask(b.textContent)));
$("#new").addEventListener("click", () => {
  session = null; try { localStorage.removeItem(SKEY); } catch {}
  location.hash = "chat"; location.reload();
});

// ------------------------------------------------------------------ export
const csvCell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
async function exportConversation() {
  if (!session) return;
  const r = await fetch(`/api/session/${session}`);
  if (!r.ok) return;
  const { messages } = await r.json();
  const rows = [["no", "role", "message", "interpreted_as", "type", "style", "cited_provisions"]];
  let n = 0;
  for (const m of messages) {
    if (m.role === "user") n += 1;
    const labels = new Map((m.meta?.sources || []).map((src) => [src.id, src.label]));
    const cited = [...new Set((m.cited_ids || []).map((id) => labels.get(id) || id))].join("; ");
    rows.push([n, m.role === "user" ? "you" : "assistant", m.content,
      m.role === "user" && m.standalone && m.standalone !== m.content ? m.standalone : "",
      m.kind, ({ legal: "Legal detail", plain: "Explanatory" })[m.meta?.style] || "", cited]);
  }
  // BOM so spreadsheet apps read the text as UTF-8
  const csv = "\ufeff" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = `ai-act-conversation-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
$("#export").addEventListener("click", exportConversation);
const enableExport = () => { $("#export").disabled = !session; };

async function restore() {
  if (!session) return;
  try {
    const r = await fetch(`/api/session/${session}`);
    if (!r.ok) { session = null; return; }
    const { messages } = await r.json();
    for (const m of messages) {
      if (m.role === "user") { addMsg("user", esc(m.content)); continue; }
      const map = sourcesMap(m.meta?.sources);
      const d = addMsg(`bot ${m.kind}`, `<div class="body">${renderMarkdown(m.content, map, m.meta?.brackets || {})}</div>`);
      if (m.kind === "answer") showSources(m.meta?.sources, m.cited_ids);
      d.insertAdjacentHTML("beforeend", metaLine({ ...m.meta, kind: m.kind, citations: null }));
    }
  } catch {}
}

async function loadInfo() {
  try {
    const i = await (await fetch("/api/info")).json();
    $("#banner").innerHTML = `<b>${esc(i.corpus.version)}.</b> ${esc(i.corpus.notice)} <a href="${esc(i.corpus.url)}" target="_blank" rel="noopener">Source on EUR-Lex</a>`;
    const pf = i.performance;
    $("#models").innerHTML = `Generation <b>${esc(i.models.answer)}</b><br>Guard <b>${esc(i.models.guard)}</b><br>Embeddings <b>${esc(i.models.embedder)}</b><br>${esc(i.chunks)} chunks`
      + (pf ? `<br><abbr title="Time to first token: from sending a question to the first word of the answer (median of ${pf.n_answers} eval answers)">TTFT</abbr> <b>${pf.ttft_p50_s} s</b><br>Speed <b>${pf.tokens_per_s_p50} tok/s</b><br>Full answer <b>${pf.total_p50_s} s</b>` : "");
  } catch { $("#banner").textContent = "Could not load service info."; }
}

// ------------------------------------------------------------------ source code
async function loadSource() {
  const files = await (await fetch("/api/source")).json();
  const nav = $("#files");
  let group = "";
  for (const f of files) {
    if (f.group !== group) { group = f.group; nav.insertAdjacentHTML("beforeend", `<h4>${esc(group)}</h4>`); }
    const b = document.createElement("button");
    b.textContent = f.path.split("/").pop(); b.title = f.path;
    b.addEventListener("click", () => openFile(f, b));
    nav.appendChild(b);
  }
  const first = nav.querySelector("button"); if (first) first.click();
}
async function openFile(f, btn) {
  document.querySelectorAll(".files button").forEach((x) => x.classList.toggle("on", x === btn));
  const { text } = await (await fetch(`/api/source/file?path=${encodeURIComponent(f.path)}`)).json();
  $("#file-path").textContent = f.path; $("#file-lines").textContent = `${f.lines} lines`;
  const code = $("#file-code");
  code.textContent = text; // textContent: never parsed as HTML
  code.className = `hljs language-${f.path.endsWith(".py") ? "python" : f.path.split(".").pop()}`;
  delete code.dataset.highlighted;
  if (window.hljs) window.hljs.highlightElement(code);
}

// ------------------------------------------------------------------ scheme
async function loadScheme() {
  const r = await fetch("/api/scheme");
  if (!r.ok) { $("#scheme-meta").textContent = "No diagram exported yet (scheme/embed.html)."; return; }
  const d = await r.json();
  const img = new Image();
  img.src = d.src;  // a PNG data URI extracted server-side; no script from the export is used
  img.alt = "System diagram: traffic limits, pre-filter, relevance floor, guard, hybrid retrieval, answer generation, post-check and conversation memory";
  $("#scheme").replaceChildren(img);
  $("#scheme-meta").textContent = `Exported from draw.io, updated ${d.updated}.`;
  const btn = $("#scheme-zoom");
  btn.addEventListener("click", () => {
    const actual = $("#scheme").classList.toggle("actual");
    btn.setAttribute("aria-pressed", String(actual));
    btn.textContent = actual ? "Fit to width" : "Actual size";
  });
}

// ------------------------------------------------------------------ evaluation
const pct = (v) => (v == null ? "–" : v.toFixed(2));
const bar = (v) => `<td class="num bar"><i style="width:${Math.round((v || 0) * 100)}%"></i><span>${pct(v)}</span></td>`;

async function loadEvals() {
  const e = await (await fetch("/api/evals")).json();
  const R = e.retrieval, P = (k) => R[k]?.metrics?.product;
  const g2d = P("dev_gemini2"), g2t = P("test_gemini2");
  let h = `<div class="page-head"><h1>Evaluation</h1><p class="page-desc">Deterministic evaluations, plus an LLM judge for the generation model. Every decision was made on a dev set and confirmed once on a frozen test set; a gap under 5 points counts as a tie.</p></div>`;
  h += `<div class="cards">
    <div class="card"><div class="k">Retrieval recall@5 (test)</div><div class="v">${pct(g2t?.["recall@5"])}</div><div class="d">right provision in the top 5 · 25 held-out questions</div></div>
    <div class="card"><div class="k">Retrieval recall@1 (test)</div><div class="v">${pct(g2t?.["recall@1"])}</div><div class="d">dev ${pct(g2d?.["recall@1"])} · 50 questions</div></div>
    <div class="card"><div class="k">Off-topic blocked before any LLM call</div><div class="v">${pct(e.floors.gemini2?.chosen_blocks_off_topic)}</div><div class="d">relevance floor ${e.floors.gemini2?.chosen} · 0 in-scope blocked</div></div>
    <div class="card"><div class="k">Chunking: recall at 500 words (test)</div><div class="v">${pct(e.chunking.test?.structural?.dense?.["recall@500w"])}</div><div class="d">structural chunks vs 0.52–0.92 for alternatives</div></div>
  </div>`;
  // evaluation methodology: how the measurements turned into decisions
  h += `<div class="block"><h3>Eval methodology</h3>
    <ul class="method">
      <li><b>Three layers of evaluation.</b> Deterministic checks (expected facts, valid citations, correct refusals) on 1,000 cases; an LLM judge (Claude Sonnet 5.5) scoring every answer 0–10 on five criteria; and a blind human review of 100 dev cases.</li>
      <li><b>Generation model: Gemini without reasoning, chosen mainly for latency.</b> The judge scored all three setups almost equally (9.09–9.13), but Gemini without reasoning starts answering in 1.8 s against 6.3–6.8 s with reasoning, with no long waits, at about half the cost of Gemini with reasoning.</li>
      <li><b>Blind human review.</b> 100 dev questions, the three setups' answers shown as A/B/C in shuffled order without model names, each scored 0–10. All three scored high (8.8–9.1 on average), with a lean towards Mistral (better than Gemini without reasoning on 45 cases, worse on 27; not statistically significant). The judge and the human agreed only weakly per answer, so the judge is used for catching failures, not for ranking near-equal setups.</li>
      <li><b>Raw vs rewritten question.</b> Searching with the user's raw message or with the guard's rewrite found the right provision equally often (395 dev questions: top-8 hit rate 94.7% vs 95.4%). The rewrite was kept anyway: it turns follow-ups and unclear wording into a complete question in the Act's terms, so the model is never left with an unclear question, which is meant to raise answer quality.</li>
    </ul></div>`;

  // answer model (end-to-end runs, LLM judge)
  const G = e.generation;
  if (G) {
    const runs = G.runs, sel = (r) => (r.key === G.selected ? " sel" : "");
    const cells = (f, cls = "num") => runs.map((r) => `<td class="${cls}${sel(r)}">${f(r)}</td>`).join("");
    const row = (label, f, extra = "") => `<tr${extra}><td>${label}</td>${cells(f)}</tr>`;
    const s = (v) => `${v.toFixed(1)} s`;
    h += `<div class="block"><h3>Generation model</h3><p class="note">End-to-end runs of all ${G.n_cases} cases, Legal detail style, same retrieval, guard and prompts; only the generation model or its reasoning level changes. TTFT (time to first token) here is measured from the generation-model call, so it excludes the guard and retrieval. Scores from an LLM judge (Claude Sonnet 5.5, 0–10) on the ${G.n_shared} cases all three runs answered. Reasoning gave no measurable quality gain, so the fastest and cheapest setup was kept.</p>
      <table class="gen"><tr><th>Metric</th>${runs.map((r) => `<th class="${sel(r).trim()}"><code>${r.model}</code><br><span class="th-sub">${r.thinking}</span>${r.key === G.selected ? `<br><span class="chosen">selected</span>` : ""}</th>`).join("")}</tr>
      ${row("Judge overall (0–10)", (r) => r.judge_overall.toFixed(2))}
      ${row("TTFT, median", (r) => s(r.first_word_p50_s))}
      ${row("TTFT, 90% within", (r) => s(r.first_word_p90_s))}
      ${row("TTFT, slowest", (r) => s(r.first_word_max_s))}
      ${row(`Answer cost, ${G.n_cases} cases`, (r) => `$${r.answer_cost_usd.toFixed(2)}`)}
      </table></div>`;

    // LLM-as-judge components: one small bar chart per criterion, the three runs as series
    const crit = [
      ["Correctness", "correctness", "Judge, 0–10: are the legal statements right?"],
      ["Completeness", "completeness", "Judge, 0–10: does it cover what the question needs?"],
      ["Grounding", "grounding", "Judge, 0–10: is every claim supported by the excerpts?"],
      ["Citations", "citations", "Judge, 0–10: are the cited provisions the right ones?"],
      ["Clarity", "clarity", "Judge, 0–10: is it easy to read and well structured?"],
      ["Expected facts found", "facts_found", `Deterministic check: gold facts present, of ${G.n_shared} answers`],
    ];
    const level = (r) => r.thinking.split(" (")[0].replace(/^(thinking|reasoning) /, "");
    const chart = ([title, k, sub]) => {
      const max = k === "facts_found" ? G.n_shared : 10;
      const fmt = (v) => (k === "facts_found" ? `${v} (${((100 * v) / max).toFixed(1)}%)` : v.toFixed(2));
      const base = runs.find((r) => r.key === G.selected)[k];
      return `<figure class="jchart"><figcaption><b>${title}</b><span>${sub}</span></figcaption>
        ${runs.map((r, i) => {
          const d = r[k] - base;
          const delta = r.key === G.selected ? "selected setup" : `${d >= 0 ? "+" : "−"}${k === "facts_found" ? Math.abs(d) : Math.abs(d).toFixed(2)} vs selected`;
          return `<div class="jbar" tabindex="0" aria-label="${esc(`${r.model} ${level(r)}, ${title} ${fmt(r[k])}`)}" data-tip="${esc(`${r.model}, ${r.thinking}|${title}: ${fmt(r[k])}|${delta}`)}">
            <div class="jlab"><span>${r.model} · ${level(r)}</span><b>${fmt(r[k])}</b></div>
            <div class="jtrack"><i style="width:${((100 * r[k]) / max).toFixed(1)}%;background:var(--series-${i + 1})"></i></div></div>`;
        }).join("")}
        <div class="jaxis"><span>0</span><span>${max}</span></div></figure>`;
    };
    h += `<div class="block"><h3>LLM-as-judge assessment components</h3><p class="note">The judge overall score above, broken down by criterion, on the same ${G.n_shared} cases. Bars start at 0, so the small gaps between runs show at their true size. "Expected facts found" is the deterministic check, not the judge. Hover or focus a bar to see its difference from the selected setup.</p>
      <div class="jlegend">${runs.map((r, i) => `<span><i style="background:var(--series-${i + 1})"></i><code>${r.model}</code> ${r.thinking.split(" (")[0]}${r.key === G.selected ? ' <em class="chosen">selected</em>' : ""}</span>`).join("")}</div>
      <div class="jgrid">${crit.map(chart).join("")}</div><div class="jtip" role="tooltip" hidden></div></div>`;
  }

  // answer style (Legal detail vs Explanatory), same model, same judge prompt
  const S = e.styles;
  if (S) {
    const st = S.styles, ssel = (r) => (r.key === S.selected ? " sel" : "");
    const srow = (label, f) => `<tr><td>${label}</td>${st.map((r) => `<td class="num${ssel(r)}">${f(r)}</td>`).join("")}</tr>`;
    const f2 = (v) => v.toFixed(2);
    h += `<div class="block"><h3>Answer style</h3><p class="note">The same ${S.n_cases} cases in both styles of the chat toggle, same model (<code>${S.model}</code>, thinking low) and the same style-aware judge prompt (Claude Sonnet 5.5); compared on the ${S.n_shared} cases answered in both. Clarity is judged against each style's own aim, so it is not a strict like-for-like comparison; correctness, grounding and facts are. Explanatory removed legal jargon but stayed dense and long, and paraphrasing cost some accuracy (better on ${S.plain_better} cases, worse on ${S.plain_worse}; ${S.facts_lost} expected facts lost, ${S.facts_gained} gained). Legal detail stays the default; the explanatory prompt is being reworked.</p>
      <table class="gen"><tr><th>Metric</th>${st.map((r) => `<th class="${ssel(r).trim()}">${r.label}${r.key === S.selected ? `<br><span class="chosen">default</span>` : ""}</th>`).join("")}</tr>
      ${srow("Judge overall (0–10)", (r) => f2(r.judge_overall))}
      ${srow("Correctness", (r) => f2(r.correctness))}
      ${srow("Grounding", (r) => f2(r.grounding))}
      ${srow("Completeness", (r) => f2(r.completeness))}
      ${srow("Citations", (r) => f2(r.citations))}
      ${srow("Clarity (against the style's aim)", (r) => f2(r.clarity))}
      ${srow(`Expected facts found (of ${S.n_shared})`, (r) => r.facts_found)}
      ${srow("Words per answer, median", (r) => r.words_p50)}
      ${srow("Words per sentence, median", (r) => r.words_per_sentence_p50.toFixed(1))}
      ${srow("Flesch reading ease, median (higher = easier)", (r) => r.flesch_p50)}
      ${srow("Legal-jargon phrases per answer", (r) => f2(r.jargon_per_answer))}
      ${srow("Citations per answer, median", (r) => r.citations_p50)}
      ${srow("TTFT, median", (r) => `${r.ttft_p50_s.toFixed(1)} s`)}
      ${srow(`Answer cost, ${S.n_cases} cases`, (r) => `$${r.answer_cost_usd.toFixed(2)}`)}
      </table></div>`;
  }

  // embedders
  const emb = [["local", "local bge-small (CPU)"], ["gemini1", "gemini-embedding-001"], ["gemini2", "gemini-embedding-2"]];
  h += `<div class="block"><h3>Embedding model</h3><p class="note">Same questions and pipeline; only the embedder changes. Product configuration (resolver + hybrid).</p>
    <table><tr><th>Embedder</th><th>Dev recall@1</th><th>Dev recall@5</th><th>Dev MRR</th><th>Test recall@1</th><th>Test recall@5</th><th>Test MRR</th></tr>
    ${emb.map(([k, n]) => { const d = P(`dev_${k}`), t = P(`test_${k}`); return `<tr class="${k === "gemini2" ? "best" : ""}"><td>${n}</td>${bar(d?.["recall@1"])}${bar(d?.["recall@5"])}${bar(d?.mrr)}${bar(t?.["recall@1"])}${bar(t?.["recall@5"])}${bar(t?.mrr)}</tr>`; }).join("")}
    </table></div>`;

  // ablation
  const abl = R.dev_local?.metrics;
  if (abl) {
    const names = { bm25: "BM25", dense: "Dense (bge-small)", hybrid: "Hybrid (RRF)", "+glossary": "+ lay→legal glossary", "+titles": "+ title ranker (rejected)", product: "+ reference resolver (product)" };
    h += `<div class="block"><h3>Retrieval ablation (dev, local embeddings)</h3><p class="note">Each component added in turn; only components that help are kept.</p>
      <table><tr><th>Configuration</th><th>recall@1</th><th>recall@5</th><th>MRR</th></tr>
      ${Object.entries(names).map(([k, n]) => `<tr class="${k === "product" ? "best" : ""}"><td>${n}</td>${bar(abl[k]?.["recall@1"])}${bar(abl[k]?.["recall@5"])}${bar(abl[k]?.mrr)}</tr>`).join("")}
      </table></div>`;
  }

  // chunking
  const C = e.chunking;
  if (C.dev) {
    const order = [["fixed_250", "Fixed windows, 250 words"], ["fixed_500", "Fixed windows, 500 words"], ["recursive_350", "Recursive splitter, 350 words"], ["article", "One chunk per article"], ["paragraph", "One chunk per paragraph"], ["structural", "Structural (production)"], ["structural_nohdr", "Structural, no header"]];
    h += `<div class="block"><h3>Chunking strategy</h3><p class="note">Recall at a fixed context budget (words sent to the model), dense retrieval. Dev ${C.dev._n} / test ${C.test?._n} questions. Details in the log below and in docs/CHUNKING.md.</p>
      <table><tr><th>Strategy</th><th>Chunks</th><th>Dev @500</th><th>Dev @1500</th><th>Dev @3000</th><th>Test @500</th><th>Test @1500</th><th>Test @3000</th></tr>
      ${order.map(([k, n]) => { const d = C.dev[k], t = C.test?.[k]; return `<tr class="${k === "structural" ? "best" : ""}"><td>${n}</td><td class="num">${d.n_chunks}</td>${bar(d.dense["recall@500w"])}${bar(d.dense["recall@1500w"])}${bar(d.dense["recall@3000w"])}${bar(t?.dense["recall@500w"])}${bar(t?.dense["recall@1500w"])}${bar(t?.dense["recall@3000w"])}</tr>`; }).join("")}
      </table></div>`;
  }
  $("#eval-page").innerHTML = h;
  const tip = $("#eval-page .jtip");
  if (tip) {
    const show = (el, x, y) => {
      const [a, b, c] = el.dataset.tip.split("|");
      tip.innerHTML = `<div class="t1">${esc(a)}</div><div class="t2">${esc(b)}</div><div class="t3">${esc(c)}</div>`;
      tip.hidden = false;
      const w = tip.offsetWidth, ht = tip.offsetHeight;
      tip.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, x + 12))}px`;
      tip.style.top = `${y - ht - 12 < 8 ? y + 16 : y - ht - 12}px`;
    };
    document.querySelectorAll("#eval-page .jbar").forEach((el) => {
      el.addEventListener("mousemove", (ev) => show(el, ev.clientX, ev.clientY));
      el.addEventListener("mouseleave", () => { tip.hidden = true; });
      el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); });
      el.addEventListener("blur", () => { tip.hidden = true; });
    });
  }
}

// ------------------------------------------------------------------ sidebar + theme
const shell = $(".shell");
const mobile = () => window.matchMedia("(max-width: 900px)").matches;
function closeMobileSidebar() { shell.classList.remove("open"); }
$("#toggle-sidebar").addEventListener("click", () => {
  if (mobile()) shell.classList.toggle("open");
  else { shell.classList.toggle("collapsed"); try { localStorage.setItem("aiact.sidebar", shell.classList.contains("collapsed") ? "closed" : "open"); } catch {} }
});
$("#scrim").addEventListener("click", closeMobileSidebar);
try { if (localStorage.getItem("aiact.sidebar") === "closed" && !mobile()) shell.classList.add("collapsed"); } catch {}

function applyTheme(t) {
  if (t === "dark") document.documentElement.dataset.theme = "dark"; else delete document.documentElement.dataset.theme;
  $("#hl-light").disabled = t === "dark"; $("#hl-dark").disabled = t !== "dark";
}
applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
$("#toggle-theme").addEventListener("click", () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(t);
  try { localStorage.setItem("aiact.theme", t); } catch {}
});
async function loadDoc(name) {
  const d = await (await fetch(`/api/docs/${name}`)).json();
  $("#doc").innerHTML = d.html; // our own repository docs, rendered server-side
}

window.addEventListener("hashchange", () => {
  const h = location.hash.slice(1);
  if (["chat", "scheme", "source", "evaluation", "agentic"].includes(h)) showTab(h);
});

// ------------------------------------------------------------------ boot
loadInfo();
restore().then(enableExport);
const start = location.hash.slice(1);
if (["scheme", "source", "evaluation", "agentic"].includes(start)) showTab(start);
