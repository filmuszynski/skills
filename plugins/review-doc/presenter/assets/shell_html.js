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

  /* An earlier round's item key (r<i>:m:<id>, r<i>:e:<id>), or its lost stop. */
  function isEarlierKey(key) {
    return /^(lost:)?r\d+:/.test(key);
  }

  /* A copy of probe.js's tagNameOf, pinned equal by a test: the shell cannot
     call into the frame. */
  function tagNameOf(startTag) {
    var m = /^<\s*([a-zA-Z][a-zA-Z0-9-]*)/.exec(String(startTag || ""));
    return m ? m[1].toLowerCase() : "";
  }

  /* The entries of runOffsets(alt, neu), placed in the new text as the probe
     reads it. runOffsets counts squeezed text, without spaces, and the probe's
     flat text keeps them, so its positions would land short. Same entries,
     same order: a changed run is kept when it is the next one runOffsets kept.
     `index` gives the changed run (as revertedText counts them) of each entry,
     which is how a click on an adopted rewrite's k-th underline finds its run. */
  function neuOffsets(runs, offs) {
    var pairs = [], index = [], pos = 0, c = 0, k = 0;
    for (var i = 0; i < (runs || []).length; i++) {
      var r = runs[i];
      if (r.same) { pos += r.text.length; continue; }
      if (k < offs.length && r.added === offs[k].now) {
        pairs.push([pos, pos + r.added.length]);
        index.push(c);
        k++;
      }
      pos += r.added.length;
      c++;
    }
    return {pairs: pairs, index: index};
  }

  /* A pill's words: the first 24 characters of a comment's quote, or the
     element a rewrite is in. */
  function pillLabel(kind, earlier, entry) {
    var head = earlier ? (kind === "comment" ? "Earlier comment" : "Earlier rewrite")
                       : (kind === "comment" ? "Comment" : "Rewrite");
    if (kind === "comment") {
      var flat = String(entry.quote || "").replace(/\s+/g, " ").trim();
      return head + ' "' + (flat.length > 24 ? flat.slice(0, 24) + "…" : flat) + '"';
    }
    var tag = tagNameOf(entry.tag);
    return tag ? head + " in " + tag : head;
  }

  /* The backend and its message handling, with the DOM kept out: env gives
     post(type, fields), frameRect(), entry, enable(on) for the Comment and Edit
     text buttons, away(path or null) for the strip, and lost(pills, pick),
     pillRect(item key) and pulsePill(item key) for the lost-items strip.
     Everything is read from
     host.state.data at the moment it is needed, because undo and redo replace
     that object wholesale. The backend never deletes a comment it could not
     draw: the counters and the prompt count state, not stops (decision 8). */
  function createBackend(host, env) {
    var chosen = host.state.mode || "use";
    var up = false, onEntry = false, due = true, opened = false, asking = false;
    var stops = [], rects = Object.create(null), helloTimer = null;
    /* The last drawn's lookup step per item key, and the item keys at step 0. */
    var found = Object.create(null), lost = [];
    var later = env.later || function (fn, ms) { return setTimeout(fn, ms); };
    var cancel = env.cancel || function (h) { clearTimeout(h); };

    /* A document without a probe (a PDF, an image, a page we could not inject)
       never says hello; after this long the strip says so. */
    var HELLO_WAIT = 1500;
    /* Characters an edit's before or after text may hold. */
    var EDIT_MAX = 20000;
    /* Switching away from Edit text makes the probe commit the open edit, and
       that edit arrives after chosen has already changed. Leaving Edit text
       allows exactly one more edit (decision 11); the first edit taken, every
       hello and every bye use the allowance up. */
    var allowEdit = false;

    function frameRect() { return env.frameRect(); }

    function live() { return up && onEntry; }

    function effective() { return live() ? chosen : "use"; }

    function offsOf(alt, neu) {
      return neuOffsets(host.runs(alt, neu), host.runOffsets(alt, neu));
    }

    /* The item an item key names (m:<id>, e:<id>, r<i>:m:<id>, r<i>:e:<id>),
       or null when the state holds no such item. */
    function itemOf(key) {
      var m = isStr(key) ? /^(?:r(0|[1-9]\d*):)?([me]):(.+)$/.exec(key) : null;
      if (!m) return null;
      var src = host.state.data, earlier = m[1] !== undefined;
      if (earlier) {
        src = Array.isArray(src.rounds) ? src.rounds[Number(m[1])] : null;
        if (!src || typeof src !== "object") return null;
      }
      var map = m[2] === "m" ? src.marks : src.edits;
      if (!own(map, m[3]) || !map[m[3]] || typeof map[m[3]] !== "object") return null;
      return {kind: m[2] === "m" ? "comment" : "edit", earlier: earlier, id: m[3], entry: map[m[3]]};
    }

    /* Every item key in state order: comments before rewrites, the current
       round first, then the earlier rounds oldest first (decision 9). */
    function itemKeys() {
      var data = host.state.data, out = [], rounds = Array.isArray(data.rounds) ? data.rounds : [];
      function add(pre, src) {
        if (!src || typeof src !== "object") return;
        Object.keys(src.marks || {}).forEach(function (id) { out.push(pre + "m:" + id); });
        Object.keys(src.edits || {}).forEach(function (id) { out.push(pre + "e:" + id); });
      }
      add("", data);
      for (var i = 0; i < rounds.length; i++) add("r" + i + ":", rounds[i]);
      return out;
    }

    /* The counters' scope: earlier items in Previous, current ones in Current. */
    function inScope(key) {
      var s = host.scope ? host.scope() : "current";
      return s === "all" || (s === "previous") === isEarlierKey(key);
    }

    function postDraw() {
      due = false;
      var data = host.state.data, marks = [], edits = [], earlier = [], id, key;
      for (id in data.marks) {
        var mk = data.marks[id];
        marks.push({id: id, quote: mk.quote, occ: mk.occ || 0, sel: mk.sel, tag: mk.tag || "",
                    text: mk.text || "", before: mk.before || "", after: mk.after || ""});
      }
      for (id in data.edits) {
        var ed = data.edits[id];
        edits.push({id: id, sel: ed.sel, alt: ed.alt, neu: ed.neu, tag: ed.tag || "", text: ed.text || "",
                    offs: offsOf(ed.alt, ed.neu).pairs,
                    runs: host.runs(ed.alt, ed.neu), fine: host.fineRuns(ed.alt, ed.neu)});
      }
      /* Earlier rounds are drawn as tint, and their bubbles read from the
         host's prevInfo, the map md's earlier rounds fill. */
      var rounds = Array.isArray(data.rounds) ? data.rounds : [];
      for (var ri = 0; ri < rounds.length; ri++) {
        var rd = rounds[ri];
        if (!rd || typeof rd !== "object") continue;
        for (id in rd.marks || {}) {
          var em = rd.marks[id];
          if (!em || typeof em !== "object" || !isStr(em.quote)) continue;
          key = "r" + ri + ":m:" + id;
          earlier.push({key: key, kind: "comment", quote: em.quote, occ: em.occ || 0, sel: em.sel || "",
                        tag: em.tag || "", text: em.text || "", before: em.before || "", after: em.after || ""});
          host.noteEarlier(key, {kind: "comment", quote: em.quote, comment: em.comment});
        }
        for (id in rd.edits || {}) {
          var ee = rd.edits[id];
          if (!ee || typeof ee !== "object" || !isStr(ee.alt) || !isStr(ee.neu)) continue;
          key = "r" + ri + ":e:" + id;
          earlier.push({key: key, kind: "edit", sel: ee.sel || "", tag: ee.tag || "", text: ee.text || "",
                        alt: ee.alt, neu: ee.neu, offs: offsOf(ee.alt, ee.neu).pairs});
          host.noteEarlier(key, {kind: "edit", was: ee.alt, now: ee.neu});
        }
      }
      env.post("draw", {marks: marks, edits: edits, earlier: earlier});
    }

    /* The strip of items the page no longer has a place for. It shows the pills
       in the counters' scope, and none while the frame is away from the entry. */
    function renderLost() {
      var pills = [];
      for (var i = 0; live() && i < lost.length; i++) {
        var it = itemOf(lost[i]);
        if (!it || !inScope(lost[i])) continue;
        pills.push({key: lost[i], label: pillLabel(it.kind, it.earlier, it.entry), earlier: it.earlier});
      }
      env.lost(pills, pick);
    }

    /* A pill opens the bubble its item opens on the page. */
    function pick(key) {
      var it = lost.indexOf(key) === -1 ? null : itemOf(key), rect = it ? env.pillRect(key) : null;
      if (!rect) return;
      if (it.earlier) {
        host.showEarlier(key, rect);
      } else if (it.kind === "comment") {
        host.showComment(it.id, rect);
      } else {
        var id = it.id;
        host.showChange(rect, it.entry.alt, it.entry.neu, "This rewrite", "Revert this", function () {
          if (!own(host.state.data.edits, id)) return;
          delete host.state.data.edits[id];
          host.save("revert:" + id);
          changed();
        });
      }
    }

    function forget() {
      stops = [];
      rects = Object.create(null);
      found = Object.create(null);
      lost = [];
      renderLost();
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
      /* On a rewrite the page already carried, the probe numbers the underlines
         along offs, which leaves out runs that only removed words. */
      var n = m.n, f = found["e:" + id];
      if (f && f.adopted) {
        n = offsOf(ed.alt, ed.neu).index[m.n];
        if (n === undefined) return;
      }
      var run = null, k = 0;
      for (var i = 0; i < runs.length; i++) {
        if (runs[i].same) continue;
        if (k === n) run = runs[i];
        k++;
      }
      if (!run) return;
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
         reviewer chose Edit text (or just left it), and none large enough to
         bloat the state. */
      if (chosen !== "edit" && !allowEdit) return;
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
      allowEdit = false;
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

    /* Rects only for the keys of the probe's stops, in a map without a prototype. */
    function keepRects(rs) {
      var map = Object.create(null);
      for (var i = 0; i < stops.length; i++) {
        var key = stops[i].key;
        if (key.indexOf("lost:") === 0 || !Object.prototype.hasOwnProperty.call(rs, key)) continue;
        var r = cleanRect(rs[key]);
        if (r) map[key] = r;
      }
      return map;
    }

    /* Only well-formed stops are kept, and `found` only for items the state
       holds. Decision 5 sets each current comment's drift; an item at step 0 is
       lost, and gets a pill and a stop after the probe's stops. */
    function onDrawn(m) {
      if (!Array.isArray(m.stops)) return;
      var list = [], i, fm = m.found && typeof m.found === "object" ? m.found : {};
      for (i = 0; i < m.stops.length; i++) {
        var s = m.stops[i];
        if (!s || !isStr(s.key) || (s.kind !== "comment" && s.kind !== "edit")) continue;
        list.push({key: s.key, kind: s.kind});
      }
      var keys = itemKeys(), fd = Object.create(null), gone = [], drift = host.drift();
      for (i = 0; i < keys.length; i++) {
        var f = Object.prototype.hasOwnProperty.call(fm, keys[i]) ? fm[keys[i]] : null;
        if (!f || typeof f !== "object" || [0, 1, 2, 3].indexOf(f.step) === -1 || !itemOf(keys[i])) continue;
        fd[keys[i]] = {step: f.step, sel: isStr(f.sel) ? f.sel : "", adopted: f.adopted === true};
        if (f.step === 0) gone.push(keys[i]);
        if (keys[i].indexOf("m:") === 0) {
          var id = keys[i].slice(2);
          if (f.step === 1) delete drift[id];
          else drift[id] = f.step === 0 ? "gone" : "moved";
        }
      }
      for (i = 0; i < gone.length; i++) list.push({key: "lost:" + gone[i], kind: itemOf(gone[i]).kind});
      stops = list;
      rects = keepRects(m.rects && typeof m.rects === "object" ? m.rects : {});
      found = fd;
      lost = gone;
      renderLost();
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
        allowEdit = false;
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
        allowEdit = false;
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
      } else if (t === "rects") {
        /* Boxes moved after a redraw; the stops stay as drawn. */
        if (live() && m.rects && typeof m.rects === "object") rects = keepRects(m.rects);
      } else if (t === "earlier-click") {
        var er = cleanRect(m.rect), it = itemOf(m.key);
        if (!live() || !er || !it || !it.earlier) return;
        host.showEarlier(m.key, toShell(er, frameRect()));
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
      /* The probe's stops in page order, then the lost items; only those in
         the counters' scope, as md's navTargets does. */
      stops: function (kind) {
        var out = [];
        for (var i = 0; i < stops.length; i++) {
          if (!inScope(stops[i].key)) continue;
          if (kind === "all" || (kind === "comments" && stops[i].kind === "comment") ||
              (kind === "edits" && stops[i].kind === "edit")) out.push(stops[i].key);
        }
        return out;
      },
      rect: function (key) {
        if (isStr(key) && key.indexOf("lost:") === 0) {
          var pr = env.pillRect(key.slice(5));
          if (pr) return pr;
        }
        return toShell(rects[key] || {left: 0, top: 0, right: 0, bottom: 0}, frameRect());
      },
      scrollTo: function (key) {
        if (isStr(key) && key.indexOf("lost:") === 0) env.pulsePill(key.slice(5));
        else env.post("scroll-to", {key: key});
      },
      /* A lost item has nothing in the frame to light. */
      open: function (id) {
        if (isStr(id) && id.indexOf("lost:") === 0) return;
        opened = true;
        env.post("open", {id: id});
      },
      isEarlier: isEarlierKey,
      /* shell.js's onScope calls this: the pills follow the counters' scope. */
      rescope: renderLost,
      /* shell.js's closeBubble calls this, so a bubble closed from the shell
         side (Cancel, a click outside) un-lights the comment in the frame too. */
      closed: closed,
      /* The reviewer's choice is kept while away and comes back on the entry. */
      mode: function (m) {
        if (chosen === "edit" && m !== "edit") allowEdit = true;
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
      var lostStrip = document.getElementById("html-lost");
      var lostRow = lostStrip ? lostStrip.querySelector(".lost-pills") : null;
      /* Compared by attribute, so an item key never has to be escaped into a selector. */
      function pillFor(key) {
        var bs = lostRow ? lostRow.children : [];
        for (var i = 0; i < bs.length; i++) if (bs[i].getAttribute("data-key") === key) return bs[i];
        return null;
      }
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
        },
        lost: function (pills, pick) {
          if (!lostStrip || !lostRow) return;
          lostRow.textContent = "";
          pills.forEach(function (p) {
            var b = document.createElement("button");
            b.type = "button";
            b.className = "lost-pill" + (p.earlier ? " earlier" : "");
            b.setAttribute("data-key", p.key);
            b.textContent = p.label;
            b.addEventListener("click", function () { pick(p.key); });
            lostRow.appendChild(b);
          });
          lostStrip.hidden = !pills.length;
        },
        pillRect: function (key) {
          var b = pillFor(key);
          return b ? b.getBoundingClientRect() : null;
        },
        /* The counters' step to a pill: the pill is always in view, so it only pulses. */
        pulsePill: function (key) {
          var b = pillFor(key);
          if (!b) return;
          b.classList.remove("is-target");
          void b.offsetWidth;
          b.classList.add("is-target");
          setTimeout(function () { b.classList.remove("is-target"); }, 1500);
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
