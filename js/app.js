import * as S from "./store.js";
import {
  db, load, query, STATUS, STATUS_LABEL, CAT_COLOR, SUBTAG_LABEL, stateName, enabledStates, plannedStates,
  categories, catName, liveSessions, loadCatalog, relDate, fmtDate,
} from "./data.js";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const main = $("#main");

const ICON = {
  home: '<svg viewBox="0 0 24 24"><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/></svg>',
  list: '<svg viewBox="0 0 24 24"><path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r=".8"/><circle cx="4" cy="12" r=".8"/><circle cx="4" cy="18" r=".8"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="m12 3.5 2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.8z"/></svg>',
  folder: '<svg viewBox="0 0 24 24"><path d="M3 7.5a2 2 0 0 1 2-2h4l2 2.2h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>',
  pulse: '<svg viewBox="0 0 24 24"><path d="M3 12h4l2.5-6 5 12 2.5-6h4"/></svg>',
  gear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.8 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.8-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.8H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.8-1.2V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.8 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.8H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  db: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="6" rx="7.5" ry="2.8"/><path d="M4.5 6v12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/></svg>',
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  dl: '<svg viewBox="0 0 24 24"><path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 20h14"/></svg>',
};

// ---------------------------------------------------------------- routing
function parseHash() {
  const h = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = h.split("?");
  const p = new URLSearchParams(qs || "");
  return { path: path || "/", p };
}
function go(path, params = {}) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (Array.isArray(v)) { if (v.length) p.set(k, v.join(",")); }
    else if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, v === true ? "1" : v);
  });
  const s = p.toString();
  location.hash = `#${path}${s ? "?" + s : ""}`;
}
function setParam(k, v) {
  const { path, p } = parseHash();
  if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) p.delete(k);
  else p.set(k, Array.isArray(v) ? v.join(",") : v);
  const s = p.toString();
  history.replaceState(null, "", `#${path}${s ? "?" + s : ""}`);
}
const list = (p, k) => (p.get(k) ? p.get(k).split(",").filter(Boolean) : []);

// ---------------------------------------------------------------- small renderers
function ovals(status) {
  const idx = Math.min(STATUS.indexOf(status), 4);
  const dead = status === "vetoed" || status === "failed";
  const reached = dead ? -1 : idx;
  let html = "";
  for (let i = 0; i < 5; i++) html += `<i class="${i <= reached ? "on" : ""}"></i>`;
  if (dead) html = `<i class="on"></i><i class="x"></i><i></i><i></i><i></i>`;
  return `<span class="ovals ${status}" role="img" aria-label="${esc(STATUS_LABEL[status])}">${html}</span>`;
}
function bar(b) {
  const cats = Object.entries(b.categories || {});
  if (!cats.length) return `<span class="bar"><i style="background:var(--line-2)"></i></span>`;
  return `<span class="bar">${cats.map(([k, v]) => `<i style="background:${CAT_COLOR[k] || "var(--ink-3)"};opacity:${v.level === "match" ? 1 : .35}"></i>`).join("")}</span>`;
}
function catTags(b) {
  return Object.entries(b.categories || {}).map(([k, v]) =>
    `<span class="tag cat ${v.level}" style="${v.level === "match" ? `background:${CAT_COLOR[k]}` : `color:${CAT_COLOR[k]}`}" title="${v.level === "match" ? "Matched" : "Possible match"}">${esc(catName(k))}${v.level === "possible" ? "?" : ""}</span>`).join("");
}
function mineTags(id) {
  const m = S.bill(id);
  if (!m) return "";
  let h = "";
  if (m.watch) h += `<span class="tag user flag" title="Watching">★ Watching</span>`;
  if (m.stance) h += `<span class="tag stance-${m.stance}">${esc(cap(m.stance))}</span>`;
  if (m.priority === "high") h += `<span class="tag prio-high">High priority</span>`;
  (m.tags || []).forEach((t) => (h += `<span class="tag user">#${esc(t)}</span>`));
  const notes = (m.notes || []).filter((n) => !n.deleted).length;
  if (notes) h += `<span class="tag user">${notes} note${notes > 1 ? "s" : ""}</span>`;
  return h;
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
function billRow(b, { selectable = false, selected = false } = {}) {
  return `<div class="row ${selected ? "sel" : ""}" data-id="${esc(b.id)}" tabindex="0" role="button" aria-label="${esc(b.state + " " + b.number + ": " + b.title)}">
    ${bar(b)}
    <div class="id">${esc(b.state)} ${esc(b.number)}<small>${esc(sessionShort(b))}</small></div>
    <div class="t"><b>${esc(b.title)}</b><div class="sub">${catTags(b)}${mineTags(b.id)}<span>${esc(b.last_action || "")}</span></div></div>
    <div class="statuscell">${ovals(b.status)}<span>${esc(STATUS_LABEL[b.status] || "")}</span></div>
    <div class="date">${esc(relDate(b.last_action_date))}<small>last action</small></div>
    ${selectable ? `<input type="checkbox" class="chk rowchk" aria-label="Select" ${selected ? "checked" : ""} hidden>` : ""}
  </div>`;
}
function sessionShort(b) {
  const n = b.session_name || b.session;
  const m = n.match(/\b(20\d\d)(?:-(20\d\d))?\b/);
  const special = /special|called/i.test(n) ? " special" : "";
  return m ? (m[2] ? `${m[1]}–${m[2].slice(2)}` : m[1]) + special : n;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2200);
}
const refOf = (b) => ({ state: b.state, number: b.number, title: (b.title || "").slice(0, 200), session: b.session, url: b.url || "" });

// ---------------------------------------------------------------- nav
function renderNav() {
  const { path, p } = parseHash();
  const mine = (id) => S.bill(id);
  const counts = {};
  categories().forEach((c) => (counts[c.key] = query({ cats: [c.key] }, mine).length));
  const watchN = Object.values(S.getState().bills).filter((b) => b.watch).length;
  const here = (pth, key, val) => path === pth && (key ? p.get(key) === val : ![...p.keys()].some((k) => ["cat", "watch"].includes(k)));
  const link = (href, label, icon, current, count = "") =>
    `<a href="${href}" ${current ? 'aria-current="page"' : ""}>${icon}<span>${esc(label)}</span>${count !== "" ? `<span class="count">${count}</span>` : ""}</a>`;
  let h = "";
  h += link("#/", "Dashboard", ICON.home, path === "/");
  h += link("#/bills", "All tracked bills", ICON.list, here("/bills"));
  h += link("#/bills?watch=1", "Watchlist", ICON.star, here("/bills", "watch", "1"), watchN || "");
  h += `<div class="group">Topics</div>`;
  categories().forEach((c) => {
    h += `<a href="#/bills?cat=${c.key}" ${here("/bills", "cat", c.key) ? 'aria-current="page"' : ""}><span class="dot" style="background:${CAT_COLOR[c.key]}"></span><span>${esc(c.name)}</span><span class="count">${counts[c.key]}</span></a>`;
  });
  h += `<div class="group">Your folders</div>`;
  S.folders().forEach((f) => {
    const n = Object.values(S.getState().bills).filter((b) => b.folders?.includes(f.id)).length;
    h += `<a href="#/folder/${f.id}" ${path === "/folder/" + f.id ? 'aria-current="page"' : ""}><span class="dot" style="background:${f.color};border-radius:3px"></span><span>${esc(f.name)}</span><span class="count">${n}</span></a>`;
  });
  h += link("#/folders", S.folders().length ? "Manage folders" : "Create a folder", ICON.folder, path === "/folders");
  if (S.getState().views.length) {
    h += `<div class="group">Saved searches</div>`;
    S.getState().views.forEach((v) => (h += `<a href="${esc(v.hash)}">${ICON.search}<span>${esc(v.name)}</span></a>`));
  }
  h += `<div class="group">More</div>`;
  h += link("#/search", "Search every bill", ICON.search, path === "/search");
  h += link("#/activity", "Activity", ICON.pulse, path === "/activity");
  h += link("#/sources", "Data sources", ICON.db, path === "/sources");
  h += link("#/settings", "Settings & sync", ICON.gear, path === "/settings");
  $("#nav").innerHTML = h;

  const si = S.syncInfo();
  const cfg = S.syncConfig();
  $("#railFoot").innerHTML = `<div class="sync-pill ${si.state === "ok" || si.state === "idle" ? "on" : si.state === "error" ? "err" : ""}"><i></i>${
    cfg ? (si.state === "error" ? "Sync problem" : si.state === "busy" ? "Saving…" : "Notes synced") : "Notes saved in this browser"
  }</div><div style="margin-top:6px">Data updated ${esc(relDate(db.meta.generated))}</div>`;

  const tabs = [["#/", "Home", ICON.home, path === "/"], ["#/bills", "Bills", ICON.list, path === "/bills" && !p.get("watch")],
    ["#/bills?watch=1", "Watchlist", ICON.star, p.get("watch") === "1"], ["#/folders", "Folders", ICON.folder, path.startsWith("/folder")],
    ["#/search", "Search", ICON.search, path === "/search"]];
  $("#tabbar").innerHTML = tabs.map(([h2, l, i, c]) => `<a href="${h2}" ${c ? 'aria-current="page"' : ""}>${i}<span>${l}</span></a>`).join("");
}

// ---------------------------------------------------------------- dashboard
function viewDashboard() {
  const mine = (id) => S.bill(id);
  const all = query({}, mine);
  const cats = categories();
  const band = cats.map((c) => {
    const rows = all.filter((b) => b.categories?.[c.key]?.level === "match");
    const by = (st) => rows.filter((b) => st.includes(b.status)).length;
    return `<a href="#/bills?cat=${c.key}" style="--c:${CAT_COLOR[c.key]}">
      <div class="n">${rows.length}</div><div class="nm">${esc(c.name)}</div>
      <div class="bk"><span><b>${by(["committee", "introduced"])}</b> pending</span><span><b>${by(["passed_one", "passed_both"])}</b> moving</span><span><b>${by(["enacted"])}</b> enacted</span><span><b>${by(["failed", "vetoed"])}</b> stopped</span></div>
    </a>`;
  }).join("");

  const states = enabledStates();
  const live = liveSessions();
  const matrix = `<table class="matrix"><thead><tr><th scope="col" style="text-align:left">State</th>${cats.map((c) => `<th scope="col"><span class="dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${CAT_COLOR[c.key]};margin-right:5px"></span>${esc(c.name)}</th>`).join("")}<th scope="col">Sessions shown</th></tr></thead><tbody>
    ${states.map((s) => `<tr><th scope="row">${esc(s.name)}</th>${cats.map((c) => {
      const n = all.filter((b) => b.state === s.code && b.categories?.[c.key]?.level === "match").length;
      return `<td><a href="#/bills?cat=${c.key}&state=${s.code}" class="${n ? "hot" : "z"}" style="${n ? `background:${CAT_COLOR[c.key]}` : ""}">${n}</a></td>`;
    }).join("")}<td class="small muted">${esc([...live[s.code] || []].map((code) => s.sessions.find((x) => x.code === code)?.name || code).join(", ") || "None yet")}</td></tr>`).join("")}
    ${plannedStates().map((s) => `<tr><th scope="row" class="muted">${esc(s.name)}</th><td class="off" colspan="${cats.length + 1}">Being added</td></tr>`).join("")}
  </tbody></table>`;

  const lastSeen = S.getState().lastSeen || "";
  const tracked = new Set(all.map((b) => b.id));
  const feed = db.changes.filter((e) => tracked.has(e.bill) || S.bill(e.bill)?.watch).slice(0, 12);
  const feedHtml = feed.length ? `<ul class="feed">${feed.map((e) => `<li data-id="${esc(e.bill)}" class="${e.seen > lastSeen ? "new" : ""}"><div class="when">${esc(relDate(e.date))}</div><div class="what"><b>${esc(e.state)} ${esc(e.number)}</b> ${esc(e.text)}<span>${esc(e.title)}</span></div></li>`).join("")}</ul>`
    : `<div class="empty"><b>No changes yet</b>New actions on tracked bills appear here after each update.</div>`;

  const today = new Date().toISOString().slice(0, 16);
  const hearings = all.flatMap((b) => (b.hearings || []).filter((h) => h.date >= today.slice(0, 10)).map((h) => ({ ...h, b })))
    .sort((a, b) => a.date.localeCompare(b.date)).slice(0, 8);
  const hearHtml = hearings.length ? `<ul class="feed">${hearings.map((h) => `<li data-id="${esc(h.b.id)}"><div class="when">${esc(fmtDate(h.date.slice(0, 10)))}${h.date.length > 10 ? `<br>${esc(new Date(h.date).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }))}` : ""}</div><div class="what"><b>${esc(h.b.state)} ${esc(h.b.number)}</b> ${esc(h.committee || h.chamber)}<span>${esc(h.b.title)}</span></div></li>`).join("")}</ul>`
    : `<div class="empty small">No hearings scheduled on tracked bills. Most legislatures return in January.</div>`;

  const watched = all.filter((b) => S.bill(b.id)?.watch).slice(0, 6);
  const watchHtml = watched.length ? `<div class="list">${watched.map((b) => billRow(b)).join("")}</div>`
    : `<div class="empty small"><b>Nothing on your watchlist</b>Open any bill and choose Watch to follow it here.</div>`;

  const moving = all.filter((b) => b.categories && Object.values(b.categories).some((v) => v.level === "match")).slice(0, 8);

  main.innerHTML = `
    <div class="head"><div><h1>State reform legislation</h1><p>${all.length} bills across ${states.length} states matching your three topics in recent sessions. Updated ${esc(relDate(db.meta.generated))}.</p></div>
      <div class="actions"><a class="btn" href="#/bills">See all bills</a></div></div>
    <div class="catband">${band}</div>
    <div class="dash">
      <div>
        <section class="panel"><h2>By state <a href="#/sources">Data sources</a></h2>${matrix}</section>
        <section class="panel"><h2>Latest action <a href="#/bills">All bills</a></h2>${moving.length ? `<div class="list">${moving.map((b) => billRow(b)).join("")}</div>` : `<div class="empty"><b>No bills found yet</b>The first data update may still be running.</div>`}</section>
      </div>
      <div>
        <section class="panel"><h2>What changed <a href="#/activity">All activity</a></h2>${feedHtml}</section>
        <section class="panel"><h2>Upcoming hearings</h2>${hearHtml}</section>
        <section class="panel"><h2>Watchlist <a href="#/bills?watch=1">Open</a></h2>${watchHtml}</section>
      </div>
    </div>`;
}

// ---------------------------------------------------------------- bill list
let selected = new Set();
let pageSize = 60;
let moreFilters = false;

function filtersFrom(p) {
  return {
    q: p.get("q") || "", cats: list(p, "cat"), states: list(p, "state"), status: list(p, "status"),
    level: p.get("level") || "match", scope: p.get("scope") || "live", subtag: p.get("subtag") || "",
    tag: p.get("tag") || "", watch: p.get("watch") === "1", stance: p.get("stance") || "", sort: p.get("sort") || "recent",
    hidden: p.get("hidden") === "1", folder: p.get("folder") || "",
  };
}

function viewBills(p, opts = {}) {
  const f = { ...filtersFrom(p), ...(opts.force || {}) };
  if (f.watch || f.folder) { f.level = "all"; f.scope = p.get("scope") || "all"; }
  const mine = (id) => S.bill(id);
  let rows = query(f, mine);
  // Bills you saved from "Search every bill" that aren't in any topic.
  if (f.watch || f.folder) {
    const have = new Set(rows.map((b) => b.id));
    Object.entries(S.getState().bills).forEach(([id, m]) => {
      if (have.has(id) || !m.ref) return;
      if (f.watch && !m.watch) return;
      if (f.folder && !m.folders?.includes(f.folder)) return;
      if (db.byId.has(id)) return;
      rows.push({ id, ...m.ref, session_name: m.ref.session, status: "introduced", categories: {}, last_action: "Saved from full search", _ref: true });
    });
  }
  const cats = categories();
  const title = opts.title || (f.watch ? "Watchlist" : f.cats.length === 1 ? catName(f.cats[0]) : "All tracked bills");
  const desc = opts.desc || (f.cats.length === 1 ? cats.find((c) => c.key === f.cats[0])?.description : "Bills in any of your three topics. Use the filters to narrow by state, status or your own tags.");
  const subtags = [...new Set((f.cats.length ? cats.filter((c) => f.cats.includes(c.key)) : cats).flatMap((c) => c.subtags))];
  const tags = S.allTags();
  const statesList = enabledStates();

  const moreCount = f.status.length + (f.subtag ? 1 : 0) + (f.tag ? 1 : 0) + (f.stance ? 1 : 0);
  const moreOpen = moreFilters || moreCount > 0;
  const chip = (k, v, label, on, dot) => `<button class="fchip" data-k="${k}" data-v="${esc(v)}" aria-pressed="${on}">${dot ? `<span class="dot" style="background:${dot}"></span>` : ""}${esc(label)}</button>`;
  main.innerHTML = `
    <div class="head"><div><h1>${esc(title)}</h1>${desc ? `<p>${esc(desc)}</p>` : ""}</div>
      <div class="actions">
        <button class="btn ghost" id="saveView">Save search</button>
        <button class="btn" id="csv">${ICON.dl}Export CSV</button>
      </div></div>
    <div class="filters">
      <label class="search">${ICON.search}<input class="input" id="q" type="search" placeholder="Search titles, summaries, sponsors, bill numbers" value="${esc(f.q)}" aria-label="Search"></label>
      <select class="select" id="state" aria-label="State"><option value="">All states</option>${statesList.map((s) => `<option value="${s.code}" ${f.states[0] === s.code ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
      <select class="select" id="sort" aria-label="Sort"><option value="recent">Latest action</option><option value="introduced">Newest filed</option><option value="progress">Furthest along</option><option value="state">State and number</option></select>
      <select class="select" id="scope" aria-label="Sessions"><option value="live">Recent sessions</option><option value="all">All sessions on file</option></select>
    </div>
    <div class="filters chipset">${opts.hideCats ? "" : cats.map((c) => chip("cat", c.key, c.name, f.cats.includes(c.key), CAT_COLOR[c.key])).join("")}
      <button class="fchip" data-k="level" data-v="all" aria-pressed="${f.level === "all"}" title="Also show bills that only matched indirect or technical language">Include possible matches</button>
      <button class="fchip more-toggle" id="moreF" aria-expanded="${moreOpen}">${moreCount ? `More filters (${moreCount})` : "More filters"}</button></div>
    <div class="morefilters" id="moreFilters" ${moreOpen ? "" : "hidden"}>
      <div class="fgroup"><span>Status</span><div class="chipset">${["committee", "passed_one", "passed_both", "enacted", "failed"].map((s) => chip("status", s, STATUS_LABEL[s], f.status.includes(s))).join("")}</div></div>
      ${subtags.length ? `<div class="fgroup"><span>Type of bill</span><div class="chipset">${subtags.map((s) => chip("subtag", s, SUBTAG_LABEL[s] || s, f.subtag === s)).join("")}</div></div>` : ""}
      <div class="fgroup"><span>Your stance</span><div class="chipset">${["support", "oppose", "monitor"].map((s) => chip("stance", s, cap(s), f.stance === s)).join("")}</div></div>
      ${tags.length ? `<div class="fgroup"><span>Your tags</span><div class="chipset">${tags.map((t) => chip("tag", t, "#" + t, f.tag === t)).join("")}</div></div>` : ""}
    </div>
    <div class="resultbar"><span>${rows.length} bill${rows.length === 1 ? "" : "s"}${f.hidden ? " marked not relevant" : ""}</span>
      <span><button class="btn ghost small" id="selmode">Select bills</button> <button class="btn ghost small" id="showHidden">${f.hidden ? "Back to the list" : "Bills you marked not relevant"}</button></span></div>
    <div class="list" id="rows">${rows.slice(0, pageSize).map((b) => billRow(b, { selectable: true, selected: selected.has(b.id) })).join("") ||
      `<div class="empty"><b>No bills match these filters</b>${f.watch ? "Open a bill and choose Watch to add it here." : "Try clearing a filter or switching to all sessions."}</div>`}</div>
    ${rows.length > pageSize ? `<button class="btn more" id="more">Show ${Math.min(60, rows.length - pageSize)} more</button>` : ""}
    <div class="bulk" id="bulk" hidden></div>`;

  $("#sort").value = f.sort; $("#scope").value = f.scope;
  const rerender = () => route();
  let tq;
  $("#q").addEventListener("input", (e) => { clearTimeout(tq); tq = setTimeout(() => { setParam("q", e.target.value); pageSize = 60; rerenderKeepFocus(); }, 180); });
  $("#state").addEventListener("change", (e) => { setParam("state", e.target.value); rerender(); });
  $("#sort").addEventListener("change", (e) => { setParam("sort", e.target.value === "recent" ? "" : e.target.value); rerender(); });
  $("#scope").addEventListener("change", (e) => { setParam("scope", e.target.value === "live" ? "" : e.target.value); rerender(); });
  $("#moreF").addEventListener("click", () => { moreFilters = !$("#moreFilters").hidden ? false : true; $("#moreFilters").hidden = !moreFilters; $("#moreF").setAttribute("aria-expanded", moreFilters); });
  $$(".fchip[data-k]").forEach((c) => c.addEventListener("click", () => {
    const k = c.dataset.k, v = c.dataset.v;
    const { p: cur } = parseHash();
    if (k === "cat" || k === "status") {
      const l = list(cur, k); setParam(k, l.includes(v) ? l.filter((x) => x !== v) : [...l, v]);
    } else if (k === "level") setParam("level", cur.get("level") === "all" ? "" : "all");
    else setParam(k, cur.get(k) === v ? "" : v);
    pageSize = 60; rerender();
  }));
  $("#showHidden").addEventListener("click", () => { setParam("hidden", f.hidden ? "" : "1"); rerender(); });
  $("#more")?.addEventListener("click", () => { pageSize += 60; rerender(); });
  $("#csv").addEventListener("click", () => downloadCSV(rows, title));
  $("#saveView").addEventListener("click", () => {
    const name = prompt("Name this search", title + (f.states.length ? ` in ${stateName(f.states[0])}` : ""));
    if (name) { S.saveView(name, location.hash); toast("Search saved"); }
  });
  setupSelect(rows);
}

function rerenderKeepFocus() {
  const el = document.activeElement; const id = el?.id; const pos = el?.selectionStart;
  route();
  if (id) { const n = document.getElementById(id); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch {} } }
}

let selMode = false;
function setupSelect(rows) {
  const btn = $("#selmode"); const bulk = $("#bulk");
  const paint = () => {
    $$(".rowchk").forEach((c) => (c.hidden = !selMode));
    $$("#rows .row").forEach((r) => { r.style.paddingLeft = selMode ? "34px" : ""; r.classList.toggle("sel", selected.has(r.dataset.id)); const c = $(".rowchk", r); if (c) c.checked = selected.has(r.dataset.id); });
    btn.textContent = selMode ? "Done selecting" : "Select bills";
    bulk.hidden = !selMode;
    if (selMode) {
      bulk.innerHTML = `<b>${selected.size} selected</b>
        <button class="btn small" data-a="all">Select all ${rows.length}</button>
        <button class="btn small" data-a="watch">Watch</button>
        <select class="select" data-a="folder" aria-label="Add to folder"><option value="">Add to folder…</option>${S.folders().map((f) => `<option value="${f.id}">${esc(f.name)}</option>`).join("")}<option value="__new">New folder…</option></select>
        <button class="btn small" data-a="tag">Add tag</button>
        <button class="btn small" data-a="hide">Not relevant</button>
        <button class="btn small" data-a="clear">Clear</button>`;
      bulk.onclick = (e) => {
        const a = e.target.dataset.a; if (!a || a === "folder") return;
        const ids = [...selected];
        if (a === "all") rows.forEach((b) => selected.add(b.id));
        if (a === "clear") selected.clear();
        if (a === "watch") { ids.forEach((id) => { const b = findBill(id); if (!S.bill(id)?.watch) S.toggleWatch(id, b && refOf(b)); }); toast(`Watching ${ids.length} bills`); }
        if (a === "tag") { const t = prompt("Tag to add"); if (t) { ids.forEach((id) => S.addTag(id, t, findBill(id) && refOf(findBill(id)))); toast(`Tagged ${ids.length} bills`); } }
        if (a === "hide") { ids.forEach((id) => S.setField(id, "hidden", !(S.bill(id)?.hidden), findBill(id) && refOf(findBill(id)))); selected.clear(); toast("Updated"); route(); return; }
        paint();
      };
      $("[data-a=folder]", bulk).onchange = (e) => {
        let fid = e.target.value; if (!fid) return;
        if (fid === "__new") { const n = prompt("Folder name"); if (!n) return; fid = S.createFolder(n).id; }
        [...selected].forEach((id) => { if (!S.bill(id)?.folders?.includes(fid)) S.toggleFolder(id, fid, findBill(id) && refOf(findBill(id))); });
        toast(`Added ${selected.size} bills`); paint();
      };
    }
  };
  btn.addEventListener("click", () => { selMode = !selMode; if (!selMode) selected.clear(); paint(); });
  $("#rows").addEventListener("click", (e) => {
    if (!selMode) return;
    const r = e.target.closest(".row"); if (!r) return;
    e.stopPropagation(); e.preventDefault();
    selected.has(r.dataset.id) ? selected.delete(r.dataset.id) : selected.add(r.dataset.id);
    paint();
  }, true);
  paint();
}

function findBill(id) {
  return db.byId.get(id) || (S.bill(id)?.ref ? { id, ...S.bill(id).ref } : null) || catalogHit.get(id) || null;
}

function wireRows(container) {
  if (!container) return;
  container.addEventListener("click", (e) => {
    const r = e.target.closest("[data-id]"); if (!r || selMode) return;
    openBill(r.dataset.id);
  });
  container.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-id]")) { e.preventDefault(); openBill(e.target.dataset.id); }
  });
}

function downloadCSV(rows, name) {
  const cols = ["State", "Bill", "Session", "Title", "Topics", "Status", "Last action", "Last action date", "Sponsors", "Watching", "Stance", "Priority", "Tags", "Notes", "Link"];
  const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [cols.map(q).join(",")];
  rows.forEach((b) => {
    const m = S.bill(b.id) || {};
    lines.push([b.state, b.number, b.session_name || b.session, b.title,
      Object.entries(b.categories || {}).map(([k, v]) => catName(k) + (v.level === "possible" ? " (possible)" : "")).join("; "),
      STATUS_LABEL[b.status], b.last_action, b.last_action_date, (b.sponsors || []).filter((s) => s.role === "primary").map((s) => s.name).join("; "),
      m.watch ? "yes" : "", m.stance || "", m.priority || "", (m.tags || []).join("; "),
      (m.notes || []).filter((n) => !n.deleted).map((n) => n.text).join(" | "), b.url].map(q).join(","));
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `${name.replace(/[^\w]+/g, "-").toLowerCase()}-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ---------------------------------------------------------------- folders
function viewFolders() {
  const fs = S.folders();
  main.innerHTML = `
    <div class="head"><div><h1>Folders</h1><p>Group bills however you work: by campaign, coalition partner, client or priority. A bill can sit in several folders.</p></div>
      <div class="actions"><button class="btn primary" id="newFolder">New folder</button></div></div>
    ${fs.length ? `<div class="grid2">${fs.map((f) => {
      const n = Object.values(S.getState().bills).filter((b) => b.folders?.includes(f.id)).length;
      return `<a class="folder" href="#/folder/${f.id}"><b><span class="dot" style="background:${f.color}"></span>${esc(f.name)}</b><small>${n} bill${n === 1 ? "" : "s"}</small></a>`;
    }).join("")}</div>` : `<div class="panel empty"><b>No folders yet</b>Create one, then add bills from a bill's details or by selecting several in a list.</div>`}`;
  $("#newFolder").onclick = () => { const n = prompt("Folder name"); if (n?.trim()) { const f = S.createFolder(n); go(`/folder/${f.id}`); } };
}

function viewFolder(id, p) {
  const f = S.folders().find((x) => x.id === id);
  if (!f) { main.innerHTML = `<div class="empty"><b>That folder was deleted</b><a href="#/folders">See your folders</a></div>`; return; }
  viewBills(p, { force: { folder: id }, title: f.name, desc: "Bills you've added to this folder.", hideCats: false });
  const actions = $(".head .actions");
  actions.insertAdjacentHTML("afterbegin", `<button class="btn ghost" id="ren">Rename</button><button class="btn ghost" id="del">Delete folder</button>`);
  $("#ren").onclick = () => { const n = prompt("Rename folder", f.name); if (n?.trim()) { S.renameFolder(id, n.trim()); route(); } };
  $("#del").onclick = () => { if (confirm(`Delete “${f.name}”? The bills stay in the tracker; only the folder goes.`)) { S.deleteFolder(id); go("/folders"); } };
}

// ---------------------------------------------------------------- full search
const catalogHit = new Map();
async function viewSearch(p) {
  const q = p.get("q") || "";
  const st = p.get("state") || "";
  const states = enabledStates();
  main.innerHTML = `
    <div class="head"><div><h1>Search every bill</h1><p>Every bill filed in the states covered, on any subject. Use this for one-off questions; anything you watch or file in a folder stays on your lists.</p></div></div>
    <div class="filters">
      <label class="search">${ICON.search}<input class="input" id="sq" type="search" placeholder="Words in the title, or a bill number like HB 1234" value="${esc(q)}" aria-label="Search every bill"></label>
      <select class="select" id="sst" aria-label="State"><option value="">All states</option>${states.map((s) => `<option value="${s.code}" ${st === s.code ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
    </div>
    <div class="resultbar" id="sinfo"></div>
    <div class="list" id="srows"><div class="empty">Type at least two letters to search.</div></div>`;
  let t;
  const run = async () => {
    const qv = $("#sq").value.trim().toLowerCase(); const sv = $("#sst").value;
    setParam("q", qv); setParam("state", sv);
    if (qv.length < 2) { $("#srows").innerHTML = `<div class="empty">Type at least two letters to search.</div>`; $("#sinfo").textContent = ""; return; }
    $("#sinfo").textContent = "Searching…";
    const codes = sv ? [sv] : states.map((s) => s.code);
    const cats = await Promise.all(codes.map(loadCatalog));
    const words = qv.split(/\s+/);
    const hits = cats.flat().filter((r) => words.every((w) => r._t.includes(w)))
      .sort((a, b) => (b.last_action_date || "").localeCompare(a.last_action_date || ""));
    hits.forEach((h) => catalogHit.set(h.id, h));
    $("#sinfo").textContent = `${hits.length} bill${hits.length === 1 ? "" : "s"}${hits.length > 150 ? ", showing the 150 most recent" : ""}`;
    $("#srows").innerHTML = hits.slice(0, 150).map((h) => {
      const full = db.byId.get(h.id);
      const b = full || { ...h, categories: Object.fromEntries((h.cats || "").split(",").filter(Boolean).map((x) => { const [k, l] = x.split(":"); return [k, { level: l === "m" ? "match" : "possible" }]; })), session_name: h.session, last_action: "" };
      return billRow(b);
    }).join("") || `<div class="empty"><b>No bills found</b>Try fewer or different words.</div>`;
  };
  $("#sq").addEventListener("input", () => { clearTimeout(t); t = setTimeout(run, 250); });
  $("#sst").addEventListener("change", run);
  if (q) run();
}

// ---------------------------------------------------------------- activity
function viewActivity(p) {
  const lastSeen = S.getState().lastSeen || "";
  const onlyMine = p.get("mine") === "1";
  const mine = (id) => S.bill(id);
  const tracked = new Set(query({ level: "all", scope: "all" }, mine).map((b) => b.id));
  const evs = db.changes.filter((e) => (onlyMine ? S.bill(e.bill)?.watch || S.bill(e.bill)?.folders?.length : tracked.has(e.bill) || S.bill(e.bill)?.watch)).slice(0, 300);
  main.innerHTML = `
    <div class="head"><div><h1>Activity</h1><p>Every new action, status change and newly found bill, newest first. Items since your last visit are highlighted.</p></div>
      <div class="actions"><button class="btn" id="mineOnly" aria-pressed="${onlyMine}">Only my watchlist and folders</button><button class="btn ghost" id="seen">Mark all as seen</button></div></div>
    <section class="panel">${evs.length ? `<ul class="feed">${evs.map((e) => `<li data-id="${esc(e.bill)}" class="${e.seen > lastSeen ? "new" : ""}"><div class="when">${esc(relDate(e.date))}</div><div class="what"><b>${esc(e.state)} ${esc(e.number)}</b> ${esc(e.text)}<span>${esc(e.title)}</span></div></li>`).join("")}</ul>`
      : `<div class="empty"><b>Nothing here yet</b>Changes are recorded from the second data update onward.</div>`}</section>`;
  $("#mineOnly").onclick = () => { setParam("mine", onlyMine ? "" : "1"); route(); };
  $("#seen").onclick = () => { S.markSeen(); route(); toast("Marked as seen"); };
}

// ---------------------------------------------------------------- sources / health
function viewSources() {
  const H = db.health;
  const rows = Object.entries(db.meta.states).map(([code, s]) => {
    const h = H[code];
    if (!s.enabled) return `<tr><th scope="row">${esc(s.name)}</th><td class="muted">Being added</td><td></td><td></td><td></td></tr>`;
    const sess = Object.entries(h?.sessions || {}).map(([k, v]) => {
      const nm = s.sessions.find((x) => x.code === k)?.name || k;
      return `<div>${esc(nm)}: ${v.error ? `<span class="bad">error</span> <span class="small muted">${esc(v.error)}</span>` : v.note ? `<span class="muted">${esc(v.note)}</span>` : `${v.bills} bills`}</div>`;
    }).join("");
    const stale = h?.last_success && (Date.now() - new Date(h.last_success)) > 2 * 864e5;
    return `<tr><th scope="row">${esc(s.name)}</th><td>${h ? (h.ok && !stale ? `<span class="ok">Working</span>` : `<span class="bad">${stale ? "Not updating" : "Problem"}</span>`) : "Waiting for first run"}</td>
      <td>${h?.last_success ? esc(relDate(h.last_success)) : "Never"}</td><td>${h ? `${(h.bills_total || 0).toLocaleString()} bills<br><span class="small muted">${h.tracked} in your topics</span>` : ""}</td><td class="small">${sess}${(h?.warnings || []).length ? `<div class="muted">${h.warnings.length} minor warnings</div>` : ""}</td></tr>`;
  }).join("");
  main.innerHTML = `
    <div class="head"><div><h1>Data sources</h1><p>Bills come straight from each legislature's own website or data files, collected twice a day by scripts in your GitHub repository. If a state shows a problem, its site probably changed and the script for that state needs updating.</p></div></div>
    <section class="panel"><table class="health"><thead><tr><th>State</th><th>Status</th><th>Last successful update</th><th>Bills</th><th>Sessions</th></tr></thead><tbody>${rows}</tbody></table></section>`;
}

// ---------------------------------------------------------------- settings
function viewSettings() {
  const cfg = S.syncConfig(); const si = S.syncInfo();
  const theme = document.documentElement.dataset.theme || "auto";
  main.innerHTML = `
    <div class="head"><div><h1>Settings & sync</h1><p>Your watchlist, folders, tags and notes are private. They're kept in this browser, and can also be saved to a private GitHub repository so they follow you to your phone and other computers.</p></div></div>
    <section class="panel">
      <h2>Sync your notes</h2>
      ${cfg ? `<p>Saving to <b>${esc(cfg.repo)}</b>. ${si.state === "error" ? `<span class="bad">${esc(si.message)}</span>` : `Last saved ${esc(cfg.last ? relDate(cfg.last) : "not yet")}.`}</p>
        <div class="links"><button class="btn" id="syncNow">Sync now</button><button class="btn ghost" id="unsync">Stop syncing on this device</button></div>`
      : `<ol class="steps">
          <li>On GitHub, create a new <b>private</b> repository, for example <i>tracker-notes</i>. It can be empty.</li>
          <li>Go to GitHub Settings, Developer settings, Fine-grained personal access tokens, and generate a token. Under Repository access choose <i>Only select repositories</i> and pick that repository. Under Permissions, set <i>Contents</i> to Read and write. Nothing else is needed.</li>
          <li>Paste the repository name and token below. Do this once on each device you use.</li>
        </ol>
        <form class="form" id="syncForm" style="margin-top:14px">
          <label>Private repository<span>owner/name</span><input class="input" name="repo" required placeholder="MoveBeyondFPTP/tracker-notes" autocomplete="off"></label>
          <label>Access token<span>Stored only in this browser. It can read and write that one repository and nothing else.</span><input class="input" name="token" type="password" required autocomplete="off"></label>
          <div><button class="btn primary">Connect and sync</button> <span id="syncErr" class="bad small"></span></div>
        </form>`}
    </section>
    <section class="panel">
      <h2>Back up or move your notes</h2>
      <p class="muted small">Download everything you've added as a file, or load a file from another browser. Loading merges; it never deletes.</p>
      <div class="links"><button class="btn" id="exp">${ICON.dl}Download backup</button><label class="btn">Load a backup<input type="file" id="imp" accept="application/json" hidden></label></div>
    </section>
    <section class="panel">
      <h2>Appearance</h2>
      <div class="seg" role="group" aria-label="Theme">${["auto", "light", "dark"].map((t) => `<button data-t="${t}" aria-pressed="${theme === t}">${cap(t === "auto" ? "match system" : t)}</button>`).join("")}</div>
    </section>
    ${S.getState().views.length ? `<section class="panel"><h2>Saved searches</h2>${S.getState().views.map((v) => `<div class="line" style="display:flex;gap:8px;align-items:center;margin:6px 0"><a href="${esc(v.hash)}">${esc(v.name)}</a><button class="btn ghost small" data-delview="${v.id}">Remove</button></div>`).join("")}</section>` : ""}`;

  $("#syncForm")?.addEventListener("submit", async (e) => {
    e.preventDefault(); const fd = new FormData(e.target); $("#syncErr").textContent = "Connecting…";
    try { await S.connectSync(fd.get("repo"), fd.get("token")); toast("Sync is on"); route(); }
    catch (err) { $("#syncErr").textContent = err.message; }
  });
  $("#syncNow")?.addEventListener("click", async () => { await S.syncNow(); toast(S.syncInfo().state === "ok" ? "Synced" : "Sync problem"); route(); });
  $("#unsync")?.addEventListener("click", () => { if (confirm("Stop syncing on this device? Your notes stay in this browser and in the repository.")) { S.disconnectSync(); route(); } });
  $("#exp").onclick = () => {
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([S.exportJSON()], { type: "application/json" }));
    a.download = `tracker-notes-${new Date().toISOString().slice(0, 10)}.json`; a.click();
  };
  $("#imp").onchange = async (e) => {
    const file = e.target.files[0]; if (!file) return;
    try { S.importJSON(await file.text()); toast("Backup loaded"); route(); } catch (err) { alert(err.message); }
  };
  $$("[data-t]").forEach((b) => (b.onclick = () => {
    const t = b.dataset.t; if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
    try { localStorage.setItem("fod.theme", t); } catch {}
    route();
  }));
  $$("[data-delview]").forEach((b) => (b.onclick = () => { S.deleteView(b.dataset.delview); route(); }));
}

// ---------------------------------------------------------------- bill drawer
let openId = null;
function openBill(id) {
  openId = id;
  setParam("b", id);
  renderDrawer();
  const d = $("#drawer"); d.classList.add("open"); d.setAttribute("aria-hidden", "false");
  $("#scrim").hidden = false;
  setTimeout(() => $(".x", d)?.focus(), 50);
}
function closeBill() {
  openId = null; setParam("b", "");
  const d = $("#drawer"); d.classList.remove("open"); d.setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true;
  route();
}

function renderDrawer() {
  const id = openId; if (!id) return;
  const full = db.byId.get(id);
  const b = full || findBill(id);
  const d = $("#drawer");
  if (!b) { d.innerHTML = `<div class="dhead"><h2>Bill not found</h2><button class="btn ghost x" aria-label="Close">${ICON.x}</button></div><div class="dbody">This bill is no longer in the data.</div>`; $(".x", d).onclick = closeBill; return; }
  const m = S.bill(id) || { tags: [], folders: [], notes: [] };
  const ref = refOf(b);
  const st = full?.status || b.status || "introduced";
  const idx = Math.min(STATUS.indexOf(st), 4);
  const dead = st === "failed" || st === "vetoed";
  const stages = ["Introduced", "Committee", "One chamber", "Both chambers", "Enacted"];
  const track = `<div class="track ${st === "enacted" ? "enacted" : dead ? "dead" : ""}">${stages.map((s, i) => `<div class="${(!dead && i <= idx) || (dead && i <= Math.max(1, Math.min(idx, 3))) ? "on" : ""}"><i></i>${s}</div>`).join("")}</div>
    <div class="small" style="margin-top:6px">${esc(STATUS_LABEL[st])}${dead ? "" : ""}${full?.note ? `. ${esc(full.note)}` : ""}</div>`;

  const why = Object.entries(full?.categories || b.categories || {}).map(([k, v]) => `<div class="why" style="--c:${CAT_COLOR[k]}"><b>${esc(catName(k))}</b> ${v.level === "match" ? "" : "<span class='muted'>(possible match)</span>"}
    ${v.terms?.length ? `<div class="terms">Matched ${v.terms.slice(0, 5).map((t) => `<q>${esc(t)}</q>`).join(", ")}</div>` : ""}
    ${v.subtags?.length ? `<div class="terms">${v.subtags.map((s) => esc(SUBTAG_LABEL[s] || s)).join(", ")}</div>` : ""}</div>`).join("");

  const primary = (full?.sponsors || []).filter((s) => s.role === "primary" || s.role === "sponsor");
  const co = (full?.sponsors || []).filter((s) => s.role === "cosponsor");
  const acts = [...(full?.actions || [])].reverse();
  const hearings = (full?.hearings || []).filter((h) => h.date);
  const notes = (m.notes || []).filter((n) => !n.deleted);
  const fs = S.folders();

  d.innerHTML = `
    <div class="dhead"><div><div class="num">${esc(stateName(b.state))} ${esc(b.number)} <span class="muted">${esc(full?.session_name || b.session_name || b.session || "")}</span></div><h2>${esc(b.title)}</h2></div>
      <button class="btn ghost x" aria-label="Close">${ICON.x}</button></div>
    <div class="dbody">
      <div class="sec"><div class="links">
        <button class="btn ${m.watch ? "" : "primary"}" id="dWatch" aria-pressed="${!!m.watch}">${ICON.star}${m.watch ? "Watching" : "Watch"}</button>
        ${b.url ? `<a class="btn" href="${esc(b.url)}" target="_blank" rel="noopener">${ICON.ext}Official page</a>` : ""}
        ${full?.text_url ? `<a class="btn" href="${esc(full.text_url)}" target="_blank" rel="noopener">${ICON.ext}Bill text</a>` : ""}
        <button class="btn ghost" id="dHide">${m.hidden ? "Restore to lists" : "Not relevant"}</button>
      </div></div>
      <div class="sec"><h3>Progress</h3>${track}</div>

      <div class="sec mine"><h3 style="margin-bottom:10px">Your notes</h3>
        <div class="line"><label>Stance</label><div class="seg" id="dStance">${["support", "oppose", "monitor"].map((s) => `<button data-v="${s}" aria-pressed="${m.stance === s}">${cap(s)}</button>`).join("")}</div></div>
        <div class="line"><label>Priority</label><div class="seg" id="dPrio">${["high", "medium", "low"].map((s) => `<button data-v="${s}" aria-pressed="${m.priority === s}">${cap(s)}</button>`).join("")}</div></div>
        <div class="line"><label>Folders</label><div class="folderpick">${fs.map((f) => `<button class="fchip" data-f="${f.id}" aria-pressed="${m.folders?.includes(f.id)}"><span class="dot" style="background:${f.color};border-radius:2px"></span>${esc(f.name)}</button>`).join("")}<button class="fchip" id="dNewFolder">New folder</button></div></div>
        <div class="line"><label>Tags</label><div class="tagedit">${(m.tags || []).map((t) => `<span class="tag user">#${esc(t)}<button data-rmtag="${esc(t)}" aria-label="Remove tag ${esc(t)}">×</button></span>`).join("")}<input id="dTag" list="tagList" placeholder="Add a tag" aria-label="Add a tag"><datalist id="tagList">${S.allTags().map((t) => `<option value="${esc(t)}">`).join("")}</datalist></div></div>
        <textarea id="dNote" rows="3" placeholder="Add a note: who you talked to, next steps, coalition positions…"></textarea>
        <div style="margin-top:8px"><button class="btn small primary" id="dAddNote">Add note</button></div>
        ${notes.length ? `<ul class="notes">${notes.map((n) => `<li><div class="meta"><span>${esc(new Date(n.at).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }))}</span><button data-rmnote="${n.id}">Delete</button></div>${esc(n.text)}</li>`).join("")}</ul>` : ""}
      </div>

      ${why ? `<div class="sec"><h3>Why it's tracked</h3>${why}</div>` : ""}
      ${full?.summary ? `<div class="sec"><h3>Official summary</h3><div class="summary">${esc(full.summary)}</div></div>` : ""}
      ${hearings.length ? `<div class="sec"><h3>Hearings</h3><ul class="timeline">${hearings.map((h) => `<li><span class="d">${esc(fmtDate(h.date.slice(0, 10)))}</span><span>${esc(h.committee || "")} <span class="c">${esc(h.chamber)}</span></span></li>`).join("")}</ul></div>` : ""}
      ${primary.length || co.length ? `<div class="sec"><h3>Sponsors</h3><div class="sponsors"><b>${primary.map((s) => esc(s.name)).join(", ")}</b>${co.length ? `${primary.length ? ", with " : ""}${co.slice(0, 25).map((s) => esc(s.name)).join(", ")}${co.length > 25 ? ` and ${co.length - 25} more` : ""}` : ""}</div></div>` : ""}
      ${full?.subjects?.length ? `<div class="sec"><h3>Official subjects</h3><div class="small muted">${full.subjects.map(esc).join(", ")}</div></div>` : ""}
      ${acts.length ? `<div class="sec"><h3>History</h3><ul class="timeline">${acts.map((a) => `<li><span class="d">${esc(fmtDate(a.date))}</span><span>${esc(a.text)} ${a.chamber ? `<span class="c">${esc(a.chamber)}</span>` : ""}</span></li>`).join("")}</ul></div>`
        : !full ? `<div class="sec small muted">This bill isn't in your three topics, so only basic details are kept. The official page has its full history.</div>` : ""}
    </div>`;

  $(".x", d).onclick = closeBill;
  $("#dWatch").onclick = () => { const w = S.toggleWatch(id, ref); toast(w ? "Added to your watchlist" : "Removed from your watchlist"); renderDrawer(); };
  $("#dHide").onclick = () => { S.setField(id, "hidden", !m.hidden, ref); toast(m.hidden ? "Restored" : "Hidden from lists"); renderDrawer(); };
  $$("#dStance button").forEach((x) => (x.onclick = () => { S.setField(id, "stance", m.stance === x.dataset.v ? "" : x.dataset.v, ref); renderDrawer(); }));
  $$("#dPrio button").forEach((x) => (x.onclick = () => { S.setField(id, "priority", m.priority === x.dataset.v ? "" : x.dataset.v, ref); renderDrawer(); }));
  $$("[data-f]", d).forEach((x) => (x.onclick = () => { S.toggleFolder(id, x.dataset.f, ref); renderDrawer(); }));
  $("#dNewFolder").onclick = () => { const n = prompt("Folder name"); if (n?.trim()) { const f = S.createFolder(n); S.toggleFolder(id, f.id, ref); renderDrawer(); } };
  $("#dTag").onkeydown = (e) => { if (e.key === "Enter" && e.target.value.trim()) { S.addTag(id, e.target.value, ref); renderDrawer(); $("#dTag").focus(); } };
  $("#dTag").onchange = (e) => { if (e.target.value.trim() && S.allTags().includes(e.target.value.trim())) { S.addTag(id, e.target.value, ref); renderDrawer(); } };
  $$("[data-rmtag]", d).forEach((x) => (x.onclick = () => { S.removeTag(id, x.dataset.rmtag); renderDrawer(); }));
  $("#dAddNote").onclick = () => { const t = $("#dNote").value; if (t.trim()) { S.addNote(id, t, ref); renderDrawer(); toast("Note saved"); } };
  $$("[data-rmnote]", d).forEach((x) => (x.onclick = () => { if (confirm("Delete this note?")) { S.deleteNote(id, x.dataset.rmnote); renderDrawer(); } }));
}

// ---------------------------------------------------------------- router
function route() {
  const { path, p } = parseHash();
  renderNav();
  if (path === "/") viewDashboard();
  else if (path === "/bills") viewBills(p);
  else if (path === "/folders") viewFolders();
  else if (path.startsWith("/folder/")) viewFolder(path.split("/")[2], p);
  else if (path === "/search") viewSearch(p);
  else if (path === "/activity") viewActivity(p);
  else if (path === "/sources") viewSources();
  else if (path === "/settings") viewSettings();
  else viewDashboard();
  const b = p.get("b");
  if (b && b !== openId) openBill(b);
  if (!b && openId) closeBill();
}

let lastPath = "";
window.addEventListener("hashchange", () => {
  const { path } = parseHash();
  if (path !== lastPath) { selected.clear(); selMode = false; pageSize = 60; window.scrollTo(0, 0); lastPath = path; }
  route();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && openId) closeBill();
  if (e.key === "/" && !e.target.matches("input, textarea, select")) { const q = $("#q") || $("#sq"); if (q) { e.preventDefault(); q.focus(); } }
});
$("#scrim").addEventListener("click", closeBill);
wireRows(main);
S.onChange(() => { renderNav(); });

(async function start() {
  try { const t = localStorage.getItem("fod.theme"); if (t && t !== "auto") document.documentElement.dataset.theme = t; } catch {}
  main.innerHTML = `<div class="loading">Loading bills…</div>`;
  try {
    await load();
  } catch (e) {
    main.innerHTML = `<div class="empty"><b>The bill data hasn't been published yet</b>The first update runs in GitHub Actions and takes a few minutes. Reload this page once it finishes.</div>`;
    return;
  }
  lastPath = parseHash().path;
  route();
  if (S.syncConfig()) S.syncNow().then(() => { if (!openId) route(); });
})();
