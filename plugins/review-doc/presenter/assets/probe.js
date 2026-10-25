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
    var chars = [], at = [], first = new Map();
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
                if (!first.has(k)) first.set(k, at.length - 1);
              } else if (lastIsSpace() && at[at.length - 1].node === k) {
                at[at.length - 1].len += j - s;
              }
            } else {
              chars.push(c);
              at.push({node: k, off: j, len: 1});
              if (!first.has(k)) first.set(k, at.length - 1);
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
      var gone = at.pop();
      if (gone.node && first.get(gone.node) === at.length) first.delete(gone.node);
    }
    /* `first` maps a text node to its first entry in `at`, so flatIndex need not
       scan the whole list for every boundary point. */
    return {text: chars.join(""), at: at, first: first};
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
    var last = -1, i, idx;
    if (node.nodeType === 3 && flat.first && flat.first.has(node)) {
      /* A text node's entries are contiguous: count the ones before `off`. With
         none counted, the point sits after the last real entry before them. */
      i = flat.first.get(node);
      var k = i;
      while (k < flat.at.length && flat.at[k].node === node && flat.at[k].off < off) k++;
      if (k === i) {
        k = i - 1;
        while (k >= 0 && !flat.at[k].node) k--;
        k++;
      }
      idx = k;
      if (isStart) while (idx < flat.at.length && !flat.at[idx].node) idx++;
      return idx;
    }
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
    idx = last + 1;
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

  /* ---------------------------------------------------------- finding again */

  /* Does an element's text still begin as it did when the item was stored? Twenty
     characters survive a typo fixed later in the sentence and still reject a
     different paragraph. */
  function startMatches(stored, now) {
    stored = String(stored || "");
    now = String(now || "");
    var n = Math.min(20, stored.length);
    return now.slice(0, n) === stored.slice(0, n);
  }

  /* "p" out of '<p class="lead">'; "" when it does not parse. */
  function tagNameOf(startTag) {
    var m = /^<\s*([a-zA-Z][a-zA-Z0-9-]*)/.exec(String(startTag || ""));
    return m ? m[1].toLowerCase() : "";
  }

  function commonSuffix(a, b) {
    var n = 0;
    while (n < a.length && n < b.length && a.charAt(a.length - 1 - n) === b.charAt(b.length - 1 - n)) n++;
    return n;
  }

  function commonPrefix(a, b) {
    var n = 0;
    while (n < a.length && n < b.length && a.charAt(n) === b.charAt(n)) n++;
    return n;
  }

  /* How well the words around the quote at `at` match the stored surroundings. */
  function contextScore(text, at, quote, before, after) {
    return commonSuffix(String(before || ""), text.slice(0, at)) +
           commonPrefix(String(after || ""), text.slice(at + quote.length));
  }

  /* The occurrence of `quote` in `text` whose surroundings match best; ties go to
     the first. -1 when there is none. */
  function bestOccurrence(text, quote, before, after) {
    var best = -1, bestScore = -1, from = 0, at;
    while ((at = text.indexOf(quote, from)) !== -1) {
      var sc = contextScore(text, at, quote, before, after);
      if (sc > bestScore) { best = at; bestScore = sc; }
      from = at + 1;
    }
    return best;
  }

  /* Where a stored comment lives now. Four steps, each weaker than the last:
     1. the stored selector, if the element still starts as it did (its original
        text, when the probe has saved one, so the reviewer's own rewrite of the
        start does not count against it) and still holds the quote;
     2. the first element of the same tag that does;
     3. the quote anywhere in the body, taking the occurrence whose surroundings
        match best;
     4. nowhere: null.
     `env` is {bySel, byTag, body, flatOf, origOf}. `at` is the flat index of the
     quote in the flat text of `el`. */
  function findMark(mk, env) {
    var quote = mk && mk.quote;
    if (!quote) return null;
    function check(el) {
      if (!el) return null;
      var live = env.flatOf(el), orig = env.origOf ? env.origOf(el) : null;
      /* The stored text is the live text when the comment was made, which may
         already carry the reviewer's own rewrite: either reading passes. */
      if (!startMatches(mk.text, live.text) && !(orig && startMatches(mk.text, orig.text))) return null;
      if (live.text.indexOf(quote) === -1) return null;
      var at = nthIndex(live.text, quote, mk.occ || 0);
      return at === -1 ? live.text.indexOf(quote) : at;
    }
    var el = env.bySel(mk.sel), at = check(el), i;
    if (at !== null) return {el: el, at: at, step: 1};
    var name = tagNameOf(mk.tag), list = name ? env.byTag(name) : [];
    for (i = 0; i < list.length; i++) {
      at = check(list[i]);
      if (at !== null) return {el: list[i], at: at, step: 2};
    }
    var flat = env.flatOf(env.body), b = bestOccurrence(flat.text, quote, mk.before, mk.after);
    if (b === -1) return null;
    var k = b;
    while (k < b + quote.length && !flat.at[k].node) k++;
    var entry = flat.at[k];
    if (!entry || !entry.node) return null;
    el = passageAnchor(entry.node);
    var f2 = env.flatOf(el);
    /* A quote that runs across blocks is not inside the first one: widen. */
    while (f2.text.indexOf(quote) === -1 && el.parentNode && el !== env.body) {
      el = el.parentNode;
      f2 = env.flatOf(el);
    }
    for (i = 0; i < f2.at.length; i++) {
      if (f2.at[i].node === entry.node && f2.at[i].off === entry.off) break;
    }
    at = i < f2.at.length ? i : bestOccurrence(f2.text, quote, mk.before, mk.after);
    if (at === -1) return null;
    return {el: el, at: at, step: 3};
  }

  /* An element whose original markup reads as one of `texts`: the one already tied
     to the rewrite (idInUse), then the stored selector, then the first of the same
     tag in document order. Elements in `claimed` (keyed by env.keyOf, plus
     `prefix`) are taken; a hit is claimed here. `which` is the index in `texts`. */
  function editHost(ed, env, claimed, prefix, texts) {
    function test(el) {
      if (!el) return -1;
      var f = env.origOf ? env.origOf(el) : null, t = (f || env.flatOf(el)).text, i;
      for (i = 0; i < texts.length; i++) if (t === texts[i]) return i;
      return -1;
    }
    function take(el, step, which) {
      claimed[prefix + env.keyOf(el)] = true;
      return {el: el, step: step, which: which};
    }
    var el = null, hit, i;
    if (env.idInUse && ed.id !== undefined) {
      el = env.idInUse(ed.id);
      if (el && !claimed[prefix + env.keyOf(el)] && (hit = test(el)) !== -1) return take(el, 1, hit);
    }
    el = env.bySel(ed.sel);
    if (el && !claimed[prefix + env.keyOf(el)] && (hit = test(el)) !== -1) return take(el, 1, hit);
    var name = tagNameOf(ed.tag), list = name ? env.byTag(name) : [];
    for (i = 0; i < list.length; i++) {
      if (claimed[prefix + env.keyOf(list[i])]) continue;
      if ((hit = test(list[i])) !== -1) return take(list[i], 2, hit);
    }
    return null;
  }

  /* Where a stored rewrite lives now: an element showing `alt` (still to apply) or
     `neu` (the page already carries it, so `adopted`). Steps 1 and 2 only. */
  function findEdit(ed, env, claimed) {
    var h = editHost(ed, env, claimed, "", [ed.alt, ed.neu]);
    return h ? {el: h.el, step: h.step, adopted: h.which === 1} : null;
  }

  /* An earlier round's rewrite: only where the element already shows `neu`, and
     only when there are runs to tint. Its claims are kept apart from the current
     rewrites', since a reviewer may rewrite the same words again. */
  function findEarlierEdit(ed, env, claimed) {
    if (!ed.offs || !ed.offs.length) return null;
    var h = editHost({sel: ed.sel, tag: ed.tag}, env, claimed, "earlier:", [ed.neu]);
    return h ? {el: h.el, step: h.step} : null;
  }

  /* A triple click ends at offset 0 of the next block, and so does a drag over
     several blocks released at the start of the one after. Pull the end back to
     the end of the last text before the end point in document order: a triple
     click then ends in its own block, so the passage anchor is that block and
     not the common parent, and a drag keeps every block it covered (ruling 11).
     Blank text between blocks does not count; it would put the end back into
     the common parent. */
  function pullEndBack(range) {
    if (range.endOffset !== 0) return;
    var block = passageAnchor(range.startContainer);
    if (!block || inside(range.endContainer, block)) return;
    function filled(k) { return /\S/.test(String(k.nodeValue)); }
    function lastText(n) {
      if (n.nodeType === 3) return filled(n) ? n : null;
      if (n.nodeType !== 1 || SKIP[tagOf(n)]) return null;
      var kids = n.childNodes || [], i, t;
      for (i = kids.length - 1; i >= 0; i--) {
        t = lastText(kids[i]);
        if (t) return t;
      }
      return null;
    }
    function prevSibling(n) {
      var kids = n.parentNode ? n.parentNode.childNodes : [], i;
      for (i = 1; i < kids.length; i++) if (kids[i] === n) return kids[i - 1];
      return null;
    }
    var n = range.endContainer, t = null, p;
    while (n && !t && tagOf(n) !== "BODY") {
      p = prevSibling(n);
      while (!p && n.parentNode && tagOf(n) !== "BODY") {
        n = n.parentNode;
        if (tagOf(n) !== "BODY") p = prevSibling(n);  /* never walk out of body */
      }
      if (!p) break;
      t = lastText(p);
      n = p;
    }
    if (t) range.setEnd(t, String(t.nodeValue).length);
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
  var rectsPosted = {}, rectsNext = null, rectsTimer = null, lastRectsPost = 0;
  var keySeq = 0;
  var touched = [];         /* elements whose original markup we saved (el.__rdOrig) */
  var pending = null, pendingSel = null;   /* last committed edit the shell has not named yet */
  var editing = null, startHTML = "", startText = "";
  var host = null, root = null, boxWrap = null;
  var creditHost = null, creditRoot = null;

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
      setCredit(m.credit);
      post("hello", {path: ENTRY_PATH, title: document.title});
    } else if (m.type === "mode") {
      setMode(m.mode);
    } else if (m.type === "draw") {
      onDraw(m);
    } else if (m.type === "scroll-to") {
      scrollToStop(m.key);
    } else if (m.type === "open") {
      /* A current item's id, or an earlier item's key (isOpen tells them apart). */
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
    ".box { position: absolute; box-sizing: border-box; pointer-events: none; margin: 0; padding: 0; }\n" +
    ".comment { background: rgba(217,166,46,.22); border-bottom: 2px solid #D9A62E; }\n" +
    ".comment.open { background: rgba(217,166,46,.45); }\n" +
    ".run { background: rgba(240,132,78,.26); border-bottom: 2px solid #F0844E; }\n" +
    ".run.open { background: rgba(240,132,78,.45); }\n" +
    ".run.caret { background: #F0844E; border: 0; }\n" +
    /* md's cut mark: the scissors over a place where words were only removed. */
    ".run.caret::after { content: \"\\2702\"; position: absolute; left: 4px; top: -7px;" +
    " font: 9px/1 sans-serif; color: #B8500F; }\n" +
    /* Earlier rounds: the tint of md's mark.prev-comment and mark.prev-edit, no line. */
    ".prev-comment { background: rgba(217, 166, 46, .11); }\n" +
    ".prev-comment.open { background: rgba(217, 166, 46, .2); }\n" +
    ".prev-edit { background: rgba(240, 132, 78, .13); }\n" +
    ".prev-edit.open { background: rgba(240, 132, 78, .24); }\n" +
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
     its scripts reach the boxes; it never takes a pointer event. It is a
     zero-size box at the page origin, so the page's own scroll carries the boxes
     with the text. A page that rewrites <html> may drop it, so every redraw puts
     it back. */
  function layer() {
    if (!host) {
      host = document.createElement("review-doc-layer");
      var props = [["all", "initial"], ["position", "absolute"], ["left", "0"], ["top", "0"],
                   ["width", "0"], ["height", "0"], ["overflow", "visible"],
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

  /* The shell's credit line, after the page's own content: the last child of
     <html>, so it follows <body> whatever the body's layout. Closed shadow,
     like the layer; nothing in it is page text, so it is never selected,
     commented on or rewritten. */
  var CREDIT_CSS =
    ":host { display: block; }\n" +
    ".credit { display: flex; justify-content: center; padding: 32px 16px 40px;" +
    " font: 13px/1.5 system-ui, -apple-system, 'Segoe UI', sans-serif; color: #6f675c;" +
    " user-select: none; -webkit-user-select: none; }\n" +
    ".credit-capsule { display: inline-flex; flex-wrap: wrap; justify-content: center;" +
    " border: 1px solid #d9d3c8; border-radius: 999px; overflow: hidden; background: #F6F4EF; }\n" +
    ".credit-seg { padding: .3em 1.1em; font: inherit; color: inherit; background: none; border: 0;" +
    " text-decoration: none; white-space: nowrap; transition: background-color .15s ease, color .15s ease; }\n" +
    ".credit-seg + .credit-seg { border-left: 1px solid #d9d3c8; }\n" +
    ".credit-seg:first-child { color: #b5562a; }\n" +
    "a.credit-seg:hover, .credit-settings:hover { background: #efeae0; color: #b5562a; }\n" +
    ".credit-seg:focus-visible { outline: 2px solid #F0844E; outline-offset: -2px; }\n" +
    ".credit-settings { cursor: pointer; }\n" +
    ".credit-gear { width: 1.2em; height: 1.2em; margin-right: .35em; vertical-align: -.25em; fill: none;" +
    " stroke: currentColor; stroke-width: 1.3; stroke-linejoin: round; transition: transform .3s ease; }\n" +
    ".credit-settings:hover .credit-gear { transform: rotate(45deg); }\n" +
    ".credit-settings[aria-disabled=\"true\"] { opacity: .55; cursor: default; background: none; color: inherit; }\n" +
    "@media (prefers-reduced-motion: reduce) { .credit-seg, .credit-gear { transition: none; } }\n";

  function setCredit(html) {
    if (typeof html !== "string" || !html || !document.documentElement) return;
    if (!creditHost) {
      creditHost = document.createElement("review-doc-credit");
      creditHost.style.setProperty("all", "initial", "important");
      creditHost.style.setProperty("display", "block", "important");
      creditRoot = creditHost.attachShadow({mode: "closed"});
      creditRoot.addEventListener("click", onCreditClick);
    }
    creditRoot.innerHTML = "<style>" + CREDIT_CSS + "</style><div class=\"credit\">" + html + "</div>";
    placeCredit();
  }

  /* A page that rewrites <html> may drop it; every redraw puts it back. */
  function placeCredit() {
    var de = document.documentElement;
    if (creditHost && de && creditHost.parentNode !== de) de.appendChild(creditHost);
  }

  /* Its links open as links do (onClick lets every click on it through); its
     Settings part opens the shell's panel next to it. */
  function onCreditClick(ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest("#open-settings") : null;
    if (!b || b.getAttribute("aria-disabled") === "true") return;
    post("settings", {rect: plainRect(b.getBoundingClientRect())});
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

  /* Is this stop's item the one the shell has open? Current items are named by
     id, earlier ones by their item key. */
  function isOpen(s) {
    if (openId == null) return false;
    return s.earlier ? s.key === openId : s.id === openId;
  }

  /* Draws every stop and returns {stop key: first rect}. Earlier boxes go in
     first, so a current box on the same words paints over them. `quiet` (from
     onDraw) leaves the rects to the drawn message; otherwise a change in any
     first rect is posted as `rects`. */
  function redraw(quiet) {
    clearTimeout(redrawTimer);
    redrawTimer = null;
    if (!drawnOnce) return {};
    layer();
    placeCredit();
    var op = mode === "use" ? ".35" : "1";
    if (host.style.getPropertyValue("opacity") !== op) host.style.setProperty("opacity", op, "important");
    while (boxWrap.lastChild) boxWrap.removeChild(boxWrap.lastChild);
    boxes = [];
    /* Rects are viewport ones; the boxes are placed from the layer's own corner. */
    var o = host.getBoundingClientRect();
    var firsts = {}, pass, i, j;
    for (pass = 0; pass < 2; pass++) {
      for (i = 0; i < stops.length; i++) {
        var s = stops[i], rs;
        if (!!s.earlier !== (pass === 0)) continue;
        rs = rectsOf(s);
        if (rs.length) firsts[s.key] = rs[0];
        for (j = 0; j < rs.length; j++) {
          var r = rs[j], d = document.createElement("div");
          d.className = "box " +
                        (s.earlier ? (s.kind === "comment" ? "prev-comment" : "prev-edit")
                                   : (s.kind === "comment" ? "comment" : "run")) +
                        (s.caret ? " caret" : "") +
                        (isOpen(s) ? " open" : "") +
                        (pulseKey === s.key ? " is-target" : "");
          d.style.left = (r.left - o.left) + "px";
          d.style.top = (r.top - o.top) + "px";
          d.style.width = (r.right - r.left) + "px";
          d.style.height = (r.bottom - r.top) + "px";
          boxWrap.appendChild(d);
          boxes.push({key: s.key, kind: s.kind, id: s.id, n: s.n, earlier: !!s.earlier, rect: r});
        }
      }
    }
    if (quiet !== true) postRects(firsts);
    return firsts;
  }

  function sameRects(a, b) {
    var k;
    for (k in a) {
      var x = a[k], y = b[k];
      if (!y || x.left !== y.left || x.top !== y.top || x.right !== y.right || x.bottom !== y.bottom) return false;
    }
    for (k in b) if (!(k in a)) return false;
    return true;
  }

  /* The shell keeps the first rect of every stop to place its bubbles. After a
     redraw that moved any of them, send the new set: at most one message per
     200 ms, and the last change in a burst is always sent. */
  function postRects(firsts) {
    rectsNext = firsts;
    if (rectsTimer) return;   /* the trailing call will send the newest set */
    if (sameRects(firsts, rectsPosted)) return;
    var wait = 200 - (Date.now() - lastRectsPost);
    if (wait <= 0) flushRects();
    else rectsTimer = setTimeout(flushRects, wait);
  }

  function flushRects() {
    clearTimeout(rectsTimer);
    rectsTimer = null;
    if (!rectsNext || sameRects(rectsNext, rectsPosted)) return;
    lastRectsPost = Date.now();
    rectsPosted = rectsNext;
    post("rects", {rects: rectsNext});
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
    for (var i = 0; i < list.length; i++) if (list[i] !== host && list[i] !== creditHost) return false;
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

  /* A stable name for an element within this page load, for the claims. */
  function keyOf(el) {
    if (!el.__rdKey) el.__rdKey = ++keySeq;
    return String(el.__rdKey);
  }

  /* The live document as the lookup helpers see it, built once per draw. The
     body's flat text is kept for the draw, since step 3 reads it for every mark;
     `settle` drops it after the rewrites have changed the page. */
  function liveEnv() {
    var bodyFlat = null, env = {
      bySel: bySel,
      byTag: function (name) {
        return Array.prototype.slice.call(document.getElementsByTagName(name));
      },
      body: document.body,
      flatOf: function (el) {
        if (el !== document.body) return flatText(el);
        if (!bodyFlat) bodyFlat = flatText(el);
        return bodyFlat;
      },
      origOf: function (el) {
        return el.__rdOrig === undefined ? null : origFlat(el);
      },
      keyOf: keyOf,
      idInUse: idInUse,
      settle: function () { bodyFlat = null; }
    };
    return env;
  }

  /* [start, end] of one entry of `offs`, which the channel sends as pairs;
     runOffsets' own {s, e} shape is read too. */
  function offPair(o) {
    if (!o) return null;
    if (o.length === 2) return [o[0], o[1]];
    if (typeof o.s === "number") return [o.s, o.e];
    return null;
  }

  /* Live ranges over every `offs` range of the flat text, in order. */
  function offPieces(flat, offs) {
    var out = [], i;
    for (i = 0; i < (offs || []).length; i++) {
      var o = offPair(offs[i]);
      if (o && o[1] > o[0]) out = out.concat(piecesFor(flat, o[0], o[1]));
    }
    return out;
  }

  /* Decision 10 for every stored edit, plus naming the last commit (decision 11)
     and putting back elements whose edit left the state (undo, reset). The host
     element comes from findEdit (decision 4), whose claims live in `claimed` for
     the whole draw. Records each edit in `found` and returns [{edit, el, adopted}]
     for the edits whose element was found. */
  function applyEdits(edits, env, claimed, found) {
    var ids = {}, i, j, out = [];
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
      var ed = edits[i], key = "e:" + ed.id, f = findEdit(ed, env, claimed);
      if (!f) {
        found[key] = {step: 0, sel: ed.sel};
        continue;
      }
      var el = f.el;
      /* The rewrite now hangs on this element: no other one may still carry it. */
      for (j = 0; j < touched.length; j++) {
        var o = touched[j];
        if (o !== el && o.__rdEdit === ed.id) {
          o.__rdEdit = null;
          if (o !== editing && o.innerHTML !== o.__rdOrig) o.innerHTML = o.__rdOrig;
        }
      }
      saveOrig(el);
      el.__rdEdit = ed.id;
      if (el !== editing) {
        if (f.adopted) {
          /* The page's own markup already reads `neu`: show it as it is. */
          if (el.innerHTML !== el.__rdOrig) el.innerHTML = el.__rdOrig;
        } else if (flatText(el).text !== ed.neu) {
          if (el.innerHTML !== el.__rdOrig) el.innerHTML = el.__rdOrig;
          if (flatText(el).text !== ed.alt) {   /* the page changed under us */
            found[key] = {step: 0, sel: ed.sel};
            continue;
          }
          if (ed.fine) retext(el, ed.fine);
          else el.textContent = ed.neu;   /* no runs (diff refused): plain text is all we have */
        }
      }
      found[key] = {step: f.step, sel: selectorFor(el)};
      if (f.adopted) found[key].adopted = true;
      out.push({edit: ed, el: el, adopted: f.adopted});
    }
    return out;
  }

  /* A comment's stop, wherever findMark puts it now (decision 3). An earlier
     round's comment is keyed by its item key and drawn as tint. */
  function markStop(mk, env, found, earlier) {
    var key = earlier ? mk.key : "m:" + mk.id, f = findMark(mk, env);
    if (!f) {
      found[key] = {step: 0, sel: mk.sel};
      return null;
    }
    found[key] = {step: f.step, sel: selectorFor(f.el)};
    var pieces = piecesFor(env.flatOf(f.el), f.at, f.at + mk.quote.length);
    if (!pieces.length) return null;
    var st = {key: key, kind: "comment", id: mk.id, n: 0, first: pieces[0], pieces: pieces};
    if (earlier) st.earlier = true;
    return st;
  }

  /* An earlier round's rewrite: one tinted stop over all its runs, keyed by the
     item key, on the element that shows `neu` now. When that element is being
     rewritten again, its text no longer matches `offs`: the item is listed as
     lost, so it stays reachable from its pill. */
  function earlierEditStop(ed, env, claimed, found) {
    var f = findEarlierEdit(ed, env, claimed), flat = f ? env.flatOf(f.el) : null;
    if (!f || flat.text !== ed.neu) {
      found[ed.key] = {step: 0, sel: ed.sel};
      return null;
    }
    found[ed.key] = {step: f.step, sel: selectorFor(f.el)};
    var pieces = offPieces(flat, ed.offs);
    if (!pieces.length) return null;
    return {key: ed.key, kind: "edit", n: 0, first: pieces[0], pieces: pieces, earlier: true};
  }

  /* One stop per changed run of the coalesced runs, placed over the shown (neu)
     text: added words get the underline, a pure deletion gets a caret. A rewrite
     the page already carries (adopted) has no runs of ours to follow; it gets one
     stop per `offs` range instead. */
  function editStops(ed, el, adopted) {
    var flat = flatText(el), out = [], p = 0, n = 0, i;
    if (adopted) {
      for (i = 0; i < (ed.offs || []).length; i++) {
        var ps = offPieces(flat, [ed.offs[i]]);
        if (ps.length) out.push({key: "e:" + ed.id + ":" + i, kind: "edit", id: ed.id, n: i, first: ps[0], pieces: ps});
      }
      return out;
    }
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

  /* The whole state, drawn afresh: current rewrites applied first (they change
     the page), then current comments, then the earlier rounds as tint. One env
     and one set of claims serve the whole draw. `drawn` names every item's
     lookup step in `found`. */
  function onDraw(msg) {
    lastDraw = msg;
    var marks = msg.marks || [], edits = msg.edits || [], earlier = msg.earlier || [];
    var env = liveEnv(), claimed = {}, found = {}, next = [], i, st;
    var applied = applyEdits(edits, env, claimed, found);
    env.settle();
    for (i = 0; i < marks.length; i++) {
      st = markStop(marks[i], env, found);
      if (st) next.push(st);
    }
    for (i = 0; i < applied.length; i++) {
      next = next.concat(editStops(applied[i].edit, applied[i].el, applied[i].adopted));
    }
    for (i = 0; i < earlier.length; i++) {
      var it = earlier[i];
      if (!it || !it.key) continue;
      st = it.kind === "edit" ? earlierEditStop(it, env, claimed, found) : markStop(it, env, found, true);
      if (st) next.push(st);
    }
    next.sort(function (a, b) {
      try {
        return a.first.compareBoundaryPoints(Range.START_TO_START, b.first);
      } catch (e) {
        return 0;
      }
    });
    stops = next;
    drawnOnce = true;
    var rects = redraw(true), list = [];
    for (i = 0; i < stops.length; i++) {
      var entry = {key: stops[i].key, kind: stops[i].kind};
      if (stops[i].earlier) entry.earlier = true;
      list.push(entry);
    }
    /* `drawn` carries the rects; a pending `rects` from the old stops is moot. */
    clearTimeout(rectsTimer);
    rectsTimer = null;
    rectsNext = null;
    rectsPosted = rects;
    post("drawn", {stops: list, rects: rects, found: found});
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
    /* A copy, so pulling a triple click's end back (decision 13) leaves the
       reader's own selection as it is. */
    var range = s.getRangeAt(0).cloneRange();
    if (!inside(range.commonAncestorContainer, document.body)) return;
    pullEndBack(range);
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

  /* The box under a point. A current box wins over an earlier box at the same
     spot, since the current item is the one the reviewer can still change. */
  function hit(x, y) {
    var prev = null;
    for (var i = boxes.length - 1; i >= 0; i--) {
      var r = boxes[i].rect;
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) {
        if (!boxes[i].earlier) return boxes[i];
        if (!prev) prev = boxes[i];
      }
    }
    return prev;
  }

  function commentClick(ev) {
    var s = window.getSelection();
    if (s && !s.isCollapsed) return;   /* the mouseup just made a selection */
    var b = hit(ev.clientX, ev.clientY);
    if (!b) return;
    if (b.earlier) post("earlier-click", {key: b.key, rect: plainRect(b.rect)});
    else if (b.kind === "comment") post("mark-click", {id: b.id, rect: plainRect(b.rect)});
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
    var s = window.getSelection();
    /* A drag that ended on this element picked its words: keep them selected. */
    if (s && !s.isCollapsed && s.rangeCount) {
      var g = s.getRangeAt(0);
      if (inside(g.startContainer, el) && inside(g.endContainer, el)) return;
    }
    var r = caretAt(x, y);
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

  /* Leaving the page (a link, a reload) must not lose what was typed: an open
     edit is committed before the shell hears `bye` (decision 12). */
  function onPageHide() {
    if (editing) commit();
    post("bye");
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
    if (creditHost && ev.target === creditHost) return;   /* the credit line is ours */
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

  /* A scroll that moves the marked text redraws at once, so the hit areas and an
     inner scroller's boxes keep up with it; any other scroll waits for soon(). */
  function onScroll(ev) {
    if (!movesStops(ev && ev.target)) { soon(); return; }
    redraw();
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
  window.addEventListener("pagehide", onPageHide);
  new MutationObserver(onMutations).observe(document.documentElement,
    {subtree: true, childList: true, characterData: true, attributes: true});

  window.__reviewDocProbe = {phase: 3};
})();
