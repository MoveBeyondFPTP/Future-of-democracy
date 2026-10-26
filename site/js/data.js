// Loads the published data files and answers queries over them.

export const STATUS = ["introduced", "committee", "passed_one", "passed_both", "enacted", "vetoed", "failed"];
export const STATUS_LABEL = {
  introduced: "Introduced", committee: "In committee", passed_one: "Passed one chamber",
  passed_both: "Passed legislature", enacted: "Enacted", vetoed: "Vetoed", failed: "Failed / dead",
};
export const CAT_COLOR = { rcv: "var(--rcv)", svra: "var(--svra)", pr: "var(--pr)" };
export const SUBTAG_LABEL = {
  ban: "Ban / repeal", adoption: "Adoption", local_option: "Local option", primaries: "Primaries",
  overseas_military: "Overseas & military", study_commission: "Study / commission", top_four_five: "Top-four / final-five",
  constitutional_amendment: "Constitutional amendment", comprehensive_svra: "Comprehensive VRA",
  dilution_cause_of_action: "Vote-dilution claims", preclearance: "Preclearance", language_access: "Language access",
  data_repository: "Election data hub", at_large_conversion: "At-large to districts", repeal_or_limit: "Repeal / limit",
  stv_proportional_rcv: "STV / proportional RCV", multi_member_districts: "Multi-member districts",
  party_list_mixed: "Party list / mixed member", semi_proportional: "Cumulative / limited voting",
  congressional: "Congressional", electoral_college: "Electoral votes", local_government: "Local government",
};

const D = { meta: null, health: {}, changes: [], bills: [], byId: new Map(), catalogs: new Map() };
export const db = D;

async function getJSON(path) {
  const r = await fetch(`${path}?v=${D.stamp || Date.now()}`, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export async function load() {
  D.meta = await getJSON("data/meta.json");
  D.stamp = encodeURIComponent(D.meta.generated || "");
  const [health, changes] = await Promise.all([
    getJSON("data/health.json").catch(() => ({})),
    getJSON("data/changes.json").catch(() => []),
  ]);
  D.health = health; D.changes = changes;
  const states = Object.entries(D.meta.states).filter(([, s]) => s.enabled).map(([c]) => c);
  const files = await Promise.all(states.map((c) => getJSON(`data/bills/${c}.json`).catch(() => null)));
  D.bills = files.filter(Boolean).flatMap((f) => f.bills);
  D.bills.forEach((b) => { b._text = `${b.number} ${b.number.replace(/\s/g, "")} ${b.title} ${b.summary || ""} ${(b.sponsors || []).map((s) => s.name).join(" ")} ${(b.subjects || []).join(" ")}`.toLowerCase(); D.byId.set(b.id, b); });
  return D;
}

export function stateName(code) { return D.meta?.states?.[code]?.name || code; }
export function enabledStates() { return Object.entries(D.meta.states).filter(([, s]) => s.enabled).map(([c, s]) => ({ code: c, ...s })); }
export function plannedStates() { return Object.entries(D.meta.states).filter(([, s]) => !s.enabled).map(([c, s]) => ({ code: c, ...s })); }
export function categories() { return D.meta.categories; }
export function catName(k) { return D.meta.categories.find((c) => c.key === k)?.name || k; }

export function isCurrent(b) {
  const s = D.meta.states[b.state]?.sessions?.find((x) => x.code === b.session);
  return !!s?.current;
}
// "Recent sessions": the session(s) marked current in config/states.yml, plus any
// session with action in roughly the last 13 months. Off-season this keeps last
// session's results visible; once a new session opens its bills join automatically.
let _live = null;
export function liveSessions() {
  if (_live) return _live;
  const cutoff = new Date(Date.now() - 400 * 864e5).toISOString().slice(0, 10);
  const recent = {};
  D.bills.forEach((b) => { if ((b.last_action_date || "") >= cutoff) (recent[b.state] ||= new Set()).add(b.session); });
  const out = {};
  for (const [code, s] of Object.entries(D.meta.states)) {
    out[code] = new Set(s.sessions.filter((x) => x.current || recent[code]?.has(x.code)).map((x) => x.code));
  }
  return (_live = out);
}

export function sessionsFor(code) { return D.meta.states[code]?.sessions || []; }

// Query: {q, cats[], states[], status[], level ('match'|'all'), scope ('live'|'all'), subtag, tag, folder, watch, hidden, sort}
export function query(f, mine) {
  const live = liveSessions();
  const q = (f.q || "").trim().toLowerCase();
  const words = q ? q.split(/\s+/) : [];
  let rows = D.bills.filter((b) => {
    const m = mine(b.id);
    if (!f.hidden && m?.hidden) return false;
    if (f.hidden && !m?.hidden) return false;
    if (f.scope !== "all" && !live[b.state]?.has(b.session)) return false;
    const cats = Object.entries(b.categories || {}).filter(([, v]) => f.level === "all" || v.level === "match").map(([k]) => k);
    if (!cats.length && !m?.watch && !(m?.folders?.length)) return false;
    if (f.cats?.length && !f.cats.some((c) => cats.includes(c))) return false;
    if (f.states?.length && !f.states.includes(b.state)) return false;
    if (f.status?.length && !f.status.includes(b.status)) return false;
    if (f.subtag && !Object.values(b.categories || {}).some((v) => v.subtags?.includes(f.subtag))) return false;
    if (f.tag && !m?.tags?.includes(f.tag)) return false;
    if (f.folder && !m?.folders?.includes(f.folder)) return false;
    if (f.watch && !m?.watch) return false;
    if (f.stance && m?.stance !== f.stance) return false;
    if (words.length && !words.every((w) => b._text.includes(w))) return false;
    return true;
  });
  const sort = f.sort || "recent";
  const key = {
    recent: (b) => b.last_action_date || "",
    introduced: (b) => b.introduced || "",
    progress: (b) => String(STATUS.indexOf(b.status) === 4 ? 9 : Math.min(STATUS.indexOf(b.status), 4)) + (b.last_action_date || ""),
    state: (b) => `${b.state}${b.number.replace(/\d+/, (n) => n.padStart(6, "0"))}`,
  }[sort];
  rows.sort((a, b) => (key(a) < key(b) ? 1 : key(a) > key(b) ? -1 : 0));
  if (sort === "state") rows.reverse();
  return rows;
}

// ----- full catalog search (every bill, any topic) ----------------------
export async function loadCatalog(code) {
  if (D.catalogs.has(code)) return D.catalogs.get(code);
  const p = getJSON(`data/catalog/${code}.json`).then((j) => j.rows.map((r) => ({
    id: r[0], number: r[1], session: r[2], title: r[3], status: STATUS[r[4]] || "introduced",
    last_action_date: r[5], cats: r[6], url: r[7], state: code, _t: `${r[1]} ${r[1].replace(/\s/g, "")} ${r[3]}`.toLowerCase(),
  }))).catch(() => []);
  D.catalogs.set(code, p);
  return p;
}

export function relDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  const days = Math.round((Date.now() - d) / 864e5);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days > 1 && days < 7) return `${days} days ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}
export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
