/* game.js — Pixel Office Scene
 *
 * Full office environment drawn with Phaser Graphics.
 * Two agent sprites sit at their desks; pose changes with state.
 * Speech bubbles appear when agents post new messages.
 */
(function () {
  "use strict";

  /* ── Palette ── */
  var C = {
    WALL: 0x12122e, WALL_LINE: 0x1a1a3e,
    FLOOR_A: 0x2a2a3e, FLOOR_B: 0x252538,
    BASEBOARD: 0x2a2a4e,
    SHELF: 0x3d2b1f,
    BOOKS: [0x42a5f5, 0xffa726, 0xef5350, 0x66bb6a, 0x7c4dff],
    WB_FRAME: 0x888888, WB_FILL: 0xdddddd,
    CLOCK_FACE: 0xcccccc, CLOCK_HAND: 0x333333,
    TABLE: 0x5a4738, TABLE_LEG: 0x4a3728,
    MUG: 0x5d4037, STEAM: 0xffffff,
    ACCENT: 0x4fc3f7,
  };

  var SHEETS = {
    executor: { path: "assets/sprites/executor.png", fw: 816, fh: 547 },
    reviewer: { path: "assets/sprites/reviewer.png", fw: 408, fh: 1094 },
  };

  var IDLE = 0, WORKING = 1, ALERT = 2, SUCCESS = 3;
  var STATUS = ["\u2615 Idle", "\u2328 Working\u2026", "\u2757 Alert", "\u2728 Done!"];

  /* ── State ── */
  var scene = null, gfx = null;
  var sprites = {}, nameTxt = {}, statusTxt = {};
  var bubbleObj = { executor: null, reviewer: null };
  var tgt = { executor: 0, reviewer: 0 };
  var cur = { executor: -1, reviewer: -1 };
  var lastMsg = { executor: "", reviewer: "" };

  /* ── Office Drawing ── */

  function drawOffice(g, w, h) {
    g.clear();
    var wallH = h * 0.42;

    // Wall
    g.fillStyle(C.WALL); g.fillRect(0, 0, w, wallH);
    g.lineStyle(1, C.WALL_LINE, 0.25);
    for (var y = 16; y < wallH - 8; y += 20) {
      g.lineBetween(0, y, w, y);
      var off = (Math.floor(y / 20) % 2) * 36;
      for (var x = off; x < w; x += 72) g.lineBetween(x, y, x, y + 20);
    }

    // Baseboard
    g.fillStyle(C.BASEBOARD); g.fillRect(0, wallH - 6, w, 6);

    // Floor — checkered
    for (var fy = wallH; fy < h; fy += 28) {
      for (var fx = 0; fx < w; fx += 28) {
        var light = ((Math.floor(fx / 28) + Math.floor(fy / 28)) % 2) === 0;
        g.fillStyle(light ? C.FLOOR_A : C.FLOOR_B);
        g.fillRect(fx, fy, 28, 28);
      }
    }

    // Bookshelf (left wall)
    drawBookshelf(g, w * 0.06, wallH * 0.15, 56, wallH * 0.6);

    // Whiteboard (center wall)
    drawWhiteboard(g, w * 0.5, wallH * 0.12, Math.min(w * 0.22, 160), wallH * 0.55);

    // Clock (right wall)
    drawClock(g, w * 0.94, wallH * 0.28, 16);

    // Coffee table (center floor)
    drawCoffeeTable(g, w * 0.5, h * 0.68);

    // Rug / accent line
    g.lineStyle(2, C.ACCENT, 0.12);
    g.lineBetween(w * 0.15, wallH, w * 0.85, wallH);
  }

  function drawBookshelf(g, x, y, w, h) {
    g.fillStyle(C.SHELF); g.fillRect(x, y, w, h);
    var rows = 3, rh = h / rows;
    var bw = [7, 5, 8, 6, 5, 7, 6, 8, 5, 7];
    for (var r = 0; r < rows; r++) {
      g.fillStyle(C.SHELF); g.fillRect(x, y + rh * (r + 1) - 2, w, 2);
      var bx = x + 3;
      for (var b = 0; b < 6; b++) {
        g.fillStyle(C.BOOKS[(b + r) % C.BOOKS.length]);
        var cw = bw[(b + r * 3) % bw.length];
        g.fillRect(bx, y + rh * r + 3, cw, rh - 7);
        bx += cw + 1;
        if (bx > x + w - 4) break;
      }
    }
  }

  function drawWhiteboard(g, cx, y, w, h) {
    g.fillStyle(C.WB_FRAME); g.fillRect(cx - w / 2 - 2, y - 2, w + 4, h + 4);
    g.fillStyle(C.WB_FILL); g.fillRect(cx - w / 2, y, w, h);
    var lx = cx - w / 2 + 8;
    g.lineStyle(2, 0x42a5f5, 0.6); g.lineBetween(lx, y + 10, lx + w * 0.45, y + 10);
    g.lineStyle(2, 0xffa726, 0.5); g.lineBetween(lx, y + 22, lx + w * 0.35, y + 22);
    g.lineStyle(2, 0xef5350, 0.4); g.lineBetween(lx, y + 34, lx + w * 0.40, y + 34);
    g.lineStyle(1, 0x42a5f5, 0.3);
    g.strokeRect(cx + 8, y + 6, w * 0.28, 24);
    g.strokeRect(cx + 8, y + 34, w * 0.28, 16);
  }

  function drawClock(g, cx, cy, r) {
    g.fillStyle(C.CLOCK_FACE); g.fillCircle(cx, cy, r);
    g.lineStyle(2, C.SHELF); g.strokeCircle(cx, cy, r);
    var now = new Date();
    var ha = (now.getHours() % 12) / 12 * Math.PI * 2 - Math.PI / 2;
    var ma = now.getMinutes() / 60 * Math.PI * 2 - Math.PI / 2;
    g.lineStyle(2, C.CLOCK_HAND);
    g.lineBetween(cx, cy, cx + Math.cos(ha) * r * 0.5, cy + Math.sin(ha) * r * 0.5);
    g.lineStyle(1, C.CLOCK_HAND, 0.8);
    g.lineBetween(cx, cy, cx + Math.cos(ma) * r * 0.7, cy + Math.sin(ma) * r * 0.7);
    g.fillStyle(C.CLOCK_HAND); g.fillCircle(cx, cy, 2);
  }

  function drawCoffeeTable(g, cx, cy) {
    g.fillStyle(C.TABLE); g.fillRect(cx - 20, cy, 40, 12);
    g.fillStyle(C.TABLE_LEG); g.fillRect(cx - 2, cy + 12, 4, 8);
    g.fillStyle(C.MUG); g.fillRect(cx - 5, cy - 8, 10, 8);
    g.lineStyle(1, C.STEAM, 0.25);
    g.lineBetween(cx - 2, cy - 11, cx - 3, cy - 16);
    g.lineBetween(cx + 2, cy - 12, cx + 3, cy - 18);
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
    gfx = this.add.graphics();
    var w = this.scale.width, h = this.scale.height;
    drawOffice(gfx, w, h);
    placeAgents(w, h);

    this.scale.on("resize", function (sz) {
      drawOffice(gfx, sz.width, sz.height);
      placeAgents(sz.width, sz.height);
    });

    // Real-time clock
    this.time.addEvent({ delay: 60000, loop: true, callback: function () {
      if (gfx) drawOffice(gfx, scene.scale.width, scene.scale.height);
    }});
  }

  function placeAgents(w, h) {
    var exX = w * 0.25, exY = h * 0.52;
    var rvX = w * 0.75, rvY = h * 0.52;
    var exScale = Math.min((h * 0.55) / SHEETS.executor.fh, 0.32);
    var rvScale = Math.min((h * 0.55) / SHEETS.reviewer.fh, 0.16);

    var nameStyle = { fontSize: "9px", fontFamily: "'Press Start 2P', monospace", color: "#4fc3f7" };
    var statStyle = { fontSize: "13px", fontFamily: "'VT323', monospace", color: "#8e99a4" };

    if (!sprites.executor) {
      sprites.executor = scene.add.sprite(exX, exY, "executor", 0).setDepth(5);
      nameTxt.executor = scene.add.text(exX, 0, "EXECUTOR", nameStyle).setOrigin(0.5).setDepth(5);
      statusTxt.executor = scene.add.text(exX, 0, STATUS[0], statStyle).setOrigin(0.5).setDepth(5);
      addBob(sprites.executor, exY);
    }
    sprites.executor.setPosition(exX, exY).setScale(exScale);
    nameTxt.executor.setPosition(exX, h * 0.87);
    statusTxt.executor.setPosition(exX, h * 0.93);

    if (!sprites.reviewer) {
      sprites.reviewer = scene.add.sprite(rvX, rvY, "reviewer", 0).setDepth(5);
      nameTxt.reviewer = scene.add.text(rvX, 0, "REVIEWER", nameStyle).setOrigin(0.5).setDepth(5);
      statusTxt.reviewer = scene.add.text(rvX, 0, STATUS[0], statStyle).setOrigin(0.5).setDepth(5);
      addBob(sprites.reviewer, rvY);
    }
    sprites.reviewer.setPosition(rvX, rvY).setScale(rvScale);
    nameTxt.reviewer.setPosition(rvX, h * 0.87);
    statusTxt.reviewer.setPosition(rvX, h * 0.93);
  }

  function addBob(sprite, baseY) {
    scene.tweens.add({
      targets: sprite, y: baseY - 3,
      duration: 1500, yoyo: true, repeat: -1, ease: "Sine.easeInOut",
    });
  }

  function update() {
    ["executor", "reviewer"].forEach(function (role) {
      if (!sprites[role] || tgt[role] === cur[role]) return;
      cur[role] = tgt[role];
      sprites[role].setFrame(tgt[role]);
      if (statusTxt[role]) statusTxt[role].setText(STATUS[tgt[role]] || "");
    });
  }

  /* ── Public API ── */

  window.initGame = function () {
    if (window._phaserGame) return;
    if (!document.getElementById("game-container")) return;
    window._phaserGame = new Phaser.Game({
      type: Phaser.AUTO, parent: "game-container",
      backgroundColor: "#0a0a1e", pixelArt: true,
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
      if (!last || last === "reviewer") { tgt.executor = WORKING; tgt.reviewer = IDLE; }
      else { tgt.executor = IDLE; tgt.reviewer = WORKING; }
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
