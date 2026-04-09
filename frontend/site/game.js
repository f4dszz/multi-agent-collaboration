/* game.js — Lively Pixel Office Scene
 *
 * Animated office environment with Phaser 3 Graphics.
 * Inspired by Star-Office-UI — continuous ambient animations
 * keep the scene feeling alive even when agents are idle.
 */
(function () {
  "use strict";

  /* ── Palette ── */
  var C = {
    WALL: 0x1a1f42, WALL_LINE: 0x242a50,
    FLOOR_A: 0x3a3058, FLOOR_B: 0x302848,
    BASEBOARD: 0x4a4070,
    RUG: 0x4a2040, RUG_EDGE: 0x5a2850,
    SHELF: 0x5a4030, SHELF_EDGE: 0x4a3020,
    BOOKS: [0x42a5f5, 0xffa726, 0xef5350, 0x66bb6a, 0xce93d8, 0x7c4dff, 0xffee58],
    WB_FRAME: 0x8888aa, WB_FILL: 0x182028,
    CLOCK_FACE: 0xd0d0d0, CLOCK_RIM: 0x6a5848, CLOCK_HAND: 0x222222,
    DESK: 0x5a4838, DESK_EDGE: 0x4a3828, DESK_LEG: 0x3a2818,
    MONITOR: 0x222222, MONITOR_SCREEN: 0x0a1a10, MONITOR_BEZEL: 0x333333,
    PLANT_POT: 0x8a5a3a, PLANT_LEAF: 0x3a8a3a, PLANT_LEAF2: 0x2a7a2a,
    MUG: 0x7a5a4a, COFFEE: 0x3a2010,
    WINDOW_FRAME: 0x5a5a7a, WINDOW_SKY: 0x0a0a30, STAR: 0xffffff,
    MOON: 0xf0e8b0,
    ACCENT: 0x4fc3f7, GLOW_EX: 0x42a5f5, GLOW_RV: 0xffa726,
  };

  var SHEETS = {
    executor: { path: "assets/sprites/executor.png", fw: 816, fh: 547 },
    reviewer: { path: "assets/sprites/reviewer.png", fw: 408, fh: 1094 },
  };

  var IDLE = 0, WORKING = 1, ALERT = 2, SUCCESS = 3;
  var STATUS_LABEL = ["\u2615 Idle", "\u2328 Working\u2026", "\u2757 Alert", "\u2728 Done!"];
  var CODE_TOKENS = ["</>", "{ }", "=>", "fn()", "0x", "if", "++", "&&", "//", "==", "[]", "**"];

  /* ── Mutable state ── */
  var scene = null, bgGfx = null, fgGfx = null;
  var sprites = {}, nameTxt = {}, statusTxt = {};
  var bubbleObj = { executor: null, reviewer: null };
  var tgt = { executor: 0, reviewer: 0 };
  var cur = { executor: -1, reviewer: -1 };
  var lastMsg = { executor: "", reviewer: "" };

  // Animated element refs
  var stars = [], steamParts = [], codeParticles = [];
  var wbCodeLines = [], plantLeaves = [];
  var glowGfx = null, activeGlow = null;
  var layout = {};  // cached positions

  /* ── Static background (drawn once + on resize) ── */

  function drawBackground(g, w, h) {
    g.clear();
    var wallH = h * 0.48;
    layout.wallH = wallH;

    // Wall
    g.fillStyle(C.WALL); g.fillRect(0, 0, w, wallH);
    g.lineStyle(1, C.WALL_LINE, 0.25);
    for (var y = 10; y < wallH - 8; y += 16) {
      g.lineBetween(0, y, w, y);
      var off = (Math.floor(y / 16) % 2) * 28;
      for (var x = off; x < w; x += 56) g.lineBetween(x, y, x, y + 16);
    }

    // Baseboard
    g.fillStyle(C.BASEBOARD); g.fillRect(0, wallH - 6, w, 6);

    // Floor — checkered
    var ts = 22;
    for (var fy = wallH; fy < h; fy += ts)
      for (var fx = 0; fx < w; fx += ts) {
        g.fillStyle(((fx / ts | 0) + (fy / ts | 0)) % 2 === 0 ? C.FLOOR_A : C.FLOOR_B);
        g.fillRect(fx, fy, ts, ts);
      }

    // Rug in center
    var rugW = w * 0.28, rugH = h * 0.18;
    var rugX = w * 0.5 - rugW / 2, rugY = h * 0.68;
    g.fillStyle(C.RUG_EDGE); g.fillRect(rugX - 3, rugY - 3, rugW + 6, rugH + 6);
    g.fillStyle(C.RUG); g.fillRect(rugX, rugY, rugW, rugH);
    // Rug pattern — diamond
    g.lineStyle(1, C.RUG_EDGE, 0.4);
    g.lineBetween(rugX + rugW * 0.5, rugY + 4, rugX + rugW - 8, rugY + rugH * 0.5);
    g.lineBetween(rugX + rugW - 8, rugY + rugH * 0.5, rugX + rugW * 0.5, rugY + rugH - 4);
    g.lineBetween(rugX + rugW * 0.5, rugY + rugH - 4, rugX + 8, rugY + rugH * 0.5);
    g.lineBetween(rugX + 8, rugY + rugH * 0.5, rugX + rugW * 0.5, rugY + 4);

    // Window (left wall)
    drawWindow(g, w * 0.15, wallH * 0.12, Math.max(60, w * 0.10), wallH * 0.55);

    // Bookshelf (left-center wall)
    drawBookshelf(g, w * 0.30, wallH * 0.10, Math.max(50, w * 0.07), wallH * 0.65);

    // Whiteboard (center wall)
    var wbW = Math.min(w * 0.22, 170), wbH = wallH * 0.48;
    layout.wb = { x: w * 0.50, y: wallH * 0.10, w: wbW, h: wbH };
    drawWhiteboard(g, layout.wb.x, layout.wb.y, wbW, wbH);

    // Clock (right wall)
    var cr = Math.max(12, w * 0.018);
    layout.clock = { x: w * 0.93, y: wallH * 0.30, r: cr };
    drawClockFace(g, layout.clock.x, layout.clock.y, cr);

    // Desks
    var deskW = Math.max(80, w * 0.14), deskH = 16;
    layout.deskEx = { x: w * 0.22 - deskW / 2, y: h * 0.62, w: deskW, h: deskH };
    layout.deskRv = { x: w * 0.78 - deskW / 2, y: h * 0.62, w: deskW, h: deskH };
    drawDesk(g, layout.deskEx);
    drawDesk(g, layout.deskRv);

    // Monitors on desks
    var monW = 32, monH = 24;
    layout.monEx = { x: w * 0.22 - monW / 2, y: h * 0.62 - monH - 4, w: monW, h: monH };
    layout.monRv = { x: w * 0.78 - monW / 2, y: h * 0.62 - monH - 4, w: monW, h: monH };
    drawMonitor(g, layout.monEx);
    drawMonitor(g, layout.monRv);

    // Coffee mug on executor desk
    layout.mug = { x: w * 0.22 + deskW / 2 - 18, y: h * 0.62 - 8 };
    drawMug(g, layout.mug.x, layout.mug.y);

    // Plant (right side)
    layout.plant = { x: w * 0.90, y: h * 0.62 };
    drawPlantPot(g, layout.plant.x, layout.plant.y);
  }

  function drawWindow(g, cx, y, w, h) {
    layout.win = { x: cx - w / 2, y: y, w: w, h: h };
    g.fillStyle(C.WINDOW_FRAME); g.fillRect(cx - w / 2 - 4, y - 4, w + 8, h + 8);
    g.fillStyle(C.WINDOW_SKY); g.fillRect(cx - w / 2, y, w, h);
    // Cross bar
    g.fillStyle(C.WINDOW_FRAME);
    g.fillRect(cx - 2, y, 4, h);
    g.fillRect(cx - w / 2, y + h * 0.5 - 2, w, 4);
    // Moon
    var moonR = Math.max(6, w * 0.12);
    layout.moon = { x: cx - w * 0.2, y: y + h * 0.25, r: moonR };
    g.fillStyle(C.MOON); g.fillCircle(layout.moon.x, layout.moon.y, moonR);
    g.fillStyle(C.WINDOW_SKY); g.fillCircle(layout.moon.x + 3, layout.moon.y - 2, moonR * 0.75);
  }

  function drawBookshelf(g, cx, y, w, h) {
    var x = cx - w / 2;
    g.fillStyle(C.SHELF_EDGE); g.fillRect(x - 2, y - 2, w + 4, h + 4);
    g.fillStyle(C.SHELF); g.fillRect(x, y, w, h);
    var rows = 3, rh = h / rows;
    var bw = [6, 5, 7, 5, 6, 8, 5, 7, 6, 5];
    for (var r = 0; r < rows; r++) {
      g.fillStyle(C.SHELF_EDGE); g.fillRect(x, y + rh * (r + 1) - 2, w, 3);
      var bx = x + 3;
      for (var b = 0; b < 8; b++) {
        g.fillStyle(C.BOOKS[(b + r * 2) % C.BOOKS.length]);
        var cw = bw[(b + r * 3) % bw.length];
        g.fillRect(bx, y + rh * r + 4, cw, rh - 9);
        bx += cw + 1;
        if (bx > x + w - 3) break;
      }
    }
  }

  function drawWhiteboard(g, cx, y, w, h) {
    g.fillStyle(C.WB_FRAME); g.fillRect(cx - w / 2 - 3, y - 3, w + 6, h + 6);
    g.fillStyle(C.WB_FILL); g.fillRect(cx - w / 2, y, w, h);
    // Title bar
    g.fillStyle(0x1a3a2a); g.fillRect(cx - w / 2, y, w, 10);
    g.fillStyle(0x66bb6a); g.fillCircle(cx - w / 2 + 6, y + 5, 2);
    g.fillStyle(0xffee58); g.fillCircle(cx - w / 2 + 14, y + 5, 2);
    g.fillStyle(0xef5350); g.fillCircle(cx - w / 2 + 22, y + 5, 2);
  }

  function drawClockFace(g, cx, cy, r) {
    g.fillStyle(C.CLOCK_RIM); g.fillCircle(cx, cy, r + 2);
    g.fillStyle(C.CLOCK_FACE); g.fillCircle(cx, cy, r);
    // Hour marks
    for (var i = 0; i < 12; i++) {
      var a = (i / 12) * Math.PI * 2 - Math.PI / 2;
      g.fillStyle(C.CLOCK_HAND);
      g.fillRect(cx + Math.cos(a) * (r * 0.75) - 1, cy + Math.sin(a) * (r * 0.75) - 1, 2, 2);
    }
  }

  function drawDesk(g, d) {
    g.fillStyle(C.DESK_EDGE); g.fillRect(d.x - 1, d.y - 1, d.w + 2, d.h + 2);
    g.fillStyle(C.DESK); g.fillRect(d.x, d.y, d.w, d.h);
    g.fillStyle(C.DESK_LEG);
    g.fillRect(d.x + 4, d.y + d.h, 4, 14);
    g.fillRect(d.x + d.w - 8, d.y + d.h, 4, 14);
  }

  function drawMonitor(g, m) {
    // Stand
    g.fillStyle(C.MONITOR); g.fillRect(m.x + m.w / 2 - 3, m.y + m.h, 6, 5);
    g.fillRect(m.x + m.w / 2 - 6, m.y + m.h + 4, 12, 2);
    // Bezel
    g.fillStyle(C.MONITOR_BEZEL); g.fillRect(m.x - 2, m.y - 2, m.w + 4, m.h + 4);
    g.fillStyle(C.MONITOR_SCREEN); g.fillRect(m.x, m.y, m.w, m.h);
  }

  function drawMug(g, x, y) {
    g.fillStyle(C.MUG);
    g.fillRect(x, y, 10, 8);
    g.fillRect(x + 10, y + 2, 3, 4);
    g.fillStyle(C.COFFEE); g.fillRect(x + 1, y + 1, 8, 3);
  }

  function drawPlantPot(g, x, y) {
    g.fillStyle(C.PLANT_POT);
    g.fillRect(x - 8, y, 16, 12);
    g.fillRect(x - 6, y + 12, 12, 3);
  }

  /* ── Animated Elements ── */

  function createStars() {
    stars.forEach(function (s) { s.destroy(); });
    stars = [];
    if (!layout.win) return;
    var w = layout.win;
    for (var i = 0; i < 8; i++) {
      var sx = w.x + 4 + Math.random() * (w.w - 8);
      var sy = w.y + 4 + Math.random() * (w.h * 0.7);
      var st = scene.add.graphics().setDepth(1);
      st.fillStyle(C.STAR, 0.5 + Math.random() * 0.5);
      st.fillRect(0, 0, 2, 2);
      st.setPosition(sx, sy);
      // Twinkle tween
      scene.tweens.add({
        targets: st, alpha: 0.15 + Math.random() * 0.3,
        duration: 800 + Math.random() * 1200, yoyo: true, repeat: -1,
        ease: "Sine.easeInOut", delay: Math.random() * 2000,
      });
      stars.push(st);
    }
  }

  function createPlantLeaves() {
    plantLeaves.forEach(function (l) { l.destroy(); });
    plantLeaves = [];
    if (!layout.plant) return;
    var px = layout.plant.x, py = layout.plant.y;
    var leafData = [
      { dx: 0, dy: -14, r: 0 }, { dx: -6, dy: -10, r: -0.4 },
      { dx: 6, dy: -10, r: 0.4 }, { dx: -3, dy: -18, r: -0.15 },
      { dx: 4, dy: -16, r: 0.2 },
    ];
    leafData.forEach(function (ld, i) {
      var leaf = scene.add.graphics().setDepth(3);
      leaf.fillStyle(i < 3 ? C.PLANT_LEAF : C.PLANT_LEAF2);
      leaf.fillEllipse(0, 0, 8, 14);
      leaf.setPosition(px + ld.dx, py + ld.dy);
      leaf.setRotation(ld.r);
      // Gentle sway
      scene.tweens.add({
        targets: leaf, rotation: ld.r + (i % 2 === 0 ? 0.08 : -0.08),
        duration: 2000 + i * 300, yoyo: true, repeat: -1, ease: "Sine.easeInOut",
        delay: i * 200,
      });
      plantLeaves.push(leaf);
    });
  }

  function createWhiteboardCode() {
    wbCodeLines.forEach(function (t) { t.destroy(); });
    wbCodeLines = [];
    if (!layout.wb) return;
    var wb = layout.wb;
    var lines = [
      "def run(task):", "  plan = analyze()", "  for s in plan:",
      "    execute(s)", "  return result", "# consensus?",
      "review(output)", "if ok: commit()", "else: revise()",
    ];
    var baseY = wb.y + 14;
    var lineH = Math.min(10, (wb.h - 18) / 7);
    for (var i = 0; i < 7 && i < lines.length; i++) {
      var lt = scene.add.text(wb.x - wb.w / 2 + 6, baseY + i * lineH, lines[i], {
        fontSize: "8px", fontFamily: "monospace",
        color: "#33ff66", resolution: 2,
      }).setDepth(2).setAlpha(0.7);
      wbCodeLines.push(lt);
    }
  }

  // Scroll whiteboard code continuously
  var wbScrollIdx = 0;
  var wbCodeBank = [
    "import agent", "def execute():", "  task = inbox.read()",
    "  result = llm(task)", "  outbox.write(result)", "class Reviewer:",
    "  def check(self, r):", "    if r.quality > 0.9:", "      return APPROVE",
    "    return REVISE", "# round += 1", "consensus = False",
    "while not consensus:", "  ex.run()", "  rv.check()",
    "  if rv.ok:", "    consensus = True", "deploy(result)",
    "log.info('done')", "return SUCCESS",
  ];

  function scrollWhiteboardCode() {
    if (!wbCodeLines.length) return;
    wbCodeLines.forEach(function (lt, i) {
      var idx = (wbScrollIdx + i) % wbCodeBank.length;
      lt.setText(wbCodeBank[idx]);
    });
    wbScrollIdx = (wbScrollIdx + 1) % wbCodeBank.length;
  }

  // Steam particles rising from coffee mug
  function spawnSteam() {
    if (!layout.mug || !scene) return;
    var mx = layout.mug.x + 5, my = layout.mug.y - 2;
    var p = scene.add.graphics().setDepth(4);
    p.fillStyle(0xffffff, 0.25);
    p.fillCircle(0, 0, 1.5);
    p.setPosition(mx + (Math.random() - 0.5) * 4, my);
    steamParts.push({ g: p, life: 0 });
  }

  function updateSteam() {
    for (var i = steamParts.length - 1; i >= 0; i--) {
      var s = steamParts[i];
      s.life++;
      s.g.y -= 0.4;
      s.g.x += (Math.random() - 0.5) * 0.3;
      s.g.setAlpha(Math.max(0, 0.25 - s.life * 0.008));
      if (s.life > 30) { s.g.destroy(); steamParts.splice(i, 1); }
    }
  }

  // Code particles floating from active agent
  function spawnCodeParticle(role) {
    if (!sprites[role] || !scene) return;
    var sp = sprites[role];
    var token = CODE_TOKENS[(Math.random() * CODE_TOKENS.length) | 0];
    var color = role === "executor" ? "#42a5f5" : "#ffa726";
    var pt = scene.add.text(sp.x + (Math.random() - 0.5) * 30, sp.y - sp.displayHeight * 0.3, token, {
      fontSize: "9px", fontFamily: "monospace", color: color, resolution: 2,
    }).setOrigin(0.5).setDepth(8).setAlpha(0.8);
    codeParticles.push({ txt: pt, life: 0, vx: (Math.random() - 0.5) * 0.6, vy: -0.5 - Math.random() * 0.3 });
  }

  function updateCodeParticles() {
    for (var i = codeParticles.length - 1; i >= 0; i--) {
      var p = codeParticles[i];
      p.life++;
      p.txt.x += p.vx;
      p.txt.y += p.vy;
      p.txt.setAlpha(Math.max(0, 0.8 - p.life * 0.015));
      if (p.life > 50) { p.txt.destroy(); codeParticles.splice(i, 1); }
    }
  }

  // Monitor screen glow when agent is working
  function drawMonitorContent(g, mon, isWorking) {
    g.fillStyle(isWorking ? 0x0a2a10 : C.MONITOR_SCREEN);
    g.fillRect(mon.x, mon.y, mon.w, mon.h);
    if (isWorking) {
      // Scrolling green code lines
      for (var i = 0; i < 4; i++) {
        var lw = 6 + Math.random() * (mon.w - 12);
        g.fillStyle(0x33ff66, 0.4 + Math.random() * 0.3);
        g.fillRect(mon.x + 3, mon.y + 3 + i * 5, lw, 2);
      }
    } else {
      // Idle screensaver — small dot
      g.fillStyle(C.ACCENT, 0.3);
      g.fillCircle(mon.x + mon.w / 2, mon.y + mon.h / 2, 2);
    }
  }

  // Glow circle under active agent
  function drawAgentGlow(g, role) {
    if (!sprites[role]) return;
    var sp = sprites[role];
    var color = role === "executor" ? C.GLOW_EX : C.GLOW_RV;
    var state = tgt[role];
    if (state === WORKING) {
      g.fillStyle(color, 0.12);
      g.fillEllipse(sp.x, sp.y + sp.displayHeight * 0.4, sp.displayWidth * 0.9, 12);
      g.fillStyle(color, 0.06);
      g.fillEllipse(sp.x, sp.y + sp.displayHeight * 0.4, sp.displayWidth * 1.3, 18);
    } else if (state === SUCCESS) {
      g.fillStyle(0x66bb6a, 0.10);
      g.fillEllipse(sp.x, sp.y + sp.displayHeight * 0.4, sp.displayWidth * 0.8, 10);
    } else if (state === ALERT) {
      g.fillStyle(0xef5350, 0.10);
      g.fillEllipse(sp.x, sp.y + sp.displayHeight * 0.4, sp.displayWidth * 0.8, 10);
    }
  }

  // Clock hands (animated per-frame)
  function drawClockHands(g) {
    if (!layout.clock) return;
    var cl = layout.clock;
    var now = new Date();
    var ha = ((now.getHours() % 12) + now.getMinutes() / 60) / 12 * Math.PI * 2 - Math.PI / 2;
    var ma = now.getMinutes() / 60 * Math.PI * 2 - Math.PI / 2;
    var sa = now.getSeconds() / 60 * Math.PI * 2 - Math.PI / 2;
    g.lineStyle(2, C.CLOCK_HAND);
    g.lineBetween(cl.x, cl.y, cl.x + Math.cos(ha) * cl.r * 0.5, cl.y + Math.sin(ha) * cl.r * 0.5);
    g.lineStyle(1, C.CLOCK_HAND, 0.9);
    g.lineBetween(cl.x, cl.y, cl.x + Math.cos(ma) * cl.r * 0.7, cl.y + Math.sin(ma) * cl.r * 0.7);
    g.lineStyle(1, 0xef5350, 0.7);
    g.lineBetween(cl.x, cl.y, cl.x + Math.cos(sa) * cl.r * 0.65, cl.y + Math.sin(sa) * cl.r * 0.65);
    g.fillStyle(C.CLOCK_HAND); g.fillCircle(cl.x, cl.y, 1.5);
  }

  /* ── Speech Bubbles ── */

  function showBubble(role, text) {
    if (!scene || !sprites[role]) return;
    clearBubble(role);
    var raw = text.replace(/[#*`_\[\]]/g, "").replace(/\n+/g, " ").trim();
    if (!raw) return;
    var display = raw.length > 60 ? raw.substring(0, 57) + "\u2026" : raw;
    var sp = sprites[role];
    var bx = sp.x, by = sp.y - sp.displayHeight * 0.45 - 20;
    var bg = scene.add.graphics().setDepth(10);
    var txt = scene.add.text(bx, by, "", {
      fontSize: "11px", fontFamily: "'VT323', monospace",
      color: "#1a1a2e", wordWrap: { width: 170 }, lineSpacing: 1,
    }).setOrigin(0.5).setDepth(11);
    var idx = 0;
    var timer = scene.time.addEvent({
      delay: 22, repeat: display.length - 1,
      callback: function () {
        idx++;
        txt.setText(display.substring(0, idx));
        var b = txt.getBounds();
        bg.clear();
        bg.fillStyle(0xffffff, 0.92);
        bg.fillRoundedRect(b.x - 8, b.y - 5, b.width + 16, b.height + 10, 3);
        bg.lineStyle(1, 0x333333, 0.5);
        bg.strokeRoundedRect(b.x - 8, b.y - 5, b.width + 16, b.height + 10, 3);
        bg.fillTriangle(bx - 4, b.y + b.height + 5, bx + 4, b.y + b.height + 5, bx, b.y + b.height + 12);
      },
    });
    bubbleObj[role] = { bg: bg, txt: txt, timer: timer };
    scene.time.delayedCall(7000, function () { clearBubble(role); });
  }

  function clearBubble(role) {
    var b = bubbleObj[role];
    if (!b) return;
    if (b.timer) b.timer.destroy();
    if (b.bg) b.bg.destroy();
    if (b.txt) b.txt.destroy();
    bubbleObj[role] = null;
  }

  /* ── Phaser Scene ── */

  function preload() {
    this.load.spritesheet("executor", SHEETS.executor.path,
      { frameWidth: SHEETS.executor.fw, frameHeight: SHEETS.executor.fh });
    this.load.spritesheet("reviewer", SHEETS.reviewer.path,
      { frameWidth: SHEETS.reviewer.fw, frameHeight: SHEETS.reviewer.fh });
  }

  function create() {
    scene = this;
    bgGfx = this.add.graphics().setDepth(0);
    fgGfx = this.add.graphics().setDepth(6);
    glowGfx = this.add.graphics().setDepth(4);

    var w = this.scale.width, h = this.scale.height;
    drawBackground(bgGfx, w, h);
    createStars();
    createPlantLeaves();
    createWhiteboardCode();
    placeAgents(w, h);

    // Periodic events
    this.time.addEvent({ delay: 2500, loop: true, callback: scrollWhiteboardCode });
    this.time.addEvent({ delay: 400, loop: true, callback: spawnSteam });
    this.time.addEvent({ delay: 800, loop: true, callback: function () {
      if (tgt.executor === WORKING) spawnCodeParticle("executor");
      if (tgt.reviewer === WORKING) spawnCodeParticle("reviewer");
    }});

    this.scale.on("resize", function (sz) {
      drawBackground(bgGfx, sz.width, sz.height);
      stars.forEach(function (s) { s.destroy(); }); stars = [];
      plantLeaves.forEach(function (l) { l.destroy(); }); plantLeaves = [];
      wbCodeLines.forEach(function (t) { t.destroy(); }); wbCodeLines = [];
      createStars();
      createPlantLeaves();
      createWhiteboardCode();
      placeAgents(sz.width, sz.height);
    });
  }

  function placeAgents(w, h) {
    var exX = w * 0.22, rvX = w * 0.78;
    var targetH = h * 0.38;
    var exScale = Math.min(targetH / SHEETS.executor.fh, 0.36);
    var rvScale = Math.min(targetH / SHEETS.reviewer.fh, 0.20);
    var exY = h * 0.52, rvY = h * 0.50;

    var nameStyle = { fontSize: "9px", fontFamily: "'Press Start 2P', monospace", color: "#4fc3f7", resolution: 2 };
    var statStyle = { fontSize: "13px", fontFamily: "'VT323', monospace", color: "#8e99a4", resolution: 2 };

    if (!sprites.executor) {
      sprites.executor = scene.add.sprite(exX, exY, "executor", 0).setDepth(5);
      nameTxt.executor = scene.add.text(exX, 0, "EXECUTOR", nameStyle).setOrigin(0.5).setDepth(7);
      statusTxt.executor = scene.add.text(exX, 0, STATUS_LABEL[0], statStyle).setOrigin(0.5).setDepth(7);
      addBob(sprites.executor, exY);
    }
    sprites.executor.setPosition(exX, exY).setScale(exScale);
    nameTxt.executor.setPosition(exX, h * 0.87);
    statusTxt.executor.setPosition(exX, h * 0.93);

    if (!sprites.reviewer) {
      sprites.reviewer = scene.add.sprite(rvX, rvY, "reviewer", 0).setDepth(5);
      nameTxt.reviewer = scene.add.text(rvX, 0, "REVIEWER", nameStyle).setOrigin(0.5).setDepth(7);
      statusTxt.reviewer = scene.add.text(rvX, 0, STATUS_LABEL[0], statStyle).setOrigin(0.5).setDepth(7);
      addBob(sprites.reviewer, rvY);
    }
    sprites.reviewer.setPosition(rvX, rvY).setScale(rvScale);
    nameTxt.reviewer.setPosition(rvX, h * 0.87);
    statusTxt.reviewer.setPosition(rvX, h * 0.93);
  }

  function addBob(sprite, baseY) {
    scene.tweens.add({
      targets: sprite, y: baseY - 3,
      duration: 1800, yoyo: true, repeat: -1, ease: "Sine.easeInOut",
    });
  }

  /* ── Per-frame update — the "alive" loop ── */

  var frameCount = 0;

  function update(time) {
    frameCount++;

    // Apply state changes to sprites
    ["executor", "reviewer"].forEach(function (role) {
      if (!sprites[role] || tgt[role] === cur[role]) return;
      cur[role] = tgt[role];
      sprites[role].setFrame(tgt[role]);
      if (statusTxt[role]) statusTxt[role].setText(STATUS_LABEL[tgt[role]] || "");
    });

    // Animated foreground layer (redrawn each frame)
    fgGfx.clear();
    // Monitor screens — show code when working
    if (layout.monEx) drawMonitorContent(fgGfx, layout.monEx, tgt.executor === WORKING);
    if (layout.monRv) drawMonitorContent(fgGfx, layout.monRv, tgt.reviewer === WORKING);
    // Clock hands (smooth second hand)
    drawClockHands(fgGfx);

    // Glow under active agents
    glowGfx.clear();
    drawAgentGlow(glowGfx, "executor");
    drawAgentGlow(glowGfx, "reviewer");

    // Particle systems
    updateSteam();
    updateCodeParticles();

    // Whiteboard glow pulse when someone is working
    if ((tgt.executor === WORKING || tgt.reviewer === WORKING) && layout.wb) {
      var pulse = 0.03 + Math.sin(time / 400) * 0.02;
      fgGfx.fillStyle(0x33ff66, pulse);
      fgGfx.fillRect(layout.wb.x - layout.wb.w / 2, layout.wb.y, layout.wb.w, layout.wb.h);
    }
  }

  /* ── Public API ── */

  window.initGame = function () {
    if (window._phaserGame) return;
    if (!document.getElementById("game-container")) return;
    window._phaserGame = new Phaser.Game({
      type: Phaser.AUTO, parent: "game-container",
      backgroundColor: "#0e0e20", pixelArt: true,
      scale: { mode: Phaser.Scale.RESIZE, autoCenter: Phaser.Scale.CENTER_BOTH },
      scene: { preload: preload, create: create, update: update },
    });
  };

  window.updateAgentStates = function (data) {
    if (!data || !data.room) return;
    var busy = data.busy, st = data.room.state;
    var msgs = (data.messages || []).filter(function (m) {
      return m.sender === "executor" || m.sender === "reviewer";
    });
    var last = msgs.length ? msgs[msgs.length - 1].sender : null;

    // Speech bubbles on new messages
    ["executor", "reviewer"].forEach(function (role) {
      var rm = msgs.filter(function (m) { return m.sender === role; });
      if (rm.length) {
        var c = rm[rm.length - 1].content || "";
        if (c !== lastMsg[role]) { lastMsg[role] = c; showBubble(role, c); }
      }
    });

    if (st === "completed") { tgt.executor = SUCCESS; tgt.reviewer = SUCCESS; return; }
    if (busy) {
      // When busy, the backend creates a streaming message with the active
      // agent's sender BEFORE streaming starts. So the last agent message
      // in the list IS the currently-working agent (its streaming output).
      if (last === "executor") { tgt.executor = WORKING; tgt.reviewer = IDLE; }
      else if (last === "reviewer") { tgt.executor = IDLE; tgt.reviewer = WORKING; }
      else { tgt.executor = WORKING; tgt.reviewer = IDLE; }
      return;
    }
    tgt.executor = IDLE; tgt.reviewer = IDLE;
    if (last === "reviewer" && msgs.length) {
      var lr = null;
      for (var i = msgs.length - 1; i >= 0; i--)
        if (msgs[i].sender === "reviewer") { lr = msgs[i]; break; }
      if (lr) {
        var t = (lr.content || "").toUpperCase();
        if (~t.indexOf("CONSENSUS") || ~t.indexOf("APPROVED") || ~t.indexOf("\u901A\u8FC7"))
          tgt.reviewer = SUCCESS;
        else if (~t.indexOf("REJECT") || ~t.indexOf("\u4FEE\u6539") || ~t.indexOf("\u95EE\u9898"))
          { tgt.reviewer = ALERT; tgt.executor = ALERT; }
      }
    }
  };
})();
