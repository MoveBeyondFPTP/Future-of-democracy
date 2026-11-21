// Your private tracker state: watchlist, folders, tags, notes, stance, priority.
// Saved in this browser right away, and (once set up in Settings) synced to a
// private GitHub repository so it follows you across devices.

const KEY = "fod.state.v1";
const SYNC_KEY = "fod.sync.v1";
const FILE = "tracker-state.json";

const blank = () => ({
  version: 1,
  updated: new Date(0).toISOString(),
  bills: {},        // id -> {watch, tags[], folders[], stance, priority, hidden, notes[], updated, ref}
  folders: [],      // {id, name, color, created, updated, deleted?}
  lastSeen: null,   // ISO time you last opened the activity feed
  views: [],        // saved searches {id, name, hash}
});

function safeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { localStorage.setItem(k, v); return true; } catch { return false; } }

let state = (() => {
  try { return { ...blank(), ...JSON.parse(safeGet(KEY) || "{}") }; } catch { return blank(); }
})();
let sync = (() => { try { return JSON.parse(safeGet(SYNC_KEY) || "null"); } catch { return null; } })();
const listeners = new Set();
let syncStatus = { state: sync ? "idle" : "off", message: "" };
let pushTimer = null;
let remoteSha = null;

export const now = () => new Date().toISOString();
export const uid = () => Math.random().toString(36).slice(2, 10);
export function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit() { listeners.forEach((fn) => fn()); }

function persist() {
  state.updated = now();
  safeSet(KEY, JSON.stringify(state));
  emit();
  if (sync) schedulePush();
}

export function getState() { return state; }
export function bill(id) { return state.bills[id] || null; }

function touch(id, ref) {
  const b = state.bills[id] || { watch: false, tags: [], folders: [], stance: "", priority: "", hidden: false, notes: [] };
  if (ref) b.ref = ref;   // minimal copy (number, title, state) so folders list bills without loading data
  b.updated = now();
  state.bills[id] = b;
  return b;
}

export function setField(id, field, value, ref) { touch(id, ref)[field] = value; persist(); }
export function toggleWatch(id, ref) { const b = touch(id, ref); b.watch = !b.watch; persist(); return b.watch; }
export function addTag(id, tag, ref) {
  tag = tag.trim(); if (!tag) return;
  const b = touch(id, ref); if (!b.tags.includes(tag)) b.tags.push(tag); persist();
}
export function removeTag(id, tag) { const b = touch(id); b.tags = b.tags.filter((t) => t !== tag); persist(); }
export function toggleFolder(id, folderId, ref) {
  const b = touch(id, ref);
  b.folders = b.folders.includes(folderId) ? b.folders.filter((f) => f !== folderId) : [...b.folders, folderId];
  persist();
}
export function addNote(id, text, ref) {
  text = text.trim(); if (!text) return;
  touch(id, ref).notes.unshift({ id: uid(), at: now(), text }); persist();
}
export function deleteNote(id, noteId) {
  const b = touch(id); b.notes = b.notes.map((n) => n.id === noteId ? { ...n, deleted: true, text: "" } : n); persist();
}
export function allTags() {
  const s = new Set();
  Object.values(state.bills).forEach((b) => (b.tags || []).forEach((t) => s.add(t)));
  return [...s].sort((a, b) => a.localeCompare(b));
}

export function folders() { return state.folders.filter((f) => !f.deleted); }
const PALETTE = ["#5B3FD1", "#0E7C6B", "#A86A12", "#B3261E", "#2563A8", "#6B7280", "#8A3FA0", "#1E7A45"];
export function createFolder(name) {
  const f = { id: uid(), name: name.trim(), color: PALETTE[folders().length % PALETTE.length], created: now(), updated: now() };
  state.folders.push(f); persist(); return f;
}
export function renameFolder(id, name) { const f = state.folders.find((x) => x.id === id); if (f) { f.name = name; f.updated = now(); persist(); } }
export function deleteFolder(id) {
  const f = state.folders.find((x) => x.id === id); if (!f) return;
  f.deleted = true; f.updated = now();
  Object.values(state.bills).forEach((b) => { if (b.folders?.includes(id)) { b.folders = b.folders.filter((x) => x !== id); b.updated = now(); } });
  persist();
}
export function markSeen() { state.lastSeen = now(); persist(); }
export function saveView(name, hash) { state.views.push({ id: uid(), name, hash, updated: now() }); persist(); }
export function deleteView(id) { state.views = state.views.filter((v) => v.id !== id); persist(); }

export function exportJSON() { return JSON.stringify(state, null, 1); }
export function importJSON(text) {
  const incoming = JSON.parse(text);
  if (!incoming || typeof incoming !== "object" || !incoming.bills) throw new Error("That file isn't a tracker export.");
  state = merge(state, incoming); persist();
}

// ----- merging (used for sync and import): newest edit wins per bill/folder; notes are unioned
function merge(a, b) {
  const out = { ...blank(), ...a };
  out.bills = { ...a.bills };
  for (const [id, rb] of Object.entries(b.bills || {})) {
    const lb = out.bills[id];
    if (!lb) { out.bills[id] = rb; continue; }
    const newer = (rb.updated || "") > (lb.updated || "") ? rb : lb;
    const notes = new Map();
    [...(lb.notes || []), ...(rb.notes || [])].forEach((n) => {
      const prev = notes.get(n.id);
      notes.set(n.id, prev ? (n.deleted || prev.deleted ? { ...n, deleted: true, text: "" } : n) : n);
    });
    out.bills[id] = { ...newer, notes: [...notes.values()].sort((x, y) => (y.at || "").localeCompare(x.at || "")) };
  }
  const fm = new Map((a.folders || []).map((f) => [f.id, f]));
  (b.folders || []).forEach((f) => { const l = fm.get(f.id); if (!l || (f.updated || "") > (l.updated || "")) fm.set(f.id, f); });
  out.folders = [...fm.values()];
  const vm = new Map((a.views || []).map((v) => [v.id, v]));
  (b.views || []).forEach((v) => vm.set(v.id, v));
  out.views = [...vm.values()];
  out.lastSeen = [a.lastSeen, b.lastSeen].filter(Boolean).sort().pop() || null;
  return out;
}

// ----- GitHub sync -------------------------------------------------------
export function syncConfig() { return sync; }
export function syncInfo() { return syncStatus; }
function setSync(s, message = "") { syncStatus = { state: s, message }; emit(); }

async function gh(path, opts = {}) {
  const r = await fetch(`https://api.github.com/repos/${sync.repo}/contents/${path}`, {
    ...opts,
    headers: { Authorization: `Bearer ${sync.token}`, Accept: "application/vnd.github+json", ...(opts.headers || {}) },
  });
  return r;
}
const b64e = (s) => btoa(unescape(encodeURIComponent(s)));
const b64d = (s) => decodeURIComponent(escape(atob(s.replace(/\n/g, ""))));

async function pull() {
  const r = await gh(FILE + `?t=${Date.now()}`);
  if (r.status === 404) { remoteSha = null; return null; }
  if (r.status === 401 || r.status === 403) throw new Error("GitHub refused the token. Check that it has Contents read and write access to that repository.");
  if (!r.ok) throw new Error(`GitHub returned ${r.status} while loading your notes.`);
  const j = await r.json();
  remoteSha = j.sha;
  return JSON.parse(b64d(j.content));
}

export async function syncNow() {
  if (!sync) return;
  setSync("busy");
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      const remote = await pull();
      if (remote) state = merge(state, remote);
      safeSet(KEY, JSON.stringify(state));
      const body = { message: `Update tracker notes ${now()}`, content: b64e(JSON.stringify(state, null, 1)) };
      if (remoteSha) body.sha = remoteSha;
      const r = await gh(FILE, { method: "PUT", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
      if (r.status === 409 || r.status === 422) continue;   // someone saved in between: pull, merge, retry
      if (!r.ok) throw new Error(`GitHub returned ${r.status} while saving your notes.`);
      remoteSha = (await r.json()).content.sha;
      sync.last = now(); safeSet(SYNC_KEY, JSON.stringify(sync));
      setSync("ok");
      return;
    }
    throw new Error("Couldn't save after three tries because another device kept saving at the same time.");
  } catch (e) {
    setSync("error", e.message || String(e));
  }
}

function schedulePush() {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(syncNow, 1800);
}

export async function connectSync(repo, token) {
  repo = repo.trim().replace(/^https:\/\/github\.com\//, "").replace(/\.git$/, "").replace(/\/$/, "");
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) throw new Error("Enter the repository as owner/name, for example MoveBeyondFPTP/tracker-notes.");
  const r = await fetch(`https://api.github.com/repos/${repo}`, { headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" } });
  if (r.status === 404) throw new Error("GitHub can't find that repository with this token. Check the name, and that the token was given access to it.");
  if (!r.ok) throw new Error(`GitHub returned ${r.status}. Check the token.`);
  const info = await r.json();
  if (!info.private) throw new Error("That repository is public. Use a private repository so your notes stay private.");
  sync = { repo, token, last: null };
  safeSet(SYNC_KEY, JSON.stringify(sync));
  await syncNow();
  if (syncStatus.state === "error") throw new Error(syncStatus.message);
}

export function disconnectSync() {
  sync = null; try { localStorage.removeItem(SYNC_KEY); } catch {}
  setSync("off");
}

// Pull remote changes when the tab regains focus (another device may have edited).
if (typeof window !== "undefined") {
  window.addEventListener("focus", () => { if (sync && syncStatus.state !== "busy") syncNow(); });
}
