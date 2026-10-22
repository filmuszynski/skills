/* review-doc probe (1.2). Runs inside the reviewed page, on the page's own origin.
 * This file holds the probe's pure text helpers (flat text, retext, edit target,
 * passage anchor, selectors). They touch only nodeType, nodeValue, tagName,
 * childNodes, parentNode, attributes, id and className, so node tests can run
 * them on plain fake trees. Below them sits the live wiring: the postMessage
 * channel to the review shell, the three modes, the overlay layer that draws
 * marks, selection comments and Edit text in place. */
(function () {
  "use strict";

  /* The path this document was loaded at. The probe runs before any page script,
     so a pushState during load cannot make the entry page look like another one. */
  var ENTRY_PATH = location.pathname;

  /* Tags that flow inside a line of text. Everything else is a block for our
     purposes: it gets a virtual space at its edges and can be a comment anchor. */
  var INLINE = {A: 1, ABBR: 1, B: 1, BDI: 1, BDO: 1, CITE: 1, CODE: 1, DATA: 1, DFN: 1,
                EM: 1, I: 1, KBD: 1, LABEL: 1, MARK: 1, Q: 1, S: 1, SAMP: 1, SMALL: 1,
                SPAN: 1, STRONG: 1, SUB: 1, SUP: 1, TIME: 1, U: 1, VAR: 1};
  /* Never part of the visible text. */
  var SKIP = {SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1};
  /* Never editable, nor anything inside them. A button is here because Space and
     Enter inside it fire its click. */
  var NO_EDIT = {SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, SVG: 1, MATH: 1, INPUT: 1,
                 TEXTAREA: 1, SELECT: 1, OPTION: 1, BUTTON: 1, IFRAME: 1, IMG: 1, VIDEO: 1,
                 AUDIO: 1, CANVAS: 1, "REVIEW-DOC-LAYER": 1};

  /* Void tags that sit inside a line of text without making their parent a block
     of blocks: <p>Line one<br>Line two</p> is still one editable paragraph. */
  var LEAF = {BR: 1, WBR: 1, IMG: 1};

  function tagOf(n) {
    return n && n.nodeType === 1 ? String(n.tagName).toUpperCase() : "";
  }

  /* The text a reader sees, in one string, plus where each character lives.
     Whitespace runs (and non-breaking spaces) collapse to one space that stands
     for the whole raw run; a block boundary adds a virtual space (node: null)
     unless a space is already there; the ends are trimmed. */
  function flatText(el) {
    var chars = [], at = [];
    function lastIsSpace() {
      return chars.length > 0 && chars[chars.length - 1] === " ";
    }
    function boundary() {
      if (chars.length && !lastIsSpace()) {
        chars.push(" ");
        at.push({node: null, off: 0, len: 0});
      }
    }
    function walk(n) {
      var kids = n.childNodes || [], i;
      for (i = 0; i < kids.length; i++) {
        var k = kids[i];
        if (k.nodeType === 3) {
          var v = String(k.nodeValue), j = 0;
          while (j < v.length) {
            var c = v.charAt(j);
            if (/[\s ]/.test(c)) {
              var s = j;
              while (j < v.length && /[\s ]/.test(v.charAt(j))) j++;
              if (chars.length && !lastIsSpace()) {
                chars.push(" ");
                at.push({node: k, off: s, len: j - s});
              } else if (lastIsSpace() && at[at.length - 1].node === k) {
                at[at.length - 1].len += j - s;
              }
            } else {
              chars.push(c);
              at.push({node: k, off: j, len: 1});
              j++;
            }
          }
        } else if (k.nodeType === 1 && !SKIP[tagOf(k)] && tagOf(k) !== "WBR" && tagOf(k) !== "IMG") {
          /* WBR and an inline image add no text and are not a block edge:
             super<wbr>long reads "superlong", a<img>b reads "ab". */
          var block = !INLINE[tagOf(k)];
          if (block) boundary();
          walk(k);
          if (block) boundary();
        }
      }
    }
    walk(el);
    while (chars.length && chars[chars.length - 1] === " ") {
      chars.pop();
      at.pop();
    }
    return {text: chars.join(""), at: at};
  }

  function pathOf(n) {
    var p = [];
    while (n && n.parentNode) {
      p.unshift(Array.prototype.indexOf.call(n.parentNode.childNodes, n));
      n = n.parentNode;
    }
    return p;
  }

  /* Document order of two nodes: -1 before, 0 same, 1 after; an ancestor comes
     before its descendants. */
  function cmpNodes(a, b) {
    var pa = pathOf(a), pb = pathOf(b), i;
    for (i = 0; i < pa.length && i < pb.length; i++) {
      if (pa[i] !== pb[i]) return pa[i] < pb[i] ? -1 : 1;
    }
    return pa.length === pb.length ? 0 : (pa.length < pb.length ? -1 : 1);
  }

  function inside(a, root) {
    for (var n = a; n; n = n.parentNode) if (n === root) return true;
    return false;
  }

  /* The flat position of a DOM boundary point: the first entry at or after it,
     text.length past the end. With `isStart` true (the start of a selection) the
     result also skips forward over virtual spaces, so a selection that begins at
     the top of a paragraph does not pick up the space before it. An end point
     keeps the plain result. */
  function flatIndex(flat, node, off, isStart) {
    var last = -1, i;
    var child = node.nodeType === 1 ? (node.childNodes[off] || null) : null;
    for (i = 0; i < flat.at.length; i++) {
      var e = flat.at[i], before;
      if (!e.node) continue;
      if (node.nodeType === 3) {
        before = e.node === node ? e.off < off : cmpNodes(e.node, node) < 0;
      } else if (child) {
        before = cmpNodes(e.node, child) < 0;
      } else {
        before = inside(e.node, node) || cmpNodes(e.node, node) < 0;
      }
      if (before) last = i;
    }
    var idx = last + 1;
    if (isStart) while (idx < flat.at.length && !flat.at[idx].node) idx++;
    return idx;
  }

  function nthIndex(hay, needle, n) {
    var at = -1, from = 0;
    for (var seen = 0; seen <= n; seen++) {
      at = hay.indexOf(needle, from);
      if (at === -1) return -1;
      from = at + 1;
    }
    return at;
  }

  /* Put a stored rewrite on the element without touching its markup. `runs` are
     over the flat original text. Changed runs go last first, so the positions of
     the earlier ones stay valid; only text nodes are trimmed or grown. */
  function retext(el, runs) {
    var flat = flatText(el), spots = [], p = 0, i;
    for (i = 0; i < runs.length; i++) {
      var r = runs[i];
      if (r.same) {
        p += r.text.length;
      } else {
        spots.push({p: p, added: r.added || "", removed: r.removed || ""});
        p += (r.removed || "").length;
      }
    }
    for (i = spots.length - 1; i >= 0; i--) {
      var s = spots[i], k, e;
      /* Delete: every mapped entry, highest offset first within its node. */
      for (k = s.p + s.removed.length - 1; k >= s.p; k--) {
        e = flat.at[k];
        if (e && e.node) {
          e.node.nodeValue = String(e.node.nodeValue).slice(0, e.off) +
                             String(e.node.nodeValue).slice(e.off + e.len);
        }
      }
      if (!s.added) continue;
      var target = null, pos = 0, q;
      /* A replacement goes where the first deleted real character stood, so a
         link around a replaced word keeps its replacement. Only a pure insertion
         uses the neighbour rule below. */
      for (q = s.p; q < s.p + s.removed.length; q++) {
        if (flat.at[q] && flat.at[q].node) {
          target = flat.at[q].node;
          pos = flat.at[q].off;
          break;
        }
      }
      if (!target && s.p > 0 && flat.at[s.p - 1] && flat.at[s.p - 1].node) {
        e = flat.at[s.p - 1];
        target = e.node;
        pos = e.off + e.len;
      } else if (!target && flat.at[s.p] && flat.at[s.p].node) {
        target = flat.at[s.p].node;
        pos = flat.at[s.p].off;
      }
      if (target) {
        var v = String(target.nodeValue);
        target.nodeValue = v.slice(0, pos) + s.added + v.slice(pos);
      } else {
        var doc = el.ownerDocument || document;
        el.appendChild(doc.createTextNode(s.added));
      }
    }
  }

  /* Which element Edit text takes for a click on `node`, or null. */
  function editTarget(node) {
    var n = node && node.nodeType === 3 ? node.parentNode : node, t;
    for (t = n; t; t = t.parentNode) {
      if (t.nodeType === 1 && NO_EDIT[tagOf(t)]) return null;
    }
    var el = n;
    while (el && el.nodeType === 1 && INLINE[tagOf(el)]) el = el.parentNode;
    if (!el || el.nodeType !== 1) return null;
    var pick = el, blockKid = false, i;
    for (i = 0; i < el.childNodes.length; i++) {
      var k = el.childNodes[i];
      if (k.nodeType === 1 && !INLINE[tagOf(k)] && !SKIP[tagOf(k)] && !LEAF[tagOf(k)]) blockKid = true;
    }
    if (tagOf(el) === "HTML" || tagOf(el) === "BODY" || blockKid) {
      pick = null;
      for (t = n; t && t !== el; t = t.parentNode) pick = t;
      if (!pick || pick.parentNode !== el) return null;
    }
    return flatText(pick).text ? pick : null;
  }

  /* The element a selected passage hangs on, from the range's common ancestor. */
  function passageAnchor(node) {
    var el = node && node.nodeType === 3 ? node.parentNode : node;
    while (el && el.nodeType === 1 && INLINE[tagOf(el)] && el.parentNode) el = el.parentNode;
    if (tagOf(el) === "HTML") {
      for (var i = 0; i < el.childNodes.length; i++) {
        if (tagOf(el.childNodes[i]) === "BODY") return el.childNodes[i];
      }
      if (el.ownerDocument && el.ownerDocument.body) return el.ownerDocument.body;
    }
    return el;
  }

  /* CSS.escape where it exists, a local escape of non-identifier characters
     where it does not (node, tests). */
  function cssEsc(s) {
    s = String(s);
    if (typeof CSS !== "undefined" && CSS.escape) return CSS.escape(s);
    var out = s.replace(/[^a-zA-Z0-9_ -￿-]/g, function (c) { return "\\" + c; });
    return /^[0-9]/.test(out) ? "\\3" + out.charAt(0) + " " + out.slice(1) : out;
  }

  function stepFor(el) {
    var tag = String(el.tagName).toLowerCase(), s = tag, cls = String(el.getAttribute("class") || "").trim();
    if (cls) s += "." + cssEsc(cls.split(/\s+/)[0]);
    var par = el.parentNode, same = 0, idx = 0, i;
    if (par) {
      for (i = 0; i < par.childNodes.length; i++) {
        var k = par.childNodes[i];
        if (k.nodeType === 1 && String(k.tagName).toLowerCase() === tag) {
          same++;
          if (k === el) idx = same;
        }
      }
    }
    if (same > 1) s += ":nth-of-type(" + idx + ")";
    return s;
  }

  function selectorFor(el) {
    if (el.id) return "#" + cssEsc(el.id);
    var tag = tagOf(el);
    if (tag === "BODY" || tag === "HTML") return tag.toLowerCase();
    var steps = [], root = "", cur = el;
    while (cur && cur.nodeType === 1) {
      var t = tagOf(cur);
      if (t === "BODY" || t === "HTML") break;
      if (cur.id) { root = "#" + cssEsc(cur.id); break; }
      steps.unshift(stepFor(cur));
      cur = cur.parentNode;
    }
    if (steps.length > 4) return (root ? root + " " : "") + steps.slice(-4).join(" > ");
    return (root ? root + " > " : "") + steps.join(" > ");
  }

  /* The element's start tag as the author wrote it, minus what the probe added. */
  function startTag(el) {
    var s = "<" + String(el.tagName).toLowerCase(), i;
    for (i = 0; i < el.attributes.length; i++) {
      var a = el.attributes[i];
      if (a.name === "contenteditable" || a.name === "spellcheck") continue;
      s += " " + a.name + '="' + a.value + '"';
    }
    s += ">";
    return s.length > 120 ? s.slice(0, 119) + "…" : s;
  }

  /* ------------------------------------------------------------ live wiring */

  /* The shell runs on the review server; this page is served 100 ports above it.
     Only those three spellings of the shell's own origin may talk to us. */
  var SHELL_PORT = Number(location.port) - 100;
  var ORIGINS = ["http://127.0.0.1:" + SHELL_PORT, "http://localhost:" + SHELL_PORT,
                 "http://[::1]:" + SHELL_PORT];

  var shellOrigin = null;   /* fixed by the first accepted init */
  var mode = "use";
  var stops = [];           /* [{key, kind, id, n, first, pieces, caret}] in document order */
  var boxes = [];           /* what the last redraw drew, for hit-testing */
  var drawnOnce = false;
  var lastDraw = null;      /* the last draw message, re-run when an edit round posts nothing */
  var openId = null;
  var pulseKey = null, pulseTimer = null;
  var redrawTimer = null;
  var lastScrollPost = 0;
  var touched = [];         /* elements whose original markup we saved (el.__rdOrig) */
  var pending = null, pendingSel = null;   /* last committed edit the shell has not named yet */
  var editing = null, startHTML = "", startText = "";
  var host = null, root = null, boxWrap = null;

  function post(type, fields) {
    if (!shellOrigin || window.parent === window) return;
    var m = {rd: 1, type: type}, k;
    for (k in (fields || {})) m[k] = fields[k];
    window.parent.postMessage(m, shellOrigin);
  }

  function onMessage(ev) {
    if (ev.source !== window.parent) return;
    if (ORIGINS.indexOf(ev.origin) === -1) return;
    if (shellOrigin && ev.origin !== shellOrigin) return;
    var m = ev.data;
    if (!m || typeof m !== "object" || m.rd !== 1) return;
    if (!shellOrigin) {
      if (m.type !== "init") return;
      shellOrigin = ev.origin;
    }
    if (m.type === "init") {
      setMode(m.mode);
      post("hello", {path: ENTRY_PATH, title: document.title});
    } else if (m.type === "mode") {
      setMode(m.mode);
    } else if (m.type === "draw") {
      onDraw(m);
    } else if (m.type === "scroll-to") {
      scrollToStop(m.key);
    } else if (m.type === "open") {
      openId = m.id == null ? null : m.id;
      redraw();
    } else if (m.type === "clear-selection") {
      var s = window.getSelection();
      if (s) s.removeAllRanges();
      openId = null;
      redraw();
    }
  }

  function setMode(m) {
    if (m !== "use" && m !== "comment" && m !== "edit") return;
    if (m === mode) return;   /* a repeat must not end an edit in progress */
    if (editing) commit();
    mode = m;
    if (drawnOnce) redraw();
  }

  /* ---------------------------------------------------------------- the layer */

  var LAYER_CSS =
    ".box { position: fixed; box-sizing: border-box; pointer-events: none; margin: 0; padding: 0; }\n" +
    ".comment { background: rgba(217,166,46,.22); border-bottom: 2px solid #D9A62E; }\n" +
    ".comment.open { background: rgba(217,166,46,.45); }\n" +
    ".run { background: rgba(240,132,78,.26); border-bottom: 2px solid #F0844E; }\n" +
    ".run.open { background: rgba(240,132,78,.45); }\n" +
    ".run.caret { background: #F0844E; border: 0; }\n" +
    "@keyframes nav-pulse {\n" +
    "  0%   { box-shadow: 0 0 0 0 rgba(240, 132, 78, .55); }\n" +
    "  70%  { box-shadow: 0 0 0 10px rgba(240, 132, 78, 0); }\n" +
    "  100% { box-shadow: 0 0 0 0 rgba(240, 132, 78, 0); }\n" +
    "}\n" +
    ".is-target { animation: nav-pulse 1.3s ease-out; border-radius: 4px; }\n" +
    "@media (prefers-reduced-motion: reduce) {\n" +
    "  .is-target { animation: none; outline: 2px solid #F0844E; outline-offset: 3px; }\n" +
    "}\n";

  /* One element on <html>, its shadow root closed so neither the page's CSS nor
     its scripts reach the boxes; it never takes a pointer event. A page that
     rewrites <html> may drop it, so every redraw puts it back. */
  function layer() {
    if (!host) {
      host = document.createElement("review-doc-layer");
      var props = [["all", "initial"], ["position", "fixed"], ["inset", "0"],
                   ["z-index", "2147483647"], ["pointer-events", "none"]];
      for (var i = 0; i < props.length; i++) host.style.setProperty(props[i][0], props[i][1], "important");
      root = host.attachShadow({mode: "closed"});
      var st = document.createElement("style");
      st.textContent = LAYER_CSS;
      root.appendChild(st);
      boxWrap = document.createElement("div");
      root.appendChild(boxWrap);
    }
    if (host.parentNode !== document.documentElement) document.documentElement.appendChild(host);
    return root;
  }

  function nonEmpty(r) {
    return r.width > 0 && r.height > 0;
  }

  /* An element whose whole text was deleted has no line box for its caret, yet
     it must stay clickable for Revert: a thin box at its own left edge, as tall
     as the element or, when it collapsed to nothing, one line. An element that
     is not rendered at all gets no box. */
  function emptyBox(el, out) {
    if (!el || !el.getBoundingClientRect || !el.getClientRects().length) return out;
    var r = el.getBoundingClientRect(), h = r.bottom - r.top;
    if (!(h > 0)) {
      var lh = parseFloat(getComputedStyle(el).lineHeight);
      h = lh > 0 ? lh : 16;
    }
    out.push({left: r.left, right: r.left + 3, top: r.top, bottom: r.top + h});
    return out;
  }

  /* Viewport rectangles of one stop, rebuilt each time (layout moves). */
  function rectsOf(stop) {
    var out = [], i, j;
    if (stop.caret) {
      var rs = stop.caret.range.getClientRects(), b = null;
      for (j = 0; j < rs.length; j++) {
        if (nonEmpty(rs[j])) { b = stop.caret.side === "right" ? rs[j] : (b || rs[j]); }
      }
      if (!b) b = stop.caret.range.getBoundingClientRect();
      if (!b || !b.height) return emptyBox(stop.caret.el, out);
      var x = stop.caret.side === "right" ? b.right : b.left;
      out.push({left: x - 1.5, right: x + 1.5, top: b.top, bottom: b.bottom});
      return out;
    }
    for (i = 0; i < stop.pieces.length; i++) {
      var rects = stop.pieces[i].getClientRects();
      for (j = 0; j < rects.length; j++) {
        var r = rects[j];
        if (nonEmpty(r)) out.push({left: r.left, right: r.right, top: r.top, bottom: r.bottom});
      }
    }
    return out;
  }

  function redraw() {
    clearTimeout(redrawTimer);
    redrawTimer = null;
    if (!drawnOnce) return;
    layer();
    var op = mode === "use" ? ".35" : "1";
    if (host.style.getPropertyValue("opacity") !== op) host.style.setProperty("opacity", op, "important");
    while (boxWrap.lastChild) boxWrap.removeChild(boxWrap.lastChild);
    boxes = [];
    for (var i = 0; i < stops.length; i++) {
      var s = stops[i], rs = rectsOf(s);
      for (var j = 0; j < rs.length; j++) {
        var r = rs[j], d = document.createElement("div");
        d.className = "box " + (s.kind === "comment" ? "comment" : "run") +
                      (s.caret ? " caret" : "") +
                      (openId != null && s.id === openId ? " open" : "") +
                      (pulseKey === s.key ? " is-target" : "");
        d.style.left = r.left + "px";
        d.style.top = r.top + "px";
        d.style.width = (r.right - r.left) + "px";
        d.style.height = (r.bottom - r.top) + "px";
        boxWrap.appendChild(d);
        boxes.push({key: s.key, kind: s.kind, id: s.id, n: s.n, rect: r});
      }
    }
  }

  /* Coalesced: a burst of scroll, resize or DOM changes costs one redraw. */
  function soon() {
    if (!drawnOnce || redrawTimer) return;
    redrawTimer = setTimeout(redraw, 60);
  }

  function onMutations(records) {
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.target === host) continue;
      if (r.type === "childList" && onlyHost(r.addedNodes) && onlyHost(r.removedNodes)) continue;
      soon();
      return;
    }
  }

  function onlyHost(list) {
    for (var i = 0; i < list.length; i++) if (list[i] !== host) return false;
    return true;
  }

  /* ------------------------------------------------------- finding and drawing */

  function bySel(sel) {
    try {
      return sel ? document.querySelector(sel) : null;
    } catch (e) {
      return null;   /* an invalid selector is simply not found */
    }
  }

  /* Live ranges over the real characters of flat[a, b), one per run of
     neighbouring characters in the same text node. Virtual spaces add nothing. */
  function piecesFor(flat, a, b) {
    var spans = [], cur = null, i;
    for (i = a; i < b && i < flat.at.length; i++) {
      var e = flat.at[i];
      if (!e.node) { cur = null; continue; }
      if (cur && cur.node === e.node && cur.end === e.off) {
        cur.end = e.off + e.len;
      } else {
        cur = {node: e.node, start: e.off, end: e.off + e.len};
        spans.push(cur);
      }
    }
    var out = [];
    for (i = 0; i < spans.length; i++) {
      var r = document.createRange();
      r.setStart(spans[i].node, spans[i].start);
      r.setEnd(spans[i].node, spans[i].end);
      out.push(r);
    }
    return out;
  }

  function charRange(e) {
    var r = document.createRange();
    r.setStart(e.node, e.off);
    r.setEnd(e.node, e.off + e.len);
    return r;
  }

  /* Where a pure deletion sits in the shown text: right after the character
     before it, else right before the character after it, else the element. */
  function caretFor(el, flat, p) {
    if (p > 0 && flat.at[p - 1] && flat.at[p - 1].node) return {range: charRange(flat.at[p - 1]), side: "right", el: el};
    if (flat.at[p] && flat.at[p].node) return {range: charRange(flat.at[p]), side: "left", el: el};
    var r = document.createRange();
    r.selectNodeContents(el);
    return {range: r, side: "left", el: el};
  }

  function saveOrig(el) {
    if (el.__rdOrig === undefined) {
      el.__rdOrig = el.innerHTML;
      touched.push(el);
    }
  }

  /* The flat text of an element's original markup, read off a detached copy.
     The copy lives in an inert document, so its images do not load and its
     inline handlers do not fire a second time. */
  function origFlat(el) {
    if (el.__rdOrig === undefined) return flatText(el);
    var copy = document.implementation.createHTMLDocument("").createElement(el.tagName);
    copy.innerHTML = el.__rdOrig;
    return flatText(copy);
  }

  function idInUse(id) {
    for (var i = 0; i < touched.length; i++) if (touched[i].__rdEdit === id) return touched[i];
    return null;
  }

  /* Decision 10 for every stored edit, plus naming the last commit (decision 11)
     and putting back elements whose edit left the state (undo, reset). Returns
     [{edit, el}] for the edits whose element was found. */
  function applyEdits(edits) {
    var ids = {}, i, found = [];
    for (i = 0; i < edits.length; i++) ids[edits[i].id] = true;
    if (pending) {
      for (i = 0; i < edits.length; i++) {
        if (edits[i].sel === pendingSel && !idInUse(edits[i].id)) {
          pending.__rdEdit = edits[i].id;
          pending = pendingSel = null;
          break;
        }
      }
    }
    for (i = 0; i < touched.length; i++) {
      var t = touched[i];
      if (t.__rdEdit && !ids[t.__rdEdit] && t !== editing) {
        t.__rdEdit = null;
        if (t.innerHTML !== t.__rdOrig) t.innerHTML = t.__rdOrig;
      }
    }
    for (i = 0; i < edits.length; i++) {
      var ed = edits[i], el = idInUse(ed.id);
      if (!el) {
        el = bySel(ed.sel);
        if (el && el.__rdEdit && ids[el.__rdEdit] && el.__rdEdit !== ed.id) el = null;
        if (el) {
          saveOrig(el);
          el.__rdEdit = ed.id;
        }
      }
      if (!el) continue;
      if (el !== editing && flatText(el).text !== ed.neu) {
        if (el.innerHTML !== el.__rdOrig) el.innerHTML = el.__rdOrig;
        if (flatText(el).text !== ed.alt) continue;   /* the page changed under us */
        if (ed.fine) retext(el, ed.fine);
        else el.textContent = ed.neu;   /* no runs (diff refused): plain text is all we have */
      }
      found.push({edit: ed, el: el});
    }
    return found;
  }

  function markStop(mk) {
    var el = bySel(mk.sel);
    if (!el || !mk.quote) return null;
    var flat = flatText(el), at = nthIndex(flat.text, mk.quote, mk.occ || 0);
    if (at === -1) at = flat.text.indexOf(mk.quote);
    if (at === -1) return null;
    var pieces = piecesFor(flat, at, at + mk.quote.length);
    if (!pieces.length) return null;
    return {key: "m:" + mk.id, kind: "comment", id: mk.id, n: 0, first: pieces[0], pieces: pieces};
  }

  /* One stop per changed run of the coalesced runs, placed over the shown (neu)
     text: added words get the underline, a pure deletion gets a caret. */
  function editStops(ed, el) {
    var flat = flatText(el), out = [], p = 0, n = 0, i;
    var runs = ed.runs || [{same: false, added: flat.text, removed: ed.alt}];
    for (i = 0; i < runs.length; i++) {
      var r = runs[i];
      if (r.same) { p += r.text.length; continue; }
      var add = r.added || "", st = {key: "e:" + ed.id + ":" + n, kind: "edit", id: ed.id, n: n};
      if (add) {
        st.pieces = piecesFor(flat, p, p + add.length);
        st.first = st.pieces[0];
      } else {
        st.caret = caretFor(el, flat, p);
        st.pieces = [];
        st.first = st.caret.range;
      }
      if (st.first) out.push(st);
      p += add.length;
      n++;
    }
    return out;
  }

  function onDraw(msg) {
    lastDraw = msg;
    var marks = msg.marks || [], edits = msg.edits || [], i, next = [];
    var found = applyEdits(edits);
    for (i = 0; i < marks.length; i++) {
      var ms = markStop(marks[i]);
      if (ms) next.push(ms);
    }
    for (i = 0; i < found.length; i++) next = next.concat(editStops(found[i].edit, found[i].el));
    next.sort(function (a, b) {
      try {
        return a.first.compareBoundaryPoints(Range.START_TO_START, b.first);
      } catch (e) {
        return 0;
      }
    });
    stops = next;
    drawnOnce = true;
    redraw();
    var list = [], rects = {};
    for (i = 0; i < stops.length; i++) {
      list.push({key: stops[i].key, kind: stops[i].kind});
      var rs = rectsOf(stops[i]);
      if (rs.length) rects[stops[i].key] = rs[0];
    }
    post("drawn", {stops: list, rects: rects});
  }

  function scrollToStop(key) {
    var s = null;
    for (var i = 0; i < stops.length; i++) if (stops[i].key === key) s = stops[i];
    if (!s) return;
    var n = s.first.startContainer, el = n.nodeType === 1 ? n : n.parentNode;
    if (el && el.scrollIntoView) el.scrollIntoView({block: "center"});
    pulseKey = key;
    clearTimeout(pulseTimer);
    pulseTimer = setTimeout(function () { pulseKey = null; redraw(); }, 1500);
    redraw();
  }

  /* ------------------------------------------------------------- Comment mode */

  function plainRect(r) {
    return {left: r.left, top: r.top, right: r.right, bottom: r.bottom};
  }

  /* After a mouseup: a real selection of at least two characters inside body
     becomes a `select`. The quote is cut from the anchor's flat text, not from
     Selection.toString(), so the shell can always find it again. */
  function checkSelection() {
    if (mode !== "comment" || editing) return;
    var s = window.getSelection();
    if (!s || s.isCollapsed || !s.rangeCount || !document.body) return;
    var range = s.getRangeAt(0);
    if (!inside(range.commonAncestorContainer, document.body)) return;
    var anchor = passageAnchor(range.commonAncestorContainer);
    if (!anchor) return;
    var flat = flatText(anchor);
    var start = flatIndex(flat, range.startContainer, range.startOffset, true);
    var end = flatIndex(flat, range.endContainer, range.endOffset);
    if (end <= start) return;
    var raw = flat.text.slice(start, end), quote = raw.trim();
    if (quote.length < 2) return;
    start += raw.length - raw.replace(/^\s+/, "").length;
    var occ = 0, at = flat.text.indexOf(quote);
    while (at !== -1 && at < start) {
      occ++;
      at = flat.text.indexOf(quote, at + 1);
    }
    var stop = start + quote.length;
    post("select", {
      quote: quote, occ: occ, rect: plainRect(range.getBoundingClientRect()),
      anchor: {sel: selectorFor(anchor), tag: startTag(anchor), text: flat.text.slice(0, 80),
               before: flat.text.slice(Math.max(0, start - 30), start),
               after: flat.text.slice(stop, stop + 30)}
    });
  }

  function hit(x, y) {
    for (var i = boxes.length - 1; i >= 0; i--) {
      var r = boxes[i].rect;
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return boxes[i];
    }
    return null;
  }

  function commentClick(ev) {
    var s = window.getSelection();
    if (s && !s.isCollapsed) return;   /* the mouseup just made a selection */
    var b = hit(ev.clientX, ev.clientY);
    if (!b) return;
    if (b.kind === "comment") post("mark-click", {id: b.id, rect: plainRect(b.rect)});
    else post("run-click", {id: b.id, n: b.n, rect: plainRect(b.rect)});
  }

  /* ---------------------------------------------------------------- Edit text */

  function caretAt(x, y) {
    if (document.caretRangeFromPoint) return document.caretRangeFromPoint(x, y);
    if (document.caretPositionFromPoint) {
      var p = document.caretPositionFromPoint(x, y);
      if (!p) return null;
      var r = document.createRange();
      r.setStart(p.offsetNode, p.offset);
      r.collapse(true);
      return r;
    }
    return null;
  }

  function startEdit(el, x, y) {
    saveOrig(el);
    editing = el;
    startHTML = el.innerHTML;
    startText = flatText(el).text;
    el.setAttribute("contenteditable", "true");
    el.setAttribute("spellcheck", "false");
    el.focus();
    var r = caretAt(x, y), s = window.getSelection();
    if (r && s && inside(r.startContainer, el)) {
      s.removeAllRanges();
      s.addRange(r);
    }
  }

  function stopEditing() {
    var el = editing;
    editing = null;   /* first, so the focusout that blur fires finds nothing to commit */
    if (el.blur) el.blur();
    el.removeAttribute("contenteditable");
    el.removeAttribute("spellcheck");
    return el;
  }

  /* Typing, or restoring startHTML, replaces the text nodes the stops' live
     ranges point at, so they collapse. When no edit is posted, no draw will
     follow; rebuild the stops from the last one ourselves. */
  function drawAgain() {
    if (lastDraw) onDraw(lastDraw);
  }

  function commit() {
    if (!editing) return;
    var el = stopEditing();
    var neu = flatText(el).text, alt = origFlat(el).text;
    if (neu === startText || (!el.__rdEdit && neu === alt)) {
      drawAgain();                              /* nothing to post in this round */
      return;
    }
    var sel = selectorFor(el);
    if (!el.__rdEdit) {
      pending = el;
      pendingSel = sel;
    }
    post("edit", {id: el.__rdEdit || null, alt: alt, neu: neu,
                  anchor: {sel: sel, tag: startTag(el), text: alt.slice(0, 80)}});
  }

  function cancelEdit() {
    if (!editing) return;
    var el = editing;
    /* Escape without typing leaves the markup alone: reassigning it would
       replace the descendants and drop the page's listeners on them. */
    if (el.innerHTML !== startHTML) el.innerHTML = startHTML;
    stopEditing();
    drawAgain();
  }

  function editClick(ev) {
    if (editing && inside(ev.target, editing)) return;   /* moving the caret */
    if (editing) commit();
    var el = editTarget(ev.target);
    if (el) startEdit(el, ev.clientX, ev.clientY);
  }

  function onBeforeInput(ev) {
    if (!editing || !inside(ev.target, editing)) return;
    ev.stopImmediatePropagation();
    var t = String(ev.inputType || "");
    if (t === "insertFromPaste") {
      /* Paste is plain text on one line; insertText keeps the browser's own undo. */
      ev.preventDefault();
      var text = ev.dataTransfer ? ev.dataTransfer.getData("text/plain") : "";
      if (text) document.execCommand("insertText", false, text.replace(/\s+/g, " "));
      return;
    }
    if (t.indexOf("format") === 0 || t === "insertParagraph" || t === "insertLineBreak" ||
        t === "insertFromDrop" || t === "deleteByDrag") {
      ev.preventDefault();
    }
  }

  function onInput(ev) {
    if (editing && inside(ev.target, editing)) ev.stopImmediatePropagation();
  }

  function onFocusOut(ev) {
    if (editing && ev.target === editing) commit();
  }

  /* ------------------------------------------------------------- the events */

  /* Use mode: a link to another origin opens in a new tab, so the frame never
     shows a page that has no probe. Same-origin links navigate the frame. */
  function followOut(ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
    if (!a) return;
    var url;
    try {
      url = new URL(a.getAttribute("href"), document.baseURI);
    } catch (e) {
      return;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return;
    if (url.origin === location.origin) {
      /* _top or _parent would take the review shell itself away; keep it in the frame.
         A link without its own target takes the page's <base target>. */
      var raw = a.getAttribute("target");
      if (raw === null) {
        var base = document.querySelector("base[target]");
        if (base) raw = base.getAttribute("target");
      }
      var tgt = String(raw || "").toLowerCase();
      if (tgt === "_top" || tgt === "_parent") {
        ev.preventDefault();
        location.href = a.href;
      }
      return;
    }
    ev.preventDefault();
    window.open(url.href, "_blank", "noopener");
  }

  /* click, dblclick, auxclick and submit. Use mode leaves the page alone; Comment
     and Edit text swallow them before any page listener (decision 14), except
     one Alt+click in Comment mode. */
  function onClick(ev) {
    if (mode === "use") {
      if (ev.type === "click") followOut(ev);
      return;
    }
    if (mode === "comment" && ev.type === "click" && ev.altKey) return;
    ev.stopImmediatePropagation();
    ev.preventDefault();
    if (ev.type !== "click") return;
    if (mode === "comment") commentClick(ev);
    else editClick(ev);
  }

  function typingInPageField(t) {
    var tag = tagOf(t);
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || !!(t && t.isContentEditable);
  }

  function onKey(ev) {
    if (editing && inside(ev.target, editing)) {
      ev.stopImmediatePropagation();
      if (ev.type !== "keydown") return;
      var mod = ev.ctrlKey || ev.metaKey;
      if (ev.key === "Enter") {
        ev.preventDefault();
        commit();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        cancelEdit();
      } else if (mod && /^[biu]$/i.test(ev.key)) {
        ev.preventDefault();
      }
      return;
    }
    if (ev.type !== "keydown") return;
    var k = String(ev.key || "").toLowerCase();
    if ((ev.ctrlKey || ev.metaKey) && (k === "z" || k === "y")) {
      /* The page's own form fields keep their native undo, in every mode. */
      if (typingInPageField(ev.target)) return;
      ev.preventDefault();
      post("key", {key: k, shift: !!ev.shiftKey});
    } else if (ev.key === "Escape") {
      post("key", {key: "Escape"});
    }
  }

  function onMouseDown() {
    post("down");
  }

  function onMouseUp() {
    if (mode === "comment") setTimeout(checkSelection, 10);
  }

  /* Only a scroll that moves the text the bubbles point at closes them: the page
     itself, or a scroller holding a stop. A carousel or ticker elsewhere scrolls
     every few hundred ms and would close a comment while it is being typed. */
  function movesStops(t) {
    if (!t || t === document || t === document.documentElement || t === document.body ||
        t === document.scrollingElement) return true;
    if (!t.contains) return false;
    for (var i = 0; i < stops.length; i++) {
      if (stops[i].first && t.contains(stops[i].first.startContainer)) return true;
    }
    return false;
  }

  function onScroll(ev) {
    soon();
    if (!movesStops(ev && ev.target)) return;
    var now = Date.now();
    if (now - lastScrollPost >= 200) {
      lastScrollPost = now;
      post("scroll");
    }
  }

  /* Registered when the probe loads, before any page script, on window in the
     capture phase, so ours run first and can stop the page's own listeners. */
  window.addEventListener("message", onMessage);
  window.addEventListener("click", onClick, true);
  window.addEventListener("dblclick", onClick, true);
  window.addEventListener("auxclick", onClick, true);
  window.addEventListener("submit", onClick, true);
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("keyup", onKey, true);
  window.addEventListener("keypress", onKey, true);
  window.addEventListener("beforeinput", onBeforeInput, true);
  window.addEventListener("input", onInput, true);
  window.addEventListener("focusout", onFocusOut, true);
  window.addEventListener("mousedown", onMouseDown, true);
  window.addEventListener("mouseup", onMouseUp, true);
  window.addEventListener("scroll", onScroll, {capture: true, passive: true});
  window.addEventListener("resize", soon);
  window.addEventListener("pagehide", function () { post("bye"); });
  new MutationObserver(onMutations).observe(document.documentElement,
    {subtree: true, childList: true, characterData: true, attributes: true});

  window.__reviewDocProbe = {phase: 3};
})();
