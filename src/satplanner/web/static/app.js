"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, options) {
  const response = await fetch(path, options);
  return response.json();
}

async function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

let toastTimer = null;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 4000);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function table(columns, rows, emptyMessage) {
  if (!rows.length) return `<p class="muted">${escapeHtml(emptyMessage)}</p>`;
  const head = columns.map((c) => `<th class="${c.num ? "num" : ""}">${escapeHtml(c.label)}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns
        .map((c) => {
          const value = c.get(row);
          return `<td class="${c.num ? "num" : ""} ${c.cls ? c.cls(row) : ""}">${value}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function notice(message) {
  return `<div class="notice">${escapeHtml(message)}</div>`;
}

// -- tabs -----------------------------------------------------------------

document.querySelectorAll("#tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    button.classList.add("active");
    $("tab-" + button.dataset.tab).classList.add("active");
    if (button.dataset.tab === "grid") loadGrid();
    if (button.dataset.tab === "setup") loadSetup();
  });
});

// -- overview -------------------------------------------------------------

async function loadReport() {
  const report = await api("/api/report");
  if (!report.ok) {
    $("progress-cards").innerHTML = "";
    $("diff-table").innerHTML = notice(report.error || "Nothing to report yet.");
    $("shopping-table").innerHTML = "";
    $("build-order").innerHTML = "";
    $("unplanned").innerHTML = "";
    return;
  }

  const p = report.progress;
  const pct = p.machines_planned ? Math.round((p.machines_built / p.machines_planned) * 100) : 0;
  $("progress-cards").innerHTML = [
    ["Built", `${p.machines_built} / ${p.machines_planned}`, `${pct}% of the plan`],
    ["Still to build", p.machines_missing, p.complete ? "plan complete" : "machines"],
    ["Power when finished", `${report.power_mw} MW`, "at 100% clock"],
    ["Plan", escapeHtml(report.plan.name), `${report.plan.blocks} blocks`],
  ]
    .map(
      ([label, value, sub]) =>
        `<div class="card"><div class="label">${label}</div><div class="value">${value}</div><div class="muted small">${sub}</div></div>`
    )
    .join("");

  $("diff-table").innerHTML = table(
    [
      { label: "Block", get: (r) => escapeHtml(r.block_id) },
      { label: "Building", get: (r) => escapeHtml(r.building) },
      { label: "Recipe", get: (r) => escapeHtml(r.recipe) },
      { label: "Have", num: true, get: (r) => r.have },
      { label: "Want", num: true, get: (r) => r.want },
      {
        label: "Missing",
        num: true,
        get: (r) => r.missing,
        cls: (r) => (r.missing > 0 ? "bad" : "good"),
      },
    ],
    report.rows.filter((r) => r.missing > 0).concat(report.rows.filter((r) => r.missing === 0)),
    "No plan loaded yet - add one on the Plan tab."
  );

  $("shopping-table").innerHTML = table(
    [
      { label: "Part", get: (r) => escapeHtml(r.item) },
      { label: "Needed", num: true, get: (r) => r.needed },
      { label: "In storage", num: true, get: (r) => r.in_storage },
      {
        label: "Short by",
        num: true,
        get: (r) => r.short_by,
        cls: (r) => (r.short_by > 0 ? "bad" : "good"),
      },
    ],
    report.shopping_list,
    "Nothing left to build."
  );

  $("build-order").innerHTML = report.build_order.length
    ? report.build_order
        .map(
          (s) =>
            `<div class="node"><span class="accent">Stage ${s.stage}</span> &mdash; ${escapeHtml(
              s.blocks.join(", ")
            )}<div class="muted small">${escapeHtml(s.reason)}</div></div>`
        )
        .join("")
    : `<p class="muted">Nothing planned.</p>`;

  $("unplanned").innerHTML = table(
    [
      { label: "Building", get: (r) => escapeHtml(r.building) },
      { label: "Recipe", get: (r) => escapeHtml(r.recipe) },
      { label: "Count", num: true, get: (r) => r.count },
    ],
    report.unplanned,
    "Everything you have built is accounted for in the plan."
  );

  $("sourcing-list").innerHTML = report.sourcing.length
    ? report.sourcing
        .map((entry) => {
          const nodes = entry.nodes.length
            ? table(
                [
                  { label: "Node", get: (n) => escapeHtml(n.node) },
                  { label: "Purity", get: (n) => escapeHtml(n.purity) },
                  { label: "Extractor", get: (n) => escapeHtml(n.extractor) },
                  { label: "Yield /min", num: true, get: (n) => n.rate_per_minute },
                  { label: "Distance", num: true, get: (n) => `${n.distance_m} m` },
                  { label: "World X, Y", get: (n) => `<span class="mono">${n.world_x}, ${n.world_y}</span>` },
                ],
                entry.nodes,
                "No free nodes found."
              )
            : notice(entry.note || "No free nodes of this resource were found.");
          return `<h2>${escapeHtml(entry.resource)} &mdash; ${entry.needed_per_minute}/min needed, ${entry.covered_per_minute}/min covered</h2>${nodes}`;
        })
        .join("")
    : `<p class="muted">This plan needs no raw inputs, or no plan is loaded.</p>`;

  $("save-label").textContent = report.state.save_name
    ? `${report.state.save_name} - ${report.state.machines} machines`
    : "no save loaded";

  if (report.state.warnings && report.state.warnings.length) {
    $("diff-table").insertAdjacentHTML("beforebegin", report.state.warnings.map(notice).join(""));
  }
}

// -- grid -----------------------------------------------------------------

const view = { x: 0, y: 0, scale: 0.02, data: null, dragging: false, lastX: 0, lastY: 0 };

function worldToScreen(wx, wy) {
  return [wx * view.scale + view.x, wy * view.scale + view.y];
}

function screenToWorld(sx, sy) {
  return [(sx - view.x) / view.scale, (sy - view.y) / view.scale];
}

async function loadGrid() {
  const data = await api("/api/grid");
  if (!data.ok) {
    $("grid-anchor").textContent = data.error || "No save loaded.";
    return;
  }
  view.data = data;
  $("grid-anchor").innerHTML =
    `grid origin <span class="mono">${data.anchor.origin_x.toFixed(1)}, ${data.anchor.origin_y.toFixed(1)}</span> ` +
    `&middot; cell ${data.anchor.cell_uu / 100} m &middot; from ${escapeHtml(data.anchor.source)}`;
  recentre();
}

function recentre() {
  const canvas = $("grid-canvas");
  const points = (view.data?.built || []).concat(view.data?.suggested?.map((s) => ({ x: s.world_x, y: s.world_y })) || []);
  if (!points.length) {
    view.x = canvas.clientWidth / 2;
    view.y = canvas.clientHeight / 2;
    drawGrid();
    return;
  }
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const spanX = Math.max(1, Math.max(...xs) - Math.min(...xs));
  const spanY = Math.max(1, Math.max(...ys) - Math.min(...ys));
  view.scale = Math.min(canvas.clientWidth / (spanX * 1.3), canvas.clientHeight / (spanY * 1.3));
  const midX = (Math.max(...xs) + Math.min(...xs)) / 2;
  const midY = (Math.max(...ys) + Math.min(...ys)) / 2;
  view.x = canvas.clientWidth / 2 - midX * view.scale;
  view.y = canvas.clientHeight / 2 - midY * view.scale;
  drawGrid();
}

function drawGrid() {
  const canvas = $("grid-canvas");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
  if (!view.data) return;

  const cell = view.data.anchor.cell_uu;
  const anchor = view.data.anchor;

  // Foundation lattice, drawn only when the cells are big enough to read.
  const cellPx = cell * view.scale;
  if (cellPx > 6) {
    ctx.strokeStyle = "#252a35";
    ctx.lineWidth = 1;
    const [w0x, w0y] = screenToWorld(0, 0);
    const [w1x, w1y] = screenToWorld(canvas.clientWidth, canvas.clientHeight);
    const startX = Math.floor((w0x - anchor.origin_x) / cell) * cell + anchor.origin_x;
    const startY = Math.floor((w0y - anchor.origin_y) / cell) * cell + anchor.origin_y;
    ctx.beginPath();
    for (let wx = startX; wx <= w1x; wx += cell) {
      const [sx] = worldToScreen(wx, 0);
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, canvas.clientHeight);
    }
    for (let wy = startY; wy <= w1y; wy += cell) {
      const [, sy] = worldToScreen(0, wy);
      ctx.moveTo(0, sy);
      ctx.lineTo(canvas.clientWidth, sy);
    }
    ctx.stroke();
  }

  if ($("show-foundations").checked) {
    ctx.fillStyle = "rgba(120,132,156,0.28)";
    for (const f of view.data.foundations) {
      const [sx, sy] = worldToScreen(f.x, f.y);
      const size = Math.max(2, cellPx * 0.9);
      ctx.fillRect(sx - size / 2, sy - size / 2, size, size);
    }
  }

  const dot = Math.max(3, Math.min(14, cellPx * 0.55));
  ctx.fillStyle = "#63c98a";
  for (const m of view.data.built) {
    const [sx, sy] = worldToScreen(m.x, m.y);
    ctx.fillRect(sx - dot / 2, sy - dot / 2, dot, dot);
  }

  ctx.strokeStyle = "#f2a23c";
  ctx.lineWidth = 2;
  for (const s of view.data.suggested) {
    const [sx, sy] = worldToScreen(s.world_x, s.world_y);
    ctx.strokeRect(sx - dot / 2, sy - dot / 2, dot, dot);
  }
}

function setupGridInteraction() {
  const canvas = $("grid-canvas");

  canvas.addEventListener("mousedown", (e) => {
    view.dragging = true;
    view.lastX = e.offsetX;
    view.lastY = e.offsetY;
  });
  window.addEventListener("mouseup", () => (view.dragging = false));

  canvas.addEventListener("mousemove", (e) => {
    if (view.dragging) {
      view.x += e.offsetX - view.lastX;
      view.y += e.offsetY - view.lastY;
      view.lastX = e.offsetX;
      view.lastY = e.offsetY;
      drawGrid();
    }
    if (!view.data) return;
    const [wx, wy] = screenToWorld(e.offsetX, e.offsetY);
    const anchor = view.data.anchor;
    const cx = Math.floor((wx - anchor.origin_x) / anchor.cell_uu + 0.5);
    const cy = Math.floor((wy - anchor.origin_y) / anchor.cell_uu + 0.5);
    const near = nearestItem(wx, wy);
    $("grid-readout").textContent =
      `world ${wx.toFixed(0)}, ${wy.toFixed(0)}  |  cell ${cx}, ${cy}` + (near ? `  |  ${near}` : "");
  });

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const [wx, wy] = screenToWorld(e.offsetX, e.offsetY);
    view.scale *= factor;
    view.x = e.offsetX - wx * view.scale;
    view.y = e.offsetY - wy * view.scale;
    drawGrid();
  }, { passive: false });

  $("show-foundations").addEventListener("change", drawGrid);
  $("grid-reset").addEventListener("click", recentre);
  window.addEventListener("resize", drawGrid);
}

function nearestItem(wx, wy) {
  if (!view.data) return "";
  const threshold = view.data.anchor.cell_uu;
  let best = null;
  let bestDist = threshold * threshold;
  for (const m of view.data.built) {
    const d = (m.x - wx) ** 2 + (m.y - wy) ** 2;
    if (d < bestDist) {
      bestDist = d;
      best = `${m.building}: ${m.recipe}`;
    }
  }
  for (const s of view.data.suggested) {
    const d = (s.world_x - wx) ** 2 + (s.world_y - wy) ** 2;
    if (d < bestDist) {
      bestDist = d;
      best = `build here: ${s.building} (${s.recipe})`;
    }
  }
  return best || "";
}

// -- plan -----------------------------------------------------------------

async function loadPlan() {
  const data = await api("/api/plan");
  $("plan-json").value = JSON.stringify(data.plan, null, 2);
}

$("plan-save").addEventListener("click", async () => {
  let parsed;
  try {
    parsed = JSON.parse($("plan-json").value);
  } catch (err) {
    $("plan-status").textContent = "That is not valid JSON.";
    return;
  }
  const result = await post("/api/plan", { plan: parsed });
  $("plan-status").textContent = result.ok ? "Saved." : result.error;
  if (result.ok) loadReport();
});

// -- setup ----------------------------------------------------------------

async function loadSetup() {
  const status = await api("/api/status");
  $("status-block").innerHTML = table(
    [
      { label: "Setting", get: (r) => escapeHtml(r[0]) },
      { label: "Value", get: (r) => `<span class="mono">${escapeHtml(r[1])}</span>` },
    ],
    [
      ["Save folder", status.settings.save_dir || "not found"],
      ["Game docs (recipes)", status.settings.docs_json || "not found"],
      ["Recipes loaded", status.recipes],
      ["Resource nodes known", status.node_data],
      ["Modeler folder", status.settings.modeler_dir || "not found"],
      ["Selected save", status.selected_save || "none"],
      ["Last error", status.last_error || "none"],
    ],
    ""
  );

  const saves = await api("/api/saves");
  $("save-list").innerHTML = table(
    [
      { label: "Save", get: (s) => escapeHtml(s.name) },
      { label: "Modified", get: (s) => escapeHtml(s.modified_iso) },
      { label: "Size", num: true, get: (s) => `${s.size_mb} MB` },
      { label: "", get: (s) => `<button data-save="${escapeHtml(s.path)}">Use</button>` },
    ],
    saves.saves || [],
    "No save files found. Check the save folder on this tab."
  );

  $("save-list").querySelectorAll("button[data-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const result = await post("/api/select-save", { path: button.dataset.save });
      toast(result.ok ? "Save loaded." : result.error);
      loadReport();
    });
  });

  if (status.settings.modeler_dir && !$("modeler-dir").value) {
    $("modeler-dir").value = status.settings.modeler_dir;
  }
}

$("modeler-scan").addEventListener("click", async () => {
  const dir = $("modeler-dir").value.trim();
  const result = await api("/api/modeler/scan" + (dir ? `?dir=${encodeURIComponent(dir)}` : ""));
  if (!result.ok) {
    $("modeler-results").innerHTML = notice(result.error);
    return;
  }
  $("modeler-results").innerHTML =
    `<p class="muted small">Scanned ${escapeHtml(result.directory)}</p>` +
    table(
      [
        { label: "File", get: (f) => `<span class="mono">${escapeHtml(f.path)}</span>` },
        { label: "Kind", get: (f) => escapeHtml(f.kind), cls: (f) => (f.importable ? "good" : "muted") },
        { label: "Detail", get: (f) => escapeHtml(f.detail) },
        { label: "Size", num: true, get: (f) => `${f.size_kb} kB` },
        {
          label: "",
          get: (f) => (f.importable ? `<button data-import="${escapeHtml(f.path)}">Import</button>` : ""),
        },
      ],
      result.files,
      "Nothing in that folder looks like a project file."
    );

  $("modeler-results").querySelectorAll("button[data-import]").forEach((button) => {
    button.addEventListener("click", async () => {
      const outcome = await post("/api/modeler/import", { path: button.dataset.import });
      toast(outcome.ok ? "Plan imported." : outcome.error);
      if (outcome.ok) {
        loadPlan();
        loadReport();
      }
    });
  });
});

// -- boot -----------------------------------------------------------------

$("refresh").addEventListener("click", async () => {
  const result = await post("/api/refresh", { force: true });
  toast(result.ok ? "Save re-read." : result.error);
  loadReport();
  if ($("tab-grid").classList.contains("active")) loadGrid();
});

setupGridInteraction();
loadReport();
loadPlan();

// The save file only changes when the game autosaves, so a slow poll is plenty.
setInterval(loadReport, 60000);
