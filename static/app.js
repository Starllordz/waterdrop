// Waterdrop — front-end logic (vanilla JS, no build step).

// Tabs are organized by media type (what the user thinks in: photos vs videos).
// Whether each pair is byte-identical or just similar is shown as a per-card badge.
const MEDIA_TABS = [
  { key: "photo", label: "Photos" },
  { key: "video", label: "Videos" },
];

const state = {
  groups: [],        // all duplicate groups from the last scan
  activeTab: "photo",
  recoverable: 0,    // bytes, decremented as files are deleted
  permanent: false,
  folderNames: { A: "Folder 1", B: "Folder 2" },  // basenames of the scanned folders
  bulk: { mode: "folder", side: "A", scope: "all" },  // bulk-delete selection
};

const TAB_LABEL = { photo: "photos", video: "videos" };

const $ = (sel) => document.querySelector(sel);

// Inline SVG icon (references the sprite defined in index.html).
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;

const basename = (p) => (p || "").replace(/\/+$/, "").split("/").pop() || p;

// Lazy-load thumbnails + metadata only when scrolled into view.
const lazyObserver = new IntersectionObserver((entries, obs) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    obs.unobserve(entry.target);
    loadThumb(entry.target);
    if (entry.target._loadInfo) entry.target._loadInfo();
  }
}, { rootMargin: "300px" });

// --------------------------------------------------------------------------- //
// Formatting helpers
// --------------------------------------------------------------------------- //
function fmtSize(bytes) {
  if (bytes >= 1024 * 1024 * 1024) return (bytes / 1073741824).toFixed(1) + " GB";
  if (bytes >= 1024 * 1024) return (bytes / 1048576).toFixed(1) + " MB";
  if (bytes >= 1024) return (bytes / 1024).toFixed(0) + " KB";
  return bytes + " B";
}

function fmtDuration(seconds) {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function megapixels(info) {
  return info.width && info.height ? (info.width * info.height) / 1e6 : 0;
}

// Build the technical metadata line shown under each preview.
function fmtInfoLine(info) {
  const parts = [];
  if (info.width && info.height) parts.push(`${info.width}×${info.height}`);
  if (info.kind === "video") {
    if (info.duration) parts.push(fmtDuration(info.duration));
    if (info.bitrate) parts.push((info.bitrate / 1e6).toFixed(1) + " Mbps");
  } else {
    const mp = megapixels(info);
    if (mp) parts.push(mp.toFixed(1) + " MP");
  }
  return parts.join(" · ");
}

function api(path, opts) {
  return fetch(path, opts).then((r) => r.json());
}

let toastTimer;
function toast(msg, isError) {
  let el = $("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, 2600);
}

function loadThumb(wrap) {
  const img = new Image();
  img.onload = () => {
    wrap.innerHTML = "";
    wrap.appendChild(img);
    if (wrap.dataset.kind === "video") {
      const play = document.createElement("span");
      play.className = "play";
      play.innerHTML = icon("play");
      wrap.appendChild(play);
    }
  };
  img.onerror = () => {
    wrap.innerHTML = `<svg class="ph"><use href="#i-image"></use></svg>`;
  };
  img.src = "/api/thumb?path=" + encodeURIComponent(wrap.dataset.path);
}

// --------------------------------------------------------------------------- //
// Folder pickers
// --------------------------------------------------------------------------- //
document.querySelectorAll("[data-pick]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const res = await api("/api/pick-folder", { method: "POST" });
    if (res.cancelled || !res.path) return;
    $("#" + btn.dataset.pick).value = res.path;
    refreshStartButton();
  });
});

function refreshStartButton() {
  const a = $("#folderA").value.trim();
  const b = $("#folderB").value.trim();
  $("#startScan").disabled = !(a && b);
}

// The folder fields are also editable: typing/pasting a path works everywhere,
// including systems where no native folder dialog is available.
["folderA", "folderB"].forEach((id) =>
  $("#" + id).addEventListener("input", refreshStartButton)
);

// Ask the server what it supports. If a recoverable Trash isn't available on
// this system, force permanent delete and explain why.
api("/api/capabilities").then((caps) => {
  if (caps && caps.trash === false) {
    const cb = $("#permanent");
    cb.checked = true;
    cb.disabled = true;
    state.permanent = true;
    const label = document.querySelector(".switch-label");
    if (label) {
      label.innerHTML =
        'Delete permanently <span class="hint">(Trash not available on this system)</span>';
    }
  }
}).catch(() => {});

// Range sliders -> live output
for (const id of ["imageThreshold", "videoTolerance"]) {
  const input = $("#" + id);
  const out = $("#" + id + "Out");
  input.addEventListener("input", () => { out.textContent = input.value; });
}

$("#permanent").addEventListener("change", (e) => { state.permanent = e.target.checked; });

// --------------------------------------------------------------------------- //
// Scan
// --------------------------------------------------------------------------- //
$("#startScan").addEventListener("click", startScan);

async function startScan() {
  const body = {
    folderA: $("#folderA").value.trim(),
    folderB: $("#folderB").value.trim(),
    imageThreshold: Number($("#imageThreshold").value),
    videoTolerance: Number($("#videoTolerance").value),
  };

  $("#startScan").disabled = true;
  $("#results").hidden = true;
  $("#progress").hidden = false;
  setProgress(0, "Starting…");

  const res = await api("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.error) {
    $("#progress").hidden = true;
    $("#startScan").disabled = false;
    toast(res.error, true);
    return;
  }
  pollScan(res.jobId);
}

function setProgress(fraction, label) {
  $("#barFill").style.width = Math.round(fraction * 100) + "%";
  $("#progressLabel").textContent = label;
}

function pollScan(jobId) {
  const tick = async () => {
    const job = await api("/api/scan/" + jobId);
    if (job.status === "running") {
      setProgress((job.step || 0) / (job.total || 3), job.label || "Scanning…");
      setTimeout(tick, 600);
    } else if (job.status === "done") {
      setProgress(1, "Done");
      setTimeout(() => {
        $("#progress").hidden = true;
        onScanDone(job);
      }, 350);
    } else {
      $("#progress").hidden = true;
      $("#startScan").disabled = false;
      toast(job.error || "Scan failed.", true);
    }
  };
  tick();
}

function onScanDone(job) {
  state.groups = job.groups || [];
  state.recoverable = job.summary ? job.summary.recoverable : 0;
  state.folderNames = {
    A: basename(job.folderA) || "Folder 1",
    B: basename(job.folderB) || "Folder 2",
  };
  // Derive the media type of each group (duplicates within a group share a kind).
  for (const g of state.groups) {
    g.mediaType = g.files[0] && g.files[0].kind === "video" ? "video" : "photo";
  }
  $("#startScan").disabled = false;
  $("#results").hidden = false;

  const counts = mediaCounts();
  const firstWithItems = MEDIA_TABS.find((t) => counts[t.key] > 0);
  state.activeTab = firstWithItems ? firstWithItems.key : "photo";

  renderTabs();
  renderSummary();
  renderBulkBar();
  renderGrid();
}

// --------------------------------------------------------------------------- //
// Rendering
// --------------------------------------------------------------------------- //
function mediaCounts() {
  const counts = { photo: 0, video: 0 };
  for (const g of state.groups) {
    if (!g.deleted) counts[g.mediaType]++;
  }
  return counts;
}

function renderTabs() {
  const counts = mediaCounts();
  const tabs = $("#tabs");
  tabs.innerHTML = "";
  for (const t of MEDIA_TABS) {
    const btn = document.createElement("button");
    btn.className = "tab" + (t.key === state.activeTab ? " active" : "");
    btn.innerHTML = `${t.label}<span class="count">${counts[t.key] || 0}</span>`;
    btn.addEventListener("click", () => {
      state.activeTab = t.key;
      renderTabs();
      renderBulkBar();
      renderGrid();
    });
    tabs.appendChild(btn);
  }
}

// --------------------------------------------------------------------------- //
// Bulk delete bar
// --------------------------------------------------------------------------- //
const SCOPES = [
  { key: "identical", label: "Identical" },
  { key: "similar", label: "Similar" },
  { key: "all", label: "All" },
];

const MODES = [
  { key: "folder", label: "From a folder" },
  { key: "best", label: "Keep best quality" },
];

// Quality score of a file: pixel count (from the scan's resolution) if known,
// otherwise 0 so the tie-breaker (file size) decides.
function fileScore(f) {
  const m = /(\d+)\s*[x×]\s*(\d+)/.exec(f.dimensions || "");
  return m ? Number(m[1]) * Number(m[2]) : 0;
}

// The highest-quality file of a group: most pixels, then largest size.
function bestFile(files) {
  let best = files[0];
  for (const f of files) {
    const s = fileScore(f), bs = fileScore(best);
    if (s > bs || (s === bs && f.size > best.size)) best = f;
  }
  return best;
}

function scopeMatches(g) {
  const { scope } = state.bulk;
  if (scope === "identical") return g.category === "IDENTICAL";
  if (scope === "similar") return g.category !== "IDENTICAL";
  return true;
}

// Files the current bulk selection would delete.
//  - "folder" mode: the copy on the chosen side of every matching group
//    (keeping the copy on the other side).
//  - "best" mode: every copy of a group EXCEPT its highest-quality one.
function bulkTargets() {
  const out = [];
  for (const g of state.groups) {
    if (g.deleted || g.mediaType !== state.activeTab || !scopeMatches(g)) continue;
    const live = g.files.filter((f) => !f.deleted);
    if (state.bulk.mode === "best") {
      if (live.length < 2) continue;
      const keep = bestFile(live);
      for (const f of live) if (f !== keep) out.push({ group: g, file: f });
    } else {
      // Delete every copy on the chosen side, as long as the other side keeps one.
      const onSide = live.filter((f) => f.side === state.bulk.side);
      const onOther = live.filter((f) => f.side !== state.bulk.side);
      if (onSide.length && onOther.length) {
        for (const f of onSide) out.push({ group: g, file: f });
      }
    }
  }
  return out;
}

function renderBulkBar() {
  const bar = $("#bulk");
  const anyInTab = state.groups.some(
    (g) => !g.deleted && g.mediaType === state.activeTab
  );
  bar.hidden = !anyInTab;
  if (!anyInTab) return;

  const isBest = state.bulk.mode === "best";
  const targets = bulkTargets();
  const totalBytes = targets.reduce((sum, t) => sum + (t.file.size || 0), 0);

  const seg = (id, items, current, attr) =>
    `<span class="seg" id="${id}">` + items.map((it) =>
      `<button data-${attr}="${it.key}" class="${current === it.key ? "on" : ""}" title="${it.label}">${it.label}</button>`
    ).join("") + `</span>`;

  const segMode = seg("segMode", MODES, state.bulk.mode, "mode");
  const segFolder = `<span class="bulk-group"><span class="lbl">from</span>` +
    `<span class="seg" id="segFolder">` + ["A", "B"].map((s) =>
      `<button data-side="${s}" class="${state.bulk.side === s ? "on" : ""}" title="${state.folderNames[s]}">${state.folderNames[s]}</button>`
    ).join("") + `</span></span>`;
  const segScope = seg("segScope", SCOPES, state.bulk.scope, "scope");

  const btnLabel = isBest
    ? `Keep best — delete ${targets.length}`
    : `Delete ${targets.length}`;

  bar.innerHTML =
    `<span class="bulk-title">${icon("both")} Bulk delete <span style="color:var(--ink-soft);font-weight:600">(${TAB_LABEL[state.activeTab]})</span></span>` +
    `<span class="bulk-group"><span class="lbl">mode</span>${segMode}</span>` +
    (isBest ? "" : segFolder) +
    `<span class="bulk-group"><span class="lbl">what</span>${segScope}</span>` +
    `<button class="btn-bulk" id="btnBulk" ${targets.length ? "" : "disabled"}>` +
    `${icon("trash")} ${btnLabel} ${targets.length ? "(~" + fmtSize(totalBytes) + ")" : ""}</button>`;

  bar.querySelectorAll("#segMode button").forEach((b) =>
    b.addEventListener("click", () => { state.bulk.mode = b.dataset.mode; renderBulkBar(); })
  );
  bar.querySelectorAll("#segFolder button").forEach((b) =>
    b.addEventListener("click", () => { state.bulk.side = b.dataset.side; renderBulkBar(); })
  );
  bar.querySelectorAll("#segScope button").forEach((b) =>
    b.addEventListener("click", () => { state.bulk.scope = b.dataset.scope; renderBulkBar(); })
  );
  $("#btnBulk").addEventListener("click", doBulkDelete);
}

async function doBulkDelete() {
  const targets = bulkTargets();
  if (!targets.length) return;
  const scopeWord = state.bulk.scope === "all"
    ? "" : SCOPES.find((s) => s.key === state.bulk.scope).label.toLowerCase() + " ";
  const what = `${targets.length} ${scopeWord}${TAB_LABEL[state.activeTab]}`;
  const how = state.permanent
    ? "They will be permanently deleted and cannot be recovered."
    : "They will be moved to the Trash.";
  const question = state.bulk.mode === "best"
    ? `Keep the highest-quality copy in each group and delete the other ${what}?`
    : `Delete ${what} from "${state.folderNames[state.bulk.side]}"?`;
  if (!confirm(`${question}\n${how}`)) return;

  // Delete in small batches so the user sees live progress and cards disappear
  // as we go, rather than one long unresponsive request.
  const byPath = new Map(targets.map((t) => [t.file.path, t.file]));
  const paths = targets.map((t) => t.file.path);
  const total = paths.length;
  const CHUNK = 25;
  let done = 0, failedCount = 0;

  const setBtn = (txt) => {
    const b = $("#btnBulk");
    if (b) { b.disabled = true; b.innerHTML = icon("trash") + " " + txt; }
  };
  setBtn(`Deleting 0/${total}…`);

  for (let i = 0; i < paths.length; i += CHUNK) {
    const slice = paths.slice(i, i + CHUNK);
    let res;
    try {
      res = await api("/api/delete-bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: slice, permanent: state.permanent }),
      });
    } catch (e) {
      res = { error: String(e) };
    }
    if (res.error) { toast(res.error, true); break; }

    const failed = new Set(res.failed || []);
    for (const p of slice) {
      if (failed.has(p)) { failedCount++; continue; }
      const f = byPath.get(p);
      if (f) f.deleted = true;
    }
    // Resolve groups that now have a single copy left, then update the view.
    for (const g of state.groups) {
      if (!g.deleted && g.files.filter((f) => !f.deleted).length <= 1) g.deleted = true;
    }
    state.recoverable = Math.max(0, state.recoverable - (res.freed || 0));
    done += slice.length;

    renderTabs();
    renderSummary();
    renderGrid();      // cards vanish progressively → visible feedback
    setBtn(`Deleting ${Math.min(done, total)}/${total}…`);
  }

  renderBulkBar();
  const ok = done - failedCount;
  if (failedCount) toast(`Deleted ${ok}, ${failedCount} failed.`, true);
  else toast(`Deleted ${ok} file${ok === 1 ? "" : "s"} ${state.permanent ? "permanently" : "to Trash"}.`);
}

function renderSummary() {
  const live = state.groups.filter((g) => !g.deleted);
  const identical = live.filter((g) => g.category === "IDENTICAL").length;
  const similar = live.length - identical;
  $("#summaryText").innerHTML =
    `${live.length} duplicate group${live.length === 1 ? "" : "s"} ` +
    `<span class="muted">(${identical} identical · ${similar} similar)</span> · ` +
    `<span class="recover">~${fmtSize(state.recoverable)} recoverable</span>`;
}

function renderGrid() {
  const grid = $("#grid");
  grid.innerHTML = "";
  const items = state.groups.filter(
    (g) => g.mediaType === state.activeTab && !g.deleted
  );
  $("#emptyState").hidden = items.length > 0;
  for (const group of items) {
    grid.appendChild(renderCard(group));
  }
}

function renderCard(group) {
  const card = document.createElement("div");
  card.className = "card";

  const tag = document.createElement("div");
  tag.className = "card-tag";
  const isIdentical = group.category === "IDENTICAL";
  tag.innerHTML =
    `<span>${isIdentical ? "Exact duplicate" : "Looks the same"}</span>` +
    `<span class="badge ${isIdentical ? "identical" : ""}">${
      isIdentical ? "100% identical" : "similar"
    }</span>`;
  card.appendChild(tag);

  const pair = document.createElement("div");
  pair.className = "pair";
  // Most groups are pairs, but some have 3+ copies. Lay them out so there is
  // never a lone item with an empty half: even counts pair up in 2 columns,
  // odd counts sit on a single row of N equal columns.
  const n = group.files.length;
  const cols = n % 2 === 0 ? 2 : n;
  pair.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  for (const file of group.files) {
    pair.appendChild(renderSide(group, file, card));
  }
  card.appendChild(pair);

  // Footer: delete all copies at once.
  const foot = document.createElement("div");
  foot.className = "card-foot";
  const both = document.createElement("button");
  both.className = "btn-both";
  both.innerHTML = icon("both") + (n > 2 ? ` Delete all ${n} copies` : " Delete both copies");
  both.addEventListener("click", () => deleteBoth(group, card));
  foot.appendChild(both);
  card.appendChild(foot);
  return card;
}

function renderSide(group, file, card) {
  const side = document.createElement("div");
  side.className = "side";
  file._sideEl = side;
  if (file.deleted) side.classList.add("deleted");

  const fld = state.folderNames[file.side] || ("Folder " + file.side);
  const head = document.createElement("div");
  head.className = "side-head";
  head.title = file.path;
  head.innerHTML = `<span class="chip">${file.side}</span><span class="fld">${fld}</span>`;
  side.appendChild(head);

  const wrap = document.createElement("div");
  wrap.className = "thumb-wrap";
  wrap.dataset.path = file.path;
  wrap.dataset.kind = file.kind;
  wrap.innerHTML = '<span class="spinner"></span>';
  wrap.addEventListener("click", () => openLightbox(file));
  // Schedule lazy loading of both thumbnail and technical info for this side.
  wrap._loadInfo = () => loadInfo(group, file);
  lazyObserver.observe(wrap);
  side.appendChild(wrap);

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.innerHTML =
    `<span class="fname">${file.name}</span>` +
    `<span class="specs" data-role="specs">${fmtSize(file.size)}` +
    (file.dimensions ? " · " + file.dimensions : "") + `</span>` +
    `<span class="qual" data-role="qual"></span>`;
  side.appendChild(meta);
  file._specsEl = meta.querySelector('[data-role="specs"]');
  file._qualEl = meta.querySelector('[data-role="qual"]');

  const btn = document.createElement("button");
  btn.className = "btn-del";
  btn.innerHTML =
    icon("trash") + ` Delete from <span class="fld-name">${fld}</span>`;
  btn.title = "Delete this copy (from " + fld + ")";
  btn.addEventListener("click", () => deleteFile(group, file, side, card));
  side.appendChild(btn);

  return side;
}

// --------------------------------------------------------------------------- //
// Metadata + quality comparison
// --------------------------------------------------------------------------- //
function fillSpecs(file) {
  if (!file._specsEl || !file.info) return;
  const line = fmtInfoLine(file.info);
  file._specsEl.textContent = fmtSize(file.info.size) + (line ? " · " + line : "");
}

async function loadInfo(group, file) {
  if (file.info) { fillSpecs(file); applyQuality(group); return; }
  try {
    file.info = await api("/api/info?path=" + encodeURIComponent(file.path));
    fillSpecs(file);
    applyQuality(group);
  } catch (_) { /* ignore */ }
}

// When both sides have metadata, mark which copy is higher quality.
function applyQuality(group) {
  const files = group.files.filter((f) => !f.deleted && f.info);
  if (files.length < 2) return;

  const score = (f) => megapixels(f.info) || (f.info.width * f.info.height) || 0;
  let best = files[0];
  for (const f of files) {
    const better = score(f) > score(best) ||
      (score(f) === score(best) && f.size > best.size);
    if (better) best = f;
  }
  const allEqual = files.every(
    (f) => score(f) === score(best) && f.size === best.size
  );

  for (const f of files) {
    if (!f._qualEl) continue;
    if (allEqual) {
      f._qualEl.className = "qual same";
      f._qualEl.innerHTML = icon("check") + " same quality";
    } else if (f === best) {
      f._qualEl.className = "qual best";
      f._qualEl.innerHTML = icon("up") + " higher quality";
    } else {
      f._qualEl.className = "qual low";
      f._qualEl.textContent = "lower quality";
    }
  }
}

// --------------------------------------------------------------------------- //
// Delete
// --------------------------------------------------------------------------- //
async function deleteFile(group, file, sideEl, card) {
  const keep = group.files.filter((f) => f !== file && !f.deleted).map((f) => f.path);
  if (keep.length === 0) {
    toast("Can't delete the last remaining copy.", true);
    return;
  }

  const res = await api("/api/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: file.path, keep, permanent: state.permanent }),
  });
  if (res.error) { toast(res.error, true); return; }

  file.deleted = true;
  state.recoverable = Math.max(0, state.recoverable - (res.freed || 0));

  const remaining = group.files.filter((f) => !f.deleted);
  if (remaining.length <= 1) {
    group.deleted = true;
    card.classList.add("removing");
    setTimeout(() => { card.remove(); renderTabs(); renderSummary(); renderBulkBar(); }, 260);
  } else {
    sideEl.classList.add("deleted");
    const note = document.createElement("div");
    note.className = "kept-note";
    sideEl.querySelector(".btn-del").replaceWith(note);
    renderSummary();
    renderBulkBar();
  }
  toast(res.permanent ? "Deleted permanently." : "Moved to Trash.");
}

async function deleteBoth(group, card) {
  const files = group.files.filter((f) => !f.deleted);
  if (files.length === 0) return;
  if (state.permanent &&
      !confirm("Delete BOTH copies permanently? This cannot be undone.")) {
    return;
  }

  let freed = 0, failures = 0;
  for (const f of files) {
    // force:true bypasses the "keep one copy" guard — this is an explicit choice.
    const res = await api("/api/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: f.path, force: true, permanent: state.permanent }),
    });
    if (res.error) { failures++; continue; }
    f.deleted = true;
    freed += res.freed || 0;
  }
  state.recoverable = Math.max(0, state.recoverable - freed);

  if (failures) { toast(`${failures} file(s) could not be deleted.`, true); }
  if (group.files.every((f) => f.deleted)) {
    group.deleted = true;
    card.classList.add("removing");
    setTimeout(() => { card.remove(); renderTabs(); renderSummary(); renderBulkBar(); }, 260);
    if (!failures) toast(state.permanent ? "Both deleted permanently." : "Both moved to Trash.");
  }
}

// --------------------------------------------------------------------------- //
// Lightbox
// --------------------------------------------------------------------------- //
function openLightbox(file) {
  if (file.deleted) return;
  const content = $("#lightboxContent");
  content.innerHTML = "";
  const src = "/api/media?path=" + encodeURIComponent(file.path);
  if (file.kind === "video") {
    const v = document.createElement("video");
    v.src = src; v.controls = true; v.autoplay = true;
    content.appendChild(v);
  } else {
    const img = document.createElement("img");
    img.src = src;
    content.appendChild(img);
  }
  $("#lightbox").hidden = false;
}

function closeLightbox() {
  $("#lightbox").hidden = true;
  $("#lightboxContent").innerHTML = "";  // stop video playback
}
$("#lightboxClose").addEventListener("click", closeLightbox);
$("#lightbox").addEventListener("click", (e) => {
  if (e.target.id === "lightbox") closeLightbox();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#lightbox").hidden) closeLightbox();
});
