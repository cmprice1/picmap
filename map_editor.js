/* PicMap layout editor.
 *
 * Loads map_layout.json (editable), output/data.json + assets/editor_context.json
 * (read-only context), renders an approximate preview of the print map, and
 * lets you drag labels (offset-based) and glyphs (lon/lat-based). Save POSTs
 * the layout back via serve_editor.py. The Python script remains the real
 * renderer — this preview is for positioning only.
 */

"use strict";

// ── Canvas constants (match build_print_map.py's geometry) ───────────────
const VBW = 2400, VBH = 1200;            // svg units; 100 per page-inch
const PT2U = VBW / (24 * 72);            // matplotlib points -> svg units
const FS_STOP = 8.8 * PT2U * 1.6;        // label font sizes, slightly enlarged
const FS_BOLD = 9.8 * PT2U * 1.6;        //  (editor is viewed smaller than print)
const FS_PARK = 6.8 * PT2U * 1.6;
const FS_WP   = 8.0 * PT2U * 1.6;
const FS_SUB  = 6.2 * PT2U * 1.6;

const SVG_NS = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);
const svg = $("map");

// ── State ────────────────────────────────────────────────────────────────
let layout = null;        // editable model (mirrors map_layout.json)
let ctx = null;           // {view_bbox, projection, states}
let trip = null;          // output/data.json
let undoStack = [], redoStack = [];
let dirty = false;
let sel = null;           // {type, ...ref}
let placing = null;       // kind string while in click-to-place mode
let vb = { x: 0, y: 0, w: VBW, h: VBH };

// ── Projection (port of build_print_map.py, exact same formulas) ─────────
let PJ = null;
function initProjection(p) {
  const toRad = d => d * Math.PI / 180;
  const p1 = toRad(p.std1), p2 = toRad(p.std2);
  const n = 0.5 * (Math.sin(p1) + Math.sin(p2));
  const C = Math.cos(p1) ** 2 + 2 * n * Math.sin(p1);
  const rho0 = Math.sqrt(C - 2 * n * Math.sin(toRad(p.lat0))) / n;
  PJ = { n, C, rho0, lon0: p.lon0 };
}
function project(lon, lat) {
  const t = PJ.n * (lon - PJ.lon0) * Math.PI / 180;
  const rho = Math.sqrt(PJ.C - 2 * PJ.n * Math.sin(lat * Math.PI / 180)) / PJ.n;
  return [rho * Math.sin(t), PJ.rho0 - rho * Math.cos(t)];
}
function unproject(px, py) {
  const rho = Math.hypot(px, PJ.rho0 - py);
  const t = Math.atan2(px, PJ.rho0 - py);
  const s = (PJ.C - (rho * PJ.n) ** 2) / (2 * PJ.n);
  const lat = Math.asin(Math.max(-1, Math.min(1, s))) * 180 / Math.PI;
  const lon = PJ.lon0 + (t / PJ.n) * 180 / Math.PI;
  return [lon, lat];
}
// projected coords -> svg user units (y flipped) and back
function pjToU(px, py) {
  const [x0, x1, y0, y1] = ctx.view_bbox;
  return [(px - x0) / (x1 - x0) * VBW, (1 - (py - y0) / (y1 - y0)) * VBH];
}
function uToPj(u, v) {
  const [x0, x1, y0, y1] = ctx.view_bbox;
  return [x0 + u / VBW * (x1 - x0), y0 + (1 - v / VBH) * (y1 - y0)];
}
const llToU = (lon, lat) => pjToU(...project(lon, lat));
const uToLL = (u, v) => unproject(...uToPj(u, v));

function clientToU(evt) {
  const pt = new DOMPoint(evt.clientX, evt.clientY);
  const p = pt.matrixTransform(svg.getScreenCTM().inverse());
  return [p.x, p.y];
}

// ── Effective overnight stops (mirror of the Python logic) ───────────────
function effectiveStops() {
  const seen = new Set(), out = [];
  for (const s of trip.stops) {
    if (s.type !== "overnight") continue;
    const key = `${s.name}|${s.arrival.slice(0, 10)}`;
    let name, lat, lon;
    if (key in layout.stop_overrides) {
      const ov = layout.stop_overrides[key];
      if (ov === null) continue;
      name = ov.name ?? layout.display_names[key] ?? s.name;
      lat = ov.lat ?? s.lat;
      lon = ov.lon ?? s.lng;
    } else {
      name = layout.display_names[key] ?? s.name;
      lat = s.lat; lon = s.lng;
    }
    if (seen.has(name)) continue;
    seen.add(name);
    out.push({ key, name, lat, lon });
  }
  return out;
}

// ── SVG helpers ──────────────────────────────────────────────────────────
function el(tag, attrs, parent) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
const HA2ANCHOR = { left: "start", right: "end", center: "middle" };
const VA2BASE = { center: "middle", top: "hanging", bottom: "auto", baseline: "auto" };

function labelPos(anchorU, anchorV, st) {
  return [anchorU + (st.dx || 0) * PT2U, anchorV - (st.dy || 0) * PT2U];
}

// ── Rendering ────────────────────────────────────────────────────────────
let gStatic, gDyn, gSel;

function buildStatic() {
  gStatic = el("g", {}, svg);
  for (const st of ctx.states) {
    let d = "";
    for (const ring of st.rings) {
      ring.forEach(([lon, lat], i) => {
        const [u, v] = llToU(lon, lat);
        d += (i ? "L" : "M") + u.toFixed(1) + " " + v.toFixed(1);
      });
      d += "Z";
    }
    el("path", { d, class: "state" }, gStatic);
  }
  const route = trip.route.geometry.coordinates;
  const step = Math.max(1, Math.floor(route.length / 1200));
  let pts = [];
  for (let i = 0; i < route.length; i += step) pts.push(route[i]);
  pts.push(route[route.length - 1]);
  el("polyline", {
    points: pts.map(([lon, lat]) => llToU(lon, lat).map(n => n.toFixed(1)).join(",")).join(" "),
    class: "route",
  }, gStatic);
  for (const s of trip.stops) {
    if (s.type !== "day") continue;
    const [u, v] = llToU(s.lng, s.lat);
    el("circle", { cx: u, cy: v, r: 1.7, class: "daydot" }, gStatic);
  }
  gDyn = el("g", {}, svg);
  gSel = el("g", {}, svg);
}

function glyphShape(kind, big, s) {
  // Simple placeholder art; the poster's real glyphs live in Python.
  if (kind === "mountain") {
    const w = (big ? 15 : 10) * s, h = (big ? 13 : 9) * s;
    return `M${-w} 0 L${-w * 0.25} ${-h} L${w * 0.2} ${-h * 0.35} ` +
           `M${-w * 0.15} ${-h * 0.15} L${w * 0.35} ${-h * 0.75} L${w} 0`;
  }
  if (kind === "conifer") {
    const h = 11 * s, w = 4.5 * s;
    return `M0 0 L0 ${-h * 0.25} M${-w} ${-h * 0.3} L0 ${-h} L${w} ${-h * 0.3} ` +
           `M${-w * 0.7} ${-h * 0.55} L0 ${-h} L${w * 0.7} ${-h * 0.55}`;
  }
  if (kind === "broadleaf") {
    const h = 6 * s, r = 4.5 * s;
    return `M0 0 L0 ${-h} M${-r} ${-h - r * 0.8} A${r} ${r} 0 1 1 ${r} ${-h - r * 0.8} ` +
           `A${r} ${r} 0 1 1 ${-r} ${-h - r * 0.8}`;
  }
  if (kind === "bridge") {
    const w = 14, h = 6;
    return `M${-w} ${-h} L${w} ${-h} M${-w} 0 Q0 ${-h * 1.7} ${w} 0`;
  }
  if (kind === "dune") {
    return `M-11 0 Q0 -7 11 0 M0 -3.5 L-1.5 -8 M0 -3.5 L2 -7`;
  }
  return `M-5 -5 L5 5 M-5 5 L5 -5`; // unknown kind -> X placeholder
}

function renderDyn() {
  gDyn.replaceChildren();
  gSel.replaceChildren();
  const route = trip.route.geometry.coordinates;

  // Lakes
  for (const [name, ring] of Object.entries(layout.lakes)) {
    const ptsAttr = ring.map(([lon, lat]) =>
      llToU(lon, lat).map(n => n.toFixed(1)).join(",")).join(" ");
    const p = el("polygon", { points: ptsAttr, class: "lake" }, gDyn);
    attachDrag(p, { type: "lake", name });
    markSel(p, { type: "lake", name });
  }

  // Plain glyphs
  const groups = [["mtn", layout.mountains], ["con", layout.conifers], ["brd", layout.broadleaf]];
  const kinds = { mtn: "mountain", con: "conifer", brd: "broadleaf" };
  for (const [t, arr] of groups) {
    arr.forEach((entry, idx) => {
      const [lon, lat, s, big] = entry;
      const [u, v] = llToU(lon, lat);
      const g = el("g", { transform: `translate(${u} ${v})`,
                          class: "glyph" + (big ? " big" : "") }, gDyn);
      el("path", { d: glyphShape(kinds[t], !!big, s ?? 1), class: "shape" }, g);
      el("circle", { r: 13, class: "hit" }, g);
      attachDrag(g, { type: t, idx });
      markSel(g, { type: t, idx }, u, v);
    });
  }

  // Parks: glyph + italic label, separately draggable
  layout.parks.forEach((pk, idx) => {
    const [u, v] = llToU(pk.lon, pk.lat);
    const g = el("g", { transform: `translate(${u} ${v})`,
                        class: "glyph" + (pk.big ? " big" : "") }, gDyn);
    el("path", { d: glyphShape(pk.kind, !!pk.big, 0.85), class: "shape" }, g);
    el("circle", { r: 13, class: "hit" }, g);
    attachDrag(g, { type: "park", idx });
    markSel(g, { type: "park", idx }, u, v);

    const [lu, lv] = labelPos(u, v, pk);
    const t = el("text", {
      x: lu, y: lv, class: "lbl park", "font-size": FS_PARK,
      "text-anchor": HA2ANCHOR[pk.ha || "left"], "dominant-baseline": "middle",
    }, gDyn);
    fillLines(t, pk.name, "center", FS_PARK);
    attachDrag(t, { type: "park-label", idx });
    markSel(t, { type: "park-label", idx });
  });

  // Waypoint cities
  layout.waypoints.forEach((w, idx) => {
    const [u, v] = llToU(w.lon, w.lat);
    const c = el("circle", { cx: u, cy: v, r: 3.4, class: "wp-marker" }, gDyn);
    attachDrag(c, { type: "wp", idx });
    markSel(c, { type: "wp", idx }, u, v);
    drawLabel(w.name, u, v, { cls: "lbl wp", size: FS_WP });
  });

  // Overnight stops
  const editable = $("chkEditStops").checked;
  for (const s of effectiveStops()) {
    const [u, v] = llToU(s.lon, s.lat);
    const c = el("circle", { cx: u, cy: v, r: 5,
                             class: "ov-marker" + (editable ? " editable" : "") }, gDyn);
    if (editable) attachDrag(c, { type: "stop", key: s.key });
    markSel(c, { type: "stop", key: s.key }, u, v);
    drawLabel(s.name, u, v, { cls: "lbl", size: FS_STOP, stopKey: s.key });
  }

  // Start / end
  const [su, sv] = llToU(...route[0]);
  const [eu, ev] = llToU(...route[route.length - 1]);
  el("circle", { cx: su, cy: sv, r: 7, fill: "none", stroke: "#3A342B",
                 "stroke-width": 2 }, gDyn);
  el("circle", { cx: su, cy: sv, r: 2.6, fill: "#D96F47", stroke: "#3A342B" }, gDyn);
  el("path", { d: starPath(eu, ev, 9), fill: "#EFBE3F", stroke: "#3A342B",
               "stroke-width": 1.4 }, gDyn);
  drawLabel("Los Angeles", su, sv, { cls: "lbl bold", size: FS_BOLD, sub: "JUNE 28" });
  drawLabel("Raleigh", eu, ev, { cls: "lbl bold", size: FS_BOLD, sub: "AUGUST 3" });

  refreshLists();
}

function starPath(cx, cy, r) {
  let d = "";
  for (let i = 0; i < 10; i++) {
    const rr = i % 2 ? r * 0.42 : r;
    const a = -Math.PI / 2 + i * Math.PI / 5;
    d += (i ? "L" : "M") + (cx + rr * Math.cos(a)).toFixed(1) + " " +
         (cy + rr * Math.sin(a)).toFixed(1);
  }
  return d + "Z";
}

// Fill a <text> with one or more lines. A "\n" in the string becomes a
// second stacked line (matches the poster, where matplotlib splits on \n).
function fillLines(textEl, text, va, fontSize) {
  const lines = String(text).split("\n");
  textEl.textContent = "";
  if (lines.length === 1) { textEl.textContent = lines[0]; return; }
  const lh = fontSize * 1.05;
  const x = textEl.getAttribute("x");
  const firstDy = va === "top" ? 0
    : va === "bottom" ? -(lines.length - 1) * lh
    : -(lines.length - 1) / 2 * lh;
  lines.forEach((ln, i) => {
    const ts = document.createElementNS(SVG_NS, "tspan");
    ts.setAttribute("x", x);
    ts.setAttribute("dy", i === 0 ? firstDy : lh);
    ts.textContent = ln;
    textEl.appendChild(ts);
  });
}

function drawLabel(name, anchorU, anchorV, opts) {
  const st = layout.label_style[name] || { dx: 9, dy: 0, ha: "left", va: "center" };
  const [lu, lv] = labelPos(anchorU, anchorV, st);
  const t = el("text", {
    x: lu, y: lv, class: opts.cls, "font-size": opts.size,
    "text-anchor": HA2ANCHOR[st.ha || "left"],
    "dominant-baseline": VA2BASE[st.va || "center"],
  }, gDyn);
  fillLines(t, name, st.va || "center", opts.size);
  attachDrag(t, { type: "label", name, stopKey: opts.stopKey });
  markSel(t, { type: "label", name });
  if (opts.sub) {
    const s2 = el("text", {
      x: lu, y: lv + 10.5 * PT2U, class: "sub", "font-size": FS_SUB,
      "text-anchor": HA2ANCHOR[st.ha || "left"],
      "dominant-baseline": VA2BASE[st.va || "center"],
    }, gDyn);
    s2.textContent = opts.sub;
  }
}

function sameSel(a, b) {
  return a && b && a.type === b.type && a.name === b.name &&
         a.idx === b.idx && a.key === b.key;
}
function markSel(node, ref, u, v) {
  if (!sameSel(sel, ref)) return;
  const bb = node.getBBox ? node.getBBox() : null;
  if (bb && bb.width) {
    el("rect", { x: bb.x - 4, y: bb.y - 4, width: bb.width + 8, height: bb.height + 8,
                 rx: 4, class: "sel-ring",
                 transform: node.getAttribute("transform") || "" }, gSel);
  } else if (u !== undefined) {
    el("circle", { cx: u, cy: v, r: 12, class: "sel-ring" }, gSel);
  }
}

// ── Dragging ─────────────────────────────────────────────────────────────
// Listeners go on `window`, not the pressed node: renderDyn() rebuilds the
// dynamic layer during drags (replaceChildren), which destroys the pressed
// element — node-scoped listeners (and its pointer capture) would die with
// it and the drag would stall after the first frame.
function attachDrag(node, ref) {
  node.addEventListener("pointerdown", evt => {
    if (evt.button !== 0) return;
    evt.stopPropagation();
    evt.preventDefault();
    select(ref);
    const pid = evt.pointerId;
    const start = clientToU(evt);
    const snapshot = structuredClone(layout);
    let moved = false;

    const onMove = mv => {
      if (mv.pointerId !== pid) return;
      const cur = clientToU(mv);
      const du = cur[0] - start[0], dv = cur[1] - start[1];
      if (!moved && Math.hypot(du, dv) < 1.5) return;
      moved = true;
      applyDrag(ref, snapshot, du, dv, cur);
      requestRender();
    };
    const onUp = up => {
      if (up.pointerId !== pid) return;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      if (moved) commit(snapshot);
      renderDyn(); renderProps();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  });
}

function applyDrag(ref, snap, du, dv, cur) {
  const r4 = n => Math.round(n * 1e4) / 1e4;
  const r1 = n => Math.round(n * 10) / 10;
  if (ref.type === "label") {
    const old = snap.label_style[ref.name] || { dx: 9, dy: 0, ha: "left", va: "center" };
    layout.label_style[ref.name] = {
      ...old, dx: r1(old.dx + du / PT2U), dy: r1(old.dy - dv / PT2U),
    };
  } else if (ref.type === "park-label") {
    const old = snap.parks[ref.idx];
    layout.parks[ref.idx] = {
      ...old, dx: r1((old.dx || 0) + du / PT2U), dy: r1((old.dy || 0) - dv / PT2U),
    };
  } else if (ref.type === "mtn" || ref.type === "con" || ref.type === "brd") {
    const arrName = { mtn: "mountains", con: "conifers", brd: "broadleaf" }[ref.type];
    const old = snap[arrName][ref.idx];
    const [lon, lat] = uToLL(...cur);
    layout[arrName][ref.idx] = [r4(lon), r4(lat), ...old.slice(2)];
  } else if (ref.type === "park") {
    const [lon, lat] = uToLL(...cur);
    layout.parks[ref.idx] = { ...snap.parks[ref.idx], lon: r4(lon), lat: r4(lat) };
  } else if (ref.type === "wp") {
    const [lon, lat] = uToLL(...cur);
    layout.waypoints[ref.idx] = { ...snap.waypoints[ref.idx], lon: r4(lon), lat: r4(lat) };
  } else if (ref.type === "lake") {
    const [sl, sb] = uToLL(cur[0] - du, cur[1] - dv);
    const [cl, cb] = uToLL(...cur);
    const dLon = cl - sl, dLat = cb - sb;
    layout.lakes[ref.name] = snap.lakes[ref.name].map(
      ([lon, lat]) => [r4(lon + dLon), r4(lat + dLat)]);
  } else if (ref.type === "stop") {
    const [lon, lat] = uToLL(...cur);
    const old = snap.stop_overrides[ref.key];
    const name = (old && old.name) || currentStopName(ref.key);
    layout.stop_overrides[ref.key] = { ...(old || {}), name, lat: r4(lat), lon: r4(lon) };
  }
}

function currentStopName(key) {
  for (const s of effectiveStops()) if (s.key === key) return s.name;
  return key.split("|")[0];
}

let renderQueued = false;
function requestRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderDyn(); });
}

// ── Pan & zoom ───────────────────────────────────────────────────────────
function applyVB() {
  svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
}
svg.addEventListener("wheel", evt => {
  evt.preventDefault();
  const [u, v] = clientToU(evt);
  const f = evt.deltaY > 0 ? 1.15 : 1 / 1.15;
  const nw = Math.min(VBW * 1.4, Math.max(VBW / 25, vb.w * f));
  const scale = nw / vb.w;
  vb = { x: u - (u - vb.x) * scale, y: v - (v - vb.y) * scale,
         w: nw, h: vb.h * scale };
  applyVB();
}, { passive: false });

svg.addEventListener("pointerdown", evt => {
  if (placing) { placeAt(clientToU(evt)); return; }
  select(null);
  const start = { x: evt.clientX, y: evt.clientY, vb: { ...vb } };
  const scale = () => vb.w / svg.getBoundingClientRect().width;
  svg.classList.add("panning");
  try { svg.setPointerCapture(evt.pointerId); } catch (_) { /* synthetic events */ }
  const onMove = mv => {
    vb.x = start.vb.x - (mv.clientX - start.x) * scale();
    vb.y = start.vb.y - (mv.clientY - start.y) * scale();
    applyVB();
  };
  const onUp = () => {
    svg.classList.remove("panning");
    svg.removeEventListener("pointermove", onMove);
    svg.removeEventListener("pointerup", onUp);
  };
  svg.addEventListener("pointermove", onMove);
  svg.addEventListener("pointerup", onUp);
});

// ── Add / delete / hide ──────────────────────────────────────────────────
$("btnAdd").addEventListener("click", () => {
  placing = $("addKind").value;
  svg.classList.add("placing");
  setStatus("click the map to place", "");
});

function placeAt([u, v]) {
  const r4 = n => Math.round(n * 1e4) / 1e4;
  const [lon, lat] = uToLL(u, v).map(r4);
  const snap = structuredClone(layout);
  let newSel = null;
  if (placing === "mountain" || placing === "mountain-big") {
    layout.mountains.push([lon, lat, 0.9, placing === "mountain-big"]);
    newSel = { type: "mtn", idx: layout.mountains.length - 1 };
  } else if (placing === "conifer") {
    layout.conifers.push([lon, lat, 0.9]);
    newSel = { type: "con", idx: layout.conifers.length - 1 };
  } else if (placing === "broadleaf") {
    layout.broadleaf.push([lon, lat, 0.9]);
    newSel = { type: "brd", idx: layout.broadleaf.length - 1 };
  } else if (placing === "park") {
    layout.parks.push({ name: "New Park", lon, lat, kind: "mountain",
                        big: false, dx: 8, dy: 0, ha: "left" });
    newSel = { type: "park", idx: layout.parks.length - 1 };
  } else if (placing === "waypoint") {
    layout.waypoints.push({ name: "New City", lon, lat });
    newSel = { type: "wp", idx: layout.waypoints.length - 1 };
  }
  placing = null;
  svg.classList.remove("placing");
  commit(snap);
  select(newSel);
}

function deleteSelected() {
  if (!sel) return;
  const snap = structuredClone(layout);
  if (sel.type === "mtn") layout.mountains.splice(sel.idx, 1);
  else if (sel.type === "con") layout.conifers.splice(sel.idx, 1);
  else if (sel.type === "brd") layout.broadleaf.splice(sel.idx, 1);
  else if (sel.type === "park" || sel.type === "park-label") layout.parks.splice(sel.idx, 1);
  else if (sel.type === "wp") layout.waypoints.splice(sel.idx, 1);
  else if (sel.type === "lake") delete layout.lakes[sel.name];
  else return;
  commit(snap);
  select(null);
}

function hideStop(key) {
  const snap = structuredClone(layout);
  layout.stop_overrides[key] = null;
  commit(snap);
  select(null);
}
function restoreStop(key) {
  const snap = structuredClone(layout);
  delete layout.stop_overrides[key];
  commit(snap);
}

// ── Selection & side panel ───────────────────────────────────────────────
function select(ref) {
  sel = ref;
  renderDyn();
  renderProps();
}

function listItem(parent, ref, label, kind) {
  const d = document.createElement("div");
  d.className = "item" + (sameSel(sel, ref) ? " selected" : "");
  const a = document.createElement("span");
  a.textContent = displayName(label);
  const b = document.createElement("span");
  b.className = "kind";
  b.textContent = kind;
  d.append(a, b);
  d.addEventListener("click", () => select(ref));
  parent.appendChild(d);
}

function refreshLists() {
  const L = $("list-labels"); L.replaceChildren();
  for (const s of effectiveStops())
    listItem(L, { type: "label", name: s.name, stopKey: s.key }, s.name, "stop");
  listItem(L, { type: "label", name: "Los Angeles" }, "Los Angeles", "start");
  listItem(L, { type: "label", name: "Raleigh" }, "Raleigh", "end");
  layout.waypoints.forEach((w, idx) =>
    listItem(L, { type: "label", name: w.name }, w.name, "city"));

  const P = $("list-parks"); P.replaceChildren();
  layout.parks.forEach((pk, idx) =>
    listItem(P, { type: "park", idx }, pk.name, pk.kind));

  const G = $("list-glyphs"); G.replaceChildren();
  layout.mountains.forEach(([lon, lat, s, big], idx) =>
    listItem(G, { type: "mtn", idx }, `Mountain ${idx + 1}`, big ? "rockies" : "small"));
  layout.conifers.forEach((e, idx) =>
    listItem(G, { type: "con", idx }, `Conifers ${idx + 1}`, "trees"));
  layout.broadleaf.forEach((e, idx) =>
    listItem(G, { type: "brd", idx }, `Broadleaf ${idx + 1}`, "trees"));
  Object.keys(layout.lakes).forEach(name =>
    listItem(G, { type: "lake", name }, name, "lake"));
  layout.waypoints.forEach((w, idx) =>
    listItem(G, { type: "wp", idx }, w.name, "city marker"));

  const H = $("list-hidden"); H.replaceChildren();
  for (const [key, ov] of Object.entries(layout.stop_overrides)) {
    if (ov !== null) continue;
    const d = document.createElement("div");
    d.className = "item";
    d.innerHTML = `<span>${key.split("|")[0]}</span><span class="kind">restore</span>`;
    d.addEventListener("click", () => restoreStop(key));
    H.appendChild(d);
  }
  if (!H.children.length) H.innerHTML = '<div class="kind" style="padding:2px 7px">none</div>';
}

function propRow(parent, label, input) {
  const row = document.createElement("div");
  row.className = "row";
  const l = document.createElement("label");
  l.textContent = label;
  row.append(l, input);
  parent.appendChild(row);
}
function numInput(value, step, onchange) {
  const i = document.createElement("input");
  i.type = "number"; i.step = step; i.value = value;
  i.addEventListener("change", () => onchange(parseFloat(i.value)));
  return i;
}
function selInput(options, value, onchange) {
  const s = document.createElement("select");
  for (const o of options) {
    const op = document.createElement("option");
    op.value = o; op.textContent = o;
    if (o === value) op.selected = true;
    s.appendChild(op);
  }
  s.addEventListener("change", () => onchange(s.value));
  return s;
}
function textInput(value, onchange) {
  const i = document.createElement("input");
  i.type = "text"; i.value = value;
  i.addEventListener("change", () => onchange(i.value));
  return i;
}
// Multi-line name box — Enter inserts a line break (unlike a plain <input>).
function textArea(value, onchange) {
  const t = document.createElement("textarea");
  t.rows = 2; t.value = value;
  t.style.cssText = "flex:1 1 auto; width:60px; min-height:38px; font:inherit;" +
    "font-size:12px; padding:3px 6px; background:#37332a; border:1px solid #57503f;" +
    "border-radius:5px; color:#F5F0E8; resize:vertical;";
  t.addEventListener("change", () => onchange(t.value));
  return t;
}
// Toggle a label between one line and two: joins on "\n", or splits at the
// space nearest the character-count midpoint for the most balanced break.
function splitBalanced(name) {
  if (name.includes("\n")) return name.replace(/\n+/g, " ");
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length < 2) return name;
  let best = 1, bestDiff = Infinity;
  for (let i = 1; i < words.length; i++) {
    const diff = Math.abs(words.slice(0, i).join(" ").length -
                          words.slice(i).join(" ").length);
    if (diff < bestDiff) { bestDiff = diff; best = i; }
  }
  return words.slice(0, best).join(" ") + "\n" + words.slice(best).join(" ");
}
const displayName = n => String(n).replace(/\n/g, " ⏎ ");
// Name editor: textarea + a one/two-line toggle button. `apply(newName)`
// persists the change (and migrates any label_style keyed by the old name).
function nameEditor(box, btnrow, current, apply) {
  propRow(box, "name", textArea(current, apply));
  const toggle = document.createElement("button");
  toggle.textContent = current.includes("\n") ? "One line" : "Two lines";
  toggle.title = "Break the label across two lines (or rejoin)";
  toggle.addEventListener("click", () => apply(splitBalanced(current)));
  btnrow.appendChild(toggle);
}
function migrateLabelStyle(oldName, newName) {
  if (oldName !== newName && layout.label_style[oldName]) {
    layout.label_style[newName] = layout.label_style[oldName];
    delete layout.label_style[oldName];
  }
}
function mutate(fn) {
  const snap = structuredClone(layout);
  fn();
  commit(snap);
  renderDyn(); renderProps();
}

function renderProps() {
  const box = $("props");
  box.replaceChildren();
  if (!sel) { box.innerHTML = '<div class="empty">Nothing selected</div>'; return; }
  const title = document.createElement("div");
  title.style.cssText = "font-weight:500; margin-bottom:2px;";
  box.appendChild(title);

  const btnrow = document.createElement("div");
  btnrow.className = "btnrow";

  if (sel.type === "label") {
    title.textContent = `Label: ${displayName(sel.name)}`;
    const st = layout.label_style[sel.name] || { dx: 9, dy: 0, ha: "left", va: "center" };
    const upd = patch => mutate(() => {
      layout.label_style[sel.name] = { ...st, ...patch };
    });
    propRow(box, "dx (pt)", numInput(st.dx, 0.5, v => upd({ dx: v })));
    propRow(box, "dy (pt)", numInput(st.dy, 0.5, v => upd({ dy: v })));
    propRow(box, "ha", selInput(["left", "center", "right"], st.ha, v => upd({ ha: v })));
    propRow(box, "va", selInput(["center", "top", "bottom"], st.va, v => upd({ va: v })));
    // Stops and waypoints can be renamed / broken to two lines; start & end
    // (Los Angeles / Raleigh) are fixed labels, so only offer it when there's
    // a backing record to write to.
    const wpIdx = layout.waypoints.findIndex(w => w.name === sel.name);
    if (sel.stopKey) {
      nameEditor(box, btnrow, sel.name, v => mutate(() => {
        const ov = layout.stop_overrides[sel.stopKey];
        if (ov) ov.name = v;
        else layout.display_names[sel.stopKey] = v;
        migrateLabelStyle(sel.name, v);
        sel = { ...sel, name: v };
      }));
      const hide = document.createElement("button");
      hide.textContent = "Hide stop"; hide.className = "danger";
      hide.addEventListener("click", () => hideStop(sel.stopKey));
      btnrow.appendChild(hide);
    } else if (wpIdx >= 0) {
      nameEditor(box, btnrow, sel.name, v => mutate(() => {
        layout.waypoints[wpIdx].name = v;
        migrateLabelStyle(sel.name, v);
        sel = { ...sel, name: v };
      }));
    }
  } else if (sel.type === "mtn" || sel.type === "con" || sel.type === "brd") {
    const arrName = { mtn: "mountains", con: "conifers", brd: "broadleaf" }[sel.type];
    const e = layout[arrName][sel.idx];
    title.textContent = { mtn: "Mountain", con: "Conifers", brd: "Broadleaf" }[sel.type] +
                        ` ${sel.idx + 1}`;
    propRow(box, "lon", numInput(e[0], 0.01, v => mutate(() => { e[0] = v; })));
    propRow(box, "lat", numInput(e[1], 0.01, v => mutate(() => { e[1] = v; })));
    propRow(box, "scale", numInput(e[2] ?? 1, 0.05, v => mutate(() => { e[2] = v; })));
    if (sel.type === "mtn") {
      propRow(box, "rockies", selInput(["small", "big"], e[3] ? "big" : "small",
        v => mutate(() => { e[3] = v === "big"; })));
    }
    addDelete(btnrow);
  } else if (sel.type === "park" || sel.type === "park-label") {
    const pk = layout.parks[sel.idx];
    title.textContent = `Park: ${displayName(pk.name)}`;
    nameEditor(box, btnrow, pk.name, v => mutate(() => { pk.name = v; }));
    propRow(box, "kind", selInput(["mountain", "tree", "bridge", "dune"], pk.kind,
      v => mutate(() => { pk.kind = v; })));
    if (pk.kind === "mountain")
      propRow(box, "rockies", selInput(["small", "big"], pk.big ? "big" : "small",
        v => mutate(() => { pk.big = v === "big"; })));
    propRow(box, "dx (pt)", numInput(pk.dx || 0, 0.5, v => mutate(() => { pk.dx = v; })));
    propRow(box, "dy (pt)", numInput(pk.dy || 0, 0.5, v => mutate(() => { pk.dy = v; })));
    propRow(box, "ha", selInput(["left", "center", "right"], pk.ha || "left",
      v => mutate(() => { pk.ha = v; })));
    addDelete(btnrow);
  } else if (sel.type === "wp") {
    const w = layout.waypoints[sel.idx];
    title.textContent = `City: ${displayName(w.name)}`;
    nameEditor(box, btnrow, w.name, v => mutate(() => {
      migrateLabelStyle(w.name, v); w.name = v;
    }));
    addDelete(btnrow);
  } else if (sel.type === "lake") {
    title.textContent = `Lake: ${sel.name}`;
    const p = document.createElement("div");
    p.className = "empty";
    p.textContent = "Drag to move the whole shape.";
    box.appendChild(p);
    addDelete(btnrow);
  } else if (sel.type === "stop") {
    title.textContent = `Stop marker: ${currentStopName(sel.key)}`;
    const ov = layout.stop_overrides[sel.key];
    const p = document.createElement("div");
    p.className = "empty";
    p.textContent = ov && ov.lat !== undefined
      ? `Position override: ${ov.lat}, ${ov.lon}` : "At geocoded GPS position.";
    box.appendChild(p);
    if (ov && ov.lat !== undefined) {
      const reset = document.createElement("button");
      reset.textContent = "Clear position override";
      reset.addEventListener("click", () => mutate(() => {
        const { lat, lon, ...rest } = layout.stop_overrides[sel.key];
        layout.stop_overrides[sel.key] = Object.keys(rest).length ? rest : undefined;
        if (layout.stop_overrides[sel.key] === undefined)
          delete layout.stop_overrides[sel.key];
      }));
      btnrow.appendChild(reset);
    }
  }
  if (btnrow.children.length) box.appendChild(btnrow);

  function addDelete(row) {
    const del = document.createElement("button");
    del.textContent = "Delete"; del.className = "danger";
    del.addEventListener("click", deleteSelected);
    row.appendChild(del);
  }
}

// ── Undo / redo / save ───────────────────────────────────────────────────
function commit(snapshotBefore) {
  undoStack.push(snapshotBefore);
  if (undoStack.length > 100) undoStack.shift();
  redoStack = [];
  setDirty(true);
  updateUndoButtons();
}
function undo() {
  if (!undoStack.length) return;
  redoStack.push(structuredClone(layout));
  layout = undoStack.pop();
  setDirty(true);
  select(sel && null);
  updateUndoButtons();
}
function redo() {
  if (!redoStack.length) return;
  undoStack.push(structuredClone(layout));
  layout = redoStack.pop();
  setDirty(true);
  select(sel && null);
  updateUndoButtons();
}
function updateUndoButtons() {
  $("btnUndo").disabled = !undoStack.length;
  $("btnRedo").disabled = !redoStack.length;
}

function setDirty(d) {
  dirty = d;
  setStatus(d ? "unsaved changes" : "saved", d ? "dirty" : "ok");
}
function setStatus(msg, cls) {
  const s = $("status");
  s.textContent = msg;
  s.className = cls || "";
}

async function save() {
  setStatus("saving…", "");
  try {
    const r = await fetch("/api/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(layout),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    setDirty(false);
  } catch (e) {
    setStatus("save failed: " + e.message, "err");
  }
}

async function renderPoster() {
  if (dirty) await save();
  setStatus("rendering poster (takes ~a minute)…", "");
  $("btnRender").disabled = true;
  try {
    const r = await fetch("/api/render", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: "editor" }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.output || "render failed");
    setStatus("rendered ✓ — open last render to view", "ok");
    $("previewLink").href = "output/print/preview.png?" + Date.now();
  } catch (e) {
    setStatus("render failed: " + String(e.message).slice(0, 120), "err");
  } finally {
    $("btnRender").disabled = false;
  }
}

$("btnUndo").addEventListener("click", undo);
$("btnRedo").addEventListener("click", redo);
$("btnSave").addEventListener("click", save);
$("btnRender").addEventListener("click", renderPoster);
$("chkEditStops").addEventListener("change", renderDyn);
document.addEventListener("keydown", evt => {
  if (evt.target.tagName === "INPUT" || evt.target.tagName === "SELECT") return;
  if (evt.ctrlKey && evt.key === "z") { evt.preventDefault(); undo(); }
  else if (evt.ctrlKey && (evt.key === "y" || (evt.shiftKey && evt.key === "Z"))) {
    evt.preventDefault(); redo();
  } else if (evt.ctrlKey && evt.key === "s") { evt.preventDefault(); save(); }
  else if (evt.key === "Delete" || evt.key === "Backspace") deleteSelected();
  else if (evt.key === "Escape") { placing = null; svg.classList.remove("placing"); select(null); }
});
window.addEventListener("beforeunload", evt => { if (dirty) evt.preventDefault(); });

// ── Boot ─────────────────────────────────────────────────────────────────
(async function boot() {
  try {
    const [l, d, c] = await Promise.all([
      fetch("map_layout.json").then(r => r.json()),
      fetch("output/data.json").then(r => r.json()),
      fetch("assets/editor_context.json").then(r => r.json()),
    ]);
    layout = l; trip = d; ctx = c;
    initProjection(ctx.projection);
    buildStatic();
    renderDyn();
    applyVB();
    updateUndoButtons();
    setStatus("ready", "ok");
  } catch (e) {
    setStatus("load failed: " + e.message + " — serve via `python serve_editor.py`", "err");
  }
})();
