/* review-doc: the shell side of an HTML page (1.2). Loaded after shell.js, in its
 * own <script> block, only on pages of kind html.
 *
 * The reviewed page runs on http://<slug>.localhost:<review port + 100>/, an origin
 * of its own (ADR 0016). The review server binds both ports as a pair, so the
 * frame port follows from the port this page was served from.
 *
 * This file is the frame backend: the shell's marks, counters and bubbles talk to
 * the probe inside the frame over postMessage (ADR 0017). It runs after shell.js
 * and before DOMContentLoaded, so window.REVIEW_DOC_BACKEND is registered before
 * shell.js's wire() calls start() and pickBackend asks for it. Keep it that way. */
(function () {
  "use strict";

  function frameSrc(meta, loc) {
    if (!meta || !meta.target || meta.target.type !== "file") return "";
    if (loc.protocol !== "http:" || !loc.port) return "";
    var port = Number(loc.port) + 100;
    return "http://" + meta.slug + ".localhost:" + port + "/" + encodeURIComponent(meta.target.entry);
  }

  function originOf(url) {
    var m = /^https?:\/\/[^\/]+/.exec(url || "");
    return m ? m[0] : "";
  }

  /* Decision 12: comments and rewrites only live on the page the review is of. */
  function isEntryPath(path, entry) {
    var p;
    try {
      p = decodeURIComponent(path);
    } catch (e) {
      p = path;
    }
    return p === "/" || p === "/" + entry;
  }

  /* The away strip. An empty path is a document that never said hello. */
  function awayText(path, entry) {
    var shown = path || "another page";
    try {
      if (path) shown = decodeURIComponent(path);
    } catch (e) {
      shown = path;
    }
    return "You are on " + shown + ". Comments and rewrites only work on " + entry + ".";
  }

  /* The text with changed run n put back as it was and every other run kept.
     Runs are the coalesced ones, the same the edits counter counts. */
  function revertedText(runs, n) {
    var out = "", k = 0;
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i];
      if (r.same) { out += r.text; continue; }
      out += k === n ? r.removed : r.added;
      k++;
    }
    return out;
  }

  /* Probe rects are in the frame's viewport; bubbles are placed in the shell's. */
  function toShell(rect, frameRect) {
    return {left: rect.left + frameRect.left, top: rect.top + frameRect.top,
            right: rect.right + frameRect.left, bottom: rect.bottom + frameRect.top};
  }

  /* Messages from the frame are untrusted: the reviewed page's own scripts share
     the probe's window, pass the source and origin checks, and can post
     {rd: 1, ...} too. So every field is type-checked, and an id only ever
     indexes state when it is already an own key of that map (no __proto__). */
  function isStr(v) { return typeof v === "string"; }

  function isNum(v) { return typeof v === "number" && isFinite(v); }

  function own(map, id) {
    return isStr(id) && !!map && Object.prototype.hasOwnProperty.call(map, id);
  }

  function cleanRect(r) {
    if (!r || typeof r !== "object") return null;
    if (!isNum(r.left) || !isNum(r.top) || !isNum(r.right) || !isNum(r.bottom)) return null;
    return {left: r.left, top: r.top, right: r.right, bottom: r.bottom};
  }

  /* A fresh object with only the five anchor fields, or null when one is not a string. */
  function cleanAnchor(a) {
    if (!a || typeof a !== "object") return null;
    var out = {}, keys = ["sel", "tag", "text", "before", "after"];
    for (var i = 0; i < keys.length; i++) {
      if (!isStr(a[keys[i]])) return null;
      out[keys[i]] = a[keys[i]];
    }
    return out;
  }

  function newEditId() {
    return "h" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }

  /* The backend and its message handling, with the DOM kept out: env gives
     post(type, fields), frameRect(), entry, enable(on) for the Comment and Edit
     text buttons, and away(path or null) for the strip. Everything is read from
     host.state.data at the moment it is needed, because undo and redo replace
     that object wholesale. The backend never deletes a comment it could not
     draw: the counters and the prompt count state, not stops (decision 8). */
  function createBackend(host, env) {
    var chosen = host.state.mode || "use";
    var up = false, onEntry = false, due = true, opened = false, asking = false;
    var stops = [], rects = Object.create(null), helloTimer = null;
    var later = env.later || function (fn, ms) { return setTimeout(fn, ms); };
    var cancel = env.cancel || function (h) { clearTimeout(h); };

    /* A document without a probe (a PDF, an image, a page we could not inject)
       never says hello; after this long the strip says so. */
    var HELLO_WAIT = 1500;
    /* Characters an edit's before or after text may hold. */
    var EDIT_MAX = 20000;

    function frameRect() { return env.frameRect(); }

    function live() { return up && onEntry; }

    function effective() { return live() ? chosen : "use"; }

    function postDraw() {
      due = false;
      var data = host.state.data, marks = [], edits = [], id;
      for (id in data.marks) {
        var mk = data.marks[id];
        marks.push({id: id, quote: mk.quote, occ: mk.occ || 0, sel: mk.sel});
      }
      for (id in data.edits) {
        var ed = data.edits[id];
        edits.push({id: id, sel: ed.sel, alt: ed.alt, neu: ed.neu,
                    runs: host.runs(ed.alt, ed.neu), fine: host.fineRuns(ed.alt, ed.neu)});
      }
      env.post("draw", {marks: marks, edits: edits});
    }

    function forget() {
      stops = [];
      rects = Object.create(null);
    }

    /* A bubble that lit a comment in the frame lets it go when it closes. */
    function closed() {
      if (opened) {
        opened = false;
        env.post("open", {id: null});
      }
    }

    function closeBubble() {
      host.closeBubble();
      closed();
    }

    function changed() {
      host.draw();
      host.updatePrompt();
    }

    function onRunClick(m) {
      var r = cleanRect(m.rect);
      if (!own(host.state.data.edits, m.id) || !isNum(m.n) || !r) return;
      var ed = host.state.data.edits[m.id];
      var id = m.id, rect = toShell(r, frameRect());
      var runs = host.runs(ed.alt, ed.neu);
      if (!runs) {
        /* The diff was refused, so the probe drew the whole text as one run. */
        host.showChange(rect, ed.alt, ed.neu, "Before your rewrite", "Revert all", function () {
          delete host.state.data.edits[id];
          host.save("revert:" + id);
          changed();
        });
        return;
      }
      var run = null, k = 0;
      for (var i = 0; i < runs.length; i++) {
        if (runs[i].same) continue;
        if (k === m.n) run = runs[i];
        k++;
      }
      if (!run) return;
      var n = m.n;
      host.showChange(rect, run.removed, run.added, "This change", "Revert this", function () {
        if (!own(host.state.data.edits, id)) return;
        var cur = host.state.data.edits[id];
        var text = revertedText(host.runs(cur.alt, cur.neu) || runs, n);
        if (text === cur.alt) delete host.state.data.edits[id];
        else cur.neu = text;
        host.save("revert:" + id);
        changed();
      });
    }

    /* Decision 11: a new element gets its id here; the next draw carries it with
       the selector, and the probe names the element it is holding from that. */
    function onEdit(m) {
      var edits = host.state.data.edits, a = m.anchor;
      /* The page's own scripts can post edits too: none is taken unless the
         reviewer chose Edit text, and none large enough to bloat the state. */
      if (chosen !== "edit") return;
      if (!isStr(m.alt) || !isStr(m.neu)) return;
      if (m.alt.length > EDIT_MAX || m.neu.length > EDIT_MAX) return;
      if (!a || typeof a !== "object" || !isStr(a.sel) || !isStr(a.tag) || !isStr(a.text)) return;
      /* Only null makes a new id. An id the shell does not hold (or one that
         names the prototype) changes nothing; the probe forgets ids that leave
         the state on its next draw, so it is sent the state as it stands. */
      if (m.id !== null && !own(edits, m.id)) {
        postDraw();
        return;
      }
      var id = m.id === null ? newEditId() : m.id;
      var cur = m.id === null ? null : edits[id];
      if (m.neu === (cur ? cur.alt : m.alt)) {
        delete edits[id];
      } else if (cur) {
        cur.neu = m.neu;
      } else {
        edits[id] = {sec: "", alt: m.alt, neu: m.neu, sel: a.sel, tag: a.tag, text: a.text};
      }
      host.save("edit:" + id);
      changed();
    }

    /* Only well-formed stops are kept, and rects only for their keys, in a map
       without a prototype. */
    function onDrawn(m) {
      if (!Array.isArray(m.stops)) return;
      var list = [], map = Object.create(null), rs = m.rects && typeof m.rects === "object" ? m.rects : {};
      for (var i = 0; i < m.stops.length; i++) {
        var s = m.stops[i];
        if (!s || !isStr(s.key) || (s.kind !== "comment" && s.kind !== "edit")) continue;
        list.push({key: s.key, kind: s.kind});
        var r = Object.prototype.hasOwnProperty.call(rs, s.key) ? cleanRect(rs[s.key]) : null;
        if (r) map[s.key] = r;
      }
      stops = list;
      rects = map;
      /* updatePrompt runs updateCounters, so the counters wake up as soon as
         the page has drawn. */
      host.updatePrompt();
    }

    function onSelect(m) {
      var r = cleanRect(m.rect), extra = cleanAnchor(m.anchor);
      if (!isStr(m.quote) || !isNum(m.occ) || !r || !extra) return;
      host.ask({sec: "", quote: m.quote, occ: m.occ, rect: toShell(r, frameRect()),
                clear: function () { asking = false; env.post("clear-selection"); }, extra: extra});
      /* Set after ask: opening the bubble first closes any other one. */
      asking = true;
    }

    function receive(m) {
      if (!m || typeof m !== "object" || m.rd !== 1) return;
      var t = m.type;
      if (t === "hello") {
        if (!isStr(m.path)) return;
        cancel(helloTimer);
        helloTimer = null;
        up = true;
        onEntry = isEntryPath(m.path, env.entry);
        if (onEntry) {
          env.away(null);
          env.enable(true);
          env.post("mode", {mode: chosen});
          /* A new document has nothing drawn, and every load or bye marks a
             draw as due, so in practice this always draws the whole state. */
          if (due) postDraw();
        } else {
          forget();
          env.post("mode", {mode: "use"});
          env.enable(false);
          env.away(m.path);
          host.updatePrompt();
        }
      } else if (t === "bye") {
        cancel(helloTimer);
        helloTimer = null;
        up = false;
        onEntry = false;
        due = true;
        opened = false;
        asking = false;
        forget();
        env.enable(false);
        env.away(null);
        host.closeBubble();
        host.updatePrompt();
      } else if (t === "drawn") {
        if (live()) onDrawn(m);
      } else if (t === "select") {
        if (live()) onSelect(m);
      } else if (t === "mark-click") {
        var r = cleanRect(m.rect);
        if (!live() || !own(host.state.data.marks, m.id) || !r) return;
        host.showComment(m.id, toShell(r, frameRect()));
      } else if (t === "run-click") {
        if (live()) onRunClick(m);
      } else if (t === "edit") {
        if (live()) onEdit(m);
      } else if (t === "key") {
        if (m.key === "Escape") {
          /* An ask bubble closed this way also lets go of the frame's selection. */
          var wasAsking = asking;
          asking = false;
          closeBubble();
          if (wasAsking) env.post("clear-selection");
        } else if (m.key === "z" && m.shift !== true) {
          host.undo();
        } else if (m.key === "y" || m.key === "z") {
          host.redo();
        }
      } else if (t === "down" || t === "scroll") {
        asking = false;
        closeBubble();
      }
    }

    var backend = {
      /* Always the whole state (decision 1); the id is not needed. */
      draw: function () {
        if (live()) postDraw();
        else due = true;
      },
      stops: function (kind) {
        var out = [];
        for (var i = 0; i < stops.length; i++) {
          if (kind === "all" || (kind === "comments" && stops[i].kind === "comment") ||
              (kind === "edits" && stops[i].kind === "edit")) out.push(stops[i].key);
        }
        return out;
      },
      rect: function (key) {
        return toShell(rects[key] || {left: 0, top: 0, right: 0, bottom: 0}, frameRect());
      },
      scrollTo: function (key) { env.post("scroll-to", {key: key}); },
      open: function (id) {
        opened = true;
        env.post("open", {id: id});
      },
      isEarlier: function () { return false; },
      /* shell.js's closeBubble calls this, so a bubble closed from the shell
         side (Cancel, a click outside) un-lights the comment in the frame too. */
      closed: closed,
      /* The reviewer's choice is kept while away and comes back on the entry. */
      mode: function (m) {
        chosen = m;
        if (up) env.post("mode", {mode: effective()});
      }
    };

    return {
      backend: backend,
      receive: receive,
      /* Every frame load: a new document, which answers init with hello. */
      loaded: function () {
        up = false;
        onEntry = false;
        due = true;
        asking = false;
        forget();
        cancel(helloTimer);
        helloTimer = later(function () {
          helloTimer = null;
          if (up) return;
          env.enable(false);
          env.away("");   /* no path known: "another page" */
        }, HELLO_WAIT);
        env.post("init", {mode: effective()});
      }
    };
  }

  var frame = document.getElementById("review-frame");
  var meta = window.PRESENTER_DATA.meta;
  var src = frameSrc(meta, window.location);
  var origin = originOf(src);
  var current = null, frameLoaded = false;

  function onFrameMessage(ev) {
    if (!current || !frame) return;
    if (ev.source !== frame.contentWindow) return;
    if (ev.origin !== origin) return;
    current.receive(ev.data);
  }

  function post(type, fields) {
    var w = frame && frame.contentWindow;
    if (!w || !origin) return;
    var m = {rd: 1, type: type}, k;
    for (k in (fields || {})) m[k] = fields[k];
    w.postMessage(m, origin);
  }

  if (frame && src) {
    /* Listeners first, then the src: the frame can load before shell.js's
       start() asks for the backend, so a load is remembered and replayed. */
    frame.addEventListener("load", function () {
      frameLoaded = true;
      if (current) current.loaded();
    });
    window.addEventListener("message", onFrameMessage);
    frame.src = src;

    var entry = meta.target.entry;

    window.REVIEW_DOC_BACKEND = function (host) {
      var strip = document.getElementById("html-away");
      var back = document.getElementById("html-back");
      if (back) {
        back.textContent = "Back to " + entry;
        back.addEventListener("click", function () { frame.src = src; });
      }
      var env = {
        entry: entry,
        post: post,
        frameRect: function () { return frame.getBoundingClientRect(); },
        enable: function (on) {
          var bs = document.querySelectorAll('.modes button[data-mode="comment"], .modes button[data-mode="edit"]');
          for (var i = 0; i < bs.length; i++) bs[i].disabled = !on;
        },
        away: function (path) {
          if (!strip) return;
          if (path == null) { strip.hidden = true; return; }
          var span = strip.querySelector("span");
          if (span) span.textContent = awayText(path, entry);
          strip.hidden = false;
        }
      };
      current = createBackend(host, env);
      /* Until the entry page says hello, Comment and Edit text have nothing to act on. */
      env.enable(false);
      if (frameLoaded) current.loaded();
      return current.backend;
    };
  }
})();
