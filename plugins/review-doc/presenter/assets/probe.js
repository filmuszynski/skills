/* review-doc probe (1.2). Runs inside the reviewed page, on the page's own origin.
 * This file holds the probe's pure text helpers (flat text, retext, edit target,
 * passage anchor, selectors). They touch only nodeType, nodeValue, tagName,
 * childNodes, parentNode, attributes, id and className, so node tests can run
 * them on plain fake trees. The live wiring (channel, marks, editing) comes next. */
(function () {
  "use strict";

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
        } else if (k.nodeType === 1 && !SKIP[tagOf(k)]) {
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
     text.length past the end. */
  function flatIndex(flat, node, off) {
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
    return last + 1;
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
      var target = null, pos = 0;
      if (s.p > 0 && flat.at[s.p - 1] && flat.at[s.p - 1].node) {
        e = flat.at[s.p - 1];
        target = e.node;
        pos = e.off + e.len;
      } else if (flat.at[s.p] && flat.at[s.p].node) {
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
      if (k.nodeType === 1 && !INLINE[tagOf(k)] && !SKIP[tagOf(k)]) blockKid = true;
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
    var tag = String(el.tagName).toLowerCase(), s = tag, cls = String(el.className || "").trim();
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

  window.__reviewDocProbe = {phase: 3};
})();
