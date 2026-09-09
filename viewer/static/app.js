/* VEYRA SCOPE front-end. Real files only: every frame comes from
   /api/frame, which reads data/raw/. No mock clouds anywhere. */
(function () {
  "use strict";

  // SemanticPOSS taxonomy + palette transcribed from the dataset authors'
  // local-only data/raw/semanticposs/dataset/read_data.py (metadata, not data).
  var POSS_NAMES = {
    0: "unlabeled", 4: "1 person", 5: "2+ persons", 6: "rider", 7: "car",
    8: "trunk", 9: "plants", 10: "sign 1", 11: "sign 2", 12: "sign 3",
    13: "pole", 14: "trashcan", 15: "building", 16: "cone/stone",
    17: "fence", 21: "bike", 22: "ground"
  };
  var POSS_COLORS = [
    [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0], [255, 30, 30], [255, 30, 30],
    [255, 40, 200], [100, 150, 245], [135, 60, 0], [0, 175, 0], [255, 0, 0],
    [255, 0, 0], [255, 0, 0], [255, 240, 150], [125, 255, 0], [255, 200, 0],
    [50, 255, 255], [255, 120, 50], [0, 0, 0], [0, 0, 0], [0, 0, 0],
    [100, 230, 245], [128, 128, 128]
  ];
  // RELLIS-3D has no vendored taxonomy yet: deterministic categorical set.
  var RELLIS_COLORS = [
    [255, 179, 0], [128, 62, 117], [255, 104, 0], [166, 189, 215],
    [193, 0, 32], [206, 162, 98], [129, 112, 102], [0, 125, 52],
    [246, 118, 142], [0, 83, 138], [255, 122, 92], [83, 55, 122],
    [255, 142, 0], [179, 40, 81], [244, 200, 0], [127, 24, 13],
    [147, 170, 0], [89, 51, 21], [241, 58, 19], [35, 44, 22]
  ];

  var BASE_FPS = 10;   // frames per second at 1X tempo
  var CLIP_S = 15;     // playback clips never exceed 15 s wall-clock
  var TEMPOS = [1, 2, 4]; // max 4X

  var state = {
    dataset: "rellis3d", seq: null, index: 0, frames: 0,
    meta: null, color: "sem", view: "orbit",
    budget: 50000, tempo: 1, playing: false, timer: null, frame: null,
    clipTotal: 0, clipDone: 0
  };

  var $ = function (id) { return document.getElementById(id); };
  var els = {};
  ["pairLed", "pairTxt", "scopeRead", "glwrap", "gl", "skeleton", "scopeMsg",
   "frameRead", "seqRead", "ptsRead", "shownRead", "clsRead", "bankRow",
   "timeRead", "poseRead", "rangeRead", "clipRead", "hist", "prevBtn", "runBtn", "runLabel", "runIcon", "nextBtn",
   "budget", "stepRow", "scrub", "statusRoot", "statusData"
  ].forEach(function (id) { els[id] = $(id); });

  /* ---------- three.js scope ---------- */
  var renderer, scene, camera, controls, points = null, grid, survey = null;
  function textSprite(text) {
    var c = document.createElement("canvas");
    c.width = 256; c.height = 64;
    var x = c.getContext("2d");
    x.font = "600 34px ui-monospace, Menlo, monospace";
    x.fillStyle = "#8a8f98";
    x.textBaseline = "middle";
    x.fillText(text, 12, 34);
    var t = new THREE.CanvasTexture(c);
    var s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, transparent: true }));
    s.scale.set(12, 3, 1);
    return s;
  }
  function initGL() {
    var canvas = els.gl;
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0b0b);
    camera = new THREE.PerspectiveCamera(60, 1, 0.1, 2000);
    camera.position.set(-28, 16, 28);
    controls = new THREE.OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(0, 0, -12);
    grid = new THREE.GridHelper(120, 24, 0x3a3d42, 0x232320);
    scene.add(grid);
    scene.add(new THREE.AxesHelper(5));
    // Survey furniture: honest geometry only (ranges from coordinates,
    // ego mark at the sensor origin). Shown in TOP view alone.
    survey = new THREE.Group();
    [10, 30, 50].forEach(function (r) {
      var ring = new THREE.Mesh(
        new THREE.RingGeometry(r - 0.18, r + 0.18, 128),
        new THREE.MeshBasicMaterial({ color: 0x8a8f98, transparent: true, opacity: 0.55, side: THREE.DoubleSide })
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.1;
      survey.add(ring);
      var tag = textSprite(r + " M");
      tag.position.set(r + 3.5, 0.6, 0);
      survey.add(tag);
    });
    var ego = new THREE.Mesh(
      new THREE.OctahedronGeometry(1.4),
      new THREE.MeshBasicMaterial({ color: 0xffb000 })
    );
    ego.position.set(0, 0.8, 0);
    survey.add(ego);
    survey.visible = false;
    scene.add(survey);
    var size = canvas.parentElement.getBoundingClientRect();
    renderer.setSize(size.width, size.height, false);
    camera.aspect = size.width / Math.max(1, size.height);
    camera.updateProjectionMatrix();
    window.addEventListener("resize", function () {
      var r = canvas.parentElement.getBoundingClientRect();
      renderer.setSize(r.width, r.height, false);
      camera.aspect = r.width / Math.max(1, r.height);
      camera.updateProjectionMatrix();
    });
    (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
  }

  function srgb(hex) {
    var c = new THREE.Color(hex);
    if (c.convertSRGBToLinear) c.convertSRGBToLinear();
    return c;
  }
  function lerp3(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }
  function elevColor(z, zmin, zmax) {
    var t = zmax > zmin ? (z - zmin) / (zmax - zmin) : 0.5;
    var c = t < 0.5
      ? lerp3([46, 59, 70], [237, 232, 220], t * 2)
      : lerp3([237, 232, 220], [255, 59, 48], (t - 0.5) * 2);
    return [c[0] / 255, c[1] / 255, c[2] / 255];
  }

  function semColor(dataset, id) {
    var tab = dataset === "semanticposs" ? POSS_COLORS : RELLIS_COLORS;
    var c = tab[id % tab.length];
    // Unlabeled/black entries read as void: lift to faint steel so the
    // operator sees missing labels instead of nothing.
    if (c[0] === 0 && c[1] === 0 && c[2] === 0) return [0.16, 0.16, 0.15];
    return [c[0] / 255, c[1] / 255, c[2] / 255];
  }

  function className(dataset, id) {
    if (dataset === "semanticposs" && POSS_NAMES[id] !== undefined) return POSS_NAMES[id];
    return "class " + id;
  }

  function drawFrame(f) {
    if (points) { scene.remove(points); points.geometry.dispose(); points.material.dispose(); }
    var n = f.points.length;
    var pos = new Float32Array(n * 3);
    var col = new Float32Array(n * 3);
    var zmin = Infinity, zmax = -Infinity, imax = 0;
    var i, p;
    for (i = 0; i < n; i++) {
      p = f.points[i];
      pos[i * 3] = p[1]; pos[i * 3 + 1] = p[2]; pos[i * 3 + 2] = -p[0];
      if (p[2] < zmin) zmin = p[2];
      if (p[2] > zmax) zmax = p[2];
      if (f.intensity[i] > imax) imax = f.intensity[i];
    }
    for (i = 0; i < n; i++) {
      var c;
      if (state.color === "sem" && f.labels) c = semColor(f.dataset, f.labels[i]);
      else if (state.color === "int") {
        var g = imax > 0 ? f.intensity[i] / imax : 0;
        c = [g, g, g * 0.96];
      } else c = elevColor(f.points[i][2], zmin, zmax);
      // sRGB -> linear for r147 pipeline
      var tc = new THREE.Color(c[0], c[1], c[2]);
      if (tc.convertSRGBToLinear) tc.convertSRGBToLinear();
      col[i * 3] = tc.r; col[i * 3 + 1] = tc.g; col[i * 3 + 2] = tc.b;
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    points = new THREE.Points(g, new THREE.PointsMaterial({ size: 0.14, vertexColors: true, sizeAttenuation: true }));
    scene.add(points);
  }

  function setView(v) {
    state.view = v;
    document.querySelectorAll("[data-view]").forEach(function (b) {
      var on = b.getAttribute("data-view") === v;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    controls.enableRotate = v === "orbit";
    if (survey) survey.visible = (v === "top");
    if (v === "top") {
      camera.position.set(0, 130, -11.9);
      camera.up.set(0, 0, -1);
      controls.target.set(0, 0, -12);
    } else if (v === "driver") {
      camera.up.set(0, 1, 0);
      camera.position.set(0, 2.2, 6);
      controls.target.set(0, 1.2, -20);
    } else {
      camera.up.set(0, 1, 0);
      camera.position.set(-28, 16, 28);
      controls.target.set(0, 0, -12);
    }
  }

  /* ---------- data ---------- */
  function api(path) {
    return fetch(path).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " for " + path);
      return r.json();
    }).then(function (j) {
      if (j.error) throw new Error(j.error);
      return j;
    });
  }
  function showMsg(kind, html) {
    els.scopeMsg.hidden = false;
    els.scopeMsg.className = "scope-msg" + (kind === "error" ? " error" : "");
    els.scopeMsg.innerHTML = html;
  }
  function hideMsg() { els.scopeMsg.hidden = true; }

  function setLoading(on) {
    els.skeleton.hidden = !on;
    els.glwrap.setAttribute("aria-busy", on ? "true" : "false");
  }

  function loadFrame() {
    if (!state.seq) return;
    setLoading(true);
    hideMsg();
    api("/api/frame?dataset=" + encodeURIComponent(state.dataset) +
        "&seq=" + encodeURIComponent(state.seq) +
        "&index=" + state.index + "&budget=" + state.budget)
      .then(function (f) {
        state.frame = f;
        state.frames = f.frames;
        drawFrame(f);
        renderReadouts(f);
        renderStrip();
        setLoading(false);
        writeHash();
      })
      .catch(function (err) {
        setLoading(false);
        showMsg("error", "<b>FRAME LOAD FAILED</b> — " + escapeHtml(err.message) +
          ". <br>Recovery: confirm the server runs from the repo root with " +
          "<code>data/</code> present (see <code>datasets/README.md</code>).");
      });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function fmt(n) { return Number(n).toLocaleString("en-US"); }

  function renderReadouts(f) {
    els.frameRead.textContent = f.id;
    els.seqRead.textContent = state.dataset + " / " + f.seq;
    els.ptsRead.textContent = fmt(f.n_points);
    els.shownRead.textContent = fmt(f.shown) + " (1/" + f.stride + ")";
    var hist = f.hist || {};
    var ids = Object.keys(hist).map(Number).sort(function (a, b) { return hist[b] - hist[a]; });
    els.clsRead.textContent = f.paired ? String(ids.length) : "NO LABELS";
    els.timeRead.textContent = f.timestamp === null || f.timestamp === undefined
      ? "UNAVAILABLE" : Number(f.timestamp).toFixed(3) + " S";
    els.poseRead.textContent = f.pose && f.pose.available ? "WORLD / ODOM" : "IDENTITY";
    els.rangeRead.textContent = f.cropped
      ? "CROPPED ≤ " + Number(f.range_m || 100).toFixed(0) + " M"
      : "FULL FRAME";
    els.scopeRead.textContent = state.dataset.toUpperCase() + " " + f.seq + " #" + f.id;
    els.pairLed.setAttribute("data-state", f.paired ? "ok" : "bad");
    els.pairTxt.textContent = f.paired ? "SCAN+LABEL" : "SCAN ONLY";
    els.scrub.max = String(Math.max(0, f.frames - 1));
    els.scrub.value = String(f.index);
    // Histogram: bar length IS the value (exact proportion of the top class).
    els.hist.innerHTML = "";
    if (!f.paired) {
      els.hist.innerHTML = "<li class=\"empty\">No label file for this frame — showing geometry only.</li>";
      return;
    }
    var top = ids.slice(0, 8);
    var max = top.length ? hist[top[0]] : 1;
    var rest = ids.slice(8).reduce(function (a, id) { return a + hist[id]; }, 0);
    top.forEach(function (id) {
      var li = document.createElement("li");
      var c = state.dataset === "semanticposs" && POSS_COLORS[id]
        ? POSS_COLORS[id] : RELLIS_COLORS[id % RELLIS_COLORS.length];
      var pct = (100 * hist[id] / max).toFixed(1);
      li.innerHTML = "<span class=\"sw\"></span><span class=\"bar\"></span>" +
        "<span class=\"lbl mono\"></span>";
      li.children[0].style.background = "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")";
      li.children[1].style.width = pct + "%";
      li.children[1].style.background = "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")";
      li.children[2].textContent = className(state.dataset, id) + " · " + fmt(hist[id]);
      els.hist.appendChild(li);
    });
    if (rest > 0) {
      var li = document.createElement("li");
      li.innerHTML = "<span class=\"sw\" style=\"background:#3a3d42\"></span>" +
        "<span class=\"bar\" style=\"width:" + (100 * rest / max).toFixed(1) + "%\"></span>" +
        "<span class=\"lbl mono\">other · " + fmt(rest) + "</span>";
      els.hist.appendChild(li);
    }
  }

  function renderStrip() {
    // Windowed step strip around the current frame; widths scale with
    // point counts when they vary (notation-staff discipline).
    var row = els.stepRow;
    row.innerHTML = "";
    var half = 48, lo = Math.max(0, state.index - half), hi = Math.min(state.frames - 1, state.index + half);
    var frag = document.createDocumentFragment();
    for (var i = lo; i <= hi; i++) {
      (function (idx) {
        var b = document.createElement("button");
        b.type = "button";
        // Quartile wash: where this frame sits in the whole sequence.
        b.className = "step q" + Math.min(3, Math.floor(4 * idx / Math.max(1, state.frames))) +
          (idx === state.index ? " on" : "");
        b.style.width = "22px";
        b.setAttribute("aria-label", "Frame " + idx + (idx === state.index ? " (current)" : ""));
        if (idx === state.index) b.setAttribute("aria-current", "true");
        b.innerHTML = "<span class=\"tick\"></span>";
        b.title = "frame " + idx;
        b.addEventListener("click", function () { stop(); state.index = idx; loadFrame(); });
        // Pairing tick resolved lazily for the window via frame hist cache.
        if (state.frame && idx === state.index) {
          b.classList.add(state.frame.paired ? "paired" : "unpaired");
        }
        frag.appendChild(b);
      })(i);
    }
    row.appendChild(frag);
    var cur = row.querySelector(".step.on");
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest", inline: "center" });
  }

  /* ---------- transport ---------- */
  function stop() {
    state.playing = false;
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    els.runBtn.setAttribute("aria-pressed", "false");
    els.runLabel.textContent = "RUN";
    els.runIcon.innerHTML = "<path d=\"M5 3l7 5-7 5z\" fill=\"currentColor\"/>";
    els.clipRead.textContent = "15S MAX";
  }
  function play() {
    if (!state.frames) return;
    // A run is a clip: at most CLIP_S seconds per dataset, then auto-stop.
    state.clipTotal = Math.min(state.frames - 1 - state.index, CLIP_S * BASE_FPS * state.tempo);
    if (state.clipTotal <= 0) return;
    state.clipDone = 0;
    state.playing = true;
    els.runBtn.setAttribute("aria-pressed", "true");
    els.runLabel.textContent = "STOP";
    els.runIcon.innerHTML = "<path d=\"M4 3h3v10H4zM9 3h3v10H9z\" fill=\"currentColor\"/>";
    var step = function () {
      state.index = Math.min(state.frames - 1, state.index + 1);
      state.clipDone += 1;
      var left = Math.max(0, Math.ceil((state.clipTotal - state.clipDone) / (BASE_FPS * state.tempo)));
      els.clipRead.textContent = left + "S LEFT";
      loadFrame();
      if (state.clipDone >= state.clipTotal || state.index >= state.frames - 1) stop();
    };
    state.timer = setInterval(step, Math.round(1000 / (BASE_FPS * state.tempo)));
  }
  function toggle() { state.playing ? stop() : play(); }

  /* ---------- boot ---------- */
  function selectDataset(name, seq, index) {
    state.dataset = name;
    document.body.setAttribute("data-dataset", name);
    document.querySelectorAll(".dsbtn").forEach(function (b) {
      var on = b.getAttribute("data-dataset") === name;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    api("/api/datasets").then(function (all) {
      state.meta = all;
      var ds = all[name];
      els.statusRoot.textContent = "ROOT " + (ds.root || "");
      var banks = els.bankRow;
      banks.innerHTML = "";
      ds.sequences.forEach(function (s) {
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = s.id;
        b.title = s.scans + " scans, " + s.paired + " paired";
        if (s.scans === 0) b.disabled = true;
        b.addEventListener("click", function () { stop(); state.seq = s.id; state.index = 0; syncBanks(); loadFrame(); });
        banks.appendChild(b);
      });
      var want = seq && ds.sequences.some(function (s) { return s.id === seq && s.scans > 0; })
        ? seq : (ds.sequences.find(function (s) { return s.scans > 0; }) || {}).id;
      if (!want) {
        showMsg("", "<b>EMPTY DATASET</b> — no <code>.bin</code> scans found under this root. " +
          "See <code>datasets/README.md</code> for the expected layout.");
        return;
      }
      state.seq = want;
      state.index = Math.max(0, Math.min(index || 0, 1e9));
      syncBanks();
      loadFrame();
    }).catch(function (err) {
      showMsg("error", "<b>SERVER UNREACHABLE</b> — " + escapeHtml(err.message) +
        ". <br>Recovery: start it with <code>python3 viewer/server.py</code> from the repo root.");
    });
  }
  function syncBanks() {
    els.bankRow.querySelectorAll("button").forEach(function (b) {
      var on = b.textContent === state.seq;
      b.classList.toggle("on", on);
    });
  }
  function writeHash() {
    location.hash = "d=" + state.dataset + "&s=" + state.seq + "&i=" + state.index;
  }
  function readHash() {
    var m = {};
    location.hash.replace(/^#/, "").split("&").forEach(function (kv) {
      var p = kv.split("=");
      if (p.length === 2) m[p[0]] = decodeURIComponent(p[1]);
    });
    return m;
  }

  function wire() {
    document.querySelectorAll(".dsbtn").forEach(function (b) {
      b.addEventListener("click", function () { stop(); selectDataset(b.getAttribute("data-dataset")); });
    });
    document.querySelectorAll("[data-color]").forEach(function (b) {
      b.addEventListener("click", function () {
        state.color = b.getAttribute("data-color");
        document.querySelectorAll("[data-color]").forEach(function (x) {
          var on = x === b;
          x.classList.toggle("on", on);
          x.setAttribute("aria-pressed", on ? "true" : "false");
        });
        if (state.frame) { drawFrame(state.frame); renderReadouts(state.frame); }
      });
    });
    document.querySelectorAll("[data-view]").forEach(function (b) {
      b.addEventListener("click", function () { setView(b.getAttribute("data-view")); });
    });
    els.prevBtn.addEventListener("click", function () {
      stop();
      state.index = (state.index - 1 + state.frames) % Math.max(1, state.frames);
      loadFrame();
    });
    els.nextBtn.addEventListener("click", function () {
      stop();
      state.index = (state.index + 1) % Math.max(1, state.frames);
      loadFrame();
    });
    els.runBtn.addEventListener("click", toggle);
    document.querySelectorAll("[data-tempo]").forEach(function (b) {
      b.addEventListener("click", function () {
        state.tempo = parseInt(b.getAttribute("data-tempo"), 10) || 1;
        document.querySelectorAll("[data-tempo]").forEach(function (x) {
          var on = x === b;
          x.classList.toggle("on", on);
          x.setAttribute("aria-pressed", on ? "true" : "false");
        });
        if (state.playing) { stop(); play(); } // restart clip at new tempo
      });
    });
    els.budget.addEventListener("change", function () {
      state.budget = parseInt(els.budget.value, 10);
      loadFrame();
    });
    els.scrub.addEventListener("change", function () {
      stop();
      state.index = parseInt(els.scrub.value, 10) || 0;
      loadFrame();
    });
    document.addEventListener("keydown", function (e) {
      if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement && document.activeElement.tagName || "")) return;
      if (e.key === "ArrowRight") { stop(); state.index = Math.min(state.frames - 1, state.index + (e.shiftKey ? 10 : 1)); loadFrame(); }
      else if (e.key === "ArrowLeft") { stop(); state.index = Math.max(0, state.index - (e.shiftKey ? 10 : 1)); loadFrame(); }
      else if (e.key === " ") { e.preventDefault(); toggle(); }
      else if (e.key === "1" || e.key === "2" || e.key === "3") {
        var modes = ["sem", "elev", "int"];
        document.querySelector("[data-color=\"" + modes[+e.key - 1] + "\"]").click();
      }
      else if (e.key === "o" || e.key === "O") setView("orbit");
      else if (e.key === "t" || e.key === "T") setView("top");
      else if (e.key === "d" || e.key === "D") setView("driver");
    });
  }

  try {
    initGL();
  } catch (err) {
    showMsg("error", "<b>WEBGL UNAVAILABLE</b> — this browser cannot render the scope. " +
      "Recovery: use a browser with hardware WebGL enabled.");
    return;
  }
  wire();
  api("/api/datasets").then(function (all) {
    var total = Object.keys(all).reduce(function (a, k) {
      return a + all[k].sequences.reduce(function (x, s) { return x + s.scans; }, 0);
    }, 0);
    els.statusData.textContent = "DATA " + total.toLocaleString("en-US") + " SCANS INDEXED";
  }).catch(function () { /* status stays blank; boot error below covers it */ });
  var h = readHash();
  selectDataset(h.d || "rellis3d", h.s, parseInt(h.i, 10) || 0);
})();
