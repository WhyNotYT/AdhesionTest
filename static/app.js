(() => {
  "use strict";

  const boot = window.__BOOT__ || { pairs: [], defaults: {}, ranges: {}, seed: 1337, version: "1.0.0" };
  const state = {
    pairs: boot.pairs || [],
    activeId: null,
    analysis: null,
    params: structuredClone(boot.defaults || {}),
    defaults: structuredClone(boot.defaults || {}),
    activeDefaults: structuredClone(boot.defaults || {}),
    ranges: boot.ranges || {},
    tab: "align",
    activeView: null,
    pairParams: {},
    histMode: "delta",
    dragging: false,
    gridLines: null,
    gridDirty: false,
  };

  const $ = (id) => document.getElementById(id);
  const els = {
    pairList: $("pairList"),
    emptyState: $("emptyState"),
    workspace: $("workspace"),
    pairTitle: $("pairTitle"),
    pairFiles: $("pairFiles"),
    modeBadge: $("modeBadge"),
    csvLink: $("csvLink"),
    retained: $("retainedValue"),
    retainedLabel: $("retainedLabel"),
    peeled: $("peeledValue"),
    peeledLabel: $("peeledLabel"),
    damaged: $("damagedValue"),
    damagedLabel: $("damagedLabel"),
    eligible: $("eligibleValue"),
    eligibleLabel: $("eligibleLabel"),
    tabs: Array.from(document.querySelectorAll(".tab")),
    viewer: $("viewer"),
    mainImage: $("mainImage"),
    gridOverlay: $("gridOverlay"),
    applyGrid: $("applyGridButton"),
    viewerBadge: $("viewerBadge"),
    loading: $("loading"),
    viewStrip: $("viewStrip"),
    controls: $("controls"),
    controlsTitle: $("controlsTitle"),
    derived: $("derived"),
    histCanvas: $("histCanvas"),
    histTitle: $("histTitle"),
    histMeta: $("histMeta"),
    cellGrid: $("cellGrid"),
    cellsMeta: $("cellsMeta"),
    toast: $("toast"),
    zoomDialog: $("zoomDialog"),
    zoomImage: $("zoomImage"),
    fileInput: $("fileInput"),
    emptyInput: $("emptyInput"),
  };

  const CONTROL_GROUPS = {
    align: [
      { param: "registration.smooth", label: "Smooth", tip: "Gaussian smoothing of the log image used for texture matching." },
      { param: "registration.background", label: "Background", tip: "Broad Gaussian that removes illumination gradients before matching." },
      { param: "registration.radius", label: "Patch", tip: "Half-size of each registration template patch, in pixels." },
      { param: "registration.search", label: "Search", tip: "Maximum local search distance for each template match, in pixels." },
      { param: "registration.step", label: "Spacing", tip: "Spacing between registration sample points. Smaller is slower and denser." },
      { param: "registration.ncc", label: "NCC", tip: "Minimum normalized correlation for a local match to be accepted." },
      { param: "registration.inlier_ncc", label: "Inlier NCC", tip: "Minimum correlation for a match to join the final affine fit." },
      { param: "registration.robust", label: "Fit tolerance", tip: "Robust loss scale for rejecting bad matches in the affine fit." },
      { param: "display.mode", label: "Display", tip: "Tone mapping used only for the visualizations. Measurements stay in raw intensity.", type: "select", options: [["equalize", "Equalized"], ["sqrt", "Sqrt"], ["linear", "Linear"]] },
    ],
    grid: [
      { param: "grid.rows", label: "Rows", tip: "Expected number of cell rows. Changing this switches to automatic grid detection." },
      { param: "grid.cols", label: "Columns", tip: "Expected number of cell columns. Changing this switches to automatic grid detection." },
      { param: "grid.line_prominence", label: "Line sensitivity", tip: "Minimum cut-line contrast for automatic detection. Lower finds more candidate lines." },
      { param: "grid.curve_sigma", label: "Curve smoothing", tip: "Smoothing of automatically traced cut paths, in pixels." },
      { param: "exclusion.near_px", label: "Cut margin", tip: "Width around each cut centerline considered for exclusion, in pixels." },
      { param: "exclusion.abnormal_low", label: "Dark cut", tip: "Relative brightness below local background that marks an original cut as dark." },
      { param: "exclusion.abnormal_high", label: "Bright cut", tip: "Relative brightness above local background that marks an original cut as bright." },
      { param: "exclusion.dilate", label: "Cut dilation", tip: "Safety dilation applied to excluded cut pixels, in pixels." },
      { param: "exclusion.foil_ratio", label: "Foil ratio", tip: "Brightness ratio above local background that marks pre-existing bright foil." },
      { param: "exclusion.foil_min", label: "Foil floor", tip: "Absolute brightness floor for the pre-existing foil test." },
      { param: "exclusion.foil_dilate", label: "Foil dilation", tip: "Dilation applied to the pre-existing bright foil exclusion mask, in pixels." },
    ],
    signals: [
      { param: "signal.smooth", label: "Noise smooth", tip: "Gaussian smoothing applied before computing paired log intensities." },
      { param: "signal.field_sigma", label: "Background σ", tip: "Scale of the local background brightness map, in pixels." },
      { param: "signal.core_distance", label: "Core distance", tip: "Pixels this far from excluded cuts are used to estimate noise and illumination." },
      { param: "signal.robust", label: "Robust scale", tip: "Robust fitting scale for the illumination field. Smaller rejects outliers more strongly." },
      { param: "display.mode", label: "Display", tip: "Tone mapping used only for the visualizations. Measurements stay in raw intensity.", type: "select", options: [["equalize", "Equalized"], ["sqrt", "Sqrt"], ["linear", "Linear"]] },
    ],
    loss: [
      { param: "detection.sensitivity", label: "Sensitivity ×", tip: "Divides both detection thresholds. Higher values detect fainter loss." },
      { param: "detection.sigma_multiplier", label: "Sigma multiplier", tip: "Paired-change threshold before the sensitivity divisor, in residual sigmas." },
      { param: "detection.brightness_ratio", label: "Brightness ratio", tip: "Local brightness ratio required before the sensitivity divisor." },
      { param: "detection.minimum_area", label: "Min area px", tip: "Smallest accepted connected loss component, in pixels (8-connected)." },
    ],
  };

  const TAB_TITLES = { align: "Align", grid: "Grid", signals: "Signals", loss: "Detection" };
  const TAB_VIEWS = {
    align: ["align", "reference", "tape", "image"],
    grid: ["grid", "excluded"],
    signals: ["normalized", "delta", "brightness", "field"],
    loss: ["overlay", "loss", "thresholds", "delta_mask", "bright_mask", "status"],
  };

  let toastTimer = null;
  let analyzeSeq = 0;
  let analyzeTimer = null;

  function toast(message) {
    els.toast.textContent = message;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, 4200);
  }

  function getParam(path) {
    const [group, key] = path.split(".");
    return state.params?.[group]?.[key];
  }

  function setParam(path, value) {
    const [group, key] = path.split(".");
    if (!state.params[group]) state.params[group] = {};
    state.params[group][key] = value;
  }

  function rangeFor(path) {
    return state.ranges[path] || [0, 1, 0.01];
  }

  function formatValue(value, step) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "–";
    if (step >= 1) return number.toFixed(0);
    if (step >= 0.1) return number.toFixed(2).replace(/0$/, "");
    if (step >= 0.01) return number.toFixed(2);
    return number.toFixed(3);
  }

  function formatPercent(value, digits = 6) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "–";
    return number.toFixed(digits).replace(/\.?0+$/, "");
  }

  function setLoading(active) {
    els.loading.hidden = !active;
  }

  function activePair() {
    return state.pairs.find((pair) => pair.id === state.activeId) || null;
  }

  function pairStats(pair) {
    return pair?.summary?.stats || null;
  }

  function mergePairs(incoming) {
    const byId = new Map(state.pairs.map((pair) => [pair.id, pair]));
    for (const pair of incoming) byId.set(pair.id, { ...(byId.get(pair.id) || {}), ...pair });
    state.pairs = Array.from(byId.values()).sort(
      (a, b) => (a.demo ? 1 : 0) - (b.demo ? 1 : 0) || (a.order || 0) - (b.order || 0)
    );
  }

  function renderRail() {
    els.pairList.innerHTML = "";
    for (const pair of state.pairs) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pair-item" + (pair.id === state.activeId ? " is-active" : "");
      button.dataset.id = pair.id;
      const stats = pairStats(pair);
      const thumb = pair.summary?.thumb || "";
      const modeText = pair.mode === "reference"
        ? "squared-only estimate"
        : pair.mode === "taped"
          ? "taped-only estimate"
          : "";
      const valueText = stats
        ? `${formatPercent(stats.peeled_pct, 2)}% ${pair.mode === "paired" ? "peeled" : "estimated"}`
        : "not run";
      button.innerHTML = `
        ${thumb ? `<img class="pair-thumb" src="${thumb}" alt="">` : `<span class="pair-thumb"></span>`}
        <span class="pair-copy">
          <span class="pair-name">${escapeHtml(pair.label || pair.id)}</span>
          <span class="pair-sub">${pair.demo ? "demo · " : ""}${modeText ? `${modeText} · ` : ""}${valueText}</span>
        </span>
        <span class="pair-score">${stats ? `${formatPercent(stats.retained_pct, 2)}` : ""}</span>`;
      if (stats) {
        button.title = `retained ${formatPercent(stats.retained_pct, 6)}% · peeled ${formatPercent(stats.peeled_pct, 6)}%`;
      }
      button.addEventListener("click", () => selectPair(pair.id));
      els.pairList.appendChild(button);
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showWorkspace(show) {
    els.emptyState.hidden = show;
    els.workspace.hidden = !show;
  }

  function updateHeader(pair, analysis) {
    const stats = analysis?.stats || pairStats(pair) || {};
    const mode = analysis?.mode || pair?.mode || "paired";
    const estimated = mode !== "paired";
    els.pairTitle.textContent = pair?.label || "–";
    if (estimated) {
      const image = mode === "reference" ? pair?.reference : pair?.taped;
      els.pairFiles.textContent = `${image || "single image"}  ·  ${mode === "reference" ? "no Taped view" : "no Squared view"}`;
    } else {
      els.pairFiles.textContent = pair ? `${pair.reference}  ·  ${pair.taped}` : "–";
    }
    els.modeBadge.hidden = !estimated;
    els.modeBadge.textContent = mode === "reference" ? "SQUARED ONLY" : mode === "taped" ? "TAPED ONLY" : "";
    els.retainedLabel.textContent = estimated ? "100 − estimate" : "retained %";
    els.peeledLabel.textContent = estimated ? "estimated %" : "peeled %";
    els.damagedLabel.textContent = estimated ? "flagged cells" : "damaged cells";
    els.retained.textContent = formatPercent(stats.retained_pct, 6);
    els.peeled.textContent = formatPercent(stats.peeled_pct, 6);
    els.retained.title = stats.retained_pct != null ? `${formatPercent(stats.retained_pct, 6)}% retained` : "";
    els.peeled.title = stats.peeled_pct != null
      ? `${formatPercent(stats.peeled_pct, 6)}% ${estimated ? "estimated" : "peeled"}${stats.estimate_note ? ` — ${stats.estimate_note}` : ""}`
      : "";
    els.damaged.textContent = stats.damaged_cells != null ? stats.damaged_cells : "–";
    els.eligible.textContent = stats.eligible_pixels != null ? Number(stats.eligible_pixels).toLocaleString("en-US") : "–";
  }

  function allViews() {
    return (state.analysis?.views || []).slice();
  }

  function viewsForTab(tab) {
    const wanted = new Set(TAB_VIEWS[tab] || []);
    return allViews().filter((view) => wanted.has(view.key));
  }

  function renderViewStrip() {
    const views = viewsForTab(state.tab);
    els.viewStrip.innerHTML = "";
    if (!views.length) return;
    if (!views.some((view) => view.key === state.activeView)) {
      const primary = views.find((view) => view.main) || views[0];
      state.activeView = primary.key;
    }
    for (const view of views) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "view-thumb" + (view.key === state.activeView ? " is-active" : "");
      button.dataset.key = view.key;
      button.title = view.label;
      button.innerHTML = `<img src="${view.url}" alt=""><span>${escapeHtml(view.label)}</span>`;
      button.addEventListener("click", () => setMainView(view));
      els.viewStrip.appendChild(button);
    }
    const selected = views.find((view) => view.key === state.activeView) || views[0];
    setMainView(selected);
  }

  function setMainView(view) {
    if (!view) return;
    state.activeView = view.key;
    els.mainImage.src = view.url;
    els.viewerBadge.textContent = view.label;
    for (const thumb of els.viewStrip.querySelectorAll(".view-thumb")) {
      thumb.classList.toggle("is-active", thumb.dataset.key === view.key);
    }
    renderGridOverlay();
  }

  // --------------------------------------------------------------- grid editor
  function imageContentRect() {
    const rect = els.mainImage.getBoundingClientRect();
    const naturalWidth = els.mainImage.naturalWidth || rect.width || 1;
    const naturalHeight = els.mainImage.naturalHeight || rect.height || 1;
    const scale = Math.min(rect.width / naturalWidth, rect.height / naturalHeight);
    const width = naturalWidth * scale;
    const height = naturalHeight * scale;
    return {
      left: rect.left + (rect.width - width) / 2,
      top: rect.top + (rect.height - height) / 2,
      width,
      height,
      naturalWidth,
      naturalHeight,
    };
  }

  function gridGeometry() {
    const lines = state.gridLines;
    if (!lines) return null;
    const content = imageContentRect();
    if (content.width < 8 || content.height < 8) return null;
    const viewerRect = els.viewer.getBoundingClientRect();
    return {
      lines,
      content,
      left: content.left - viewerRect.left,
      top: content.top - viewerRect.top,
      sx: content.width / lines.width,
      sy: content.height / lines.height,
    };
  }

  function renderGridOverlay() {
    const lines = state.gridLines;
    const editable = Boolean(
      lines &&
      lines.x.length > 1 &&
      lines.y.length > 1 &&
      state.tab === "grid" &&
      state.activeView === "grid"
    );
    els.viewer.classList.toggle("is-grid-editable", editable);
    els.applyGrid.hidden = !(editable && state.gridDirty);
    els.gridOverlay.hidden = !editable;
    if (!editable) return;

    const geometry = gridGeometry();
    if (!geometry) {
      els.gridOverlay.hidden = true;
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, geometry.content.width);
    const height = Math.max(1, geometry.content.height);
    els.gridOverlay.style.left = `${geometry.left}px`;
    els.gridOverlay.style.top = `${geometry.top}px`;
    els.gridOverlay.style.width = `${width}px`;
    els.gridOverlay.style.height = `${height}px`;
    els.gridOverlay.width = Math.round(width * dpr);
    els.gridOverlay.height = Math.round(height * dpr);

    const ctx = els.gridOverlay.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const xs = lines.x.map((value) => value * geometry.sx);
    const ys = lines.y.map((value) => value * geometry.sy);
    const top = ys[0];
    const bottom = ys[ys.length - 1];
    const left = xs[0];
    const right = xs[xs.length - 1];

    ctx.lineWidth = 1.6;
    ctx.strokeStyle = "rgba(54, 226, 255, 0.95)";
    ctx.shadowColor = "rgba(0, 0, 0, 0.6)";
    ctx.shadowBlur = 2;
    for (const x of xs) {
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
    }
    for (const y of ys) {
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(right, y);
      ctx.stroke();
    }
    ctx.shadowBlur = 0;

    ctx.fillStyle = "rgba(12, 20, 24, 0.72)";
    ctx.strokeStyle = "rgba(54, 226, 255, 1)";
    ctx.lineWidth = 1.2;
    for (const x of xs) {
      for (const y of [top, bottom]) {
        ctx.beginPath();
        ctx.arc(x, y, 3.4, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
    }
    for (const y of ys) {
      for (const x of [left, right]) {
        ctx.beginPath();
        ctx.arc(x, y, 3.4, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
    }
  }

  function gridPointer(event) {
    const lines = state.gridLines;
    const content = imageContentRect();
    return {
      x: ((event.clientX - content.left) / Math.max(content.width, 1)) * lines.width,
      y: ((event.clientY - content.top) / Math.max(content.height, 1)) * lines.height,
      scaleX: lines.width / Math.max(content.width, 1),
      scaleY: lines.height / Math.max(content.height, 1),
    };
  }

  function gridLineAt(event) {
    const lines = state.gridLines;
    if (!lines) return null;
    const point = gridPointer(event);
    const toleranceX = 11 * point.scaleX;
    const toleranceY = 11 * point.scaleY;
    const withinRows = point.y >= lines.y[0] - toleranceY && point.y <= lines.y[lines.y.length - 1] + toleranceY;
    const withinColumns = point.x >= lines.x[0] - toleranceX && point.x <= lines.x[lines.x.length - 1] + toleranceX;
    let best = null;
    if (withinRows) {
      for (let index = 0; index < lines.x.length; index += 1) {
        const distance = Math.abs(point.x - lines.x[index]);
        if (distance <= toleranceX && (!best || distance < best.distance)) {
          best = { axis: "x", index, distance };
        }
      }
    }
    if (withinColumns) {
      for (let index = 0; index < lines.y.length; index += 1) {
        const distance = Math.abs(point.y - lines.y[index]);
        if (distance <= toleranceY && (!best || distance < best.distance)) {
          best = { axis: "y", index, distance };
        }
      }
    }
    return best;
  }

  let gridDrag = null;

  function beginGridDrag(event) {
    if (event.button !== 0 || !state.gridLines) return;
    if (els.loading && !els.loading.hidden) return;
    const hit = gridLineAt(event);
    if (!hit) return;
    gridDrag = { ...hit, moved: false };
    try {
      els.gridOverlay.setPointerCapture(event.pointerId);
    } catch (error) {
      // Synthetic or older pointer events may not support capture.
    }
    els.gridOverlay.classList.add("is-dragging");
    event.preventDefault();
  }

  function moveGridDrag(event) {
    if (!gridDrag) return;
    const lines = state.gridLines;
    const point = gridPointer(event);
    const axis = gridDrag.axis;
    const values = axis === "x" ? lines.x : lines.y;
    const limit = axis === "x" ? lines.width : lines.height;
    const minimumGap = Math.max(3, limit * 0.003);
    const lower = gridDrag.index > 0 ? values[gridDrag.index - 1] + minimumGap : 0;
    const upper = gridDrag.index < values.length - 1 ? values[gridDrag.index + 1] - minimumGap : limit - 1;
    const next = Math.min(upper, Math.max(lower, axis === "x" ? point.x : point.y));
    if (Math.abs(next - values[gridDrag.index]) > 0.01) {
      gridDrag.moved = true;
      state.gridDirty = true;
    }
    values[gridDrag.index] = next;
    renderGridOverlay();
    event.preventDefault();
  }

  function endGridDrag(event) {
    if (!gridDrag) return;
    const moved = gridDrag.moved;
    gridDrag = null;
    els.gridOverlay.classList.remove("is-dragging");
    try {
      if (els.gridOverlay.hasPointerCapture(event.pointerId)) {
        els.gridOverlay.releasePointerCapture(event.pointerId);
      }
    } catch (error) {
      // Ignore capture cleanup failures on synthetic pointer events.
    }
    if (moved) {
      renderGridOverlay();
      renderDerived();
    }
  }

  function commitGridLines() {
    const lines = state.gridLines;
    if (!lines) return;
    if (!state.params.grid) state.params.grid = {};
    state.params.grid.lines_x = lines.x.slice();
    state.params.grid.lines_y = lines.y.slice();
    if (state.analysis?.state?.grid) {
      state.params.grid.rows = Number(state.analysis.state.grid.rows || state.params.grid.rows);
      state.params.grid.cols = Number(state.analysis.state.grid.cols || state.params.grid.cols);
    }
    state.gridDirty = false;
    els.applyGrid.hidden = true;
    if (state.activeId) state.pairParams[state.activeId] = structuredClone(state.params);
    clearTimeout(analyzeTimer);
    analyze();
  }

  function clearGridLines() {
    state.gridLines = null;
    state.gridDirty = false;
    els.applyGrid.hidden = true;
    if (state.params.grid) {
      state.params.grid.lines_x = [];
      state.params.grid.lines_y = [];
    }
    renderGridOverlay();
  }

  function renderControls() {
    els.controlsTitle.textContent = TAB_TITLES[state.tab] || state.tab;
    els.controls.innerHTML = "";
    const controls = CONTROL_GROUPS[state.tab] || [];
    for (const definition of controls) {
      const value = getParam(definition.param);
      const wrapper = document.createElement("label");
      wrapper.className = "control";
      if (definition.tip) {
        wrapper.dataset.tip = definition.tip;
        wrapper.title = definition.tip;
      }
      if (definition.type === "select") {
        const options = definition.options
          .map(([key, label]) => `<option value="${key}" ${key === value ? "selected" : ""}>${label}</option>`)
          .join("");
        wrapper.innerHTML = `<span class="control-label">${definition.label}</span><span class="control-value"></span><select>${options}</select>`;
        const select = wrapper.querySelector("select");
        if (definition.tip) select.title = definition.tip;
        select.addEventListener("change", (event) => {
          setParam(definition.param, event.target.value);
          scheduleAnalysis(350);
        });
      } else {
        const [min, max, step] = rangeFor(definition.param);
        const display = formatValue(value, step);
        wrapper.innerHTML = `
          <span class="control-label">${definition.label}</span>
          <span class="control-value">${display}</span>
          <input type="range" min="${min}" max="${max}" step="${step}" value="${value}" aria-label="${definition.label}">`;
        const input = wrapper.querySelector("input");
        const output = wrapper.querySelector(".control-value");
        if (definition.tip) input.title = definition.tip;
        input.addEventListener("pointerdown", () => { state.dragging = true; });
        input.addEventListener("pointerup", () => { state.dragging = false; });
        input.addEventListener("input", () => {
          const next = Number(input.value);
          output.textContent = formatValue(next, step);
          setParam(definition.param, next);
          if (definition.param === "grid.rows" || definition.param === "grid.cols") {
            if (state.params.grid) {
              state.params.grid.lines_x = [];
              state.params.grid.lines_y = [];
            }
            state.gridLines = null;
            renderGridOverlay();
          }
          const group = definition.param.split(".")[0];
          const delay = group === "detection" ? 220 : 540;
          scheduleAnalysis(delay);
        });
      }
      els.controls.appendChild(wrapper);
    }
    renderDerived();
  }

  function renderDerived() {
    const analysis = state.analysis;
    if (!analysis) {
      els.derived.textContent = "";
      return;
    }
    const thresholds = analysis.thresholds || {};
    const stats = analysis.stats || {};
    const reg = analysis.state?.registration || {};
    const grid = analysis.state?.grid || {};
    if (state.tab === "align") {
      els.derived.innerHTML =
        `matches <b>${reg.matches ?? "–"}</b>   inliers <b>${reg.inliers ?? "–"}</b>\n` +
        `error <b>${fmt(reg.median_error_px, 2)} px</b>   ncc <b>${fmt(reg.median_ncc, 3)}</b>`;
    } else if (state.tab === "grid") {
      const hint = grid.editable
        ? `\n<span class="hint">${state.gridDirty ? "Lines moved — press Apply grid." : "Drag the cyan lines to correct the grid."}</span>`
        : "";
      els.derived.innerHTML =
        `cells <b>${grid.cells?.length ?? "–"}</b>   method <b>${grid.method || "–"}</b>\n` +
        `eligible <b>${(stats.eligible_pixels || 0).toLocaleString("en-US")}</b> px\n` +
        `excluded <b>${((stats.scrape_pixels || 0) + (stats.oldfoil_pixels || 0)).toLocaleString("en-US")}</b> px` +
        hint;
    } else if (state.tab === "signals") {
      const estimated = (analysis.mode || "paired") !== "paired";
      els.derived.innerHTML = estimated
        ? `bright σ <b>${fmt(stats.brightness_noise, 4)}</b>\n` +
          `median bright <b>${fmt(analysis.hist?.brightness?.median, 4)}</b>`
        : `sigma <b>${fmt(stats.noise, 4)}</b>   bright σ <b>${fmt(stats.brightness_noise, 4)}</b>\n` +
          `median Δ <b>${fmt(analysis.hist?.delta?.median, 4)}</b>`;
    } else {
      const estimated = (analysis.mode || "paired") !== "paired";
      els.derived.innerHTML = estimated
        ? `bright &gt; <b>${fmt(thresholds.brightness, 4)}</b>  (×${fmt(thresholds.brightness_ratio, 3)})\n` +
          `min area <b>${thresholds.minimum_area ?? "–"} px</b>\n` +
          `<b>${stats.estimate_note || "Screening estimate."}</b>`
        : `Δ &gt; <b>${fmt(thresholds.delta, 4)}</b>\n` +
          `bright &gt; <b>${fmt(thresholds.brightness, 4)}</b>  (×${fmt(thresholds.brightness_ratio, 3)})\n` +
          `min area <b>${thresholds.minimum_area ?? "–"} px</b>   σ <b>${fmt(stats.noise, 4)}</b>`;
    }
  }

  function fmt(value, digits = 2) {
    if (value == null || !Number.isFinite(Number(value))) return "–";
    return Number(value).toFixed(digits);
  }

  function drawHistogram() {
    const canvas = els.histCanvas;
    const ctx = canvas.getContext("2d");
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(280, rect.width);
    const height = Math.max(120, rect.height);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const estimated = (state.analysis?.mode || "paired") !== "paired";
    const hist = estimated ? state.analysis?.hist?.brightness : state.analysis?.hist?.delta;
    els.histTitle.textContent = estimated ? "Brightness" : "Delta";
    if (!hist) {
      els.histMeta.textContent = "";
      return;
    }
    const counts = hist.counts;
    const edges = hist.edges;
    const threshold = hist.threshold ?? (estimated ? state.analysis?.thresholds?.brightness : state.analysis?.thresholds?.delta);
    const maxCount = Math.max(...counts, 1);
    const pad = { left: 30, right: 12, top: 12, bottom: 22 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const x0 = edges[0];
    const x1 = edges[edges.length - 1];
    const xFor = (value) => pad.left + ((value - x0) / (x1 - x0)) * plotW;
    const yFor = (count) => pad.top + plotH - (Math.log1p(count) / Math.log1p(maxCount)) * plotH;

    ctx.fillStyle = "#fbf9f3";
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = "#e2ddd1";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i += 1) {
      const y = pad.top + (plotH / 3) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(width - pad.right, y);
      ctx.stroke();
    }

    for (let index = 0; index < counts.length; index += 1) {
      const left = xFor(edges[index]);
      const right = xFor(edges[index + 1]);
      const top = yFor(counts[index]);
      ctx.fillStyle = edges[index] >= (threshold ?? Infinity) ? "#e35b33" : "#c9c2b2";
      ctx.fillRect(left, top, Math.max(1, right - left - 0.6), pad.top + plotH - top);
    }

    if (Number.isFinite(threshold)) {
      const x = xFor(threshold);
      ctx.strokeStyle = "#1c1f21";
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#1c1f21";
      ctx.font = "9px ui-monospace, monospace";
      ctx.fillText("threshold", Math.min(x + 5, width - pad.right - 54), pad.top + 10);
    }

    if (Number.isFinite(hist.median)) {
      const x = xFor(hist.median);
      ctx.strokeStyle = "#2f8f55";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + plotH);
      ctx.stroke();
    }

    ctx.fillStyle = "#6d6e69";
    ctx.font = "9px ui-monospace, monospace";
    const tickValues = [x0, x0 + (x1 - x0) / 2, x1];
    for (const value of tickValues) {
      const x = xFor(value);
      const label = value.toFixed(2);
      const textWidth = ctx.measureText(label).width;
      ctx.fillText(label, Math.min(Math.max(x - textWidth / 2, 2), width - textWidth - 2), height - 6);
    }
    const sigma = estimated ? state.analysis?.stats?.brightness_noise : state.analysis?.stats?.noise;
    els.histMeta.textContent = `σ ${fmt(sigma, 4)} · min ${fmt(edges[0], 2)} · max ${fmt(edges[edges.length - 1], 2)}`;
  }

  function renderCells() {
    const grid = state.analysis?.state?.grid || {};
    const rows = Number(grid.rows || state.analysis?.params?.grid?.rows || 9);
    const cols = Number(grid.cols || state.analysis?.params?.grid?.cols || 9);
    const cells = state.analysis?.cells || [];
    const estimated = (state.analysis?.mode || "paired") !== "paired";
    const flagged = estimated ? "flagged" : "damaged";
    const noun = estimated ? "flagged" : "loss";
    els.cellGrid.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
    els.cellGrid.innerHTML = "";
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const cell = cells.find((item) => item.row === row + 1 && item.column === col + 1);
        const div = document.createElement("div");
        div.className = "cell" + (cell?.status === "Excluded" ? " is-excluded" : "");
        const value = cell?.loss_pct ?? 0;
        const blend = Math.min(1, Math.max(0, value / 18));
        const r = Math.round(245 - 66 * blend);
        const g = Math.round(241 - 150 * blend);
        const b = Math.round(226 - 174 * blend);
        div.style.background = `rgb(${r}, ${g}, ${b})`;
        div.innerHTML = `<span>${cell ? cell.cell_id : ""}</span>`;
        div.title = cell
          ? `cell ${cell.cell_id} · ${value.toFixed(2)}% ${noun} · ${cell.eligible_pixels.toLocaleString("en-US")} px`
          : "";
        els.cellGrid.appendChild(div);
      }
    }
    const flaggedCount = cells.filter((cell) => cell.status === "Damaged" || cell.status === "Bright").length;
    els.cellsMeta.textContent = `${cells.length} · ${flaggedCount} ${flagged}`;
  }

  function applyAnalysis(data) {
    state.analysis = data;
    const estimated = (data.mode || "paired") !== "paired";
    for (const button of els.tabs) {
      button.hidden = estimated && button.dataset.tab === "align";
    }
    if (estimated && state.tab === "align") state.tab = "grid";
    updateTabButtons();
    if (data.params) state.params = structuredClone(data.params);
    const grid = data.state?.grid || {};
    if (
      Array.isArray(grid.display_lines_x) &&
      grid.display_lines_x.length > 1 &&
      Array.isArray(grid.display_lines_y) &&
      grid.display_lines_y.length > 1
    ) {
      state.gridLines = {
        x: grid.display_lines_x.slice(),
        y: grid.display_lines_y.slice(),
        width: Number(grid.display_width || grid.width || 1),
        height: Number(grid.display_height || grid.height || 1),
        rows: Number(grid.rows || 9),
        cols: Number(grid.cols || 9),
      };
    } else {
      state.gridLines = null;
    }
    state.gridDirty = false;
    gridDrag = null;
    if (state.activeId) {
      state.pairParams[state.activeId] = structuredClone(state.params);
      const pair = state.pairs.find((item) => item.id === state.activeId);
      if (pair) {
        const overlay = (data.detection_views || []).find((view) => view.key === "overlay")
          || (data.views || []).find((view) => view.key === "overlay");
        pair.summary = {
          stats: data.stats,
          thresholds: data.thresholds,
          thumb: overlay ? overlay.url.replace(/overlay\.png$/, "overlay_thumb.png") : pair.summary?.thumb,
        };
      }
    }
    const pair = activePair() || data.pair;
    updateHeader(pair, data);
    els.csvLink.href = `/api/pairs/${state.activeId}/results.csv`;
    els.csvLink.hidden = false;
    renderRail();
    renderViewStrip();
    renderControls();
    drawHistogram();
    renderCells();
    renderGridOverlay();
  }

  async function analyze({ force = false } = {}) {
    if (!state.activeId) return;
    const sequence = ++analyzeSeq;
    setLoading(true);
    try {
      const response = await fetch(`/api/pairs/${state.activeId}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params: state.params, force }),
      });
      const data = await response.json();
      if (sequence !== analyzeSeq) return;
      if (!response.ok || data.error) throw new Error(data.error || "Analysis failed");
      applyAnalysis(data);
    } catch (error) {
      if (sequence === analyzeSeq) toast(error.message || "Analysis failed");
    } finally {
      if (sequence === analyzeSeq) setLoading(false);
    }
  }

  function scheduleAnalysis(delay) {
    clearTimeout(analyzeTimer);
    if (!state.activeId) return;
    analyzeTimer = setTimeout(() => analyze(), delay);
  }

  async function selectPair(id) {
    if (state.activeId === id && state.analysis) return;
    const pair = state.pairs.find((item) => item.id === id);
    if (!pair) return;
    state.activeId = id;
    state.activeView = null;
    const estimated = (pair.mode || "paired") !== "paired";
    state.tab = estimated ? "grid" : "align";
    for (const button of els.tabs) {
      button.hidden = estimated && button.dataset.tab === "align";
    }
    updateTabButtons();
    state.activeDefaults = structuredClone(pair.defaults || state.defaults);
    state.params = structuredClone(state.pairParams[id] || state.activeDefaults);
    state.analysis = null;
    state.gridLines = null;
    state.gridDirty = false;
    gridDrag = null;
    els.applyGrid.hidden = true;
    els.csvLink.hidden = true;
    showWorkspace(true);
    updateHeader(pair, null);
    renderRail();
    renderControls();
    renderViewStrip();
    drawHistogram();
    renderCells();
    await analyze();
  }

  async function uploadFiles(files) {
    if (!files || !files.length) return;
    const form = new FormData();
    for (const file of files) form.append("files", file);
    setLoading(true);
    try {
      const response = await fetch("/api/upload", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || "Upload failed");
      mergePairs(data.pairs || []);
      renderRail();
      if (data.errors?.length) toast(data.errors.join(" "));
      if (data.pairs?.length) await selectPair(data.pairs[0].id);
    } catch (error) {
      toast(error.message || "Upload failed");
    } finally {
      setLoading(false);
      els.fileInput.value = "";
      els.emptyInput.value = "";
    }
  }


  function updateTabButtons() {
    for (const button of els.tabs) {
      button.classList.toggle("is-active", button.dataset.tab === state.tab);
    }
  }

  function setTab(tab) {
    state.tab = tab;
    state.activeView = null;
    updateTabButtons();
    renderControls();
    renderViewStrip();
    drawHistogram();
    renderDerived();
    renderGridOverlay();
  }

  function resetTab() {
    const defaults = state.activeDefaults || state.defaults;
    if (state.tab === "grid") clearGridLines();
    for (const definition of CONTROL_GROUPS[state.tab] || []) {
      const [group, key] = definition.param.split(".");
      if (defaults[group] && key in defaults[group]) setParam(definition.param, defaults[group][key]);
    }
    renderControls();
    analyze();
  }

  // ------------------------------------------------------------------ events
  els.fileInput.addEventListener("change", (event) => uploadFiles(event.target.files));
  els.emptyInput.addEventListener("change", (event) => uploadFiles(event.target.files));
  $("resetButton").title = "Restore defaults and re-detect the grid";
  $("resetButton").addEventListener("click", resetTab);
  els.applyGrid.title = "Apply the dragged grid lines";
  els.applyGrid.addEventListener("click", () => {
    if (state.gridDirty) commitGridLines();
  });

  for (const button of els.tabs) {
    button.addEventListener("click", () => setTab(button.dataset.tab));
  }

  $("zoomButton").addEventListener("click", () => {
    if (!els.mainImage.src) return;
    els.zoomImage.src = els.mainImage.src;
    els.zoomDialog.showModal();
  });
  $("closeZoom").addEventListener("click", () => els.zoomDialog.close());
  els.zoomDialog.addEventListener("click", (event) => {
    if (event.target === els.zoomDialog) els.zoomDialog.close();
  });

  els.gridOverlay.addEventListener("pointerdown", beginGridDrag);
  els.gridOverlay.addEventListener("pointermove", moveGridDrag);
  els.gridOverlay.addEventListener("pointerup", endGridDrag);
  els.gridOverlay.addEventListener("pointercancel", endGridDrag);
  els.mainImage.addEventListener("load", renderGridOverlay);

  window.addEventListener("resize", () => {
    drawHistogram();
    renderGridOverlay();
  });

  // Drag and drop anywhere on the page.
  for (const eventName of ["dragenter", "dragover"]) {
    document.addEventListener(eventName, (event) => {
      event.preventDefault();
      document.body.style.outline = "2px solid #e35b33";
      document.body.style.outlineOffset = "-8px";
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    document.addEventListener(eventName, (event) => {
      event.preventDefault();
      document.body.style.outline = "";
      document.body.style.outlineOffset = "";
    });
  }
  document.addEventListener("drop", (event) => {
    if (event.dataTransfer?.files?.length) uploadFiles(event.dataTransfer.files);
  });

  $("seedValue").textContent = boot.seed;
  $("versionValue").textContent = `v${boot.version}`;

  if (state.pairs.length) {
    selectPair(state.pairs[0].id);
  } else {
    showWorkspace(false);
  }
})();
