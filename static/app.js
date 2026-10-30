// Reply race front end. Talks only to the local server (which holds the API key).
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const DEFAULT_MODELS = ["typesafe/jev-1.14", "liquid/d1", "mistralai/mistral-nemo", "openai/gpt-oss-20b",
  "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"];
// Label colors skip slots 1-2 (blue/orange identify decision models and LLMs).
// Slots 3-8 keep the validated adjacent order; "none" is neutral gray.
const SERIES = ["--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];

const state = {
  config: null, model: {}, question: {},
  race: null, lanes: new Map(), es: null, clockStart: 0, clockTimer: null,
  summary: null, sort: { key: "place", dir: 1 }, techSort: { key: "name", dir: 1 }, explorerQ: null, filter: "disagree", shown: 20,
};

// --- formatting -------------------------------------------------------------
const fmtCost = (v) => v == null ? "–" : v === 0 ? "$0" : v < 0.01 ? "$" + Number(v.toPrecision(2)).toString() : "$" + v.toFixed(3);
const fmtBig = (v) => v == null ? "–" : v < 1 ? "$" + v.toFixed(2) : "$" + Math.round(v).toLocaleString("en-US");
const fmtSec = (v) => v == null ? "–" : v < 10 ? v.toFixed(1) + " s" : Math.round(v) + " s";
const fmtPct = (v) => v == null ? "–" : Math.round(v * 100) + "%";
const fmtInt = (v) => v == null ? "–" : v.toLocaleString("en-US");
const ordinal = (n) => { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
const ratio = (a, b) => { const r = a / b; return r >= 10 ? Math.round(r) + "×" : r.toFixed(1) + "×"; };
const kindLabel = (k) => k === "decision" ? "Decision model" : "LLM";
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// --- tooltip ----------------------------------------------------------------
const tip = $("#tooltip");
function showTip(e, html) {
  tip.innerHTML = html; tip.hidden = false;
  const r = e.target.getBoundingClientRect();
  const x = e.clientX ?? r.left + r.width / 2, y = e.clientY ?? r.top;
  const w = tip.offsetWidth;
  tip.style.left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 12)) + "px";
  tip.style.top = Math.max(8, y - tip.offsetHeight - 12) + "px";
}
const hideTip = () => { tip.hidden = true; };
function bindTip(el, html) {
  el.addEventListener("mousemove", (e) => showTip(e, html));
  el.addEventListener("mouseleave", hideTip);
  el.addEventListener("focus", (e) => showTip(e, html));
  el.addEventListener("blur", hideTip);
}

// --- setup ------------------------------------------------------------------
async function init() {
  const cfg = await fetch("/api/config").then((r) => r.json());
  state.config = cfg;
  cfg.models.forEach((m) => (state.model[m.id] = m));
  cfg.questions.forEach((q) => (state.question[q.id] = q));

  $("#source").innerHTML = `Replies to <a href="${esc(cfg.post.url)}">${esc(cfg.post.author)}'s ${esc(cfg.post.title)} post</a>, read for free through the FxTwitter API. ` +
    (cfg.reference ? `Answer key: ${esc(cfg.reference.name)}'s answers on all ${cfg.total_comments} replies.` : "No answer key yet: run build_reference.py to score right answers.");

  $("#question-list").innerHTML = cfg.questions.map((q, i) => `
    <label class="choice">
      <input type="checkbox" name="question" value="${q.id}" ${i === 0 ? "checked" : ""}>
      <span class="name">${esc(q.title)}</span>
      <span class="meta">${esc(q.summary)} ${Object.keys(q.labels).length} possible answers.
        <span class="tag" title="The typed questions sent to decision models">${esc(q.primitive)}</span></span>
    </label>`).join("");

  $("#sample-list").innerHTML = cfg.samples.map((n) => `
    <label><input type="radio" name="sample" value="${n}" ${n === 100 ? "checked" : ""}><span>${n === cfg.total_comments ? n + " (all)" : n}</span></label>`).join("");
  $("#sample-hint").textContent = "Most-liked replies first.";

  for (const kind of ["decision", "llm"]) {
    $(`#${kind}-list`).innerHTML = cfg.models.filter((m) => m.kind === kind).map((m) => {
      const ref = cfg.reference && cfg.reference.model === m.id ? ` <span class="tag">answer key</span>` : "";
      return `<label class="choice" data-kind="${kind}">
        <input type="checkbox" name="model" value="${m.id}" ${DEFAULT_MODELS.includes(m.id) ? "checked" : ""}>
        <span class="name">${esc(m.name)}${ref}</span>
        <span class="meta">${esc(m.note)}</span></label>`;
    }).join("");
  }

  $$("[data-bulk]").forEach((b) => b.addEventListener("click", () => {
    $$(`#${b.dataset.bulk}-list input`).forEach((i) => (i.checked = b.dataset.on === "1"));
    updateStart();
  }));
  $("#setup-form").addEventListener("change", updateStart);
  $("#setup-form").addEventListener("submit", (e) => { e.preventDefault(); startRace(); });
  $("#stop").addEventListener("click", stopRace);
  $("#edit").addEventListener("click", () => toggleSetup(true));
  $("#see-results").addEventListener("click", () => scrollToEl($("#results")));
  $("#download").addEventListener("click", download);
  $("#more").addEventListener("click", () => { state.shown += 20; renderExplorer(); });
  $$('input[name="filter"]').forEach((i) => i.addEventListener("change", () => { state.filter = i.value; state.shown = 20; renderExplorer(); }));
  if (!cfg.has_key) showError("The server has no OPENROUTER_API_KEY. Export it and restart server.py.");
  updateStart();
  // A race may already be running, for example after a page reload: follow it.
  const cur = await fetch("/api/race/current").then((r) => r.json()).catch(() => ({}));
  if (cur.id) attach(cur.id);
}

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const scrollToEl = (el) => el.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "start" });

// Puts a race's settings back in the form (after a reload, the form starts from defaults).
function applySelection(s) {
  $$('input[name="question"]').forEach((i) => (i.checked = s.questions.includes(i.value)));
  $$('input[name="model"]').forEach((i) => (i.checked = s.models.includes(i.value)));
  $$('input[name="sample"]').forEach((i) => (i.checked = +i.value === s.sample));
  $$('input[name="llm_batch"]').forEach((i) => (i.checked = +i.value === s.llm_batch));
}

function selection() {
  return {
    questions: $$('input[name="question"]:checked').map((i) => i.value),
    models: $$('input[name="model"]:checked').map((i) => i.value),
    sample: +$('input[name="sample"]:checked').value,
    llm_batch: +$('input[name="llm_batch"]:checked').value,
  };
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
function describe(s) {
  const q = s.questions.length === 1 ? `"${state.question[s.questions[0]].title}"` : plural(s.questions.length, "question", "questions");
  const dec = s.models.filter((m) => state.model[m].kind === "decision").length;
  return `<strong>${esc(q)}</strong>, ${s.sample} replies, ${plural(s.models.length, "model", "models")} ` +
    `(${plural(dec, "decision model", "decision models")}, ${plural(s.models.length - dec, "LLM", "LLMs")})`;
}

function updateStart() {
  const btn = $("#start");
  if (state.race || state.starting) return;
  const s = selection(), ok = s.questions.length && s.models.length;
  btn.disabled = !ok;
  btn.textContent = !s.models.length ? "Pick a model" : !s.questions.length ? "Pick a question"
    : s.models.length === 1 ? `Run ${state.model[s.models[0]].name} alone` : "Start race";
  $("#run-summary").innerHTML = ok ? `Ready: ${describe(s)}` : "Pick at least one question and one model.";
}

function showError(msg) { const el = $("#form-error"); el.textContent = msg; el.hidden = !msg; if (msg) toggleSetup(true); }

function toggleSetup(show) {
  $("#setup").hidden = !show;
  $("#edit").hidden = show;
  if (show) scrollToEl($("#setup"));
}

// --- race -------------------------------------------------------------------
async function startRace() {
  if (state.starting || state.race) return;  // one click, one race
  state.starting = true;
  $("#start").disabled = true;
  showError("");
  try {
    const res = await fetch("/api/race", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(selection()) });
    const body = await res.json();
    if (res.status === 409 && body.running) return attach(body.running);
    if (!res.ok) return showError(body.error || "The race could not start.");
    $("#explainer").open = false;
    attach(body.id);
  } catch (e) {
    showError("The server did not answer. Check that server.py is running.");
  } finally {
    state.starting = false;
    updateStart();
  }
}

function attach(id) {
  state.race = id;
  $("#start").disabled = true; $("#start").textContent = "Race running";
  $("#stop").hidden = false; $("#stop").disabled = false; $("#stop").textContent = "Stop race";
  $("#see-results").hidden = true;
  $("#setup-fields").disabled = true;
  $("#explainer").open = false;
  toggleSetup(false);
  scrollToEl($("#track-section"));
  state.es?.close();
  const es = new EventSource(`/api/race/${id}/events`);
  state.es = es;
  es.onmessage = (m) => onEvent(JSON.parse(m.data));
  es.onerror = () => { if (state.race && es.readyState === EventSource.CLOSED) showError("Lost the connection to the server. Check that server.py is still running."); };
}

async function stopRace() {
  if (!state.race) return;
  $("#stop").disabled = true; $("#stop").textContent = "Stopping";
  await fetch(`/api/race/${state.race}/stop`, { method: "POST" }).catch(() => {});
}

function tickClock() { $("#clock").textContent = fmtSec((performance.now() - state.clockStart) / 1000); }

function onEvent(ev) {
  if (ev.t != null && state.race) state.clockStart = Math.min(state.clockStart || Infinity, performance.now() - ev.t * 1000);
  if (ev.type === "start") {
    // Also replayed after a reload: rebuild everything from scratch.
    const s = { questions: ev.questions, models: ev.models, sample: ev.total, llm_batch: ev.llm_batch };
    state.sel = s;
    applySelection(s);
    state.summary = { questions: s.questions, models: s.models, sample: s.sample, llm_batch: s.llm_batch,
      reference_model: state.config.reference?.model ?? null, finish_order: [], metrics: {}, items: null };
    state.clockStart = performance.now() - ev.t * 1000;
    clearInterval(state.clockTimer);
    state.clockTimer = setInterval(tickClock, 100);
    $("#run-summary").innerHTML = `Racing: ${describe(s)}`;
    $("#results").hidden = true;
    buildLanes(s);
    return;
  }
  const lane = state.lanes.get(ev.model);
  if (ev.type === "progress" && lane && !lane.finished) {
    const p = ev.done / ev.total;
    lane.el.style.setProperty("--p", p);
    $(".lane-track", lane.el).setAttribute("aria-valuenow", ev.done);
    $(".v-done", lane.el).textContent = `${ev.done}/${ev.total}`;
    $(".v-time", lane.el).textContent = fmtSec(ev.elapsed);
    if (ev.done) $(".v-cost", lane.el).textContent = fmtBig(ev.cost / ev.done * 1e6);
    if (ev.failed) {
      $(".lane-fill", lane.el).classList.add("has-fail");
      $(".lane-note", lane.el).textContent = `${ev.failed} ${ev.failed === 1 ? "answer" : "answers"} lost: the model wrote text the program could not read`;
    }
  } else if (ev.type === "finish" && lane && !lane.finished) {
    lane.finished = true;
    const m = ev.metrics;
    $(".v-time", lane.el).textContent = fmtSec(m.seconds);
    $(".v-cost", lane.el).textContent = fmtBig(m.cost_per_1m);
    if (m.stopped) {
      lane.el.classList.add("stopped");
      $(".runner", lane.el).textContent = "";
      $(".lane-note", lane.el).textContent = `Stopped at ${m.processed} of ${lane.total} replies. Left out of the rankings.`;
    } else {
      lane.el.classList.add("finished");
      lane.el.style.setProperty("--p", 1);
      state.summary.finish_order.push(ev.model);
      const place = state.summary.finish_order.length;
      $(".runner", lane.el).textContent = ordinal(place);
      $(".v-done", lane.el).textContent = `${m.answered}/${lane.total}`;
      $("#announcer").textContent = `${state.model[ev.model].name} finished ${ordinal(place)} in ${fmtSec(m.seconds)}.`;
    }
    state.summary.metrics[ev.model] = m;
    renderResults(false);
  } else if (ev.type === "error" && lane) {
    lane.finished = true;
    $(".lane-note", lane.el).textContent = `This model failed: ${ev.error}`;
  } else if (ev.type === "done") {
    state.es.close();
    clearInterval(state.clockTimer);
    $("#clock").textContent = fmtSec(ev.t);
    state.race = null;
    $("#stop").hidden = true;
    $("#setup-fields").disabled = false;
    updateStart();
    $("#start").textContent = "Start a new race";
    const stopped = Object.values(ev.summary.metrics).some((m) => m.stopped);
    $("#run-summary").innerHTML = `${stopped ? "Stopped" : "Finished"}: ${describe(state.sel)}`;
    state.summary = ev.summary;
    renderResults(true);
  }
}

function buildLanes(s) {
  const track = $("#track");
  track.innerHTML = "";
  state.lanes.clear();
  s.models.forEach((mid, i) => {
    const m = state.model[mid];
    const lane = document.createElement("div");
    lane.className = "lane"; lane.dataset.kind = m.kind;
    const sub = m.kind === "decision" ? "Decision model, one by one"
      : `LLM, ${s.llm_batch === 1 ? "one by one" : `${s.llm_batch} replies at once`}`;
    lane.innerHTML = `
      <span class="lane-no" aria-hidden="true">${i + 1}</span>
      <div class="lane-name"><strong>${esc(m.name)}</strong><span>${sub}</span></div>
      <div class="lane-track" role="progressbar" aria-label="${esc(m.name)} progress" aria-valuemin="0" aria-valuemax="${s.sample}" aria-valuenow="0">
        <div class="lane-fill"></div><div class="runner" aria-hidden="true">${m.kind === "decision" ? "D" : "L"}</div>
      </div>
      <div class="lane-stats">
        <div><b class="v-done">0/${s.sample}</b><small>replies</small></div>
        <div><b class="v-time">0.0 s</b><small>time</small></div>
        <div><b class="v-cost">–</b><small>per 1M replies</small></div>
      </div>
      <p class="lane-note"></p>`;
    track.append(lane);
    state.lanes.set(mid, { el: lane, total: s.sample, finished: false });
  });
}

// --- results ----------------------------------------------------------------
function rows() {
  const s = state.summary;
  return s.models.filter((mid) => s.metrics[mid]).map((mid) => {
    const i = s.finish_order.indexOf(mid);
    return { id: mid, ...state.model[mid], m: s.metrics[mid], stopped: !!s.metrics[mid].stopped, place: i < 0 ? 99 : i + 1 };
  });
}
const ranked = () => rows().filter((x) => !x.stopped);

// Rendered after each model finishes (final = false), then once more with every reply at the end.
function renderResults(final) {
  const s = state.summary;
  if (!rows().length) return;
  const firstShow = $("#results").hidden;
  $("#results").hidden = false;
  $("#see-results").hidden = false;
  if (firstShow && !final) $("#announcer").textContent = "First results are ready below the track.";
  $("#results-context").innerHTML = `For ${describe({ ...state.sel, models: s.models })}.`;
  const running = s.models.filter((m) => !s.metrics[m]).map((m) => state.model[m].name);
  $("#waiting").hidden = final || !running.length;
  $("#waiting").textContent = `Still running: ${running.join(", ")}. The results update when each model finishes.`;
  $("#download").hidden = !final;
  $("#explorer-block").hidden = !final;
  if (!ranked().length) return;
  renderTakeaways(); renderScoreboard(); renderTech(); renderPodiums(); renderDistributions();
  if (!final) return;
  state.explorerQ = s.questions[0]; state.shown = 20;
  $("#explorer-questions").innerHTML = s.questions.length < 2 ? "" : s.questions.map((q, i) =>
    `<label><input type="radio" name="explorer-q" value="${q}" ${i === 0 ? "checked" : ""}><span>${esc(state.question[q].title)}</span></label>`).join("");
  $$('input[name="explorer-q"]').forEach((i) => i.addEventListener("change", () => { state.explorerQ = i.value; state.shown = 20; renderExplorer(); }));
  renderExplorer();
}

const right = (x) => x.m.agreement;
const speedWords = (a, b) => Math.max(a, b) / Math.min(a, b) < 1.15 ? "about as fast"
  : a < b ? ratio(b, a) + " faster" : ratio(a, b) + " slower";  // share of replies matching the answer key

function renderTakeaways() {
  const s = state.summary, r = ranked(), refId = s.reference_model;
  const cards = [];
  const card = (kind, big, text) => cards.push(`<div class="takeaway" data-kind="${kind}"><span class="big">${big}</span><p>${text}</p></div>`);
  const fast = [...r].sort((a, b) => a.place - b.place)[0];
  card(fast.kind, fmtSec(fast.m.seconds), r.length > 1 ? `Fastest: ${esc(fast.name)}.` : `${esc(fast.name)} answered ${s.sample} replies.`);
  const usable = r.filter((x) => x.m.answered);
  const cheap = [...usable].sort((a, b) => a.m.cost_per_1m - b.m.cost_per_1m)[0];
  if (cheap) card(cheap.kind, fmtBig(cheap.m.cost_per_1m), `${r.length > 1 ? "Cheapest" : "Cost"}: ${esc(cheap.name)}, for 1 million replies.`);
  const scored = r.filter((x) => right(x) != null && x.id !== refId).sort((a, b) => right(b) - right(a));
  if (scored.length) card(scored[0].kind, fmtPct(right(scored[0])), `Most right answers: ${esc(scored[0].name)}.`);
  const dec = scored.find((x) => x.kind === "decision");
  const key = r.find((x) => x.id === refId);
  if (dec && key && key.m.cost_per_1m > 0) {
    const cheaper = dec.m.cost_per_1m <= key.m.cost_per_1m, faster = dec.m.seconds <= key.m.seconds;
    card("decision", cheaper ? ratio(key.m.cost_per_1m, dec.m.cost_per_1m) + " cheaper" : ratio(dec.m.cost_per_1m, key.m.cost_per_1m) + " the cost",
      `${esc(dec.name)} compared with ${esc(key.name)}, the model that wrote the answer key: ${speedWords(dec.m.seconds, key.m.seconds)}, same answer ${fmtPct(right(dec))} of the time.`);
  }
  const broken = r.filter((x) => x.m.failed).sort((a, b) => b.m.failed - a.m.failed)[0];
  if (broken) card(broken.kind, `${broken.m.failed} lost`, `${esc(broken.name)} wrote text the program could not read for ${broken.m.failed} of ${s.sample} replies. A decision model can only answer from the list.`);
  $("#takeaways").innerHTML = cards.join("");
  const ref = state.config.reference;
  $("#answer-key-hint").textContent = ref
    ? `Right answers: how often the model gives the same answer as the answer key. The answer key was written once by ${ref.name}, the most capable model here, thinking step by step. It is a good guide, not the absolute truth: even ${ref.name} gives a few different answers when asked again. A lost answer counts as wrong. Click a column to sort.`
    : "No answer key yet, so right answers cannot be counted.";
}

function sortableTable(el, cols, data, sortKey) {
  const refId = state.summary.reference_model;
  const st = state[sortKey];
  const col = cols.find((c) => c.key === st.key) || cols[0];
  data.sort((a, b) => { const va = col.val(a), vb = col.val(b); return (va > vb ? 1 : va < vb ? -1 : 0) * st.dir; });
  const others = data.filter((x) => x.id !== refId && !x.stopped);
  const bests = Object.fromEntries(cols.map((c) => {
    if (!c.best || others.length < 2) return [c.key, null];
    const vals = others.map(c.val).filter((v) => v >= 0 && v < 1e9);
    return [c.key, c.best === "min" ? Math.min(...vals) : Math.max(...vals)];
  }));
  el.innerHTML = `
    <caption class="visually-hidden">Results per model. The best value in each column is bold.</caption>
    <thead><tr>${cols.map((c) => `<th scope="col" ${c.key === st.key ? `aria-sort="${st.dir > 0 ? "ascending" : "descending"}"` : ""}>
      <button type="button" data-key="${c.key}" data-arrow="${st.dir > 0 ? " ▲" : " ▼"}">${esc(c.label)}</button></th>`).join("")}</tr></thead>
    <tbody>${data.map((x) => `<tr>${cols.map((c) => {
      const best = x.id !== refId && !x.stopped && bests[c.key] != null && c.val(x) === bests[c.key];
      return `<td class="${c.cls || ""} ${best ? "best" : ""}">${c.fmt(x)}</td>`;
    }).join("")}</tr>`).join("")}</tbody>`;
  $$("th button", el).forEach((b) => b.addEventListener("click", () => {
    state[sortKey] = { key: b.dataset.key, dir: st.key === b.dataset.key ? -st.dir : 1 };
    sortableTable(el, cols, data, sortKey);
    $(`th button[data-key="${b.dataset.key}"]`, el).focus();
  }));
}

const modelCol = () => ({ key: "name", label: "Model", val: (x) => x.name, cls: "model",
  fmt: (x) => `<span class="kind-dot ${x.kind}" title="${kindLabel(x.kind)}"></span>${esc(x.name)}${x.id === state.summary.reference_model ? ` <span class="tag">answer key</span>` : ""}` });

function renderScoreboard() {
  const s = state.summary;
  const anyLost = rows().some((x) => x.m.failed);
  const cols = [
    { key: "place", label: "Place", val: (x) => x.place, fmt: (x) => x.stopped ? `<span class="bad">Stopped at ${x.m.processed}</span>` : ordinal(x.place) },
    modelCol(),
    { key: "seconds", label: "Time", val: (x) => x.m.seconds, fmt: (x) => fmtSec(x.m.seconds), best: "min" },
    { key: "cost_per_1m", label: "Cost for 1M replies", val: (x) => x.m.cost_per_1m, fmt: (x) => fmtBig(x.m.cost_per_1m), best: "min" },
    { key: "right", label: "Right answers", val: (x) => right(x) ?? -1, best: "max",
      fmt: (x) => right(x) == null ? "–" : `<span class="meter" style="--kc:var(--${x.kind})"><i style="--v:${right(x)}"></i>${fmtPct(right(x))}</span>` },
  ];
  if (anyLost) cols.push({ key: "lost", label: "Lost answers", val: (x) => x.m.failed, fmt: (x) => x.m.failed ? `<span class="bad">${x.m.failed}</span>` : "0", best: "min" });
  sortableTable($("#scoreboard"), cols, rows(), "sort");
}

function renderTech() {
  const s = state.summary;
  const pq = (x, q) => x.m.per_question[q];
  const cols = [modelCol(),
    { key: "cost", label: "Cost of this race", val: (x) => x.m.cost, fmt: (x) => fmtCost(x.m.cost) }];
  s.questions.forEach((q) => {
    const t = state.question[q].title;
    if (s.questions.length > 1) cols.push({ key: "r_" + q, label: `Right: ${t}`, val: (x) => pq(x, q).agreement ?? -1, fmt: (x) => fmtPct(pq(x, q).agreement) });
    cols.push({ key: "k_" + q, label: s.questions.length > 1 ? `Kappa: ${t}` : "Cohen's kappa", val: (x) => pq(x, q).kappa ?? -2,
      fmt: (x) => pq(x, q).kappa == null ? "–" : pq(x, q).kappa.toFixed(2) });
    if (rows().some((x) => pq(x, q).to_find != null)) cols.push({ key: "f_" + q, label: s.questions.length > 1 ? `Found: ${t}` : "Found", val: (x) => pq(x, q).found ?? -1,
      fmt: (x) => pq(x, q).to_find == null ? "–" : `${pq(x, q).found} of ${pq(x, q).to_find}` });
  });
  cols.push(
    { key: "sure", label: "Sure", val: (x) => avgSettled(x) ?? -1, fmt: (x) => avgSettled(x) == null ? "n/a" : fmtPct(avgSettled(x)) },
    { key: "latency", label: "Typical call", val: (x) => x.m.latency_p50 ?? 1e9, fmt: (x) => fmtSec(x.m.latency_p50) },
    { key: "tokens_out", label: "Tokens written", val: (x) => x.kind === "decision" ? 0 : x.m.tokens_out, fmt: (x) => x.kind === "decision" ? "not billed" : fmtInt(x.m.tokens_out) },
  );
  sortableTable($("#tech-table"), cols, rows(), "techSort");
}

function avgSettled(x) {
  const v = Object.values(x.m.per_question).map((p) => p.settled).filter((v) => v != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

// Three ranked bar lists: one measure each, every model, best at the top.
function renderPodiums() {
  const r = ranked(), refId = state.summary.reference_model;
  const board = (title, sub, items, val, fmt, lowIsBest, order = val) => {
    const list = items.filter((x) => val(x) != null).sort((a, b) => (order(a) - order(b)) * (lowIsBest ? 1 : -1));
    const max = Math.max(...list.map(val), 1e-12);
    return `<figure class="podium"><figcaption><strong>${title}</strong><span>${sub}</span></figcaption>
      <ol>${list.map((x) => `<li style="--kc:var(--${x.kind})">
        <span class="who"><span class="kind-dot ${x.kind}" aria-hidden="true"></span>${esc(x.name)}</span>
        <span class="bar"><i style="--v:${Math.max(val(x) / max, 0.015)}"></i></span><b>${fmt(val(x))}</b></li>`).join("")}</ol></figure>`;
  };
  $("#podiums").innerHTML =
    board("Fastest", "Time to answer every reply, in finishing order. Shorter is better.", r, (x) => x.m.seconds, fmtSec, true, (x) => x.place) +
    board("Cheapest", "Cost for 1 million replies. Shorter is better.", r.filter((x) => x.m.answered), (x) => x.m.cost_per_1m, fmtBig, true) +
    board("Most right answers", "Same answer as the answer key. Longer is better.", r.filter((x) => x.id !== refId), (x) => right(x), fmtPct, false);
  $("#kind-legend").innerHTML = `<span><span class="kind-dot decision"></span>Decision model</span><span><span class="kind-dot llm"></span>LLM</span>`;
}

function renderDistributions() {
  const s = state.summary;
  const refName = state.config.reference?.name;
  $("#distributions").innerHTML = s.questions.map((q) => {
    const labels = Object.keys(state.question[q].labels);
    const colored = labels.filter((l) => l !== "none");
    const color = (l) => l === "none" ? "var(--muted)" : `var(${SERIES[colored.indexOf(l) % SERIES.length]})`;
    const lines = [];
    if (s.items?.[0]?.reference) {
      const c = {}; s.items.forEach((it) => { const l = it.reference[q]; if (l) c[l] = (c[l] || 0) + 1; });
      lines.push({ who: "Answer key", tip: refName, kind: "ref", counts: c, missing: 0 });
    }
    rows().forEach((x) => lines.push({ who: x.stopped ? `${x.name} (stopped)` : x.name, kind: x.kind, counts: x.m.per_question[q].counts, missing: x.m.failed }));
    return `<div class="dist"><h4>${esc(state.question[q].title)}</h4>
      ${lines.map((ln) => `<div class="dist-row"><span class="who"><span class="kind-dot ${ln.kind}" aria-hidden="true"></span>${esc(ln.who)}</span>
        <div class="dist-bar" role="img" aria-label="${esc(ln.who)}: ${labels.map((l) => `${l} ${ln.counts[l] || 0}`).join(", ")}">
        ${labels.filter((l) => ln.counts[l]).map((l) => `<span style="--c:${color(l)};flex:${ln.counts[l]}" data-tip="${esc(l)}: ${ln.counts[l]} replies (${fmtPct(ln.counts[l] / s.sample)})"></span>`).join("")}
        ${ln.missing ? `<span class="missing" style="flex:${ln.missing}" data-tip="Answers lost: ${ln.missing} replies"></span>` : ""}
        </div></div>`).join("")}
      <div class="legend">${labels.map((l) => `<span><span class="swatch" style="background:${color(l)}"></span>${esc(l.replace(/_/g, " "))}</span>`).join("")}</div></div>`;
  }).join("");
  $$("#distributions [data-tip]").forEach((el) => bindTip(el, el.dataset.tip));
}

function renderExplorer() {
  const s = state.summary, q = state.explorerQ, refId = s.reference_model;
  const labelOf = (it, mid) => it.answers[mid]?.q?.[q]?.label ?? null;
  let items = s.items;
  if (state.filter === "disagree") items = items.filter((it) => new Set([...s.models.map((m) => labelOf(it, m)), it.reference?.[q]].filter((v) => v !== undefined)).size > 1);
  const shown = items.slice(0, state.shown);
  $("#explorer").innerHTML = shown.length ? shown.map((it) => {
    const ref = it.reference?.[q];
    const chips = s.models.map((mid) => {
      const m = state.model[mid], l = labelOf(it, mid);
      const cls = ref == null ? "" : l === ref ? "hit" : "miss";
      const mark = ref == null ? "" : l === ref ? "✓" : "✗";
      return `<span class="chip ${cls}"><span class="kind-dot ${m.kind}" aria-hidden="true"></span>${esc(m.name)}: ${esc(l ?? "no answer")} <span class="mark" aria-label="${cls === "hit" ? "same as the answer key" : "different from the answer key"}">${mark}</span></span>`;
    }).join("");
    const cards = s.models.map((mid) => {
      const m = state.model[mid], a = it.answers[mid];
      if (!a) return `<div class="answer-card" data-kind="${m.kind}"><strong>${esc(m.name)}</strong><p class="bad">${s.metrics[mid]?.stopped ? "No answer: the race was stopped before this reply." : "Answer lost: the model wrote text the program could not read."}</p></div>`;
      const qa = a.q[q];
      if (m.kind === "decision") {
        const dist = Object.entries(qa.dist).sort((x, y) => y[1] - x[1]);
        return `<div class="answer-card" data-kind="decision"><strong>${esc(m.name)}</strong>
          ${dist.map(([l, v], i) => `<div class="prob ${i === 0 ? "top" : ""}"><span>${esc(l)}</span><i style="--v:${v}"></i><span>${v.toFixed(2)}</span></div>`).join("")}
          ${qa.settled ? "" : `<p class="unsettled">Not sure: no answer is clearly ahead. Code can send this reply to a person.</p>`}</div>`;
      }
      return `<div class="answer-card" data-kind="llm"><strong>${esc(m.name)}: ${esc(qa.label)}</strong><p>The text it wrote:</p><pre>${esc(a.raw)}</pre></div>`;
    }).join("");
    return `<li><details class="reply"><summary>
      <p class="reply-text">${esc(it.text)}${it.has_media ? " <span class='tag'>image or GIF</span>" : ""}</p>
      <p class="reply-meta">@${esc(it.user)}, ${fmtInt(it.likes)} likes</p>
      <div class="chips">${ref != null ? `<span class="chip ref"><span class="kind-dot ref" aria-hidden="true"></span>Answer key: ${esc(ref)}</span>` : ""}${chips}</div>
      </summary><div class="reply-detail">${cards}</div></details></li>`;
  }).join("") : `<li class="hint">Every model gave the same answer on every reply. Choose "All replies" to browse them.</li>`;
  $("#more").hidden = items.length <= state.shown;
}

function download() {
  const blob = new Blob([JSON.stringify(state.summary, null, 1)], { type: "application/json" });
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `reply-race-${state.summary.id}.json` });
  a.click(); URL.revokeObjectURL(a.href);
}

init().catch((e) => showError(`Could not load the configuration from the server: ${e.message}`));
