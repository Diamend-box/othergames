"use strict";

/* The world map.
 *
 * One continuous view: zoomed out it is the whole 7 km world with every
 * resource node on it, zoomed in it is your base on its foundation lattice.
 *
 * Colour carries one meaning only - what the planner thinks of a thing:
 *   blue     you have built it
 *   orange   the plan says do this here
 *   grey/dim you already mine it
 * A node with no marking at all is free. Most of the world is free, so
 * leaving it unmarked is what keeps the few actionable things visible.
 * The resource itself is carried by the glyph and the legend, never by hue
 * alone, because fourteen resources is far more than hue can separate.
 *
 * Terrain is not modelled. The backdrop shades resource density and marks
 * real water sources; it is not a height map and must not be read as one.
 */

(function () {
  const TAU = Math.PI * 2;

  // -- what the planner thinks of a thing ---------------------------------
  const INK = {
    built: "#3987e5",
    action: "#d95926",
    free: "#199e70",
    idle: "#898781",
    text: "#e6e8ec",
    dim: "#949aa6",
    surface: "#0f1116",
    grid: "rgba(255,255,255,0.055)",
    gridStrong: "rgba(255,255,255,0.10)",
  };

  // Glyph carries identity. The tint is decorative - a nod to what the
  // material looks like in game - and nothing depends on telling two apart.
  const RESOURCES = {
    Desc_OreIron_C: { glyph: "Fe", tint: "#c8ccd4", name: "Iron Ore" },
    Desc_OreCopper_C: { glyph: "Cu", tint: "#c9764a", name: "Copper Ore" },
    Desc_Stone_C: { glyph: "Ls", tint: "#d8d2bd", name: "Limestone" },
    Desc_Coal_C: { glyph: "C", tint: "#727785", name: "Coal" },
    Desc_OreGold_C: { glyph: "Ct", tint: "#e8b53f", name: "Caterium Ore" },
    Desc_RawQuartz_C: { glyph: "Qz", tint: "#e3a9d8", name: "Raw Quartz" },
    Desc_Sulfur_C: { glyph: "S", tint: "#e0d24a", name: "Sulfur" },
    Desc_OreBauxite_C: { glyph: "Bx", tint: "#c0785f", name: "Bauxite" },
    Desc_OreUranium_C: { glyph: "U", tint: "#7cc95a", name: "Uranium" },
    Desc_SAM_C: { glyph: "Sm", tint: "#9a6fd8", name: "SAM" },
    Desc_LiquidOil_C: { glyph: "Ol", tint: "#5c5c6b", name: "Crude Oil" },
    Desc_Water_C: { glyph: "W", tint: "#4f9ad8", name: "Water" },
    Desc_NitrogenGas_C: { glyph: "N", tint: "#6fc9c2", name: "Nitrogen Gas" },
    Desc_Geyser_C: { glyph: "Gy", tint: "#a8d8cf", name: "Geyser" },
  };
  const UNKNOWN_RESOURCE = { glyph: "?", tint: "#8b909c", name: "Unknown" };

  const PURITY_SCALE = { Impure: 0.78, Normal: 1.0, Pure: 1.28 };

  const BUILDING_GLYPHS = [
    ["Smelter", "Sm"], ["Foundry", "Fo"], ["Constructor", "Co"], ["Assembler", "As"],
    ["Manufacturer", "Mf"], ["Refinery", "Rf"], ["Blender", "Bl"], ["Packager", "Pk"],
    ["HadronCollider", "Pa"], ["QuantumEncoder", "Qe"], ["Converter", "Cv"],
    ["WaterPump", "Wp"], ["OilPump", "Op"], ["FrackingExtractor", "Fr"], ["MinerMk", "Mi"],
  ];

  function glyphForBuilding(buildingClass) {
    for (const [hint, glyph] of BUILDING_GLYPHS) {
      if ((buildingClass || "").includes(hint)) return glyph;
    }
    return "B";
  }

  function resourceInfo(resourceClass) {
    return RESOURCES[resourceClass] || UNKNOWN_RESOURCE;
  }

  // -- view ----------------------------------------------------------------
  const view = {
    data: null,
    scale: 0.0016,
    ox: 0,
    oy: 0,
    hidden: new Set(),
    showFoundations: true,
    showLinks: true,
    showTapped: true,
    backdrop: null,
    hover: null,
    dragging: false,
    moved: false,
    lastX: 0,
    lastY: 0,
  };

  // Zoom bands. `scale` is screen pixels per Unreal unit.
  const WORLD_ZOOM = 0.0042;   // below this, the whole world is in view
  const BASE_ZOOM = 0.010;     // above this, you are looking at your factory
  const BACKDROP_GONE = 0.0068; // the backdrop has faded out by here

  const canvas = () => document.getElementById("map-canvas");

  function worldToScreen(wx, wy) {
    return [wx * view.scale + view.ox, wy * view.scale + view.oy];
  }

  function screenToWorld(sx, sy) {
    return [(sx - view.ox) / view.scale, (sy - view.oy) / view.scale];
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  // -- backdrop ------------------------------------------------------------
  // Drawn once into an offscreen canvas in world space, then blitted under
  // the view transform. It fades out as you zoom in, where it would only be
  // a blurry upscale of something that means nothing at factory scale.
  function buildBackdrop(data) {
    const W = 1100;
    const H = 1000;
    const pad = 45000;
    const bounds = {
      minX: data.world.min_x - pad,
      maxX: data.world.max_x + pad,
      minY: data.world.min_y - pad,
      maxY: data.world.max_y + pad,
    };
    const off = document.createElement("canvas");
    off.width = W;
    off.height = H;
    const c = off.getContext("2d");
    const kx = W / (bounds.maxX - bounds.minX);
    const ky = H / (bounds.maxY - bounds.minY);
    const px = (wx) => (wx - bounds.minX) * kx;
    const py = (wy) => (wy - bounds.minY) * ky;

    // The same colour the canvas itself is cleared to, so the edge of this
    // image never shows up as a rectangle on the page.
    c.fillStyle = INK.surface;
    c.fillRect(0, 0, W, H);

    const blob = (x, y, radius, inner) => {
      const g = c.createRadialGradient(x, y, 0, x, y, radius);
      g.addColorStop(0, inner);
      g.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = g;
      c.beginPath();
      c.arc(x, y, radius, 0, TAU);
      c.fill();
    };

    c.globalCompositeOperation = "lighter";

    // Where resources cluster - this is real node data, softened. Kept very
    // faint: it is texture, not information anyone should measure.
    for (const node of data.nodes) {
      blob(px(node.x), py(node.y), 62000 * kx, "rgba(30,36,48,0.20)");
    }
    // Real water sources, so the wet parts of the world read as wet. Drawn
    // normally rather than additively: overlapping sources should deepen the
    // colour, not stack up into a white smear.
    c.globalCompositeOperation = "source-over";
    for (const node of data.nodes) {
      if (node.resource_class !== "Desc_Water_C" && node.resource_class !== "Desc_Geyser_C") continue;
      blob(px(node.x), py(node.y), 30000 * kx, "rgba(26,62,98,0.30)");
    }

    // A soft edge so the world does not end in a hard rectangle.
    const vignette = c.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.34, W / 2, H / 2, Math.max(W, H) * 0.70);
    vignette.addColorStop(0, "rgba(15,17,22,0)");
    vignette.addColorStop(1, "rgba(15,17,22,1)");
    c.fillStyle = vignette;
    c.fillRect(0, 0, W, H);

    return { canvas: off, bounds };
  }

  // -- framing -------------------------------------------------------------
  function fitTo(minX, minY, maxX, maxY, padding) {
    const el = canvas();
    const pad = padding || 1.25;
    const spanX = Math.max(1, maxX - minX);
    const spanY = Math.max(1, maxY - minY);
    view.scale = Math.min(el.clientWidth / (spanX * pad), el.clientHeight / (spanY * pad));
    const midX = (maxX + minX) / 2;
    const midY = (maxY + minY) / 2;
    view.ox = el.clientWidth / 2 - midX * view.scale;
    view.oy = el.clientHeight / 2 - midY * view.scale;
    draw();
  }

  function fitWorld() {
    if (!view.data) return;
    const w = view.data.world;
    fitTo(w.min_x, w.min_y, w.max_x, w.max_y, 1.06);
  }

  function fitBase() {
    if (!view.data) return;
    const b = view.data.base;
    const machines = view.data.built;
    if (!b) {
      fitWorld();
      return;
    }
    if (machines.length < 8) {
      fitTo(b.min_x, b.min_y, b.max_x, b.max_y, 1.35);
      return;
    }
    // A handful of outlying machines should not force the whole factory into
    // a few pixels, so frame the middle of the spread and let the stragglers
    // fall outside. The minimap and "Whole world" cover the rest.
    const at = (values, q) => {
      const sorted = [...values].sort((a, b) => a - b);
      return sorted[Math.max(0, Math.min(sorted.length - 1, Math.round((sorted.length - 1) * q)))];
    };
    const xs = machines.map((m) => m.x);
    const ys = machines.map((m) => m.y);
    const minX = at(xs, 0.08);
    const maxX = at(xs, 0.92);
    const minY = at(ys, 0.08);
    const maxY = at(ys, 0.92);
    if (maxX - minX < 400 || maxY - minY < 400) {
      fitTo(b.min_x, b.min_y, b.max_x, b.max_y, 1.35);
      return;
    }
    fitTo(minX, minY, maxX, maxY, 1.3);
  }

  // -- drawing -------------------------------------------------------------
  function draw() {
    const el = canvas();
    if (!el) return;
    const dpr = window.devicePixelRatio || 1;
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
      el.width = Math.round(w * dpr);
      el.height = Math.round(h * dpr);
    }
    const ctx = el.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = INK.surface;
    ctx.fillRect(0, 0, w, h);
    if (!view.data) return;

    drawBackdrop(ctx, w, h);
    drawGraticule(ctx, w, h);
    drawLattice(ctx, w, h);
    drawFoundations(ctx);
    drawLinks(ctx);
    drawNodes(ctx);
    drawBaseHalo(ctx);
    drawMachines(ctx);
    drawSuggestions(ctx);
    drawHover(ctx);
    drawScaleBar(ctx, w, h);
    drawMinimap(ctx, w, h);
  }

  function backdropAlpha() {
    // Full strength across the world view, gone by the time the lattice shows.
    if (view.scale <= WORLD_ZOOM) return 1;
    if (view.scale >= BACKDROP_GONE) return 0;
    return 1 - (view.scale - WORLD_ZOOM) / (BACKDROP_GONE - WORLD_ZOOM);
  }

  function drawBackdrop(ctx, w, h) {
    const alpha = backdropAlpha();
    if (alpha <= 0.01 || !view.backdrop) return;
    const b = view.backdrop.bounds;
    const [x0, y0] = worldToScreen(b.minX, b.minY);
    const width = (b.maxX - b.minX) * view.scale;
    const height = (b.maxY - b.minY) * view.scale;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(view.backdrop.canvas, x0, y0, width, height);
    ctx.restore();
  }

  // A 1 km graticule at world scale, stepping down as you zoom in.
  function drawGraticule(ctx, w, h) {
    const metresPerPixel = 1 / (view.scale * 100);
    let stepM = 1000;
    while (stepM / metresPerPixel > 220) stepM /= 2;
    while (stepM / metresPerPixel < 70) stepM *= 2;
    const step = stepM * 100;

    const [wx0, wy0] = screenToWorld(0, 0);
    const [wx1, wy1] = screenToWorld(w, h);
    ctx.save();
    ctx.lineWidth = 1;
    ctx.strokeStyle = INK.grid;
    ctx.beginPath();
    for (let x = Math.floor(wx0 / step) * step; x <= wx1; x += step) {
      const [sx] = worldToScreen(x, 0);
      ctx.moveTo(Math.round(sx) + 0.5, 0);
      ctx.lineTo(Math.round(sx) + 0.5, h);
    }
    for (let y = Math.floor(wy0 / step) * step; y <= wy1; y += step) {
      const [, sy] = worldToScreen(0, y);
      ctx.moveTo(0, Math.round(sy) + 0.5);
      ctx.lineTo(w, Math.round(sy) + 0.5);
    }
    ctx.stroke();

    // The world origin, which is where the grid falls back to without foundations.
    const [ox, oy] = worldToScreen(0, 0);
    if (ox > -50 && ox < w + 50 && oy > -50 && oy < h + 50) {
      ctx.strokeStyle = INK.gridStrong;
      ctx.beginPath();
      ctx.moveTo(ox - 9, oy);
      ctx.lineTo(ox + 9, oy);
      ctx.moveTo(ox, oy - 9);
      ctx.lineTo(ox, oy + 9);
      ctx.stroke();
    }
    ctx.restore();
  }

  // The in-game foundation lattice, only once cells are big enough to mean something.
  function drawLattice(ctx, w, h) {
    if (!view.data.anchor) return;
    const cell = view.data.anchor.cell_uu;
    const cellPx = cell * view.scale;
    if (cellPx < 9) return;
    const anchor = view.data.anchor;
    const alpha = Math.min(1, (cellPx - 9) / 12);
    const [wx0, wy0] = screenToWorld(0, 0);
    const [wx1, wy1] = screenToWorld(w, h);
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = "rgba(122,150,196,0.20)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    const startX = Math.floor((wx0 - anchor.origin_x) / cell) * cell + anchor.origin_x;
    const startY = Math.floor((wy0 - anchor.origin_y) / cell) * cell + anchor.origin_y;
    for (let x = startX; x <= wx1; x += cell) {
      const [sx] = worldToScreen(x, 0);
      ctx.moveTo(Math.round(sx) + 0.5, 0);
      ctx.lineTo(Math.round(sx) + 0.5, h);
    }
    for (let y = startY; y <= wy1; y += cell) {
      const [, sy] = worldToScreen(0, y);
      ctx.moveTo(0, Math.round(sy) + 0.5);
      ctx.lineTo(w, Math.round(sy) + 0.5);
    }
    ctx.stroke();
    ctx.restore();
  }

  function drawFoundations(ctx) {
    if (!view.showFoundations) return;
    const cellPx = view.data.anchor.cell_uu * view.scale;
    if (cellPx < 3) return;
    ctx.save();
    ctx.fillStyle = "rgba(108,124,152,0.26)";
    const size = Math.max(2, cellPx * 0.92);
    for (const f of view.data.foundations) {
      const [sx, sy] = worldToScreen(f.x, f.y);
      ctx.fillRect(sx - size / 2, sy - size / 2, size, size);
    }
    ctx.restore();
  }

  // Each extractor tied back to the node it sits on.
  function drawLinks(ctx) {
    if (!view.showLinks) return;
    ctx.save();
    ctx.strokeStyle = "rgba(57,135,229,0.30)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const miner of view.data.miners) {
      if (miner.node_x === null || miner.node_y === null) continue;
      const dx = miner.node_x - miner.x;
      const dy = miner.node_y - miner.y;
      if (dx * dx + dy * dy < 4) continue; // sitting right on it
      const [ax, ay] = worldToScreen(miner.x, miner.y);
      const [bx, by] = worldToScreen(miner.node_x, miner.node_y);
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
    }
    ctx.stroke();
    ctx.restore();
  }

  function statusInk(status) {
    if (status === "wanted") return INK.action;
    if (status === "tapped") return INK.idle;
    return null; // free needs no ring - see the note at the top
  }

  function visibleNodes() {
    if (!view.data) return [];
    return view.data.nodes.filter((n) => {
      if (view.hidden.has(n.resource_class)) return false;
      if (!view.showTapped && n.status === "tapped") return false;
      return true;
    });
  }

  function nodeRadius(node) {
    const purity = PURITY_SCALE[node.purity] || 1;
    const base = view.scale < WORLD_ZOOM ? 4.2 : Math.min(15, 4.2 + (view.scale - WORLD_ZOOM) * 900);
    return base * purity;
  }

  function drawNodes(ctx) {
    const showGlyph = view.scale > WORLD_ZOOM * 1.15;
    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const node of visibleNodes()) {
      const [sx, sy] = worldToScreen(node.x, node.y);
      const r = nodeRadius(node);
      if (sx < -30 || sy < -30 || sx > ctx.canvas.clientWidth + 30 || sy > ctx.canvas.clientHeight + 30) continue;
      const info = resourceInfo(node.resource_class);
      const ink = statusInk(node.status);

      // A wanted node gets a halo so it is findable at a glance.
      if (node.status === "wanted") {
        ctx.beginPath();
        ctx.arc(sx, sy, r + 6, 0, TAU);
        ctx.fillStyle = "rgba(217,89,38,0.20)";
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, TAU);
      ctx.fillStyle = info.tint;
      ctx.globalAlpha = node.status === "tapped" ? 0.38 : 0.95;
      ctx.fill();
      ctx.globalAlpha = 1;

      // A 2px ring in the surface colour keeps overlapping markers apart.
      ctx.lineWidth = 2;
      ctx.strokeStyle = INK.surface;
      ctx.stroke();
      if (ink) {
        ctx.beginPath();
        ctx.arc(sx, sy, r + 1.7, 0, TAU);
        ctx.lineWidth = node.status === "wanted" ? 2.4 : 1.4;
        ctx.strokeStyle = ink;
        ctx.stroke();
      }

      if (showGlyph && r >= 6.5) {
        ctx.fillStyle = "#10131a";
        ctx.font = `600 ${Math.round(r * 1.05)}px system-ui, "Segoe UI", sans-serif`;
        ctx.fillText(info.glyph, sx, sy + 0.5);
      }
    }
    ctx.restore();
  }

  // Zoomed out, the factory is a few pixels across - say where it is.
  function drawBaseHalo(ctx) {
    const base = view.data.base;
    if (!base || view.scale > BASE_ZOOM * 0.55) return;
    const [sx, sy] = worldToScreen(base.x, base.y);
    const spanPx = Math.max(
      (base.max_x - base.min_x) * view.scale,
      (base.max_y - base.min_y) * view.scale
    );
    const r = Math.max(16, spanPx / 2 + 8);
    ctx.save();
    ctx.beginPath();
    ctx.arc(sx, sy, r, 0, TAU);
    ctx.fillStyle = "rgba(57,135,229,0.12)";
    ctx.fill();
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1.6;
    ctx.strokeStyle = INK.built;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = INK.text;
    ctx.font = '600 12px system-ui, "Segoe UI", sans-serif';
    ctx.textAlign = "center";
    ctx.fillText("your factory", sx, sy - r - 8);
    ctx.restore();
  }

  function machineSize() {
    const cellPx = view.data.anchor.cell_uu * view.scale;
    return Math.max(view.scale < WORLD_ZOOM ? 3.5 : 6, Math.min(26, cellPx * 0.86));
  }

  function roundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  function drawMachines(ctx) {
    const size = machineSize();
    const showGlyph = size >= 11;
    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (const miner of view.data.miners) {
      const [sx, sy] = worldToScreen(miner.x, miner.y);
      const r = size * 0.62;
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, TAU);
      ctx.fillStyle = INK.built;
      ctx.fill();
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = INK.surface;
      ctx.stroke();
      if (showGlyph) {
        ctx.fillStyle = "#08111d";
        ctx.font = `600 ${Math.round(r)}px system-ui, "Segoe UI", sans-serif`;
        ctx.fillText(glyphForBuilding(miner.building_class), sx, sy + 0.5);
      }
    }

    for (const machine of view.data.built) {
      const [sx, sy] = worldToScreen(machine.x, machine.y);
      roundRect(ctx, sx - size / 2, sy - size / 2, size, size, size * 0.28);
      ctx.fillStyle = INK.built;
      ctx.fill();
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = INK.surface;
      ctx.stroke();
      if (showGlyph) {
        ctx.fillStyle = "#08111d";
        ctx.font = `600 ${Math.round(size * 0.44)}px system-ui, "Segoe UI", sans-serif`;
        ctx.fillText(glyphForBuilding(machine.building_class), sx, sy + 0.5);
      }
    }
    ctx.restore();
  }

  function drawSuggestions(ctx) {
    const size = machineSize();
    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.setLineDash([4, 3]);
    for (const s of view.data.suggested) {
      const [sx, sy] = worldToScreen(s.world_x, s.world_y);
      roundRect(ctx, sx - size / 2, sy - size / 2, size, size, size * 0.28);
      ctx.fillStyle = "rgba(217,89,38,0.16)";
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = INK.action;
      ctx.stroke();
      if (size >= 13) {
        ctx.fillStyle = INK.action;
        ctx.font = `600 ${Math.round(size * 0.44)}px system-ui, "Segoe UI", sans-serif`;
        ctx.setLineDash([]);
        ctx.fillText("+", sx, sy + 0.5);
        ctx.setLineDash([4, 3]);
      }
    }
    ctx.restore();
  }

  function drawHover(ctx) {
    if (!view.hover) return;
    const [sx, sy] = worldToScreen(view.hover.x, view.hover.y);
    ctx.save();
    ctx.beginPath();
    ctx.arc(sx, sy, view.hover.radius + 6, 0, TAU);
    ctx.lineWidth = 2;
    ctx.strokeStyle = INK.text;
    ctx.stroke();
    ctx.restore();
  }

  function drawScaleBar(ctx, w, h) {
    const metresPerPixel = 1 / (view.scale * 100);
    let metres = 1000;
    while (metres / metresPerPixel > 170) metres /= 2;
    while (metres / metresPerPixel < 55) metres *= 2;
    const px = metres / metresPerPixel;
    const x = 16;
    const y = h - 20;
    ctx.save();
    ctx.strokeStyle = INK.dim;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x, y - 5);
    ctx.lineTo(x, y);
    ctx.lineTo(x + px, y);
    ctx.lineTo(x + px, y - 5);
    ctx.stroke();
    ctx.fillStyle = INK.dim;
    ctx.font = '12px system-ui, "Segoe UI", sans-serif';
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText(metres >= 1000 ? `${metres / 1000} km` : `${metres} m`, x, y - 7);
    ctx.restore();
  }

  // A world thumbnail with the current viewport on it, so you always know
  // where in the world a 600 m factory actually sits.
  function drawMinimap(ctx, w, h) {
    if (!view.backdrop || view.scale < WORLD_ZOOM) return;
    const b = view.backdrop.bounds;
    const mw = 132;
    const mh = Math.round((mw * (b.maxY - b.minY)) / (b.maxX - b.minX));
    const x = w - mw - 14;
    const y = h - mh - 14;
    ctx.save();
    ctx.globalAlpha = 0.9;
    ctx.drawImage(view.backdrop.canvas, x, y, mw, mh);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = "rgba(255,255,255,0.22)";
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, y + 0.5, mw, mh);

    const toMiniX = (wx) => x + ((wx - b.minX) / (b.maxX - b.minX)) * mw;
    const toMiniY = (wy) => y + ((wy - b.minY) / (b.maxY - b.minY)) * mh;

    const [vx0, vy0] = screenToWorld(0, 0);
    const [vx1, vy1] = screenToWorld(w, h);
    const rx = toMiniX(vx0);
    const ry = toMiniY(vy0);
    const rw = Math.max(3, toMiniX(vx1) - rx);
    const rh = Math.max(3, toMiniY(vy1) - ry);
    ctx.strokeStyle = INK.text;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(rx, ry, rw, rh);
    ctx.restore();
  }

  // -- hit testing ---------------------------------------------------------
  function pick(wx, wy) {
    const tolerance = 14 / view.scale;
    let best = null;
    let bestDist = tolerance * tolerance;

    const consider = (x, y, radius, payload) => {
      const d = (x - wx) ** 2 + (y - wy) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = { x, y, radius, ...payload };
      }
    };

    for (const s of view.data.suggested) {
      consider(s.world_x, s.world_y, machineSize() / 2, {
        kind: "suggested",
        title: `Build here: ${s.building}`,
        lines: [s.recipe, `cell ${s.cell[0]}, ${s.cell[1]}`],
      });
    }
    for (const m of view.data.built) {
      consider(m.x, m.y, machineSize() / 2, {
        kind: "built",
        title: m.building,
        lines: [m.recipe, `clock ${Math.round(m.clock * 100)}%`, `cell ${m.cell[0]}, ${m.cell[1]}`],
      });
    }
    for (const m of view.data.miners) {
      consider(m.x, m.y, machineSize() * 0.62, {
        kind: "miner",
        title: m.building,
        lines: [m.resource || "extractor", `clock ${Math.round(m.clock * 100)}%`],
      });
    }
    for (const n of visibleNodes()) {
      const label =
        n.status === "tapped" ? "already mined" : n.status === "wanted" ? "your plan needs this" : "free";
      consider(n.x, n.y, nodeRadius(n), {
        kind: "node",
        title: `${n.resource} (${n.purity})`,
        lines: [label, n.id],
      });
    }
    return best;
  }

  // -- chrome --------------------------------------------------------------
  function renderLegend() {
    const el = document.getElementById("map-legend");
    if (!el) return;
    const swatch = (color, shape) =>
      `<span class="swatch ${shape || ""}" style="--swatch:${color}"></span>`;
    el.innerHTML =
      `<span class="legend-item">${swatch(INK.built)}you built it</span>` +
      `<span class="legend-item">${swatch(INK.action)}the plan says build here</span>` +
      `<span class="legend-item">${swatch("#c8ccd4", "round")}free node, in its own colour</span>` +
      `<span class="legend-item">${swatch(INK.idle, "round")}node you already mine</span>` +
      `<span class="legend-item legend-purity">` +
      `<span class="dot s"></span><span class="dot m"></span><span class="dot l"></span>` +
      `impure / normal / pure</span>`;
  }

  function renderLayers() {
    const el = document.getElementById("map-layers");
    if (!el || !view.data) return;
    const counts = new Map();
    for (const node of view.data.nodes) {
      counts.set(node.resource_class, (counts.get(node.resource_class) || 0) + 1);
    }
    const rows = [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([cls, count]) => {
        const info = resourceInfo(cls);
        const off = view.hidden.has(cls) ? " off" : "";
        return (
          `<button class="layer${off}" data-resource="${esc(cls)}" title="${esc(info.name)}">` +
          `<span class="layer-glyph" style="--tint:${info.tint}">${esc(info.glyph)}</span>` +
          `<span class="layer-name">${esc(info.name)}</span>` +
          `<span class="layer-count">${count}</span></button>`
        );
      })
      .join("");
    el.innerHTML = rows;
    el.querySelectorAll("button[data-resource]").forEach((button) => {
      button.addEventListener("click", () => {
        const cls = button.dataset.resource;
        if (view.hidden.has(cls)) view.hidden.delete(cls);
        else view.hidden.add(cls);
        button.classList.toggle("off", view.hidden.has(cls));
        draw();
      });
    });
  }

  function showTip(event, hit) {
    const tip = document.getElementById("map-tip");
    if (!tip) return;
    if (!hit) {
      tip.classList.remove("show");
      return;
    }
    tip.innerHTML =
      `<strong>${esc(hit.title)}</strong>` +
      hit.lines.filter(Boolean).map((line) => `<span>${esc(line)}</span>`).join("");
    tip.classList.add("show");
    const shell = document.getElementById("map-shell");
    const bounds = shell.getBoundingClientRect();
    let x = event.clientX - bounds.left + 14;
    let y = event.clientY - bounds.top + 14;
    if (x + tip.offsetWidth > bounds.width - 8) x = event.clientX - bounds.left - tip.offsetWidth - 14;
    if (y + tip.offsetHeight > bounds.height - 8) y = event.clientY - bounds.top - tip.offsetHeight - 14;
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  }

  // -- wiring --------------------------------------------------------------
  function setup() {
    const el = canvas();
    if (!el) return;

    el.addEventListener("mousedown", (e) => {
      view.dragging = true;
      view.moved = false;
      view.lastX = e.offsetX;
      view.lastY = e.offsetY;
    });
    window.addEventListener("mouseup", () => (view.dragging = false));

    el.addEventListener("mousemove", (e) => {
      if (view.dragging) {
        view.ox += e.offsetX - view.lastX;
        view.oy += e.offsetY - view.lastY;
        view.lastX = e.offsetX;
        view.lastY = e.offsetY;
        view.moved = true;
        showTip(e, null);
        draw();
        return;
      }
      if (!view.data) return;
      const [wx, wy] = screenToWorld(e.offsetX, e.offsetY);
      const hit = pick(wx, wy);
      const changed = (hit && hit.title) !== (view.hover && view.hover.title);
      view.hover = hit;
      showTip(e, hit);
      const readout = document.getElementById("map-readout");
      if (readout) {
        const anchor = view.data.anchor;
        const cx = Math.floor((wx - anchor.origin_x) / anchor.cell_uu + 0.5);
        const cy = Math.floor((wy - anchor.origin_y) / anchor.cell_uu + 0.5);
        readout.textContent = `${Math.round(wx / 100)} m, ${Math.round(wy / 100)} m  ·  cell ${cx}, ${cy}`;
      }
      if (changed) draw();
    });

    el.addEventListener("mouseleave", () => {
      view.hover = null;
      const tip = document.getElementById("map-tip");
      if (tip) tip.classList.remove("show");
      draw();
    });

    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.18 : 1 / 1.18;
      const [wx, wy] = screenToWorld(e.offsetX, e.offsetY);
      view.scale = Math.max(0.0004, Math.min(0.32, view.scale * factor));
      view.ox = e.offsetX - wx * view.scale;
      view.oy = e.offsetY - wy * view.scale;
      draw();
    }, { passive: false });

    const on = (id, handler) => {
      const node = document.getElementById(id);
      if (node) node.addEventListener("click", handler);
    };
    on("map-fit-world", fitWorld);
    on("map-fit-base", fitBase);
    on("map-layers-all", () => {
      view.hidden.clear();
      renderLayers();
      draw();
    });
    on("map-layers-none", () => {
      for (const node of view.data ? view.data.nodes : []) view.hidden.add(node.resource_class);
      renderLayers();
      draw();
    });

    const bind = (id, key) => {
      const node = document.getElementById(id);
      if (!node) return;
      node.addEventListener("change", () => {
        view[key] = node.checked;
        draw();
      });
    };
    bind("map-show-foundations", "showFoundations");
    bind("map-show-links", "showLinks");
    bind("map-show-tapped", "showTapped");

    window.addEventListener("resize", draw);
    renderLegend();
  }

  async function load() {
    const response = await fetch("/api/grid");
    const data = await response.json();
    const summary = document.getElementById("map-summary");
    if (!data.ok) {
      if (summary) summary.textContent = data.error || "No save loaded.";
      return;
    }
    const first = view.data === null;
    view.data = data;
    view.backdrop = buildBackdrop(data);

    if (summary) {
      const free = data.nodes.filter((n) => n.status === "free").length;
      const wanted = data.nodes.filter((n) => n.status === "wanted").length;
      const parts = [
        `${data.nodes.length} resource nodes`,
        `${data.built.length} machines`,
        `${data.miners.length} extractors`,
        `${free} free nodes`,
      ];
      if (wanted) parts.push(`${wanted} your plan needs`);
      summary.textContent = parts.join("  ·  ");
    }
    renderLayers();
    if (first) {
      if (data.base) fitBase();
      else fitWorld();
    } else {
      draw();
    }
  }

  window.SatMap = { load, setup, draw };
})();
