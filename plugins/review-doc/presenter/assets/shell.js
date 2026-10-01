/* Presenter shell behaviour.
 *
 * Markup contract the layouts must honour:
 *   .sec[data-sec=ID]              a reviewable section, containing .sec-tag > .sec-num + .sec-name
 *   .dec[data-for=ID]              an approve/decline control, on a section tag or on a step
 *   .note-btn[data-for=ID]         opens the note bubble for that section or step
 *   .step[data-step=ID]            a step row, containing .dec and .step-body
 *   [data-edit-id=ID]              an element the user may rewrite in place
 *   window.PRESENTER_DATA          {sections, prompt, meta} injected by shell.py
 *
 * Feedback lives ON the document rather than beside it: a comment or a rewrite
 * is reachable by clicking its own highlight. The footer holds the assembled
 * answer and the verdict that hands it over.
 *
 * Everything below is layout agnostic. A layout never touches state, undo or transport.
 */
(function () {
  "use strict";

  var D = window.PRESENTER_DATA;
  var LSKEY = "plan-review-" + D.meta.slug + "-v1";
  var HIST_MAX = 100;
  var COALESCE_MS = 1200;
  var QUOTE_CAP = 90;

  /* The footer buttons are supplied by the layout. A plan offers approve,
     changes and decline; an options screen offers one Send answer, because
     choosing IS the answer. Nothing here knows which kind it is rendering. */
  function actionFor(kind) {
    var list = D.actions || [];
    for (var i = 0; i < list.length; i++) if (list[i].verdict === kind) return list[i];
    return null;
  }

  var doc = document;
  var docEl = doc.getElementById("doc");

  var state = {
    mode: "comment",
    ui: { head: true, prompt: false, zoom: 1 },
    data: emptyData()
  };

  /* Runtime only, never persisted. */
  var origHTML = {};      // editId -> pristine innerHTML
  var origText = {};      // editId -> pristine plain text
  var drift = {};         // markId -> "moved" | "section" | "lost", when the quote no longer matches exactly

  function emptyData() {
    return {
      meta: { slug: D.meta.slug, kind: D.meta.kind, source: D.meta.source, generatedAt: D.meta.generatedAt },
      steps: {}, marks: {}, edits: {}, tables: {}, choices: {}, general: "", verdict: "", rounds: [], pending: null
    };
  }

  /* ------------------------------------------------------------ persistence */

  var forgotten = false;

  function persist() {
    if (forgotten) return;
    try {
      localStorage.setItem(LSKEY, JSON.stringify({
        mode: state.mode, ui: state.ui, data: state.data, savedAt: Date.now()
      }));
    } catch (e) { /* private window, quota, blocked storage: the page still works */ }
  }

  /* The server deletes a page stale_hours after its last build, and slugs come
     back: a plan with the same name rendered a week later would otherwise
     reopen with last week's comments. So any review not saved for that long is
     dropped, on every page load, for every page. One saved before savedAt
     existed gets stamped now and expires a full window from here.

     How long that is, is a setting, so the page asks the server that served it
     before it loads anything (see wire). With no server, from file:// or when
     it does not answer, it uses the last value it heard, else 96. */
  var DEFAULT_STALE_HOURS = 96;
  var SETTINGS_KEY = "review-doc-settings";

  function hoursMs(h) { return h * 3600 * 1000; }

  function validHours(h) { return typeof h === "number" && h % 1 === 0 && h >= 1 && h <= 720; }

  function onServer() { return /^https?:$/.test(location.protocol) && !!window.fetch; }

  function rememberSettings(s) {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({
        stale_hours: s.stale_hours, show_tips: s.show_tips !== false
      }));
    }
    catch (e) { /* blocked storage: the next load asks the server again */ }
  }

  function cachedShowTips() {
    try {
      var got = JSON.parse(localStorage.getItem(SETTINGS_KEY));
      return !(got && got.show_tips === false);
    } catch (e) { return true; }
  }

  function cachedStaleHours() {
    try {
      var got = JSON.parse(localStorage.getItem(SETTINGS_KEY));
      if (got && validHours(got.stale_hours)) return got.stale_hours;
    } catch (e) { /* nothing remembered */ }
    return DEFAULT_STALE_HOURS;
  }

  /* The settings of the server that served this page, or null. Never rejects,
     and never waits longer than timeoutMs: a server that stopped while the tab
     stayed open must not hang the page. */
  function fetchSettings(timeoutMs) {
    if (!onServer()) return Promise.resolve(null);
    var timer;
    var late = new Promise(function (res) { timer = setTimeout(function () { res(null); }, timeoutMs || 1500); });
    var got = fetch("/api/settings", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s || !validHours(s.stale_hours)) return null;
        rememberSettings(s);
        return s;
      })
      .catch(function () { return null; });
    return Promise.race([got, late]).then(function (s) { clearTimeout(timer); return s; });
  }

  /* keep: a storage key never removed here, the open page's own after a save. */
  function expireOld(maxAgeMs, keep) {
    try {
      var now = Date.now(), keys = [];
      for (var i = 0; i < localStorage.length; i++) keys.push(localStorage.key(i));
      keys.forEach(function (k) {
        if (!/^plan-review-.+-v1$/.test(k) || k === keep) return;
        var got = null;
        try { got = JSON.parse(localStorage.getItem(k)); } catch (e) { /* corrupt: drop it */ }
        if (!got || typeof got !== "object") { localStorage.removeItem(k); return; }
        if (typeof got.savedAt !== "number") {
          got.savedAt = now;
          localStorage.setItem(k, JSON.stringify(got));
        } else if (now - got.savedAt > maxAgeMs) {
          localStorage.removeItem(k);
        }
      });
    } catch (e) { /* blocked storage: nothing to expire */ }
  }

  function load() {
    var raw;
    try { raw = localStorage.getItem(LSKEY); } catch (e) { return; }
    if (!raw) return;
    try {
      var got = JSON.parse(raw);
      if (got && got.data) {
        state.data = got.data;
        if (!state.data.steps) state.data.steps = {};
        if (!state.data.marks) state.data.marks = {};
        if (!state.data.edits) state.data.edits = {};
        if (!state.data.tables) state.data.tables = {};
        if (!state.data.choices) state.data.choices = {};
        if (typeof state.data.general !== "string") state.data.general = "";
        if (typeof state.data.verdict !== "string") state.data.verdict = "";
        if (!Array.isArray(state.data.rounds)) state.data.rounds = [];
        if (!state.data.pending || typeof state.data.pending !== "object") state.data.pending = null;
      }
      if (got && got.mode) state.mode = got.mode;
      if (got && got.ui) {
        state.ui.head = got.ui.head !== false;
        /* The prompt is not restored: every page opens with it hidden, and the
           toggle only lasts for the visit. The verdict buttons copy the answer
           whether it shows or not. */
        if (typeof got.ui.zoom === "number") state.ui.zoom = got.ui.zoom;
        if (SCOPES.indexOf(got.ui.scope) >= 0) state.ui.scope = got.ui.scope;
      }
      pruneSteps();
    } catch (e) { /* corrupt payload: start clean rather than fail to open */ }
  }

  /* A change request becomes an earlier round when the page comes back on the
     rebuilt source, not when it is sent: until then Cancel can still take it
     back. A hand reload of the same build moves nothing. */
  function promoteRound(data, builtMtime) {
    var p = data.pending;
    if (!p || typeof builtMtime !== "number" || !(builtMtime > p.sourceMtime)) return false;
    data.rounds = (data.rounds || []).concat([{
      sentAt: p.sentAt, marks: data.marks || {}, edits: data.edits || {}, tables: data.tables || {}
    }]);
    data.marks = {}; data.edits = {}; data.tables = {}; data.steps = {};
    data.general = ""; data.verdict = ""; data.pending = null;
    return true;
  }

  function hasRounds() { return !!(state.data.rounds && state.data.rounds.length); }

  /* What the counters step through. The page always shows every round; this
     only chooses which of them the three counters count and visit. */
  var SCOPES = ["current", "previous", "all"];
  var SCOPE_TIPS = {
    current: "Stepping through this round",
    previous: "Stepping through earlier rounds",
    all: "Stepping through every round"
  };

  var freshRound = false;

  function nextScope(s) {
    var i = SCOPES.indexOf(s);
    return SCOPES[(i + 1) % SCOPES.length] || "current";
  }

  function scopeNow() { return hasRounds() ? (state.ui.scope || "current") : "current"; }

  /* Earlier marks nest inside current ones and the other way round, so an
     ancestor cannot decide. The element itself does: an earlier mark carries
     data-prev, and a current mark, table or decided section is current even
     when it sits inside an earlier mark. Only an element that is neither
     falls back on its ancestors. */
  function isEarlier(el) {
    if (el.hasAttribute("data-prev")) return true;
    if (el.matches && el.matches("mark.has-comment, mark.edited, mark.tbl-orphan, table[data-tchg], .chg-whole, .sec, .step")) return false;
    return !!(el.closest && el.closest("[data-prev]"));
  }

  /* "cur" for this round, "r<i>" for an earlier one (the prefix of data-prev). */
  function roundOf(el) {
    if (!isEarlier(el)) return "cur";
    var k = el.getAttribute("data-prev");
    if (k === null && el.closest) {
      var a = el.closest("[data-prev]");
      k = a ? a.getAttribute("data-prev") : "";
    }
    return String(k).split(":")[0];
  }

  function inScope(el) {
    var s = scopeNow();
    return s === "all" || (s === "previous") === isEarlier(el);
  }

  function paintScope() {
    var b = doc.getElementById("cycle-scope");
    if (!b) return;
    var s = scopeNow();
    var wasHidden = b.hidden;
    b.hidden = !hasRounds();
    /* The fade is only for the first time this page gets an earlier round. */
    if (wasHidden && !b.hidden && freshRound) {
      freshRound = false;
      b.classList.add("is-new");
      var done = function () { b.classList.remove("is-new"); };
      b.addEventListener("animationend", done);
      setTimeout(done, 600);
    }
    b.setAttribute("data-scope", s);
    b.setAttribute("data-tip", SCOPE_TIPS[s]);
    b.setAttribute("aria-label", SCOPE_TIPS[s] + ", click to change");
  }

  function onScope() {
    state.ui.scope = nextScope(scopeNow());
    navAt = { comments: -1, edits: -1, all: -1 };
    persist();
    updateCounters();
    flash(SCOPE_TIPS[state.ui.scope], "", 1800);
  }

  /* ------------------------------------------------------------------ undo */

  var RESET_TITLE = "Clear every comment, rewrite, decision and earlier round. Ctrl+Z brings it back.";

  var hist = { undo: [], redo: [], lastKey: null, lastAt: 0 };
  var baseline = null;

  function save(key) {
    persist();
    var snap = JSON.stringify(state.data);
    if (snap === baseline) return;                 // UI-only change, no history step
    var coalesce = key && key === hist.lastKey && (Date.now() - hist.lastAt) < COALESCE_MS;
    if (!coalesce) {
      hist.undo.push(baseline);
      if (hist.undo.length > HIST_MAX) hist.undo.shift();
    }
    baseline = snap;
    hist.lastKey = key || null;
    hist.lastAt = Date.now();
    hist.redo.length = 0;
    syncHistButtons();
  }

  function restore(snap) {
    state.data = JSON.parse(snap);
    baseline = snap;
    persist();
    closeBubble();
    applyDataToDoc();
    paintTableBar();
    syncGeneral();
    syncVerdict();
    updatePrompt();
    syncHistButtons();
  }

  /* The whole-plan note lives in an input, not in the document, so nothing in
     applyDataToDoc puts it back. Without this an undo reverted the stored note
     and left the old text sitting visibly in the box. */
  function syncGeneral() {
    var el = doc.getElementById("general");
    if (el && el.value !== state.data.general) el.value = state.data.general || "";
  }

  /* Reset asks twice. The first click arms it: the button inverts to red and
     wears an exclamation mark for four seconds, and only a second click inside
     that window clears anything. Undo would bring the review back either way,
     but a review is long work and finding that out afterwards is not the
     moment to learn it.

     The window disarms itself, so a stray click costs nothing. */
  var RESET_WINDOW_MS = 4000;
  var resetTimer = null;

  function resetArmed() {
    var el = doc.getElementById("reset");
    return !!el && el.classList.contains("armed");
  }

  function armReset() {
    var el = doc.getElementById("reset");
    if (!el) return;
    el.classList.add("armed");
    el.setAttribute("data-tip", "Click again to clear everything");
    el.setAttribute("aria-label", "Confirm reset, clears every comment, rewrite and decision");
    clearTimeout(resetTimer);
    resetTimer = setTimeout(disarmReset, RESET_WINDOW_MS);
  }

  function disarmReset() {
    clearTimeout(resetTimer);
    resetTimer = null;
    var el = doc.getElementById("reset");
    if (!el) return;
    el.classList.remove("armed");
    el.setAttribute("data-tip", RESET_TITLE);
    el.setAttribute("aria-label", "Reset the review");
  }

  function onReset() {
    if (resetArmed()) { disarmReset(); resetAll(); return; }
    if (!feedbackCount() && !state.data.verdict && !hasRounds()) return;
    armReset();
  }

  /* Reset is a mutation like any other: it goes through save(), so it lands on
     the undo stack and Ctrl+Z brings the whole review back. */
  function resetAll() {
    if (!feedbackCount() && !state.data.verdict && !hasRounds()) return;
    state.data = emptyData();
    /* No earlier rounds are left to step through. */
    state.ui.scope = "current";
    closeBubble();
    applyDataToDoc();
    paintTableBar();
    syncGeneral();
    syncVerdict();
    save("reset");
    updatePrompt();
  }

  function undo() {
    if (!hist.undo.length) return;
    hist.redo.push(JSON.stringify(state.data));
    restore(hist.undo.pop());
  }

  function redo() {
    if (!hist.redo.length) return;
    hist.undo.push(JSON.stringify(state.data));
    restore(hist.redo.pop());
  }

  function syncHistButtons() {
    var u = doc.getElementById("undo"), r = doc.getElementById("redo");
    var x = doc.getElementById("reset");
    if (u) u.disabled = !hist.undo.length;
    if (r) r.disabled = !hist.redo.length;
    /* Reset follows what there is to clear, not what there is to undo: an
       untouched plan has nothing to reset even after an undo refilled the
       redo stack. */
    if (x) {
      x.disabled = !feedbackCount() && !state.data.verdict && !hasRounds();
      /* An undo can empty the review while the confirm window is still open,
         and a red exclamation mark on a dead button is a promise it cannot
         keep. */
      if (x.disabled && x.classList.contains("armed")) disarmReset();
    }
  }

  function historyKeys(ev) {
    if (finishOpen()) return;
    if (!(ev.ctrlKey || ev.metaKey)) return;
    var k = ev.key.toLowerCase();
    if (k === "z" && !ev.shiftKey) { ev.preventDefault(); undo(); }
    else if (k === "y" || (k === "z" && ev.shiftKey)) { ev.preventDefault(); redo(); }
  }

  /* ------------------------------------------------------- text anchoring */

  /* Concatenate the section's text nodes so a quote can span element
     boundaries, then rebuild a Range over the original nodes. This is why a
     comment survives regeneration: it re-finds its text rather than trusting a
     DOM offset or a heading ordinal. */
  function textNodesOf(root) {
    var out = [];
    var walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
        var p = n.parentElement;
        while (p && p !== root) {
          var tag = p.tagName;
          if (tag === "SCRIPT" || tag === "STYLE" || p.classList.contains("sec-tag")) {
            return NodeFilter.FILTER_REJECT;
          }
          p = p.parentElement;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var n;
    while ((n = walker.nextNode())) out.push(n);
    return out;
  }

  /* Whitespace never decides a match. Our Markdown is hard-wrapped, so nearly
     every paragraph carries real line breaks that the browser draws as spaces,
     and a selection across two blocks gains a newline the text nodes never had.
     The stored quote is collapsed to single spaces, so an exact search failed
     on almost any passage longer than one line and the comment lost its
     highlight the moment it was saved. Both sides are now compared with all
     whitespace, soft hyphens and zero-width characters removed, and a map leads
     each remaining character back to its text node. */
  var INVISIBLE = /[\s­​-‍⁠﻿]/;

  function squeeze(s) {
    var out = [];
    for (var i = 0; i < s.length; i++) if (!INVISIBLE.test(s.charAt(i))) out.push(s.charAt(i));
    return out.join("");
  }

  function flatten(root) {
    var nodes = textNodesOf(root), chars = [], map = [];
    for (var i = 0; i < nodes.length; i++) {
      var v = nodes[i].nodeValue;
      for (var j = 0; j < v.length; j++) {
        if (INVISIBLE.test(v.charAt(j))) continue;
        chars.push(v.charAt(j));
        map.push([nodes[i], j]);
      }
    }
    return { text: chars.join(""), map: map };
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

  /* start inclusive, end exclusive, both in flattened coordinates. */
  function rangeAt(flat, start, end) {
    var a = flat.map[start], b = flat.map[end - 1];
    if (!a || !b) return null;
    var r = doc.createRange();
    r.setStart(a[0], a[1]);
    r.setEnd(b[0], b[1] + 1);
    return r;
  }

  var END_MIN = 10;              // the shortest end, without whitespace, that still identifies a passage

  /* Find a passage again. An exact match comes back with drift false. When the
     Markdown was edited and the page regenerated, the words may no longer be
     there as they were, so the passage is then looked for by its two ends: both
     ends in order and close together give the span between them, one end alone
     gives that end. Either way drift is true, and the comment keeps its
     original quote. Null only when nothing of it is left. */
  function locateQuote(root, quote, occurrence) {
    var flat = flatten(root), q = squeeze(quote || "");
    if (!q) return null;
    var at = nthIndex(flat.text, q, occurrence || 0);
    /* An earlier twin of the passage was edited away, so the count is off by
       one. The first remaining copy is the best guess. */
    if (at === -1 && occurrence) at = flat.text.indexOf(q);
    if (at !== -1) return { range: rangeAt(flat, at, at + q.length), drift: false };

    if (q.length < 2 * END_MIN) return null;         // too short to recognise by its ends
    var text = flat.text, len, at2;
    /* The longest start of the quote still in the text, then the longest end
       after it. A fixed-size end broke as soon as the edit touched its first
       few words; growing it keeps everything up to the changed word. */
    var pre = null;
    for (len = END_MIN; len <= q.length; len++) {
      at2 = text.indexOf(q.slice(0, len));
      if (at2 === -1) break;
      pre = { at: at2, len: len };
    }
    var suf = null, from = pre ? pre.at + pre.len : 0;
    for (len = END_MIN; len <= q.length; len++) {
      at2 = text.indexOf(q.slice(q.length - len), from);
      if (at2 === -1) break;
      suf = { at: at2, len: len };
    }
    var reach = q.length * 2 + 200;
    if (pre && suf && suf.at + suf.len - pre.at <= reach) {
      return { range: rangeAt(flat, pre.at, suf.at + suf.len), drift: true };
    }
    var best = !suf || (pre && pre.len >= suf.len) ? pre : suf;
    if (best) return { range: rangeAt(flat, best.at, best.at + best.len), drift: true };
    return null;
  }

  /* Which copy of the quote the selection is, counted in the same flattened
     text locateQuote searches, so the two can never disagree. */
  function occurrenceOf(root, quote, range) {
    var flat = flatten(root), q = squeeze(quote || "");
    if (!q) return 0;
    var before = -1;
    for (var i = 0; i < flat.map.length; i++) {
      var p;
      try { p = range.comparePoint(flat.map[i][0], flat.map[i][1]); } catch (e) { continue; }
      if (p >= 0) { before = i; break; }
    }
    if (before < 0) return 0;
    var occ = 0, from = 0, at;
    while ((at = flat.text.indexOf(q, from)) !== -1 && at < before) { occ++; from = at + 1; }
    return occ;
  }

  /* Each text node in the range gets its own mark, all carrying the same id.
     One mark around the whole range cannot work once a passage spans two
     paragraphs: extractContents splits both paragraphs and puts the pieces
     inside an inline element, which tears the layout apart and paints no
     highlight. Whitespace-only nodes between blocks are left alone. */
  function wrapRange(range, id, cls, attr) {
    var root = range.commonAncestorContainer;
    var nodes = root.nodeType === 3 ? [root] : textNodesOf(root);
    var first = null;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (!range.intersectsNode(n)) continue;
      var s = n === range.startContainer ? range.startOffset : 0;
      var e = n === range.endContainer ? range.endOffset : n.nodeValue.length;
      if (e <= s || !/\S/.test(n.nodeValue.slice(s, e))) continue;
      var part = n;
      if (s > 0) part = part.splitText(s);
      if (e - s < part.nodeValue.length) part.splitText(e - s);
      var m = doc.createElement("mark");
      m.className = cls || "has-comment";
      m.setAttribute(attr || "data-mark", id);
      part.parentNode.insertBefore(m, part);
      m.appendChild(part);
      if (!first) first = m;
    }
    return first;
  }

  function unwrapMarks() {
    var marks = docEl.querySelectorAll(
      "mark.has-comment, mark.tbl-orphan, mark.prev-comment, mark.prev-edit, mark.prev-pill");
    for (var i = 0; i < marks.length; i++) {
      var m = marks[i], p = m.parentNode;
      while (m.firstChild) p.insertBefore(m.firstChild, m);
      p.removeChild(m);
      p.normalize();
    }
  }

  /* ------------------------------------------------- applying data to DOM */

  function cssEsc(s) { return String(s).replace(/["\\]/g, "\\$&"); }

  function secEl(id) { return docEl.querySelector('.sec[data-sec="' + cssEsc(id) + '"]'); }

  function applyDataToDoc() {
    /* History snapshots from before tables existed carry no map. */
    if (!state.data.tables) state.data.tables = {};
    unwrapMarks();
    drift = {};
    /* Structure first: added rows and columns have to exist before the
       editables pass restores text and the marks pass re-anchors comments. */
    applyTablesToDoc();

    /* Reset every editable to pristine, then lay this session's edits on top.
       Order matters: marks are searched against the CURRENT text. */
    Object.keys(origHTML).forEach(function (id) {
      var el = docEl.querySelector('[data-edit-id="' + cssEsc(id) + '"]');
      if (!el) return;
      var edit = state.data.edits[id];
      if (edit) {
        renderEditDiff(el, edit.alt, edit.neu);
        el.classList.add("chg");
      } else {
        el.innerHTML = origHTML[id];
        el.classList.remove("chg");
        el.classList.remove("chg-whole");
      }
    });

    Object.keys(state.data.marks).forEach(anchorMark);
    Object.keys(state.data.tables).forEach(anchorLostTable);
    anchorEarlier();

    /* Sections and steps share one decision map and one kind of control. */
    var decs = docEl.querySelectorAll(".dec");
    for (var i = 0; i < decs.length; i++) paintDecision(decs[i]);
    var notes = docEl.querySelectorAll(".note-btn");
    for (var j = 0; j < notes.length; j++) paintNote(notes[j]);
    paintChoices();
  }

  /* Every comment gets a place on the page, and none of them raises an alarm.
     An exact match is highlighted as it was. A passage that has since changed
     is highlighted where its ends still are. One that is gone entirely hangs a
     marker on its section's tag, which opens the same bubble. Only a comment
     whose whole section has disappeared has nowhere to sit, and buildPrompt
     still sends it. */
  function anchorMark(id) {
    var mk = state.data.marks[id];
    var sec = mk.sec ? secEl(mk.sec) : null;
    var hit = locateQuote(sec || docEl, mk.quote, mk.occ || 0);
    if (hit && hit.range) {
      wrapRange(hit.range, id);
      if (hit.drift) drift[id] = "moved";
      return;
    }
    var tag = sec ? sec.querySelector(".sec-tag") : null;
    if (!tag) { drift[id] = "lost"; return; }
    /* Empty on purpose: the label is drawn by CSS, so it never becomes text
       that a later search could match or a rewrite could swallow. */
    var m = doc.createElement("mark");
    m.className = "has-comment at-section";
    m.setAttribute("data-mark", id);
    m.setAttribute("data-tip", "Comment on a passage that has since changed");
    var num = tag.querySelector(".sec-num");
    tag.insertBefore(m, num ? num.nextSibling : tag.firstChild);
    drift[id] = "section";
  }

  /* A restructured table whose source has since changed cannot be rebuilt,
     but it still goes out in the prompt, so it gets a place on the page the
     way a lost comment does: a marker on its section's tag that the edits
     navigation stops at. */
  function anchorLostTable(tid) {
    if (tableEl(tid)) return;
    var st = state.data.tables[tid];
    var sec = st.sec ? secEl(st.sec) : null;
    var tag = sec ? sec.querySelector(".sec-tag") : null;
    if (!tag) return;
    var m = doc.createElement("mark");
    m.className = "tbl-orphan at-section";
    m.setAttribute("data-table-lost", tid);
    m.setAttribute("data-tip", "Table change that no longer fits this table; it still goes out in the prompt");
    var num = tag.querySelector(".sec-num");
    tag.insertBefore(m, num ? num.nextSibling : tag.firstChild);
  }

  /* ------------------------------------------------------ earlier rounds */

  /* Rounds Claude already acted on. They stay on the page as an underline and
     a read-only bubble, drawn after the current round so a current mark on the
     same words keeps its fill. Never sent again. */
  var prevInfo = {};

  /* Where each changed run of a rewrite sits in the NEW text, counted in the
     squeezed coordinates locateQuote uses. A run that only removed words has no
     new text to sit on and is left out. */
  function runOffsets(alt, neu) {
    var ops = diffTokens(tokenize(alt), tokenize(neu));
    if (!ops) return [];
    var runs = coalesceRuns(buildRuns(ops)), out = [], pos = 0;
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i];
      if (r.same) { pos += squeeze(r.text).length; continue; }
      var len = squeeze(r.added).length;
      if (len) out.push({ s: pos, e: pos + len, was: r.removed, now: r.added });
      pos += len;
    }
    return out;
  }

  /* Empty like the current round's section pill, so its label never becomes
     text a later search could match. */
  function prevPill(sec, key, label) {
    var tag = sec ? sec.querySelector(".sec-tag") : null;
    if (!tag) return;
    var m = doc.createElement("mark");
    m.className = "prev-pill";
    m.setAttribute("data-prev", key);
    m.setAttribute("data-label", label);
    var num = tag.querySelector(".sec-num");
    tag.insertBefore(m, num ? num.nextSibling : tag.firstChild);
  }

  /* Which element an earlier edit belongs to: the first one whose whole text,
     squeezed, is exactly the edit's new text and that no other edit of the
     same round has claimed. A section-wide substring search put "Yes" inside
     "Yesterday" and sent two cells both rewritten to "Done" to the first one.
     -1 when no element matches. */
  function pickEditElement(texts, want, taken) {
    for (var i = 0; i < texts.length; i++) if (!taken[i] && texts[i] === want) return i;
    return -1;
  }

  /* Where an earlier edit's runs sit: its own element when one matches,
     otherwise an exact match anywhere in the section. Drift is never good
     enough, the run offsets only hold on the exact new text. */
  function earlierEditBase(sec, ed, claimed) {
    var want = squeeze(ed.neu || "");
    if (!want) return null;
    var els = sec.querySelectorAll("[data-edit-id]"), texts = [], taken = [], flats = [];
    for (var i = 0; i < els.length; i++) {
      flats.push(flatten(els[i]));
      texts.push(flats[i].text);
      taken.push(claimed.indexOf(els[i]) !== -1);
    }
    var at = pickEditElement(texts, want, taken);
    if (at !== -1) { claimed.push(els[at]); return { flat: flats[at], start: 0 }; }
    var flat = flatten(sec), start = flat.text.indexOf(want);
    return start === -1 ? null : { flat: flat, start: start };
  }

  function anchorEarlier() {
    prevInfo = {};
    (state.data.rounds || []).forEach(function (round, ri) {
      if (!round || typeof round !== "object") return;
      var r = "r" + ri + ":";
      /* One per round: two edits of the same round never share an element. */
      var claimed = [];
      /* Earlier rounds are decoration. A malformed entry, or a range that no
         longer fits, must not stop the decisions, notes and choices that
         applyDataToDoc paints after this. */
      function guarded(fn) {
        return function (id) { try { fn(id); } catch (e) { /* skip this one */ } };
      }
      Object.keys(round.marks || {}).forEach(guarded(function (id) {
        var mk = round.marks[id], sec = mk.sec ? secEl(mk.sec) : null, key = r + id;
        prevInfo[key] = { kind: "comment", quote: mk.quote, comment: mk.comment };
        var hit = sec ? locateQuote(sec, mk.quote, mk.occ || 0) : null;
        if (hit && hit.range) wrapRange(hit.range, key, "prev-comment", "data-prev");
        else if (sec) prevPill(sec, key, "comment");
      }));
      Object.keys(round.edits || {}).forEach(guarded(function (eid) {
        var ed = round.edits[eid], sec = ed.sec ? secEl(ed.sec) : null;
        var base = sec ? earlierEditBase(sec, ed, claimed) : null;
        var runs = base ? runOffsets(ed.alt || "", ed.neu || "") : [];
        if (!runs.length) {
          prevInfo[r + eid] = { kind: "edit", was: ed.alt, now: ed.neu };
          prevPill(sec, r + eid, "earlier edit");
          return;
        }
        /* The runs are wrapped last to first: wrapping splits text nodes, and a
           split only shortens the node to the LEFT of the cut, so the map
           positions of the runs still to come stay true. */
        for (var k = runs.length - 1; k >= 0; k--) {
          var run = runs[k], key = r + eid + ":" + k;
          prevInfo[key] = { kind: "edit", was: run.was, now: run.now };
          var range = rangeAt(base.flat, base.start + run.s, base.start + run.e);
          if (range) wrapRange(range, key, "prev-edit", "data-prev");
        }
      }));
      Object.keys(round.tables || {}).forEach(guarded(function (tid) {
        var st = round.tables[tid], sec = st.sec ? secEl(st.sec) : null;
        prevInfo[r + tid] = { kind: "edit", was: "", now: "", table: true };
        prevPill(sec, r + tid, "earlier table change");
      }));
    });
  }

  function showEarlier(markEl) {
    var key = markEl.getAttribute("data-prev"), info = prevInfo[key];
    if (!info) return;
    openBubble(markEl.getBoundingClientRect(), function (b) {
      b.appendChild(mkEl("p", "bubble-label", "Earlier round"));
      if (info.kind === "comment") {
        b.appendChild(mkEl("p", "bubble-quote", truncate(info.quote || "", QUOTE_CAP)));
        b.appendChild(mkEl("p", "bubble-body", info.comment || ""));
      } else if (info.table) {
        b.appendChild(mkEl("p", "bubble-body", "A table change from an earlier round."));
      } else {
        var was = info.was || "", now = info.now || "";
        b.appendChild(mkEl("p", was.trim() ? "bubble-diff old" : "bubble-diff none",
                           was.trim() ? was : "Nothing here before"));
        b.appendChild(mkEl("p", "bubble-label", "Now"));
        b.appendChild(mkEl("p", now.trim() ? "bubble-diff new" : "bubble-diff none",
                           now.trim() ? now : "Removed"));
      }
    });
    /* After openBubble, which clears every open state first. */
    var pieces = docEl.querySelectorAll('[data-prev="' + cssEsc(key) + '"]');
    for (var i = 0; i < pieces.length; i++) pieces[i].classList.add("is-open");
  }

  function paintDecision(el) {
    var id = el.getAttribute("data-for");
    var dec = (state.data.steps[id] || {}).decision || "";
    el.setAttribute("data-decision", dec);
    el.textContent = dec === "ok" ? "\u2713" : (dec === "skip" ? "\u2715" : "?");
    el.setAttribute("aria-label", nameFor(id) + ": " +
      (dec === "ok" ? "approved, click to decline" :
       dec === "skip" ? "declined, click to clear" : "undecided, click to approve"));
    el.setAttribute("data-tip",
      dec === "ok" ? "Approved. Click to decline" :
      dec === "skip" ? "Declined. Click to clear" : "Not decided yet. Click to approve");
    var holder = el.closest(".step") || el.closest(".sec");
    if (holder) holder.setAttribute("data-decision", dec);
  }

  function paintNote(el) {
    var id = el.getAttribute("data-for");
    var has = !!((state.data.steps[id] || {}).comment);
    el.setAttribute("data-has-note", has ? "yes" : "no");
    el.setAttribute("aria-label", (has ? "Edit the note on " : "Add a note on ") + nameFor(id));
    var what = stepFor(id) ? "step" : "section";
    el.setAttribute("data-tip", has ? "Edit your note on this " + what : "Add a note on this " + what);
  }

  /* ------------------------------------------------------------- choosing */

  /* One card or several, from D.select. The control sits in the card's tag row
     rather than the whole card being clickable, so selecting a sentence to
     comment on cannot change the answer by accident. */
  function pickChoice(id) {
    if (D.select === "one") {
      var was = !!state.data.choices[id];
      state.data.choices = {};
      if (!was) state.data.choices[id] = true;
    } else {
      if (state.data.choices[id]) delete state.data.choices[id];
      else state.data.choices[id] = true;
    }
    paintChoices();
    save("pick");
    updatePrompt();
  }

  function paintChoices() {
    var cards = docEl.querySelectorAll(".card");
    for (var i = 0; i < cards.length; i++) {
      var id = cards[i].getAttribute("data-choice");
      var on = !!state.data.choices[id];
      cards[i].setAttribute("data-picked", on ? "yes" : "no");
      var btn = cards[i].querySelector(".pick");
      if (btn) {
        btn.setAttribute("aria-checked", on ? "true" : "false");
        btn.setAttribute("data-tip", on ? "Chosen. Click to unselect" : "Choose this option");
      }
    }
  }

  function chosenNames() {
    var out = [];
    for (var i = 0; i < D.sections.length; i++) {
      if (state.data.choices[D.sections[i].id]) out.push(labelOf(D.sections[i]));
    }
    return out;
  }

  /* --------------------------------------------------------------- lookups */

  function sectionFor(id) {
    for (var i = 0; i < D.sections.length; i++) if (D.sections[i].id === id) return D.sections[i];
    return null;
  }

  /* Step decisions are keyed by step id, which is not a section id. Without
     this lookup a declined step is stored and shown but never reaches the
     prompt. */
  function stepFor(id) {
    for (var i = 0; i < D.sections.length; i++) {
      var steps = D.sections[i].steps || [];
      for (var j = 0; j < steps.length; j++) {
        if (steps[j].id === id) return { section: D.sections[i], step: steps[j] };
      }
    }
    return null;
  }

  function nameFor(id) {
    var st = stepFor(id);
    if (st) return st.step.name;
    var sec = sectionFor(id);
    return sec ? sec.name : id;
  }

  function labelOf(sec) { return sec.name ? sec.num + " (" + sec.name + ")" : sec.num; }

  function decisionsIn(sec) {
    var ok = [], skip = [];
    var steps = sec.steps || [];
    for (var i = 0; i < steps.length; i++) {
      var d = (state.data.steps[steps[i].id] || {}).decision;
      if (d === "ok") ok.push(steps[i]);
      else if (d === "skip") skip.push(steps[i]);
    }
    return { ok: ok, skip: skip };
  }

  /* Deciding a section decides its steps, because clicking twelve ticks to say
     the same thing is not a review.

     A step you decided by hand is left alone. Those carry no `auto` flag, so a
     later section click cannot silently flip a deliberate decline back to
     approved, which is the same overclaiming failure the prompt guards against.
     Cascaded entries are marked `auto` precisely so the next section click may
     overwrite them. */
  function cascade(sec, decision) {
    var steps = sec.steps || [];
    for (var i = 0; i < steps.length; i++) {
      var id = steps[i].id;
      var entry = state.data.steps[id];
      var mine = entry && entry.auto === true;
      if (entry && !mine) continue;                  // decided by hand, keep it
      if (entry && entry.comment && entry.comment.trim()) continue;  // has a note, keep it

      if (!decision) {
        delete state.data.steps[id];
      } else {
        state.data.steps[id] = { decision: decision, auto: true };
      }
      var btn = docEl.querySelector('.dec[data-for="' + cssEsc(id) + '"]');
      if (btn) paintDecision(btn);
    }
  }

  /* An edit is stored per element, because applying it needs the whole
     paragraph. What a person counts, though, is changes, and one paragraph can
     hold several. So the counter and the navigation work in runs while the
     prompt keeps reporting per element: the counter says how many changes you
     made, the prompt says how to apply them.

     Memoised on the new text, because updatePrompt runs on every keystroke and
     the diff is quadratic. */
  var runCountCache = {};

  function editRunCount(id, entry) {
    var hit = runCountCache[id];
    if (hit && hit.neu === entry.neu && hit.alt === entry.alt) return hit.n;
    var ops = diffTokens(tokenize(entry.alt), tokenize(entry.neu));
    var n = 1;
    if (ops) {
      n = 0;
      var runs = coalesceRuns(buildRuns(ops));
      for (var i = 0; i < runs.length; i++) if (!runs[i].same) n++;
      if (!n) n = 1;
    }
    runCountCache[id] = { alt: entry.alt, neu: entry.neu, n: n };
    return n;
  }

  function totalEditRuns() {
    var n = 0;
    Object.keys(state.data.edits).forEach(function (id) {
      if (!editLocked(id)) n += editRunCount(id, state.data.edits[id]);
    });
    return n;
  }

  function marksFor(secId) {
    return Object.keys(state.data.marks).filter(function (k) {
      return state.data.marks[k].sec === secId;
    });
  }

  function editsFor(secId) {
    return Object.keys(state.data.edits).filter(function (k) {
      return state.data.edits[k].sec === secId && !editLocked(k);
    });
  }

  function tablesIn(secId) {
    return Object.keys(state.data.tables || {}).filter(function (tid) {
      return state.data.tables[tid].sec === secId && tableHasChange(tid);
    });
  }

  /* -------------------------------------------------- in-place text edits */

  /* Text in, text out. Block elements and <br> become newlines so a rewrite
     can never inject markup back into the document. */
  function editText(el) {
    var out = "";
    (function walk(node) {
      for (var i = 0; i < node.childNodes.length; i++) {
        var c = node.childNodes[i];
        if (c.nodeType === 3) out += c.nodeValue;
        else if (c.nodeType === 1) {
          if (c.tagName === "BR") out += "\n";
          else { walk(c); if (/^(P|DIV|LI|H[1-6])$/.test(c.tagName)) out += "\n"; }
        }
      }
    })(el);
    return out.replace(/\u00a0/g, " ");
  }

  /* Word-level diff, so a rewrite highlights the words that changed rather than
     shouting the whole paragraph. Whitespace is kept as its own token, which is
     what lets the rebuilt text match the original spacing exactly. */
  function tokenize(text) {
    return String(text).match(/\s+|\S+/g) || [];
  }

  var DIFF_CELLS = 250000;   // a paragraph is small; refuse to chew a whole page

  function diffTokens(a, b) {
    var n = a.length, m = b.length;
    if (n * m > DIFF_CELLS) return null;
    var dp = [], i, j;
    for (i = 0; i <= n; i++) dp.push(new Int32Array(m + 1));
    for (i = n - 1; i >= 0; i--) {
      for (j = m - 1; j >= 0; j--) {
        dp[i][j] = (a[i] === b[j]) ? dp[i + 1][j + 1] + 1
                                   : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    var ops = [];
    i = 0; j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) { ops.push({ t: b[j], k: "same" }); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ t: a[i], k: "del" }); i++; }
      else { ops.push({ t: b[j], k: "add" }); j++; }
    }
    while (i < n) ops.push({ t: a[i++], k: "del" });
    while (j < m) ops.push({ t: b[j++], k: "add" });
    return ops;
  }

  function appendText(parent, text) {
    var parts = String(text).split("\n");
    for (var i = 0; i < parts.length; i++) {
      if (i) parent.appendChild(doc.createElement("br"));
      if (parts[i]) parent.appendChild(doc.createTextNode(parts[i]));
    }
  }

  /* The diff is per token, so rewriting "one stage earlier" as "a whole stage
     sooner" comes back as three changes with the surviving word "stage" between
     them. Reading that as three separate edits is wrong: it is one rewrite. Runs
     separated by only a short bridge of unchanged text are merged, and the
     bridge is swallowed into the change so the mark and its bubble both show the
     whole phrase. */
  var BRIDGE_WORDS = 2, BRIDGE_CHARS = 24;

  function isBridge(text) {
    var trimmed = text.trim();
    if (!trimmed) return true;                       // whitespace never separates two edits
    return trimmed.split(/\s+/).length <= BRIDGE_WORDS && text.length <= BRIDGE_CHARS;
  }

  function buildRuns(ops) {
    var runs = [], i = 0;
    while (i < ops.length) {
      if (ops[i].k === "same") {
        var t = "";
        while (i < ops.length && ops[i].k === "same") t += ops[i++].t;
        runs.push({ same: true, text: t });
      } else {
        var added = "", removed = "";
        while (i < ops.length && ops[i].k !== "same") {
          if (ops[i].k === "add") added += ops[i].t; else removed += ops[i].t;
          i++;
        }
        runs.push({ same: false, added: added, removed: removed });
      }
    }
    return runs;
  }

  function coalesceRuns(runs) {
    var out = [];
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i];
      if (r.same) { out.push(r); continue; }
      while (i + 2 < runs.length && runs[i + 1].same && !runs[i + 2].same
             && isBridge(runs[i + 1].text)) {
        r = {
          same: false,
          added: r.added + runs[i + 1].text + runs[i + 2].added,
          removed: r.removed + runs[i + 1].text + runs[i + 2].removed
        };
        i += 2;
      }
      out.push(r);
    }
    return out;
  }

  /* Rebuild the element as the new text, with only the changed runs wrapped.
     A run that removed text without adding any leaves a narrow marker, because
     otherwise a pure deletion would be invisible and unclickable. */
  function renderEditDiff(el, alt, neu) {
    var ops = diffTokens(tokenize(alt), tokenize(neu));

    /* The edit is stored as plain text, so the bold and italic have to come
       from the pristine markup. Only valid while the stored original is still
       the page's original; a regenerated page falls back to plain text. */
    var id = el.getAttribute("data-edit-id");
    var fmt = (id && origHTML[id] !== undefined && alt === origText[id])
      ? formatMap(origHTML[id]) : null;

    if (!ops) {
      /* Too different to diff. Plain text would drop a link the rewrite kept,
         and a table cell is serialised from this DOM. */
      el.textContent = "";
      appendFormatted(el, neu, 0, fmt ? wholeFormat(alt, neu, fmt) : null);
      el.classList.add("chg-whole");
      return;
    }
    el.classList.remove("chg-whole");
    var neuFmt = fmt ? newTextFormat(ops, fmt) : null;
    el.textContent = "";

    var runs = coalesceRuns(buildRuns(ops));
    var q = 0;   // position in neu
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i];
      if (r.same) {
        appendFormatted(el, r.text, q, neuFmt);
        q += r.text.length;
        continue;
      }
      var m = doc.createElement("mark");
      m.className = "edited";
      /* Each run carries what it replaced, so its bubble can show that one
         change instead of the whole paragraph around it. */
      m.setAttribute("data-was", r.removed);
      if (r.added) {
        appendFormatted(m, r.added, q, neuFmt);
        q += r.added.length;
      } else {
        m.className += " edited-cut";
        m.setAttribute("data-tip", "Text removed here");
      }
      el.appendChild(m);
    }
  }

  /* The formatting of every character of the new text, decided on the raw
     diff before coalescing: a merged run can span "Plain start bold middle",
     and deciding once per merged run would flatten its bold half. */
  function newTextFormat(ops, fmt) {
    var out = [], p = 0, i = 0;
    while (i < ops.length) {
      if (ops[i].k === "same") {
        for (var k = 0; k < ops[i].t.length; k++) out.push(fmt[p + k] || []);
        p += ops[i].t.length;
        i++;
        continue;
      }
      var removed = 0, added = 0;
      while (i < ops.length && ops[i].k !== "same") {
        if (ops[i].k === "add") added += ops[i].t.length; else removed += ops[i].t.length;
        i++;
      }
      var chain = addedChain(fmt, p, removed);
      for (var a = 0; a < added; a++) out.push(chain);
      p += removed;
    }
    return out;
  }

  /* A whole rewrite has no diff to carry formatting across, so every run of
     the original that was formatted (a link, a bold phrase) keeps it wherever
     its exact text still appears in the new text, in order. */
  /* True unless both the character at `p` and the run's own edge character are
     letters or digits, i.e. unless the run would cut a word in two. */
  function wordEdge(s, p, edge) {
    var w = /[\p{L}\p{N}]/u;
    return p < 0 || p >= s.length || !w.test(s.charAt(p)) || !w.test(edge);
  }

  function wholeFormat(alt, neu, fmt) {
    var out = [], from = 0, i, k;
    for (i = 0; i < neu.length; i++) out.push([]);
    for (i = 0; i < alt.length;) {
      var chain = fmt[i] || [];
      for (k = i + 1; k < alt.length && sameChain(fmt[k] || [], chain); k++);
      if (chain.length) {
        var run = alt.slice(i, k), at = neu.indexOf(run, from);
        /* A whole word, so link text "here" does not land inside "where". */
        while (at >= 0 && !(wordEdge(neu, at - 1, run.charAt(0)) &&
                            wordEdge(neu, at + run.length, run.charAt(run.length - 1)))) {
          at = neu.indexOf(run, at + 1);
        }
        if (at >= 0) {
          for (var p = at; p < at + k - i; p++) out[p] = chain;
          from = at + k - i;
        }
      }
      i = k;
    }
    return out;
  }

  /* One entry per character of editText(), in step with it: the inline
     elements (strong, em, code, a...) that character sat inside. Blocks, <br>
     and the review's own marks are structure, not formatting. */
  var BLOCK_TAGS = /^(P|DIV|LI|UL|OL|H[1-6]|BLOCKQUOTE|PRE|TABLE|TBODY|THEAD|TR|TD|TH)$/;

  function formatMap(html) {
    var box = doc.createElement("div");
    box.innerHTML = html;
    var chains = [];
    (function walk(node, chain) {
      for (var i = 0; i < node.childNodes.length; i++) {
        var c = node.childNodes[i];
        if (c.nodeType === 3) {
          for (var k = 0; k < c.nodeValue.length; k++) chains.push(chain);
        } else if (c.nodeType === 1) {
          if (c.tagName === "BR") { chains.push(chain); continue; }
          var inline = !BLOCK_TAGS.test(c.tagName) && c.tagName !== "MARK";
          walk(c, inline ? chain.concat([c]) : chain);
          if (/^(P|DIV|LI|H[1-6])$/.test(c.tagName)) chains.push(chain);
        }
      }
    })(box, []);
    return chains;
  }

  function sameChain(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  function commonChain(a, b) {
    var out = [];
    for (var i = 0; i < a.length && i < b.length && a[i] === b[i]; i++) out.push(a[i]);
    return out;
  }

  /* New words take the formatting of what they replaced when that was uniform,
     so retyping a bold phrase stays bold. A pure insertion is formatted only
     if both its neighbours were, so typing after a bold word is plain. */
  function addedChain(fmt, p, removedLen) {
    var chain, i;
    if (removedLen) {
      chain = fmt[p] || [];
      for (i = p + 1; i < p + removedLen; i++) chain = commonChain(chain, fmt[i] || []);
      return chain;
    }
    if (p === 0 || p >= fmt.length) return [];
    return commonChain(fmt[p - 1], fmt[p]);
  }

  /* Text starting at position p of the new text, split wherever its
     formatting changes. */
  function appendFormatted(parent, text, p, fmt) {
    if (!fmt) { appendText(parent, text); return; }
    var start = 0;
    for (var i = 1; i <= text.length; i++) {
      if (i === text.length || !sameChain(fmt[p + i] || [], fmt[p + start] || [])) {
        appendStyled(parent, text.slice(start, i), fmt[p + start] || []);
        start = i;
      }
    }
  }

  function appendStyled(parent, text, chain) {
    var host = parent;
    for (var i = 0; i < chain.length; i++) {
      var c = chain[i].cloneNode(false);
      host.appendChild(c);
      host = c;
    }
    appendText(host, text);
  }

  /* Every mark, not just the edit ones. A comment mark left inside a focused
     contenteditable swallows whatever is typed at its edge. */
  function unwrapMarksIn(el) {
    var marks = el.querySelectorAll("mark.edited, mark.has-comment, mark.prev-comment, mark.prev-edit");
    for (var i = 0; i < marks.length; i++) {
      var m = marks[i], p = m.parentNode;
      while (m.firstChild) p.insertBefore(m.firstChild, m);
      p.removeChild(m);
    }
    el.normalize();
  }

  function setEditText(el, text) {
    el.textContent = "";
    var parts = String(text).split("\n");
    for (var i = 0; i < parts.length; i++) {
      if (i) el.appendChild(doc.createElement("br"));
      el.appendChild(doc.createTextNode(parts[i]));
    }
  }

  function collectEditables() {
    var els = docEl.querySelectorAll("[data-edit-id]");
    for (var i = 0; i < els.length; i++) {
      var el = els[i], id = el.getAttribute("data-edit-id");
      origHTML[id] = el.innerHTML;
      origText[id] = editText(el).replace(/\n+$/, "");
      el.addEventListener("input", onEditInput);
      /* Marks inside a focused contenteditable fight the caret, so the element
         goes plain while it is being typed in and is re-marked on the way out.
         That is the only moment a rewrite is not highlighted. */
      el.addEventListener("focus", function (ev) { unwrapMarksIn(ev.currentTarget); });
      /* Re-apply the whole state rather than only this element's diff.
         renderEditDiff rebuilds the paragraph from plain text, which throws away
         any comment mark inside it: the comment was still in the payload but had
         vanished from the page, which reads as losing it. A full pass re-anchors
         every comment by its quoted text, and one whose text the edit destroyed
         moves to its section's tag instead of disappearing. */
      el.addEventListener("blur", function () {
        applyDataToDoc();
        updatePrompt();
      });
    }
  }

  function onEditInput(ev) {
    var el = ev.currentTarget, id = el.getAttribute("data-edit-id");
    var neu = editText(el).replace(/\n+$/, ""), alt = origText[id];
    if (neu.trim() === alt.trim()) {
      delete state.data.edits[id];
      el.classList.remove("chg");
    } else {
      state.data.edits[id] = { sec: el.getAttribute("data-sec") || "", alt: alt, neu: neu };
      el.classList.add("chg");
    }
    save("edit:" + id);
    updatePrompt();
  }

  /* Reverting goes through applyDataToDoc rather than writing innerHTML back.
     Restoring the pristine markup directly wipes any comment mark sitting in
     that paragraph; a full pass re-anchors them by their quoted text instead. */
  function settleEdit(id, neu) {
    if (neu.trim() === (origText[id] || "").trim()) delete state.data.edits[id];
    else state.data.edits[id].neu = neu;
    applyDataToDoc();
    save("revert:" + id);
    updatePrompt();
  }

  /* Undo one highlighted run: rebuild the paragraph from the DOM, swapping that
     one mark back for the text it replaced and leaving every other change, and
     every comment, where it is. */
  function revertRun(el, markEl) {
    var id = el.getAttribute("data-edit-id");
    if (!state.data.edits[id]) return;
    var out = "";
    (function walk(node) {
      for (var i = 0; i < node.childNodes.length; i++) {
        var c = node.childNodes[i];
        if (c.nodeType === 3) { out += c.nodeValue; continue; }
        if (c.nodeType !== 1) continue;
        if (c === markEl) { out += markEl.getAttribute("data-was") || ""; continue; }
        if (c.tagName === "BR") { out += "\n"; continue; }
        walk(c);
        if (/^(P|DIV|LI|H[1-6])$/.test(c.tagName)) out += "\n";
      }
    })(el);
    settleEdit(id, out.replace(/\u00a0/g, " ").replace(/\n+$/, ""));
  }

  function revertAll(id) {
    if (!state.data.edits[id]) return;
    settleEdit(id, origText[id] || "");
  }

  /* -------------------------------------------------------------- tables */

  /* A table's structure lives in state.data.tables, one entry per touched
     table. The DOM is the model within a session; the state is what puts a
     table back after a reload or an undo. An untouched table has no entry.
     Spec: docs/superpowers/specs/2026-09-11-presenter-table-editing-design.md */
  var origRows = {};   // tableId -> pristine body row ids, in order
  var origCols = {};   // tableId -> pristine column ids, in order

  function tableEls() { return docEl.querySelectorAll("table[data-table-id]"); }
  function tableEl(tid) { return docEl.querySelector('table[data-table-id="' + cssEsc(tid) + '"]'); }

  /* A cell in a removed row or column, or in a deleted table, is going away:
     it takes no typing, and a rewrite already stored for it is not sent next
     to the instruction that removes it. */
  function cellLocked(el) {
    if (!el || !/^T[DH]$/.test(el.tagName)) return false;
    return el.hasAttribute("data-dropped") || !!el.closest("tr[data-dropped], table[data-killed]");
  }

  function editLocked(id) {
    return cellLocked(docEl.querySelector('[data-edit-id="' + cssEsc(id) + '"]'));
  }
  function headRow(t) { return (t.tHead && t.tHead.rows[0]) || null; }
  function bodyRows(t) { return t.tBodies[0] ? [].slice.call(t.tBodies[0].rows) : []; }
  function rowById(t, rid) {
    if (rid === "h") return headRow(t);
    return t.querySelector('tbody > tr[data-row-id="' + cssEsc(rid) + '"]');
  }
  function cellIn(tr, cid) {
    for (var i = 0; i < tr.cells.length; i++) {
      if (tr.cells[i].getAttribute("data-col-id") === cid) return tr.cells[i];
    }
    return null;
  }
  function rowIdOf(tr) {
    return tr.parentNode && tr.parentNode.tagName === "THEAD" ? "h" : tr.getAttribute("data-row-id");
  }
  function isNewId(id) { return /^n[rc]\d+$/.test(id || ""); }
  function setFlag(el, attr, on) { if (on) el.setAttribute(attr, "yes"); else el.removeAttribute(attr); }

  function collectTables() {
    var ts = tableEls();
    for (var i = 0; i < ts.length; i++) {
      var t = ts[i], tid = t.getAttribute("data-table-id"), h = headRow(t);
      origRows[tid] = bodyRows(t).map(function (r) { return r.getAttribute("data-row-id"); });
      origCols[tid] = h ? [].slice.call(h.cells).map(function (c) { return c.getAttribute("data-col-id"); }) : [];
      t.addEventListener("input", onNewCellInput);
    }
  }

  function ensureTable(t) {
    var tid = t.getAttribute("data-table-id");
    var st = state.data.tables[tid];
    if (!st) {
      var sec = t.closest(".sec");
      st = state.data.tables[tid] = {
        sec: sec ? sec.getAttribute("data-sec") : "",
        rows: origRows[tid].slice(), cols: origCols[tid].slice(),
        dropRows: {}, dropCols: {}, cells: {}, heads: {}, killed: false
      };
    }
    return st;
  }

  /* Back to exactly the original structure means no entry at all, so the
     counter and the prompt never report a change that was undone by hand. */
  function isPristine(tid) {
    var st = state.data.tables[tid];
    return !st || (!st.killed &&
      st.rows.join("\n") === (origRows[tid] || []).join("\n") &&
      st.cols.join("\n") === (origCols[tid] || []).join("\n") &&
      !Object.keys(st.dropRows).length && !Object.keys(st.dropCols).length);
  }

  function newCellText(st, rid, cid) {
    if (!st) return "";
    return (rid === "h" ? st.heads[cid] : st.cells[rid + "|" + cid]) || "";
  }

  /* Append in the given order; anything the order does not name keeps its
     relative position at the end. */
  function orderChildren(parent, items, key, order) {
    var named = [], rest = [];
    items.forEach(function (el) { (order.indexOf(key(el)) >= 0 ? named : rest).push(el); });
    named.sort(function (a, b) { return order.indexOf(key(a)) - order.indexOf(key(b)); });
    var want = named.concat(rest);
    /* Leave the nodes alone when they are already in order. This runs on
       every blur, and moving the cell a click is about to focus can drop the
       caret. */
    var same = want.length === items.length;
    for (var i = 0; same && i < want.length; i++) same = want[i] === items[i];
    if (same) return;
    want.forEach(function (el) { parent.appendChild(el); });
  }

  function applyTable(t) {
    var tid = t.getAttribute("data-table-id");
    var st = state.data.tables[tid] || null;
    var rows = st ? st.rows : origRows[tid];
    var cols = st ? st.cols : origCols[tid];
    var tb = t.tBodies[0], head = headRow(t);
    if (!tb || !head || !rows || !cols) return;

    bodyRows(t).forEach(function (tr) {
      var rid = tr.getAttribute("data-row-id");
      if (isNewId(rid) && rows.indexOf(rid) < 0) tb.removeChild(tr);
    });
    rows.forEach(function (rid) {
      if (!isNewId(rid) || rowById(t, rid)) return;
      var tr = doc.createElement("tr");
      tr.setAttribute("data-row-id", rid);
      tr.className = "new-row";
      tb.appendChild(tr);
    });

    [head].concat(bodyRows(t)).forEach(function (tr) {
      var rid = rowIdOf(tr);
      [].slice.call(tr.cells).forEach(function (c) {
        if (c.hasAttribute("data-new-cell") && cols.indexOf(c.getAttribute("data-col-id")) < 0) tr.removeChild(c);
      });
      cols.forEach(function (cid) {
        var c = cellIn(tr, cid);
        if (!c) {
          c = doc.createElement(tr === head ? "th" : "td");
          c.setAttribute("data-col-id", cid);
          c.setAttribute("data-new-cell", rid + "|" + cid);
          c.contentEditable = state.mode === "edit" ? "true" : "false";
          tr.appendChild(c);
        }
        if (c.hasAttribute("data-new-cell")) {
          var want = newCellText(st, rid, cid);
          if (c.textContent !== want) c.textContent = want;
        }
        setFlag(c, "data-dropped", !!(st && st.dropCols[cid]));
      });
      orderChildren(tr, [].slice.call(tr.cells), function (c) { return c.getAttribute("data-col-id"); }, cols);
      if (tr !== head) setFlag(tr, "data-dropped", !!(st && st.dropRows[rid]));
    });

    orderChildren(tb, bodyRows(t), function (r) { return r.getAttribute("data-row-id"); }, rows);
    setFlag(t, "data-killed", !!(st && st.killed));
    [].slice.call(t.querySelectorAll("[data-edit-id], [data-new-cell]")).forEach(function (c) {
      var locked = cellLocked(c);
      c.contentEditable = state.mode === "edit" && !locked ? "true" : "false";
      /* Still focusable, or a click could never bring the toolbar back to it
         and Restore would be out of reach. */
      if (locked) c.tabIndex = -1; else c.removeAttribute("tabindex");
    });
    setFlag(t, "data-tchg", tableHasChange(tid));
  }

  function applyTablesToDoc() {
    var ts = tableEls();
    for (var i = 0; i < ts.length; i++) applyTable(ts[i]);
  }

  /* Typing in a cell that has no original writes straight into the state.
     Cells with an original go through onEditInput like any paragraph. */
  function onNewCellInput(ev) {
    var c = ev.target.closest ? ev.target.closest("[data-new-cell]") : null;
    if (!c) return;
    var st = ensureTable(c.closest("table[data-table-id]"));
    var key = c.getAttribute("data-new-cell").split("|");
    var text = c.textContent.replace(/\u00a0/g, " ");
    if (key[0] === "h") st.heads[key[1]] = text;
    else st.cells[key[0] + "|" + key[1]] = text;
    var t = c.closest("table[data-table-id]");
    setFlag(t, "data-tchg", tableHasChange(t.getAttribute("data-table-id")));
    save("cell:" + key.join("|"));
    updatePrompt();
  }

  /* ---- the toolbar: one element for the page, shown over the table that
     has focus, acting on the focused cell's row and column ---- */

  var curCell = null;
  var tableBar = null;

  function liveCols(st) { return st.cols.filter(function (c) { return !st.dropCols[c]; }); }
  function freshId(list, prefix) {
    var n = 1;
    while (list.indexOf(prefix + n) >= 0) n++;
    return prefix + n;
  }
  function swap(list, i, j) { var x = list[i]; list[i] = list[j]; list[j] = x; }
  function forgetCells(st, id, part) {
    Object.keys(st.cells).forEach(function (k) { if (k.split("|")[part] === id) delete st.cells[k]; });
  }

  function tableOp(op) {
    var c = curCell;
    if (!c || !docEl.contains(c)) return;
    var t = c.closest("table[data-table-id]");
    var tid = t.getAttribute("data-table-id");
    var rid = rowIdOf(c.parentNode), cid = c.getAttribute("data-col-id");
    var st = ensureTable(t);
    var ri = st.rows.indexOf(rid), ci = st.cols.indexOf(cid);
    var focus = { rid: rid, cid: cid };

    if (op === "row-above" || op === "row-below") {
      var nr = freshId(st.rows, "nr");
      st.rows.splice(rid === "h" ? 0 : ri + (op === "row-below" ? 1 : 0), 0, nr);
      focus = { rid: nr, cid: liveCols(st)[0] };
    } else if (op === "row-up" && ri > 0) {
      swap(st.rows, ri, ri - 1);
    } else if (op === "row-down" && ri >= 0 && ri < st.rows.length - 1) {
      swap(st.rows, ri, ri + 1);
    } else if (op === "row-remove" && ri >= 0) {
      /* An added row has nothing to restore, so it goes outright. */
      if (isNewId(rid)) { st.rows.splice(ri, 1); forgetCells(st, rid, 0); focus = null; }
      else if (st.dropRows[rid]) delete st.dropRows[rid];
      else st.dropRows[rid] = true;
    } else if (op === "col-left" || op === "col-right") {
      var nc = freshId(st.cols, "nc");
      st.cols.splice(ci + (op === "col-right" ? 1 : 0), 0, nc);
      focus = { rid: "h", cid: nc };
    } else if (op === "col-prev" && ci > 0) {
      swap(st.cols, ci, ci - 1);
    } else if (op === "col-next" && ci >= 0 && ci < st.cols.length - 1) {
      swap(st.cols, ci, ci + 1);
    } else if (op === "col-remove") {
      if (st.dropCols[cid]) delete st.dropCols[cid];
      else if (!removableCol(t, st, cid)) { /* the last column the table keeps */ }
      else if (isNewId(cid)) { st.cols.splice(ci, 1); delete st.heads[cid]; forgetCells(st, cid, 1); focus = null; }
      else st.dropCols[cid] = true;
    } else if (op === "table-kill") {
      st.killed = !st.killed;
    }

    if (isPristine(tid)) delete state.data.tables[tid];
    applyDataToDoc();
    save("table:" + op);
    updatePrompt();
    refocus(t, focus);
  }

  function refocus(t, f) {
    var tr = f ? rowById(t, f.rid) : null;
    var c = tr ? cellIn(tr, f.cid) : null;
    if (!c) { curCell = null; hideTableBar(); return; }
    curCell = c;
    /* A rewritten cell was just re-marked by applyDataToDoc; marks inside a
       focused contenteditable fight the caret. */
    if (c.hasAttribute("data-edit-id")) unwrapMarksIn(c);
    c.focus();
    showTableBar();
  }

  var TBAR = [
    ["Row", [
      ["row-above", "+ Above", "Insert a row above this one"],
      ["row-below", "+ Below", "Insert a row below this one"],
      ["row-up", "↑", "Move this row up"],
      ["row-down", "↓", "Move this row down"],
      ["row-remove", "Remove", "Remove this row"]]],
    ["Column", [
      ["col-left", "+ Left", "Insert a column to the left"],
      ["col-right", "+ Right", "Insert a column to the right"],
      ["col-prev", "←", "Move this column left"],
      ["col-next", "→", "Move this column right"],
      ["col-remove", "Remove", "Remove this column"]]],
    ["", [
      ["table-kill", "Delete table", "Delete the whole table"]]]
  ];

  function buildTableBar() {
    var bar = doc.createElement("div");
    bar.className = "tbl-bar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "Table");
    bar.hidden = true;
    TBAR.forEach(function (group) {
      var g = mkEl("span", "tbl-group");
      if (group[0]) g.appendChild(mkEl("span", "tbl-label", group[0]));
      group[1].forEach(function (b) {
        var btn = mkEl("button", "tbl-btn", b[1]);
        btn.type = "button";
        btn.setAttribute("data-op", b[0]);
        btn.setAttribute("data-tip", b[2]);
        btn.setAttribute("aria-label", b[2]);
        btn.addEventListener("mousedown", function (ev) {
          ev.preventDefault(); /* keep focus in the cell */
        });
        btn.addEventListener("click", function () { tableOp(b[0]); });
        g.appendChild(btn);
      });
      bar.appendChild(g);
    });
    doc.body.appendChild(bar);
    return bar;
  }

  function tbarEntry(op) {
    for (var g = 0; g < TBAR.length; g++) {
      for (var b = 0; b < TBAR[g][1].length; b++) if (TBAR[g][1][b][0] === op) return TBAR[g][1][b];
    }
    return null;
  }

  function paintTableBar() {
    if (!tableBar || !curCell || !docEl.contains(curCell)) return;
    var t = curCell.closest("table[data-table-id]");
    var tid = t.getAttribute("data-table-id");
    var st = state.data.tables[tid] || null;
    var rows = st ? st.rows : origRows[tid], cols = st ? st.cols : origCols[tid];
    var rid = rowIdOf(curCell.parentNode), cid = curCell.getAttribute("data-col-id");
    var ri = rows.indexOf(rid), ci = cols.indexOf(cid);
    var head = rid === "h", killed = !!(st && st.killed);
    var rowDropped = !!(st && st.dropRows[rid]), colDropped = !!(st && st.dropCols[cid]);
    var off = {
      "row-above": head, "row-below": false,
      "row-up": head || ri <= 0, "row-down": head || ri < 0 || ri >= rows.length - 1,
      "row-remove": head,
      "col-left": false, "col-right": false,
      "col-prev": ci <= 0, "col-next": ci < 0 || ci >= cols.length - 1,
      "col-remove": !colDropped && !removableCol(t, st, cid)
    };
    var btns = tableBar.querySelectorAll(".tbl-btn");
    for (var i = 0; i < btns.length; i++) {
      var op = btns[i].getAttribute("data-op"), entry = tbarEntry(op);
      var label = null, tip = null;
      if (op === "row-remove" && rowDropped) { label = "Restore"; tip = "Bring this row back"; }
      if (op === "col-remove" && colDropped) { label = "Restore"; tip = "Bring this column back"; }
      if (op === "table-kill" && killed) { label = "Restore table"; tip = "Bring the whole table back"; }
      btns[i].disabled = op === "table-kill" ? false : (killed || !!off[op]);
      btns[i].textContent = label || entry[1];
      btns[i].setAttribute("data-tip", tip || entry[2]);
      btns[i].setAttribute("aria-label", tip || entry[2]);
    }
  }

  function placeTableBar() {
    if (!tableBar || tableBar.hidden || !curCell || !docEl.contains(curCell)) return;
    var t = curCell.closest("table[data-table-id]");
    var r = t.getBoundingClientRect(), box = docEl.getBoundingClientRect();
    var top = Math.max(box.top + 4, r.top - tableBar.offsetHeight - 6);
    tableBar.style.left = Math.max(8, r.left) + "px";
    tableBar.style.top = top + "px";
    tableBar.style.visibility = (r.bottom < box.top + 4 || r.top > box.bottom) ? "hidden" : "";
  }

  function showTableBar() {
    if (state.mode !== "edit" || !curCell) return;
    if (!tableBar) tableBar = buildTableBar();
    tableBar.hidden = false;
    paintTableBar();
    placeTableBar();
  }

  function hideTableBar() { if (tableBar) tableBar.hidden = true; }

  /* ---- the finished table, as Markdown, for the prompt ---- */

  /* A rewritten cell back to inline Markdown. The review's own marks are
     unwrapped; everything else inline keeps its meaning. */
  function inlineMd(node) {
    var out = "";
    for (var i = 0; i < node.childNodes.length; i++) {
      var c = node.childNodes[i];
      if (c.nodeType === 3) { out += mdText(c.nodeValue); continue; }
      if (c.nodeType !== 1) continue;
      var tag = c.tagName;
      if (tag === "CODE") { out += c.textContent ? mdCode(c.textContent) : ""; continue; }
      var inner = inlineMd(c);
      if (tag === "BR") out += " ";
      else if (tag === "STRONG" || tag === "B") out += inner ? "**" + inner + "**" : "";
      else if (tag === "EM" || tag === "I") out += inner ? "*" + inner + "*" : "";
      else if (tag === "A") out += "[" + inner + "](" + mdHref(c.getAttribute("href") || "") + ")";
      /* Chrome wraps a line typed after Enter in a <div>; without the space
         its first word runs into the last word before it. */
      else if (tag === "DIV" || tag === "P") out += " " + inner;
      else out += inner;
    }
    return out;
  }

  /* Plain text as Markdown that renders back to the same text inside a table
     cell. python-markdown cannot backslash-escape < or &, so those are
     entities. */
  function mdText(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/([\\`*_\[\]|])/g, "\\$1");
  }

  /* A pipe splits the cell even inside backticks, and python-markdown then
     shows the escaping backslash literally, so such code goes out as HTML.
     Markdown is still read inside raw <code>, so every character it would
     act on is an entity there. Otherwise the fence is one backtick longer
     than the longest run inside, padded so an edge backtick stays text. */
  function mdCode(s) {
    s = String(s);
    if (s.indexOf("|") >= 0) {
      return "<code>" + s.replace(/[&<|*_`\\\[\]]/g, function (ch) {
        return "&#" + ch.charCodeAt(0) + ";";
      }) + "</code>";
    }
    var runs = s.match(/`+/g) || [];
    var longest = runs.reduce(function (n, r) { return Math.max(n, r.length); }, 0);
    if (!longest) return "`" + s + "`";
    var fence = new Array(longest + 2).join("`");
    return fence + " " + s + " " + fence;
  }

  function mdHref(s) {
    return String(s).replace(/ /g, "%20").replace(/\(/g, "%28")
      .replace(/\)/g, "%29").replace(/\|/g, "%7C");
  }

  function oneLine(s) { return String(s).replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim(); }

  /* Untouched original: its Markdown verbatim, links and all. Rewritten:
     rebuilt from the DOM, which keeps its formatting. Added: plain text. */
  function cellMd(c) {
    if (!c) return "";
    if (c.hasAttribute("data-new-cell")) return oneLine(c.textContent).replace(/\|/g, "\\|");
    var eid = c.getAttribute("data-edit-id");
    if (!(eid && state.data.edits[eid]) && c.hasAttribute("data-md")) return c.getAttribute("data-md");
    return oneLine(inlineMd(c));
  }

  function cellBlank(c) { return !c || !oneLine(c.textContent); }

  function alignFor(t) {
    var raw = (t.getAttribute("data-md-align") || "").trim().replace(/^\|/, "").replace(/\|$/, "");
    var map = {};
    raw.split("|").forEach(function (a, i) { map["c" + i] = a.trim() || "---"; });
    return map;
  }

  /* The columns the finished table will have: not removed, and an added one
     only once something was typed in it. The Remove guard counts these, so a
     blank new column cannot stand in for the last real one. */
  function keptCols(t, st) {
    var head = headRow(t), rows = [head].concat(bodyRows(t));
    return [].slice.call(head.cells).map(function (c) { return c.getAttribute("data-col-id"); })
      .filter(function (cid) {
        if (st && st.dropCols[cid]) return false;
        if (!isNewId(cid)) return true;
        return rows.some(function (tr) { return !cellBlank(cellIn(tr, cid)); });
      });
  }

  /* Removing a column must leave the finished table at least one. A column
     that would not be kept anyway (blank and added) can always go. */
  function removableCol(t, st, cid) {
    var kept = keptCols(t, st);
    return kept.indexOf(cid) < 0 || kept.length > 1;
  }

  function tableMarkdown(t) {
    var st = state.data.tables[t.getAttribute("data-table-id")] || null;
    var head = headRow(t), body = bodyRows(t);
    var cols = keptCols(t, st);
    var rows = body.filter(function (tr) {
      var rid = tr.getAttribute("data-row-id");
      if (st && st.dropRows[rid]) return false;
      if (!isNewId(rid)) return true;
      return cols.some(function (cid) { return !cellBlank(cellIn(tr, cid)); });
    });
    var align = alignFor(t);
    function line(tr) {
      return "| " + cols.map(function (cid) { return cellMd(cellIn(tr, cid)); }).join(" | ") + " |";
    }
    var out = [line(head), "|" + cols.map(function (cid) { return align[cid] || "---"; }).join("|") + "|"];
    rows.forEach(function (tr) { out.push(line(tr)); });
    return {
      md: out.join("\n"),
      addedRows: rows.filter(function (tr) { return isNewId(tr.getAttribute("data-row-id")); }).length,
      addedCols: cols.filter(isNewId).length
    };
  }

  /* The fewest single moves that turn the original order into this one: every
     item outside the longest run already in original order had to move. One
     row dragged three places is one move, not four. */
  function movedCount(orig, now) {
    var pos = now.map(function (id) { return orig.indexOf(id); })
      .filter(function (p) { return p >= 0; });
    var tails = [];
    pos.forEach(function (p) {
      var lo = 0, hi = tails.length;
      while (lo < hi) { var mid = (lo + hi) >> 1; if (tails[mid] < p) lo = mid + 1; else hi = mid; }
      tails[lo] = p;
    });
    return pos.length - tails.length;
  }

  function tableSummary(tid, built) {
    var st = state.data.tables[tid], parts = [];
    var rr = Object.keys(st.dropRows).length, rc = Object.keys(st.dropCols).length;
    var mr = movedCount(origRows[tid] || [], st.rows), mc = movedCount(origCols[tid] || [], st.cols);
    if (built.addedRows) parts.push(plural(built.addedRows, "row") + " added");
    if (rr) parts.push(plural(rr, "row") + " removed");
    if (mr) parts.push(plural(mr, "row") + " moved");
    if (built.addedCols) parts.push(plural(built.addedCols, "column") + " added");
    if (rc) parts.push(plural(rc, "column") + " removed");
    if (mc) parts.push(plural(mc, "column") + " moved");
    return parts.join(", ");
  }

  function tablePromptLines() {
    var out = [];
    Object.keys(state.data.tables).forEach(function (tid) {
      var st = state.data.tables[tid], sc = sectionFor(st.sec);
      var where = "Table in " + (sc ? labelOf(sc) : "the document");
      var t = tableEl(tid);
      if (!t) { out.push(where + ": restructured on the page, but that table has changed in the source since, so the change could not be rebuilt."); return; }
      if (st.killed) { out.push(where + ": delete it."); return; }
      var built = tableMarkdown(t), sum = tableSummary(tid, built);
      if (sum) out.push(where + ", rebuilt (" + sum + "):\n\n" + built.md);
    });
    return out;
  }

  /* An entry is only a change when it would say something in the prompt. A
     blank added row keeps the entry alive but is dropped at copy time, and a
     counter lit for it would light Request changes with nothing to send. */
  function tableHasChange(tid) {
    var st = state.data.tables[tid], t = tableEl(tid);
    if (!st) return false;
    if (st.killed || !t) return true;
    return !!tableSummary(tid, tableMarkdown(t));
  }

  function tableChangeCount() {
    return Object.keys(state.data.tables || {}).filter(tableHasChange).length;
  }

  /* ---------------------------------------------------------- the bubble */

  /* One overlay component, four jobs: ask for a comment, show an existing one,
     show what a rewrite changed, and take a note on a section or step. Keeping
     them in one place is what makes anchoring and dismissal behave the same
     everywhere. */
  var bubble = null;

  function closeBubble() {
    if (bubble && bubble.parentNode) bubble.parentNode.removeChild(bubble);
    bubble = null;
    /* The finish overlay uses is-open too, and this runs on every resize, so
       it is left alone: only closeFinish takes it down. */
    var open = doc.querySelectorAll(".is-open:not(.finish)");
    for (var i = 0; i < open.length; i++) open[i].classList.remove("is-open");
  }

  function openBubble(anchorRect, build) {
    closeBubble();
    bubble = doc.createElement("div");
    bubble.className = "bubble";
    build(bubble);
    doc.body.appendChild(bubble);

    var w = bubble.offsetWidth, h = bubble.offsetHeight;
    var left = anchorRect.left + window.scrollX;
    if (left + w > window.innerWidth - 12) left = window.innerWidth - w - 12;
    var top = anchorRect.bottom + window.scrollY + 8;
    /* Hang it above the anchor when it would otherwise fall past the fold. */
    if (anchorRect.bottom + h + 24 > window.innerHeight) {
      top = anchorRect.top + window.scrollY - h - 8;
    }
    bubble.style.left = Math.max(8, left) + "px";
    bubble.style.top = Math.max(8, top) + "px";
    return bubble;
  }

  /* Every bubble button gets a tooltip, looked up by its label so the call
     sites stay one line each. */
  var BTN_TIPS = {
    "Cancel": "Close without saving (Esc)",
    "Comment": "Save the comment (Enter)",
    "Save": "Save (Enter)",
    "Edit": "Change the text of this comment",
    "Delete": "Delete this comment",
    "Revert this": "Put the original words back for this change only",
    "Revert all": "Put the whole original paragraph back"
  };

  function mkBtn(label, cls, fn) {
    var b = doc.createElement("button");
    if (BTN_TIPS[label]) b.setAttribute("data-tip", BTN_TIPS[label]);
    b.type = "button";
    b.className = cls;
    b.textContent = label;
    b.addEventListener("click", fn);
    return b;
  }

  function mkEl(tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function actionsRow() { return mkEl("div", "bubble-actions"); }

  function submitOn(ta, commit) {
    ta.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); commit(); }
      else if (ev.key === "Escape") { ev.preventDefault(); closeBubble(); }
    });
  }

  /* ---- a new comment on a selected passage ---- */

  function askForComment(sel) {
    var range = sel.getRangeAt(0);
    var quote = sel.toString().replace(/\s+/g, " ").trim();
    var host = range.startContainer.parentElement;
    var sec = host && host.closest ? host.closest(".sec") : null;
    var secId = sec ? sec.getAttribute("data-sec") : "";
    var root = sec || docEl;
    var occ = occurrenceOf(root, quote, range);
    var rect = range.getBoundingClientRect();

    openBubble(rect, function (b) {
      b.appendChild(mkEl("p", "bubble-head", "Comment on this passage"));
      b.appendChild(mkEl("p", "bubble-quote", truncate(quote, QUOTE_CAP)));
      var ta = mkEl("textarea");
      ta.placeholder = "What is wrong with it?";
      b.appendChild(ta);
      var row = actionsRow();
      row.appendChild(mkBtn("Cancel", "btn small", function () { closeBubble(); sel.removeAllRanges(); }));
      row.appendChild(mkBtn("Comment", "btn small primary", commit));
      b.appendChild(row);
      b.appendChild(mkEl("p", "bubble-hint", "Enter saves, Esc cancels."));
      ta.focus();
      submitOn(ta, commit);

      function commit() {
        var text = ta.value.trim();
        if (!text) { closeBubble(); return; }
        var id = "m" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        state.data.marks[id] = { sec: secId, quote: quote, occ: occ, comment: text };
        closeBubble();
        sel.removeAllRanges();
        anchorMark(id);
        save("mark:" + id);
        updatePrompt();
      }
    });
  }

  /* ---- an existing comment ---- */

  function showComment(markEl) {
    var id = markEl.getAttribute("data-mark");
    var entry = state.data.marks[id];
    if (!entry) return;
    openBubble(markEl.getBoundingClientRect(), function (b) {
      b.appendChild(mkEl("p", "bubble-head", "Your comment"));
      b.appendChild(mkEl("p", "bubble-quote", truncate(entry.quote, QUOTE_CAP)));
      b.appendChild(mkEl("p", "bubble-body", entry.comment));
      if (drift[id]) {
        b.appendChild(mkEl("p", "bubble-hint", drift[id] === "moved"
          ? "The marked text has changed since. This is where it is now."
          : "The marked text is no longer in this section."));
      }
      var row = actionsRow();
      row.appendChild(mkBtn("Delete", "btn small danger", function () {
        delete state.data.marks[id];
        closeBubble();
        applyDataToDoc();
        save("unmark:" + id);
        updatePrompt();
      }));
      row.appendChild(mkBtn("Edit", "btn small primary", function () { editComment(markEl, id); }));
      b.appendChild(row);
    });
    /* After openBubble, which clears every open state first. Every piece of a
       comment that spans paragraphs lights up together. */
    var pieces = docEl.querySelectorAll('mark.has-comment[data-mark="' + cssEsc(id) + '"]');
    for (var pc = 0; pc < pieces.length; pc++) pieces[pc].classList.add("is-open");
  }

  function editComment(markEl, id) {
    var entry = state.data.marks[id];
    openBubble(markEl.getBoundingClientRect(), function (b) {
      b.appendChild(mkEl("p", "bubble-head", "Edit comment"));
      var ta = mkEl("textarea");
      ta.value = entry.comment;
      b.appendChild(ta);
      var row = actionsRow();
      row.appendChild(mkBtn("Cancel", "btn small", function () { closeBubble(); }));
      row.appendChild(mkBtn("Save", "btn small primary", commit));
      b.appendChild(row);
      ta.focus();
      submitOn(ta, commit);
      function commit() {
        var text = ta.value.trim();
        if (!text) return;
        entry.comment = text;
        closeBubble();
        save("mark:" + id);
        updatePrompt();
      }
    });
  }

  /* ---- what a rewrite changed ---- */

  function showEdit(el, anchorEl) {
    var id = el.getAttribute("data-edit-id");
    var entry = state.data.edits[id];
    if (!entry) return;
    (anchorEl || el).classList.add("is-open");

    /* Clicking one highlighted run shows that run. Only a click that landed
       outside any mark, or the whole-element fallback, falls back to the
       paragraph, because there is nothing narrower to show. */
    var isRun = anchorEl && anchorEl !== el && anchorEl.classList.contains("edited");
    var was = isRun ? (anchorEl.getAttribute("data-was") || "") : entry.alt;
    var now = isRun ? anchorEl.textContent : entry.neu;

    openBubble((anchorEl || el).getBoundingClientRect(), function (b) {
      b.appendChild(mkEl("p", "bubble-head", isRun ? "This change" : "Before your rewrite"));
      if (was.trim()) {
        b.appendChild(mkEl("p", "bubble-diff old", was));
      } else {
        b.appendChild(mkEl("p", "bubble-diff none", "Nothing here before"));
      }
      b.appendChild(mkEl("p", "bubble-label", "Now"));
      if (now.trim()) {
        b.appendChild(mkEl("p", "bubble-diff new", now));
      } else {
        b.appendChild(mkEl("p", "bubble-diff none", "Removed"));
      }
      var row = actionsRow();
      row.appendChild(mkBtn(isRun ? "Revert this" : "Revert all", "btn small danger", function () {
        if (isRun) revertRun(el, anchorEl); else revertAll(id);
        closeBubble();
      }));
      b.appendChild(row);
    });
  }

  /* ---- a note on a section or a step ---- */

  function noteFor(id, anchorEl) {
    /* Read only. Cancelling must leave no trace, so the entry is created on
       commit, never on open. */
    var entry = state.data.steps[id] || {};
    anchorEl.classList.add("is-open");
    openBubble(anchorEl.getBoundingClientRect(), function (b) {
      b.appendChild(mkEl("p", "bubble-head", "Note on " + truncate(nameFor(id), 40)));
      var ta = mkEl("textarea");
      ta.value = entry.comment || "";
      ta.placeholder = entry.decision === "skip" ? "Why not?" : "Anything to add?";
      b.appendChild(ta);
      var row = actionsRow();
      row.appendChild(mkBtn("Cancel", "btn small", function () { closeBubble(); }));
      row.appendChild(mkBtn("Save", "btn small primary", commit));
      b.appendChild(row);
      ta.focus();
      submitOn(ta, commit);
      function commit() {
        var text = ta.value.trim();
        var live = state.data.steps[id];
        if (text) {
          if (!live) live = state.data.steps[id] = {};
          live.comment = text;
        } else if (live) {
          delete live.comment;
          if (!live.decision) delete state.data.steps[id];
        }
        closeBubble();
        applyDataToDoc();
        save("note:" + id);
        updatePrompt();
      }
    });
  }

  /* ---------------------------------------------------------------- prompt */

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* One line per comment, however it was anchored. When the passage has
     changed, Claude is told so and gets the words as they were marked. */
  function markLine(lead, id, mk) {
    return "- " + lead + ' the passage "' + truncate(mk.quote, QUOTE_CAP) + '"' +
      (drift[id] ? " (the text has changed since)" : "") + ": " + mk.comment;
  }

  function truncate(s, n) { return s.length > n ? s.slice(0, n - 1) + "\u2026" : s; }

  function buildPrompt() {
    var lines = [], approved = [];

    for (var i = 0; i < D.sections.length; i++) {
      var sec = D.sections[i];
      var st = state.data.steps[sec.id] || {};
      var marks = marksFor(sec.id);
      var label = labelOf(sec);

      var touched = marks.length > 0 || editsFor(sec.id).length > 0 || !!st.comment ||
        tablesIn(sec.id).length > 0;

      if (st.decision === "skip") {
        lines.push("- " + label + ": DECLINED" + (st.comment ? ", " + st.comment : ""));
      } else if (st.decision === "ok" && touched) {
        /* Approved is not the same as approved AS WRITTEN. Saying the latter
           while the section also carries a comment or a rewrite would tell
           Claude to build the untouched version. */
        lines.push("- " + label + ": approved, with the changes noted below"
                   + (st.comment ? ". " + st.comment : ""));
      } else if (st.comment) {
        lines.push("- " + label + ": " + st.comment);
      } else if (st.decision === "ok") {
        var all = (sec.steps || []).length > 0 &&
                  decisionsIn(sec).ok.length === (sec.steps || []).length;
        approved.push(label + (all ? " and all its steps" : ""));
      }

      for (var m = 0; m < marks.length; m++) {
        var mk = state.data.marks[marks[m]];
        lines.push(markLine(label + ", on", marks[m], mk));
      }

      var dec = decisionsIn(sec);
      for (var k = 0; k < dec.skip.length; k++) {
        var sk = state.data.steps[dec.skip[k].id] || {};
        lines.push("- " + label + ", DECLINE the step \"" + dec.skip[k].name + "\""
                   + (sk.comment ? ": " + sk.comment : ""));
      }
      /* When the section and every one of its steps is approved, the section
         line already says so. Listing each step again is noise. */
      var steps = sec.steps || [];
      var allStepsOk = steps.length > 0 && dec.ok.length === steps.length;
      if (!(st.decision === "ok" && allStepsOk)) {
        for (var a = 0; a < dec.ok.length; a++) approved.push(sec.num + " / " + dec.ok[a].name);
      }
    }

    /* Only explicit approvals are listed. A section nobody touched is silence,
       not consent, and must never be reported back as approved. */
    if (approved.length) lines.push("- Approved as written: " + approved.join("; "));

    /* A comment whose section is not in the list (renamed heading, or text
       outside any section) is not dropped: it goes out on its own line. */
    Object.keys(state.data.marks).forEach(function (k) {
      if (!sectionFor(state.data.marks[k].sec)) lines.push(markLine("On", k, state.data.marks[k]));
    });

    if (state.data.general.trim()) lines.push("- " + (D.prompt.generalLabel || "Whole plan") + ": " + state.data.general.trim());

    var editIds = Object.keys(state.data.edits);
    var editLines = [];
    for (var e = 0; e < editIds.length; e++) {
      if (editLocked(editIds[e])) continue;
      var ed = state.data.edits[editIds[e]];
      var sc = sectionFor(ed.sec);
      editLines.push("- " + (sc ? labelOf(sc) : "text") + ': "' + ed.alt + '" -> "' + ed.neu + '"');
    }
    var tableLines = tablePromptLines();

    var chosen = D.meta.kind === "options" ? chosenNames() : [];
    var lead = "";
    if (D.meta.kind === "options") {
      lead = chosen.length ? "CHOSEN: " + chosen.join("; ") : "";
    } else {
      var act = actionFor(state.data.verdict);
      /* Approving an untouched page needs no "apply anything below" and no
         how-to-apply footer: there is nothing to apply. */
      var bareApprove = !!(act && act.bare && !changeCount());
      lead = act ? (bareApprove ? act.bare : act.line || "") : "";
    }

    if (!lead && !lines.length && !editLines.length && !tableLines.length) return "";

    /* Saying "nothing was chosen" is only meaningful once there is something to
       say it alongside. An untouched screen is not an answer, so it stays empty
       and the send buttons stay dark. */
    if (D.meta.kind === "options" && !chosen.length) {
      lead = "CHOSEN: nothing. None of the options fit.";
    }

    var out = D.prompt.header;
    if (lead) out += "\n\n" + lead;
    if (lines.length) out += "\n\n" + lines.join("\n");
    if (editLines.length) {
      out += "\n\nExact text changes (old -> new), apply verbatim:\n" + editLines.join("\n");
    }
    if (tableLines.length) {
      out += "\n\nTables, replace each one with the version below:\n\n" + tableLines.join("\n\n");
    }
    /* A declined plan is not going to be edited in place, so the how-to-apply
       footer would be wrong advice. */
    if (D.prompt.footer && state.data.verdict !== "decline" && !bareApprove) out += "\n\n" + D.prompt.footer;
    return out;
  }

  /* Count what a person would call feedback. An entry in the decision map is
     not automatically feedback: opening a note bubble used to create an empty
     one, so the header claimed marks that did not exist. */
  function feedbackCount() {
    var n = Object.keys(state.data.marks).length + totalEditRuns() + tableChangeCount();
    Object.keys(state.data.steps).forEach(function (k) {
      if (hasContent(state.data.steps[k])) n++;
    });
    if (state.data.general.trim()) n++;
    n += Object.keys(state.data.choices).length;
    return n;
  }

  function hasContent(entry) {
    return !!(entry && (entry.decision || (entry.comment && entry.comment.trim())));
  }

  /* What a revision would have to act on. Narrower than feedbackCount, because
     an approval is feedback but not a change: a plan whose every section is
     ticked and nothing else has nothing for another round to do. */
  function changeCount() {
    var n = Object.keys(state.data.marks).length + totalEditRuns() + tableChangeCount();
    Object.keys(state.data.steps).forEach(function (k) {
      var e = state.data.steps[k];
      if (e && (e.decision === "skip" || (e.comment && e.comment.trim()))) n++;
    });
    if (state.data.general.trim()) n++;
    return n;
  }

  /* Drop anything empty that an earlier session left behind, so a stale
     localStorage does not keep reporting phantom marks. */
  function pruneSteps() {
    Object.keys(state.data.steps).forEach(function (k) {
      if (!hasContent(state.data.steps[k])) delete state.data.steps[k];
    });
  }

  var HINTS = {
    plan: "Nothing marked yet. Drag over any sentence to comment on it, switch to " +
          "Edit text to rewrite a line, or use the tick beside a section or step.",
    options: "Nothing chosen yet. Pick a card, or drag over any sentence to say what " +
             "is wrong with it.",
    explain: "Nothing marked yet. Drag over anything that does not land and ask about it.",
    doc: "Nothing marked yet. Drag over any sentence to comment on it, switch to " +
         "Edit text to rewrite a line, or use the tick beside a section."
  };

  /* The counters double as navigation. Each click steps to the next item of
     that kind and scrolls it into view, which is the only practical way to find
     your third comment in a plan with thirty five steps. */
  var navAt = { comments: -1, edits: -1, all: -1 };

  function navTargets(kind) {
    /* A comment across two paragraphs is several marks with one id. It is
       still one comment, so only its first piece is a stop. An earlier comment
       does the same under data-prev. */
    var seenMark = {};
    function firstPiece(el) {
      var mid = el.getAttribute && (el.getAttribute("data-mark") || el.getAttribute("data-prev"));
      if (!mid) return true;
      if (seenMark[mid]) return false;
      seenMark[mid] = true;
      return true;
    }
    if (kind === "comments") {
      return [].slice.call(docEl.querySelectorAll("mark.has-comment, mark.prev-comment, mark.prev-pill[data-label='comment']"))
        .filter(inScope).filter(firstPiece);
    }
    if (kind === "edits") {
      /* Every changed run is its own stop. Grouping by element meant a second
         change in the same paragraph could never be reached, and the jump
         landed on the paragraph rather than on what you changed. querySelectorAll
         returns document order, so the cycle reads top to bottom. */
      return [].slice.call(docEl.querySelectorAll(
        "mark.edited, .chg-whole, table[data-tchg], mark.tbl-orphan, mark.prev-edit, mark.prev-pill:not([data-label='comment'])"
      )).filter(inScope).filter(function (el) {
        /* One earlier rewrite across bold and plain is several pieces under one
           key and is one stop. Current runs are each their own stop. */
        return !el.hasAttribute("data-prev") || firstPiece(el);
      }).filter(function (el) { return !cellLocked(el.closest("td, th")); });
    }
    /* Everything with a place in the document, in document order. The note on
       the whole plan is counted but has nowhere to jump to. */
    return [].slice.call(docEl.querySelectorAll(
      'mark.has-comment, mark.edited, table[data-tchg], mark.tbl-orphan, .chg-whole, .sec[data-decision="ok"], ' +
      '.sec[data-decision="skip"], .step[data-decision="ok"], .step[data-decision="skip"], ' +
      "mark.prev-comment, mark.prev-edit, mark.prev-pill"
    )).filter(inScope).filter(firstPiece).filter(function (el) {
      return !cellLocked(el.closest ? el.closest("td, th") : null);
    }).filter(function (el, i, all) {
      /* A decided section already contains its decided steps and marks; keep
         the outermost one so one click is one stop. Only within one round (both
         current, or both earlier with the same r<i>: prefix): a mark of another
         round around it does not hide it. */
      for (var j = 0; j < all.length; j++) {
        if (all[j] !== el && all[j].contains(el) && roundOf(all[j]) === roundOf(el)) return false;
      }
      return true;
    });
  }

  var reduceMotion = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : false;

  /* The scroll is animated by hand rather than with scrollIntoView({behavior:
     "smooth"}) for one reason: the pulse has to fire when the target has
     actually arrived, and the native smooth scroll gives no dependable end
     signal (scrollend is not everywhere, and polling for stillness cannot tell
     "finished" from "never started").

     requestAnimationFrame does not fire in a hidden or throttled tab, and the
     native smooth scroll does not run there either, so without the fallback
     below a jump in a background tab would silently do nothing at all. */
  function scrollCenter(el) {
    var r = el.getBoundingClientRect(), c = docEl.getBoundingClientRect();
    var want = docEl.scrollTop + (r.top - c.top) - (c.height / 2 - r.height / 2);
    var max = docEl.scrollHeight - docEl.clientHeight;
    return Math.max(0, Math.min(max, want));
  }

  function animateScroll(top, done) {
    var from = docEl.scrollTop, delta = top - from, settled = false;

    function finish() {
      if (settled) return;
      settled = true;
      docEl.scrollTop = top;
      done();
    }

    if (reduceMotion || Math.abs(delta) < 2) { finish(); return; }

    var dur = Math.min(650, Math.max(240, Math.abs(delta) * 0.45));
    var t0 = null, ticked = false;

    function step(ts) {
      if (settled) return;
      ticked = true;
      if (t0 === null) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      var e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;   // easeInOutQuad
      docEl.scrollTop = from + delta * e;
      if (p < 1) requestAnimationFrame(step); else finish();
    }

    requestAnimationFrame(step);
    /* Frames are throttled to nothing in a hidden tab, so land it outright
       rather than leaving the jump half done. */
    setTimeout(function () { if (!ticked) finish(); }, 150);
  }

  function isWellInView(el) {
    var r = el.getBoundingClientRect(), c = docEl.getBoundingClientRect();
    var pad = c.height * 0.15;
    return r.top >= c.top + pad && r.bottom <= c.bottom - pad;
  }

  function pulse(el) {
    var prev = docEl.querySelectorAll(".is-target");
    for (var i = 0; i < prev.length; i++) prev[i].classList.remove("is-target");
    /* Force a reflow so the animation restarts when the same element is hit
       twice in a row. */
    void el.offsetWidth;
    /* A comment over mixed weights is one mark per text node (see wrapRange),
       so the stop is only its first piece. Every piece pulses, or a comment
       that starts in bold lights up its bold half alone. */
    var mid = el.getAttribute("data-mark"), pid = el.getAttribute("data-prev");
    var all = mid ? docEl.querySelectorAll('mark.has-comment[data-mark="' + cssEsc(mid) + '"]') :
      pid ? docEl.querySelectorAll('[data-prev="' + cssEsc(pid) + '"]') : [el];
    for (var j = 0; j < all.length; j++) all[j].classList.add("is-target");
    setTimeout(function () {
      for (var k = 0; k < all.length; k++) all[k].classList.remove("is-target");
    }, 1500);
  }

  function jumpTo(kind) {
    var list = navTargets(kind);
    if (!list.length) return;
    navAt[kind] = (navAt[kind] + 1) % list.length;
    var el = list[navAt[kind]];
    closeBubble();
    flash((navAt[kind] + 1) + " of " + list.length, "", 2400);

    if (isWellInView(el)) { pulse(el); return; }
    animateScroll(scrollCenter(el), function () { pulse(el); });
  }

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function updateCounters() {
    paintScope();
    var counts = {
      comments: Object.keys(state.data.marks).length,
      edits: totalEditRuns() + tableChangeCount(),
      all: feedbackCount()
    };
    var lists = {
      comments: navTargets("comments"), edits: navTargets("edits"), all: navTargets("all")
    };
    if (scopeNow() !== "current") {
      /* Comments and edits count the same lists the clicks walk. The all
         counter is wider, as in 1.0.3: it also counts items with no place in
         the page (a note on the whole plan, answers), so it can exceed its
         stops. In every-round scope it adds the earlier stops to the current
         round's whole count. */
      counts.comments = lists.comments.length;
      counts.edits = lists.edits.length;
      counts.all = scopeNow() === "all"
        ? feedbackCount() + lists.all.filter(isEarlier).length
        : lists.all.length;
    }
    var btns = doc.querySelectorAll(".counter");
    for (var i = 0; i < btns.length; i++) {
      var kind = btns[i].getAttribute("data-kind");
      var n = counts[kind];
      var label = kind === "all" ? n + " marked in all" :
        plural(n, kind === "comments" ? "comment" : "edit");
      /* The chip shows a symbol and the number; the words live in the tooltip
         and the aria-label. */
      var num = btns[i].querySelector(".num");
      if (num) num.textContent = String(n);
      btns[i].disabled = !lists[kind].length;
      btns[i].setAttribute("data-tip",
        label + (btns[i].disabled ? "" : " \u00B7 click to step through them"));
      btns[i].setAttribute("aria-label",
        label + (btns[i].disabled ? "" : ", click to step through them"));
      if (counts[kind] !== (btns[i].__n)) { navAt[kind] = -1; btns[i].__n = counts[kind]; }
    }
  }

  function updatePrompt() {
    var el = doc.getElementById("prompt");
    var text = buildPrompt();
    if (el) {
      el.textContent = text || (HINTS[D.meta.kind] || HINTS.plan);
      el.classList.toggle("is-empty", !text);
    }
    /* A verdict produces an answer on its own, so those stay live even on an
       untouched plan: approving something you have no notes on is real feedback.
       A copy-only button has nothing to copy until something is marked.

       Request changes is the exception, because it means revise and re-present.
       With nothing marked it would send Claude round again with no instruction,
       so it stays grey until there is something to revise. */
    var vs = doc.querySelectorAll(".verdict");
    for (var i = 0; i < vs.length; i++) {
      var kind = vs[i].getAttribute("data-verdict");
      var off = kind === "changes" ? !changeCount() : (!kind && !text);
      vs[i].disabled = off;
      if (kind === "changes" && off) {
        vs[i].setAttribute("data-tip", "Comment, rewrite or decline something first, then this asks for another round");
      } else {
        /* Back to the button's own tooltip, not to none. */
        var base = vs[i].getAttribute("data-tip-base");
        if (base) vs[i].setAttribute("data-tip", base); else vs[i].removeAttribute("data-tip");
      }
    }
    syncHistButtons();
    updateCounters();
  }

  /* -------------------------------------------------------------- status */

  /* The message next to the verdict buttons slides in from the right with a
     fade and leaves the same way. Its box is a clip whose width is animated to
     the measured text, so the note field beside it narrows and widens in step
     instead of jumping. The text is only cleared once the box has closed; a
     new message while one shows just resizes the box to the new text. */
  var statusClear = null, statusHide = null;

  function setStatus(text, cls) {
    var el = doc.getElementById("status");
    if (!el) return;
    var inner = el.querySelector(".status-text") || el;
    clearTimeout(statusClear);
    if (!text) {
      el.classList.remove("is-on");
      el.style.width = "0px";
      statusClear = setTimeout(function () { inner.textContent = ""; el.className = ""; }, 240);
      return;
    }
    var shown = el.classList.contains("is-on");
    inner.textContent = text;
    el.className = (cls || "") + (shown ? " is-on" : "");
    /* The text is inline-block and never wraps, so its own width is right
       even while the box around it is closed. */
    var w = Math.ceil(inner.scrollWidth || inner.offsetWidth);
    if (!shown) void el.offsetWidth;   // commit the closed state so the slide in runs
    el.style.width = w + "px";
    el.classList.add("is-on");
  }

  function resetStatus() { setStatus("", ""); }

  function flash(text, cls, ms) {
    clearTimeout(statusHide);
    setStatus(text, cls == null ? "good" : cls);
    statusHide = setTimeout(resetStatus, ms || 2600);
  }

  /* navigator.clipboard needs a secure context, and file:// is not one. Opening
     the page directly is the documented fallback, so the fallback needs a
     fallback.

     opts.keepPane leaves the prompt pane alone on failure. The finish box
     copies from in front of a backdrop, where an opened pane would sit out of
     reach, so that caller says what to do on its own button instead. */
  function copyText(text, then, opts) {
    function legacy() {
      var ta = doc.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:-1000px;left:0;opacity:0";
      doc.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = doc.execCommand("copy"); } catch (e) { ok = false; }
      doc.body.removeChild(ta);
      if (!ok && !state.ui.prompt && !(opts && opts.keepPane)) {
        /* "Select the text above" needs the text on screen. */
        state.ui.prompt = true;
        applyPromptVisibility();
      }
      flash(ok ? "Copied, now paste it to Claude"
               : "Copy failed, select the text above and copy it by hand",
            ok ? "good" : "bad", 4000);
      if (then) then(ok);
    }
    if (navigator.clipboard && window.isSecureContext) {
      /* Race the write. writeText rejects when the document is not focused, and
         was measured neither resolving nor rejecting in a background tab, which
         left the footer silent. The clipboard is the only way off this page now,
         so a write that says nothing is the one failure worth guarding. */
      var settled = false;
      var done = function (ok) {
        if (settled) return;
        settled = true;
        if (ok) {
          flash("Copied, now paste it to Claude", "good", 4000);
          if (then) then(true);
        } else legacy();
      };
      navigator.clipboard.writeText(text).then(function () { done(true); },
                                               function () { done(false); });
      setTimeout(function () { done(false); }, 1200);
    } else {
      legacy();
    }
  }

  /* One click finishes the review: it records the verdict, rebuilds the answer
     so the verdict leads it, and copies. Pasting is the telling, so putting the
     copy anywhere else was asking for two clicks to do one thing.

     No toggling off. These act now, and a button that undoes itself on a second
     press would copy an answer without the verdict you just chose. */
  /* The draft number in At a glance counts review rounds on the server's side
     (1.1.5), so every browser shows the same one. Fire and forget: a lost signal
     costs one draft number, never a review. A file:// page has no server. */
  function postDraft(action) {
    if (!onServer()) return;
    var body = { slug: D.meta.slug, action: action };
    if (action === "request") body.sourceMtime = D.meta.sourceMtime;
    fetch("/api/draft", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).catch(function () {});
  }

  function finish(kind) {
    if (kind) {
      state.data.verdict = kind;
      /* A change request copied earlier and then overruled by approving or
         declining must not carry its pending round into the next build. */
      if ((kind === "approve" || kind === "decline") && state.data.pending) {
        state.data.pending = null;
        postDraft("cancel");
      }
      syncVerdict();
      save("verdict");
    }
    updatePrompt();
    var text = buildPrompt();
    if (!text) return;
    var box = kind || D.meta.kind;
    copyText(text, function (ok) {
      if (!ok || !FINISH_COPY[box]) return;
      if (kind === "changes") {
        state.data.pending = { sentAt: Date.now(), sourceMtime: D.meta.sourceMtime };
        persist();
        postDraft("request");
      }
      openFinish(box);
    });
  }

  function syncVerdict() {
    var vs = doc.querySelectorAll(".verdict");
    for (var i = 0; i < vs.length; i++) {
      vs[i].setAttribute("aria-pressed",
        vs[i].getAttribute("data-verdict") === state.data.verdict ? "true" : "false");
    }
  }

  /* ------------------------------------------------------ waiting robot */

  /* While the page waits for Claude, a small pixel robot fills the box with
     short sketches. Every open starts on a different sketch than the last one
     (remembered per browser), runs the rest in a shuffled order and rolls new
     details each time, until the page reloads or the box closes. Everything is
     the Web Animations API on SVG built here, so stop() can cancel it all. */
  var SVGNS = "http://www.w3.org/2000/svg";
  var ROBOT_LAST = "review-doc-robot-last";
  var ROBOT_PAL = ["#F0844E", "#D9A62E", "#2f7d55", "#3b6fb6", "#9a3b2a", "#8a5cc2"];
  var ROBOT_TYPOS = ["teh", "recieve", "adn", "wierd", "untill", "seperate", "definately", "occured"];
  var robot = null;

  function rnd(a, b) { return a + Math.random() * (b - a); }
  function pick(list) { return list[Math.floor(Math.random() * list.length)]; }

  /* A shuffled run of the sketch names that does not start on `last`. Pure, so
     the test can drive it with its own random source. */
  function robotOrder(names, last, random) {
    var out = names.slice();
    for (var i = out.length - 1; i > 0; i--) {
      var j = Math.floor(random() * (i + 1)), t = out[i];
      out[i] = out[j]; out[j] = t;
    }
    if (out.length > 1 && out[0] === last) { var s = out[0]; out[0] = out[1]; out[1] = s; }
    return out;
  }

  function svgEl(tag, attrs, parent) {
    var e = doc.createElementNS(SVGNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  function rect(parent, x, y, w, h, cls) {
    return svgEl("rect", { x: x, y: y, width: w, height: h, "class": cls || "" }, parent);
  }

  function origin(e, o) { e.style.transformBox = "fill-box"; e.style.transformOrigin = o || "50% 50%"; return e; }

  /* The robot: 22 x 16 grid cells drawn at 3px, standing on the ground line
     in the middle of the stage. The viewBox runs from -50 to 290 so the
     drawing (0 to 240) sits centred in a strip about four times as wide as
     it is high, the shape of the box. Groups that move get their own node so
     no CSS transform ever fights an SVG transform attribute. */
  function buildRobot(stage) {
    var svg = svgEl("svg", { viewBox: "-50 0 340 84", "class": "rb-svg", "aria-hidden": "true" });
    stage.appendChild(svg);
    svgEl("line", { x1: -50, y1: 78.5, x2: 290, y2: 78.5, "class": "rb-ground" }, svg);
    var back = svgEl("g", {}, svg);
    var pos = svgEl("g", {}, svg);
    var place = svgEl("g", { transform: "translate(87 30) scale(3)" }, pos);
    var hop = origin(svgEl("g", {}, place), "50% 100%");
    var legs = [4, 8, 12, 16].map(function (x) { return origin(rect(hop, x, 12, 2, 4, "rb-body"), "50% 0%"); });
    rect(hop, 3, 2, 16, 10, "rb-body");
    var armL = origin(rect(hop, 0, 6, 3, 3, "rb-body"), "100% 50%");
    var armR = origin(rect(hop, 19, 6, 3, 3, "rb-body"), "0% 50%");
    var look = svgEl("g", {}, hop);
    var eyes = origin(svgEl("g", {}, look));
    rect(eyes, 6, 5, 2, 3, "rb-eye");
    rect(eyes, 14, 5, 2, 3, "rb-eye");
    var carry = svgEl("g", {}, pos);
    var fx = svgEl("g", {}, svg);
    return { svg: svg, back: back, pos: pos, hop: hop, legs: legs, armL: armL, armR: armR,
             look: look, eyes: eyes, carry: carry, fx: fx };
  }

  function robotAnim(e, frames, opts) {
    if (!robot || !e.animate) return null;
    var a = e.animate(frames, opts);
    robot.anims.push(a);
    return a;
  }

  function robotLater(fn, ms) {
    if (!robot) return;
    var r = robot;
    r.timers.push(setTimeout(function () { if (robot === r) fn(); }, ms));
  }

  function robotSay(text) {
    var c = robot && robot.caption;
    if (!c) return;
    c.classList.remove("is-on");
    robotLater(function () { c.textContent = text; c.classList.add("is-on"); }, 160);
  }

  /* A prop that pops in, and a text glyph, both in stage coordinates. */
  function popIn(e, delay) {
    origin(e, "50% 100%");
    robotAnim(e, [{ transform: "scale(0)", opacity: 0 }, { transform: "scale(1.15)", opacity: 1, offset: .7 },
                  { transform: "scale(1)", opacity: 1 }],
              { duration: 320, delay: delay || 0, fill: "both", easing: "ease-out" });
    return e;
  }

  function glyph(parent, x, y, text, cls) {
    var t = svgEl("text", { x: x, y: y, "class": cls || "rb-glyph", "text-anchor": "middle" }, parent);
    t.textContent = text;
    return t;
  }

  function floatAway(e, dx, dy, ms, delay) {
    origin(e);
    robotAnim(e, [{ transform: "translate(0,0) rotate(0deg)", opacity: 0 },
                  { transform: "translate(" + dx * .2 + "px," + dy * .2 + "px) rotate(" + rnd(-20, 20) + "deg)", opacity: 1, offset: .2 },
                  { transform: "translate(" + dx + "px," + dy + "px) rotate(" + rnd(-40, 40) + "deg)", opacity: 0 }],
              { duration: ms, delay: delay || 0, fill: "both", easing: "ease-out" });
  }

  function walkLegs(r, ms, step) {
    step = step || 170;
    r.legs.forEach(function (leg, i) {
      robotAnim(leg, [{ transform: "scaleY(1)" }, { transform: "scaleY(.5)" }, { transform: "scaleY(1)" }],
                { duration: step * 2, iterations: Math.ceil(ms / (step * 2)), delay: i % 2 ? step : 0 });
    });
    robotAnim(r.hop, [{ transform: "translateY(0)" }, { transform: "translateY(-.6px)" }, { transform: "translateY(0)" }],
              { duration: step, iterations: Math.ceil(ms / step) });
  }

  function pumpArms(r, ms, beat, lift) {
    [r.armL, r.armR].forEach(function (arm, i) {
      robotAnim(arm, [{ transform: "translateY(0)" }, { transform: "translateY(" + -(lift || 2) + "px)" }, { transform: "translateY(0)" }],
                { duration: beat * 2, iterations: Math.ceil(ms / (beat * 2)), delay: i ? beat : 0 });
    });
  }

  function lookAt(r, x, y, ms, delay) {
    robotAnim(r.look, [{ transform: "translate(0,0)" }, { transform: "translate(" + x + "px," + y + "px)", offset: .12 },
                       { transform: "translate(" + x + "px," + y + "px)", offset: .88 }, { transform: "translate(0,0)" }],
              { duration: ms, delay: delay || 0, fill: "both" });
  }

  function jump(r, height, delay, times) {
    robotAnim(r.hop, [{ transform: "translateY(0) scale(1,1)" }, { transform: "translateY(0) scale(1.1,.85)", offset: .15 },
                      { transform: "translateY(" + -height + "px) scale(.92,1.1)", offset: .5 },
                      { transform: "translateY(0) scale(1.1,.88)", offset: .85 }, { transform: "translateY(0) scale(1,1)" }],
              { duration: 520, delay: delay || 0, iterations: times || 1, easing: "ease-in-out" });
  }

  function burst(parent, x, y, n, delay) {
    for (var i = 0; i < n; i++) {
      var a = (Math.PI * 2 * i) / n + rnd(-.3, .3), d = rnd(12, 22);
      var p = svgEl("rect", { x: x - 1.5, y: y - 1.5, width: 3, height: 3, fill: pick(ROBOT_PAL) }, parent);
      robotAnim(p, [{ transform: "translate(0,0) scale(1)", opacity: 1 },
                    { transform: "translate(" + Math.cos(a) * d + "px," + Math.sin(a) * d + "px) scale(.3)", opacity: 0 }],
                { duration: 600, delay: delay || 0, fill: "both", easing: "ease-out" });
    }
  }

  /* The sketches. Each one draws its props, sets its animations going and
     returns how long it runs; the director clears the props afterwards. */
  var ROBOT_SCENES = {
    typing: function (r) {
      robotSay(pick(["Typing up your changes", "Hammering the keyboard", "Writing it all down"]));
      var lap = popIn(svgEl("g", {}, r.fx));
      rect(lap, 100, 56, 40, 15, "rb-lid");
      svgEl("circle", { cx: 120, cy: 63.5, r: 2, "class": "rb-logo" }, lap);
      rect(lap, 94, 71, 52, 3, "rb-dark");
      lookAt(r, 0, 1, 4800);
      pumpArms(r, 4600, 90, 2);
      var bits = ["{", "}", "</>", ";", "=", "#", "()", "[]", "*", "+", "fn", "ok"];
      var n = 9 + Math.floor(rnd(0, 6));
      for (var i = 0; i < n; i++) {
        floatAway(glyph(r.fx, rnd(104, 136), 56, pick(bits)), rnd(-26, 26), rnd(-40, -54), rnd(900, 1400), 300 + i * rnd(280, 400));
      }
      robotLater(function () { robotSay("Saved"); jump(r, 5, 0, 1); burst(r.fx, 120, 26, 10); }, 4700);
      return 5600;
    },

    juggle: function (r) {
      robotSay(pick(["Juggling your comments", "Keeping every note in the air", "Three notes, two hands"]));
      lookAt(r, 0, -1, 4600);
      var beat = rnd(480, 600), apex = rnd(4, 12), cycle = beat * 2;
      pumpArms(r, 4400, beat / 2, 2.5);
      var balls = [0, 1, 2].map(function (i) {
        var b = svgEl("circle", { cx: 0, cy: 0, r: 3.2, fill: ROBOT_PAL[(i + Math.floor(rnd(0, 6))) % 6] }, r.fx);
        robotAnim(b, [{ transform: "translate(97px,52px)", easing: "ease-out" },
                      { transform: "translate(120px," + apex + "px)", offset: .25, easing: "ease-in" },
                      { transform: "translate(143px,52px)", offset: .5 },
                      { transform: "translate(120px,57px)", offset: .75 },
                      { transform: "translate(97px,52px)" }],
                  { duration: cycle, iterations: 4, iterationStart: i / 3 });
        return b;
      });
      var drop = Math.random() < .45;
      robotLater(function () {
        balls.forEach(function (b) { b.remove(); });
        if (drop) {
          robotSay("Oops");
          var b = svgEl("circle", { cx: 0, cy: 0, r: 3.2, fill: pick(ROBOT_PAL) }, r.fx);
          robotAnim(b, [{ transform: "translate(120px,-6px)", easing: "ease-in" },
                        { transform: "translate(120px,33px)", offset: .4, easing: "ease-out" },
                        { transform: "translate(150px,14px)", offset: .7, easing: "ease-in" },
                        { transform: "translate(200px,75px)" }],
                    { duration: 1100, fill: "both" });
          robotAnim(r.hop, [{ transform: "scale(1,1)" }, { transform: "scale(1.12,.8)", offset: .45 },
                            { transform: "scale(.96,1.05)", offset: .7 }, { transform: "scale(1,1)" }],
                    { duration: 700, delay: 380 });
          robotAnim(r.eyes, [{ transform: "scaleY(1)" }, { transform: "scaleY(.2)", offset: .2 },
                             { transform: "scaleY(.2)", offset: .8 }, { transform: "scaleY(1)" }],
                    { duration: 900, delay: 420 });
        } else {
          robotSay("Ta-da");
          robotAnim(r.hop, [{ transform: "rotate(0deg)" }, { transform: "rotate(-12deg) translateY(1px)", offset: .5 },
                            { transform: "rotate(0deg)" }], { duration: 800, easing: "ease-in-out" });
          burst(r.fx, 120, 20, 12, 300);
        }
      }, cycle * 4 - 60);
      return cycle * 4 + 1400;
    },

    fetch: function (r) {
      var dir = Math.random() < .5 ? 1 : -1;
      robotSay(pick(["Fetching a fresh copy", "Running to the printer", "Off to get the new version"]));
      var paper = popIn(svgEl("g", {}, r.carry));
      rect(paper, 106, 12, 28, 21, "rb-paper");
      [16, 20, 24, 28].forEach(function (y, i) { rect(paper, 110, y, i === 3 ? 12 : 20, 1.4, "rb-ink"); });
      lookAt(r, 1.5 * dir, 0, 1700);
      walkLegs(r, 3900, 140);
      robotAnim(r.pos, [{ transform: "translateX(0)", easing: "ease-in" }, { transform: "translateX(" + 215 * dir + "px)", offset: .42 },
                        { transform: "translateX(" + -215 * dir + "px)", offset: .58, easing: "ease-out" },
                        { transform: "translateX(0)" }], { duration: 3900 });
      robotLater(function () {
        while (paper.firstChild) paper.removeChild(paper.firstChild);
        rect(paper, 106, 12, 28, 21, "rb-paper fresh");
        svgEl("path", { d: "M113 22.5l4 4 8-8", "class": "rb-tick" }, paper);
        lookAt(r, 1.5 * dir, 0, 1700);
      }, 2000);
      robotLater(function () { robotSay("Got the new version"); jump(r, 6, 0, 1); }, 4000);
      return 5000;
    },

    idea: function (r) {
      robotSay(pick(["Thinking it over", "Hmm", "Pondering your notes"]));
      var think = svgEl("g", {}, r.fx);
      [[152, 34, 1.6], [160, 26, 2.4], [170, 17, 3.2]].forEach(function (c, i) {
        popIn(svgEl("circle", { cx: c[0], cy: c[1], r: c[2], "class": "rb-cloud" }, think), 250 + i * 300);
      });
      popIn(glyph(think, 184, 18, "?", "rb-big"), 1300);
      lookAt(r, 1.5, -1, 2400);
      robotAnim(r.hop, [{ transform: "rotate(0deg)" }, { transform: "rotate(-7deg)", offset: .2 },
                        { transform: "rotate(-7deg)", offset: .8 }, { transform: "rotate(0deg)" }],
                { duration: 2400, easing: "ease-in-out" });
      robotLater(function () {
        think.remove();
        robotSay(pick(["Got an idea", "Eureka", "Aha"]));
        var bulb = popIn(svgEl("g", {}, r.fx));
        svgEl("circle", { cx: 120, cy: 16, r: 7, "class": "rb-bulb" }, bulb);
        rect(bulb, 116.5, 22, 7, 4, "rb-dark");
        var rays = origin(svgEl("g", {}, r.fx));
        for (var i = 0; i < 8; i++) {
          var a = i * Math.PI / 4;
          svgEl("line", { x1: 120 + Math.cos(a) * 10, y1: 16 + Math.sin(a) * 10,
                          x2: 120 + Math.cos(a) * 14, y2: 16 + Math.sin(a) * 14, "class": "rb-ray" }, rays);
        }
        robotAnim(rays, [{ opacity: 0, transform: "scale(.6) rotate(0deg)" }, { opacity: 1, transform: "scale(1.1) rotate(22deg)" }],
                  { duration: 420, iterations: 5, direction: "alternate" });
        pumpArms(r, 1600, 200, 4);
        jump(r, 7, 100, 2);
      }, 2500);
      return 4900;
    },

    fishing: function (r) {
      robotSay(pick(["Fishing out bugs", "Gone fishing for typos", "Casting for bugs"]));
      var pond = svgEl("g", {}, r.back);
      var wave = svgEl("path", { d: "M168 76 q5 -3 10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0", "class": "rb-water" }, pond);
      robotAnim(wave, [{ transform: "translateX(0)" }, { transform: "translateX(-10px)" }], { duration: 900, iterations: 8 });
      lookAt(r, 1.5, 0, 6000);
      var rod = svgEl("g", {}, r.fx);
      svgEl("line", { x1: 152, y1: 53, x2: 196, y2: 22, "class": "rb-rod" }, rod);
      var line = origin(rect(rod, 195.6, 22, .8, 50, "rb-dark"), "50% 0%");
      var bob = svgEl("g", {}, rod);
      svgEl("circle", { cx: 196, cy: 72, r: 2.6, "class": "rb-bob" }, bob);
      robotAnim(line, [{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }], { duration: 500, fill: "both", easing: "ease-out" });
      robotAnim(bob, [{ transform: "translateY(-50px)" }, { transform: "translateY(0)" }], { duration: 500, fill: "both", easing: "ease-out" });
      robotAnim(bob, [{ transform: "translateY(0)" }, { transform: "translateY(1.4px)" }, { transform: "translateY(0)" }],
                { duration: 700, iterations: 4, delay: 500 });
      var wait = rnd(1700, 2700);
      robotLater(function () {
        robotAnim(bob, [{ transform: "translateY(0)" }, { transform: "translateY(4px)" }, { transform: "translateY(0)" },
                        { transform: "translateY(5px)" }, { transform: "translateY(0)" }], { duration: 500 });
        robotAnim(r.eyes, [{ transform: "scale(1)" }, { transform: "scale(1.35)", offset: .3 }, { transform: "scale(1)" }], { duration: 700 });
      }, wait);
      var boot = Math.random() < .3;
      robotLater(function () {
        bob.remove();
        robotAnim(r.hop, [{ transform: "rotate(0deg)" }, { transform: "rotate(-11deg)", offset: .3 }, { transform: "rotate(0deg)" }],
                  { duration: 900, easing: "ease-out" });
        robotAnim(line, [{ transform: "scaleY(1)" }, { transform: "scaleY(.3)" }], { duration: 450, fill: "both", easing: "ease-in" });
        var catchG = svgEl("g", {}, rod);
        var c = origin(svgEl("g", {}, catchG), "50% 0%");
        if (boot) {
          rect(c, 192, 37, 5, 8, "rb-dark");
          rect(c, 192, 43, 10, 4, "rb-dark");
        } else {
          svgEl("ellipse", { cx: 196, cy: 41, rx: 4, ry: 5, "class": "rb-bug" }, c);
          [[191, 38], [191, 42], [199, 38], [199, 42]].forEach(function (p) { rect(c, p[0], p[1], 2, 1, "rb-dark"); });
          rect(c, 195, 35, 2, 2, "rb-dark");
        }
        robotAnim(catchG, [{ transform: "translateY(36px)" }, { transform: "translateY(0)" }], { duration: 450, fill: "both", easing: "ease-in" });
        robotAnim(c, [{ transform: "rotate(-18deg)" }, { transform: "rotate(18deg)" }],
                  { duration: 180, iterations: 8, direction: "alternate", delay: 450 });
        robotSay(boot ? "Caught a boot" : "Caught a bug");
        robotLater(function () {
          catchG.remove();
          burst(r.fx, 196, 41, 9);
          if (boot) robotAnim(r.hop, [{ transform: "translateX(0)" }, { transform: "translateX(-1px)" }, { transform: "translateX(1px)" },
                                      { transform: "translateX(0)" }], { duration: 160, iterations: 4 });
          else jump(r, 5, 80, 1);
        }, 1700);
      }, wait + 550);
      return wait + 3300;
    },

    dance: function (r) {
      robotSay(pick(["Dancing while it waits", "Busting a move", "A little victory dance"]));
      var beat = rnd(320, 400), beats = 12;
      var floor = svgEl("g", {}, r.back);
      var tiles = [];
      for (var i = 0; i < 8; i++) tiles.push(rect(floor, 60 + i * 15, 79, 14, 4, ""));
      tiles.forEach(function (t, i) {
        t.setAttribute("fill", ROBOT_PAL[i % 6]);
        robotAnim(t, [{ opacity: .15 }, { opacity: .9 }, { opacity: .15 }],
                  { duration: beat * 2, iterations: beats / 2, delay: (i % 3) * beat * .66 });
      });
      robotAnim(r.hop, [{ transform: "translateY(0) rotate(0deg)" }, { transform: "translateY(-4px) rotate(-9deg)", offset: .25 },
                        { transform: "translateY(0) rotate(0deg)", offset: .5 }, { transform: "translateY(-4px) rotate(9deg)", offset: .75 },
                        { transform: "translateY(0) rotate(0deg)" }],
                { duration: beat * 4, iterations: beats / 4, easing: "ease-in-out" });
      pumpArms(r, beat * beats, beat, 4);
      robotAnim(r.pos, [{ transform: "translateX(0)" }, { transform: "translateX(-18px)", offset: .25 },
                        { transform: "translateX(18px)", offset: .75 }, { transform: "translateX(0)" }],
                { duration: beat * beats, easing: "ease-in-out" });
      for (var n = 0; n < 7; n++) {
        floatAway(glyph(r.fx, rnd(70, 170), rnd(40, 60), pick(["♪", "♫", "♩"]), "rb-note"),
                  rnd(-16, 16), rnd(-30, -40), 1400, n * beat * 1.6);
      }
      robotLater(function () { robotSay("Nailed it"); burst(r.fx, 120, 24, 14); }, beat * beats);
      return beat * beats + 900;
    },

    coffee: function (r) {
      robotSay(pick(["Refueling", "Coffee break", "One more coffee"]));
      var cup = popIn(svgEl("g", {}, r.carry));
      rect(cup, 152, 44, 9, 10, "rb-paper");
      svgEl("path", { d: "M161 46.5h2.5v4.5h-2.5", "class": "rb-handle" }, cup);
      for (var i = 0; i < 3; i++) {
        floatAway(svgEl("path", { d: "M" + (154 + i * 2.5) + " 41 q-2 -3 0 -5 t0 -5", "class": "rb-steam" }, r.carry),
                  rnd(-3, 3), -14, 1300, 200 + i * 450);
      }
      origin(cup, "50% 100%");
      var sip = [{ transform: "translate(0,0) rotate(0deg)" }, { transform: "translate(-15px,-1px) rotate(-25deg)", offset: .3 },
                 { transform: "translate(-15px,-1px) rotate(-25deg)", offset: .7 }, { transform: "translate(0,0) rotate(0deg)" }];
      robotAnim(cup, sip, { duration: 1100, delay: 900 });
      robotAnim(cup, sip, { duration: 1100, delay: 2300 });
      robotAnim(r.armR, [{ transform: "translate(0,0)" }, { transform: "translate(-3px,-2px)", offset: .3 },
                         { transform: "translate(-3px,-2px)", offset: .7 }, { transform: "translate(0,0)" }],
                { duration: 1100, delay: 900, iterations: 1 });
      robotLater(function () {
        robotSay(pick(["Fully charged", "Wide awake", "Turbo mode"]));
        robotAnim(r.eyes, [{ transform: "scale(1)" }, { transform: "scale(1.5)", offset: .1 }, { transform: "scale(1.5)", offset: .9 },
                           { transform: "scale(1)" }], { duration: 1500 });
        robotAnim(r.hop, [{ transform: "translateX(-.8px)" }, { transform: "translateX(.8px)" }],
                  { duration: 45, iterations: 30, direction: "alternate" });
        for (var z = 0; z < 4; z++) {
          var x = pick([82, 92, 148, 158]), y = rnd(26, 44);
          floatAway(svgEl("path", { d: "M" + x + " " + y + "l3 -4h-2l3 -5", "class": "rb-zap" }, r.fx), rnd(-6, 6), -8, 600, z * 220);
        }
      }, 3500);
      return 5300;
    },

    sweep: function (r) {
      robotSay(pick(["Sweeping up typos", "Tidying the page", "Cleaning up"]));
      var words = ROBOT_TYPOS.slice().sort(function () { return Math.random() - .5; }).slice(0, 3);
      var spots = [180, 224, 268], reach = [300, 900, 2000];
      var junk = words.map(function (w, i) { return glyph(r.fx, spots[i], 76, w, "rb-typo"); });
      var broom = origin(svgEl("g", {}, r.carry), "50% 0%");
      svgEl("line", { x1: 152, y1: 46, x2: 166, y2: 75, "class": "rb-rod" }, broom);
      rect(broom, 161, 74, 12, 4, "rb-broom");
      robotAnim(broom, [{ transform: "rotate(-10deg)" }, { transform: "rotate(12deg)" }],
                { duration: 260, iterations: 18, direction: "alternate", easing: "ease-in-out" });
      lookAt(r, 1.5, 1, 2700);
      walkLegs(r, 2600, 160);
      robotAnim(r.pos, [{ transform: "translateX(0)" }, { transform: "translateX(100px)" }], { duration: 2600, fill: "forwards", easing: "ease-in-out" });
      junk.forEach(function (j, i) {
        robotLater(function () {
          floatAway(j, rnd(50, 80), rnd(-24, -6), 800);
          burst(r.fx, spots[i], 74, 5);
        }, reach[i]);
      });
      robotLater(function () {
        robotSay(pick(["Spotless", "All clean", "Much better"]));
        lookAt(r, -1.5, 0, 2200);
        walkLegs(r, 2000, 160);
        robotAnim(r.pos, [{ transform: "translateX(100px)" }, { transform: "translateX(0)" }],
                  { duration: 2000, fill: "forwards", easing: "ease-in-out" });
      }, 2800);
      return 5300;
    }
  };

  /* Each open picks how the robot walks on stage, too. */
  function robotEnter(r) {
    var way = pick(["drop", "slide", "rise", "beam"]);
    if (way === "drop") {
      robotAnim(r.pos, [{ transform: "translateY(-90px)", easing: "ease-in" }, { transform: "translateY(0)", offset: .55, easing: "ease-out" },
                        { transform: "translateY(-12px)", offset: .75, easing: "ease-in" }, { transform: "translateY(0)" }],
                { duration: 900 });
      robotAnim(r.hop, [{ transform: "scale(1,1)" }, { transform: "scale(1.15,.8)" }, { transform: "scale(1,1)" }], { duration: 300, delay: 480 });
    } else if (way === "slide") {
      var d = Math.random() < .5 ? -1 : 1;
      walkLegs(r, 1000, 120);
      lookAt(r, -1.5 * d, 0, 1100);
      robotAnim(r.pos, [{ transform: "translateX(" + 215 * d + "px)" }, { transform: "translateX(0)" }], { duration: 1000, easing: "ease-out" });
    } else if (way === "rise") {
      origin(r.pos, "50% 100%");
      robotAnim(r.pos, [{ transform: "scaleY(0)" }, { transform: "scaleY(1.2)", offset: .7 }, { transform: "scaleY(1)" }],
                { duration: 650, easing: "ease-out" });
    } else {
      robotAnim(r.pos, [{ opacity: 0 }, { opacity: 1 }, { opacity: .1 }, { opacity: 1 }, { opacity: .3 }, { opacity: 1 }], { duration: 800 });
      burst(r.fx, 120, 50, 12, 500);
    }
    robotSay(pick(["Hello", "Hi there", "On it", "Reporting for duty"]));
    return 1200;
  }

  function robotBlink() {
    if (!robot) return;
    robotAnim(robot.parts.eyes, [{ transform: "scaleY(1)" }, { transform: "scaleY(.1)" }, { transform: "scaleY(1)" }], { duration: 170 });
    robotLater(robotBlink, rnd(1800, 4200));
  }

  function robotNext() {
    var r = robot;
    if (!r) return;
    if (!r.queue.length) r.queue = robotOrder(Object.keys(ROBOT_SCENES), r.prev, Math.random);
    var name = r.queue.shift();
    r.prev = name;
    var p = r.parts;
    r.anims.forEach(function (a) { try { a.cancel(); } catch (e) { /* already gone */ } });
    r.anims = [];
    [p.fx, p.back, p.carry].forEach(function (g) { while (g.firstChild) g.removeChild(g.firstChild); });
    var ms = ROBOT_SCENES[name](p);
    robotLater(robotNext, ms + rnd(300, 700));
  }

  function startRobot() {
    stopRobot();
    var stage = doc.querySelector(".robot-stage"), caption = doc.querySelector(".robot-caption");
    if (!stage) return;
    robot = { anims: [], timers: [], queue: [], prev: null, caption: caption };
    robot.parts = buildRobot(stage);
    if (reduceMotion || !stage.animate) {
      if (caption) { caption.textContent = "Waiting for the new version"; caption.classList.add("is-on"); }
      return;
    }
    var last = null;
    try { last = localStorage.getItem(ROBOT_LAST); } catch (e) { /* blocked storage */ }
    robot.queue = robotOrder(Object.keys(ROBOT_SCENES), last, Math.random);
    try { localStorage.setItem(ROBOT_LAST, robot.queue[0]); } catch (e) { /* blocked storage */ }
    robotLater(robotBlink, rnd(900, 2000));
    robotLater(robotNext, robotEnter(robot.parts));
  }

  function stopRobot() {
    if (!robot) return;
    robot.anims.forEach(function (a) { try { a.cancel(); } catch (e) { /* already gone */ } });
    robot.timers.forEach(clearTimeout);
    var stage = doc.querySelector(".robot-stage");
    while (stage && stage.firstChild) stage.removeChild(stage.firstChild);
    if (robot.caption) { robot.caption.classList.remove("is-on"); robot.caption.textContent = ""; }
    robot = null;
  }

  /* ---------------------------------------------------- finish overlay */

  var IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || "");
  var FINISH_COPY = {
    approve: { title: "Approved", close: true, forget: true,
               text: "Your approve prompt has been copied. Paste it back to Claude and close this page." },
    decline: { title: "Declined", close: true,
               text: "Your decline prompt has been copied. Paste it back to Claude and close this page." },
    changes: { title: "Waiting for Claude", close: false, wait: true,
               text: "Your change request has been copied. Paste it back to Claude and wait for this page to reload." },
    /* A choice screen's one button has no verdict; the box is named after the
       screen's kind instead, and finishes like Approved. */
    options: { title: "Answer copied", close: true, verdict: "", forget: true,
               text: "Your answer has been copied. Paste it back to Claude and close this page." },
    explain: { title: "Questions copied", close: true, verdict: "", forget: true,
               text: "Your questions have been copied. Paste them back to Claude and close this page." }
  };
  var finishKind = null, finishFrom = null, closeTimer = null;

  function finishEl(id) { return doc.getElementById(id); }
  function finishOpen() { return !!finishKind; }

  function openFinish(kind) {
    var c = FINISH_COPY[kind], root = finishEl("finish");
    if (!c || !root) return;
    closeBubble();
    hideTip();
    /* The copy may have run through the async clipboard, so activeElement is
       not reliably the button that was pressed. Name it instead. */
    if (!finishKind) finishFrom = doc.querySelector('.verdict[data-verdict="' +
                                    (c.verdict != null ? c.verdict : kind) + '"]') || doc.activeElement;
    finishKind = kind;
    root.querySelector(".finish-title-text").textContent = c.title;
    finishEl("finish-text").textContent = c.text;
    root.classList.toggle("is-wait", !!c.wait);
    root.setAttribute("data-kind", kind);
    /* The header and footer stay sharp above the blur; the header shows the
       whole title, as resting on it would. */
    doc.body.classList.add("finishing");
    var header = doc.querySelector("header");
    if (header) header.classList.add("title-peek");
    var close = finishEl("finish-close");
    close.hidden = !c.close;
    disarmClose();
    root.hidden = false;
    void root.offsetWidth;            // commit the hidden state so the fade runs
    root.classList.add("is-open");
    if (c.wait) startWaiting();
    if (kind === "changes") startRobot(); else stopRobot();
    (c.close ? close : finishEl("finish-cancel")).focus();
  }

  function closeFinish(restoreFocus) {
    var root = finishEl("finish");
    if (!root || !finishKind) return;
    finishKind = null;
    stopWaiting();
    stopRobot();
    disarmClose();
    root.classList.remove("is-open");
    doc.body.classList.remove("finishing");
    var header = doc.querySelector("header");
    if (header) header.classList.remove("title-peek");
    setTimeout(function () { if (!finishKind) root.hidden = true; }, reduceMotion ? 0 : 240);
    if (restoreFocus !== false && finishFrom && finishFrom.focus) finishFrom.focus();
  }

  function onFinishCancel() {
    forgotten = false;
    closeFinish();
    state.data.verdict = "";
    state.data.pending = null;
    postDraft("cancel");
    syncVerdict();
    save("verdict");
    updatePrompt();
  }

  function closeArmed() { var b = finishEl("finish-close"); return !!b && b.classList.contains("armed"); }

  function armClose() {
    var b = finishEl("finish-close");
    if (!b) return;
    b.classList.add("armed");
    b.querySelector(".lbl").textContent = "Confirm";
    b.setAttribute("data-tip", "Click again to close this page");
    clearTimeout(closeTimer);
    closeTimer = setTimeout(disarmClose, RESET_WINDOW_MS);
  }

  function disarmClose() {
    clearTimeout(closeTimer);
    var b = finishEl("finish-close");
    if (!b) return;
    b.classList.remove("armed");
    b.querySelector(".lbl").textContent = "Close page";
    b.setAttribute("data-tip", "Close this page");
  }

  /* After window.close() fails the page stays open with its in-memory state,
     and persist() would write the record straight back. */
  function forgetPage() {
    forgotten = true;
    try { localStorage.removeItem(LSKEY); } catch (e) { /* blocked storage */ }
  }

  /* Browsers only let a script close a window a script opened. A page opened by
     VS Code or the system browser stays, so after a moment the box says how to
     close it by hand. A Cancel inside that moment has already closed the box,
     so the late message stays out of it. */
  function onFinishClose() {
    if (!closeArmed()) { armClose(); return; }
    disarmClose();
    if (FINISH_COPY[finishKind].forget) forgetPage();
    window.close();
    setTimeout(function () {
      if (!finishKind) return;
      finishEl("finish-text").textContent =
        "Your browser keeps this tab open. Close it with " + (IS_MAC ? "Cmd+W." : "Ctrl+W.");
      finishEl("finish-close").hidden = true;
      finishEl("finish-cancel").focus();
    }, 300);
  }

  /* The clipboard is easy to overwrite before the paste happens, so every box
     offers the same prompt once more. The footer status sits behind the
     backdrop, so the button reports on itself. */
  var recopyTimer = null;

  function onFinishRecopy() {
    var b = finishEl("finish-recopy"), text = buildPrompt();
    if (!b || !text) return;
    copyText(text, function (ok) {
      b.textContent = ok ? "Copied" : "Copy failed. Cancel, then copy from the prompt pane";
      b.classList.toggle("is-done", ok);
      clearTimeout(recopyTimer);
      /* The failure is a sentence to act on, so it stays longer. */
      recopyTimer = setTimeout(function () {
        b.textContent = "Copy prompt again";
        b.classList.remove("is-done");
      }, ok ? 1500 : 5000);
    }, { keepPane: true });
  }

  function trapFinishFocus(ev) {
    if (!finishOpen() || ev.key !== "Tab") return;
    var btns = [].slice.call(finishEl("finish").querySelectorAll("button:not([hidden])"));
    if (!btns.length) return;
    var i = btns.indexOf(doc.activeElement);
    var next = ev.shiftKey ? (i <= 0 ? btns.length - 1 : i - 1) : (i + 1) % btns.length;
    ev.preventDefault();
    btns[next].focus();
  }

  /* -------------------------------------------------------- settings panel */

  /* Opened from the credit line. It edits the same config.json as the settings
     command, through the server, which checks every value again. From file://
     there is no server to ask, so the button says how to do it from Claude
     Code instead. It is aria-disabled rather than disabled, because a disabled
     button gets no mouse events and its tooltip would never show. */
  var KIND_ROWS = [
    { key: "md", label: "Markdown documents" },
    { key: "html", label: "HTML documents", note: "arrives in 1.2", off: true },
    { key: "plan", label: "Plans" },
    { key: "choice", label: "Options and explainer screens" }
  ];

  /* Hours since this page was built, or null when the page does not say. The
     server prunes by the page file's time, which is the same moment. */
  function pageAgeHours() {
    var t = Date.parse(D.meta.generatedAt || "");
    return isNaN(t) ? null : (Date.now() - t) / 3600000;
  }

  /* Same origin, so the browser sends the Origin header the server insists on. */
  function postSettings(update) {
    return fetch("/api/settings", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update)
    }).then(function (r) {
      return r.json().then(function (j) {
        if (r.ok) return { ok: true, settings: j };
        return { ok: false, field: j.field || null, error: j.error || ("Not saved (" + r.status + ")") };
      }, function () {
        return { ok: false, field: null, error: "Not saved (" + r.status + ")" };
      });
    }).catch(function () {
      return { ok: false, field: null, error: "Not saved: the review server did not answer." };
    });
  }

  function openSettings(btn, s) {
    var age = pageAgeHours();
    openBubble(btn.getBoundingClientRect(), function (b) {
      b.classList.add("settings-panel");
      b.setAttribute("role", "dialog");
      b.setAttribute("aria-label", "Review page settings");
      /* Focus goes to the panel, not into the number, so nothing opens
         highlighted; Tab reaches the hours next. */
      b.setAttribute("tabindex", "-1");
      b.appendChild(mkEl("p", "bubble-head", "Settings"));

      var hours = doc.createElement("input");
      hours.type = "number";
      hours.min = "1";
      hours.max = "720";
      hours.step = "1";
      hours.value = String(s.stale_hours);
      var hrow = mkEl("label", "set-row set-hours");
      hrow.appendChild(doc.createTextNode("Delete pages after "));
      hrow.appendChild(hours);
      hrow.appendChild(doc.createTextNode(" hours"));
      b.appendChild(hrow);
      b.appendChild(mkEl("p", "bubble-hint set-hint", "Comments not saved for as long are dropped too. 1 to 720."));

      function box(label, checked, disabled, note) {
        var l = mkEl("label", "set-row set-check" + (disabled ? " is-off" : ""));
        var c = doc.createElement("input");
        c.type = "checkbox";
        c.checked = !!checked;
        c.disabled = !!disabled;
        l.appendChild(c);
        l.appendChild(doc.createTextNode(" " + label));
        if (note) l.appendChild(mkEl("span", "set-note", note));
        b.appendChild(l);
        return c;
      }
      var auto = box("Open new pages on their own", s.auto_open);
      var tips = box("Show tooltips", s.show_tips !== false);
      b.appendChild(mkEl("p", "bubble-label", "Page types"));
      var boxes = {};
      KIND_ROWS.forEach(function (k) {
        boxes[k.key] = box(k.label, (s.kinds || {})[k.key], k.off, k.note);
      });

      var warn = mkEl("p", "set-warn");
      warn.hidden = true;
      warn.setAttribute("role", "status");
      var err = mkEl("p", "set-error");
      err.hidden = true;
      err.setAttribute("role", "alert");
      b.appendChild(warn);
      b.appendChild(err);

      var row = actionsRow();
      var save = mkBtn("Save", "btn small primary", commit);
      row.appendChild(mkBtn("Cancel", "btn small", closeBubble));
      row.appendChild(save);
      b.appendChild(row);

      /* Warn as the number changes, so the warning comes before the click. */
      function checkAge() {
        var h = Number(hours.value);
        var risky = age !== null && validHours(h) && age > h;
        warn.hidden = !risky;
        if (risky) warn.textContent = "This page is " + Math.floor(age) + " hours old and would be deleted at the next cleanup.";
        save.textContent = risky ? "Save anyway" : "Save";
      }

      function commit() {
        var update = { stale_hours: Number(hours.value), auto_open: auto.checked,
                       show_tips: tips.checked, kinds: {} };
        KIND_ROWS.forEach(function (k) { if (!k.off) update.kinds[k.key] = boxes[k.key].checked; });
        err.hidden = true;
        hours.removeAttribute("aria-invalid");
        save.disabled = true;
        postSettings(update).then(function (res) {
          save.disabled = false;
          if (res.ok) {
            rememberSettings(res.settings);
            applyTipsSetting(res.settings);
            /* Other pages' marks follow the new window at once; this page's own
               are in use and are never removed under it. */
            expireOld(hoursMs(res.settings.stale_hours), LSKEY);
            closeBubble();
            flash("Settings saved");
            return;
          }
          err.textContent = res.error;
          err.hidden = false;
          if (res.field === "stale_hours") { hours.setAttribute("aria-invalid", "true"); hours.focus(); }
        });
      }

      hours.addEventListener("input", checkAge);
      hours.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") { ev.preventDefault(); commit(); }
      });
      checkAge();
      setTimeout(function () { b.focus(); }, 0);
    });
  }

  function wireSettings() {
    var btn = doc.getElementById("open-settings");
    if (!btn) return;
    if (!onServer()) {
      btn.setAttribute("aria-disabled", "true");
      btn.setAttribute("data-tip", "Settings need the local review server. In Claude Code, run /review-doc:settings");
      return;
    }
    btn.addEventListener("click", function () {
      if (bubble && bubble.classList.contains("settings-panel")) { closeBubble(); return; }
      fetchSettings(3000).then(function (s) {
        if (!s) { flash("Settings need the review server, and it did not answer", "bad", 4000); return; }
        openSettings(btn, s);
      });
    });
  }

  /* ------------------------------------------------------------------ wiring */

  function setMode(mode) {
    state.mode = mode;
    closeBubble();
    doc.body.classList.toggle("mode-edit", mode === "edit");
    doc.body.classList.toggle("mode-comment", mode === "comment");
    var els = docEl.querySelectorAll("[data-edit-id]");
    for (var i = 0; i < els.length; i++) {
      els[i].contentEditable = (mode === "edit" && !cellLocked(els[i])) ? "true" : "false";
      if (mode !== "edit") {
        var eid = els[i].getAttribute("data-edit-id");
        var ed2 = state.data.edits[eid];
        if (ed2 && !els[i].querySelector("mark.edited")) renderEditDiff(els[i], ed2.alt, ed2.neu);
      }
    }
    var fresh = docEl.querySelectorAll("[data-new-cell]");
    for (var f = 0; f < fresh.length; f++) fresh[f].contentEditable = (mode === "edit" && !cellLocked(fresh[f])) ? "true" : "false";
    var btns = doc.querySelectorAll(".modes button");
    for (var b = 0; b < btns.length; b++) {
      btns[b].setAttribute("aria-pressed", btns[b].getAttribute("data-mode") === mode ? "true" : "false");
    }
    if (mode !== "edit") hideTableBar();
    persist();
  }

  function applyPromptVisibility() {
    doc.body.classList.toggle("prompt-hidden", !state.ui.prompt);
    var t = doc.getElementById("t-prompt");
    if (t) {
      t.setAttribute("aria-expanded", state.ui.prompt ? "true" : "false");
      t.textContent = state.ui.prompt ? "\u25BE" : "\u25B4";
      t.setAttribute("data-tip", state.ui.prompt ? "Hide prompt" : "Show prompt");
    }
  }

  /* Ctrl and the wheel scale the document only. The header, footer and bubbles
     live outside #doc and keep their own sizes, so the chrome stays put while
     the text grows. The section column is sized in em, so the measure holds and
     zooming does not turn the plan into a narrow ribbon. */
  var ZOOM_MIN = 0.7, ZOOM_MAX = 2.4;

  function setZoom(z) {
    z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(z * 20) / 20));
    state.ui.zoom = z;
    docEl.style.setProperty("--zoom", String(z));
    persist();
    return z;
  }

  function onZoomWheel(ev) {
    if (!ev.ctrlKey && !ev.metaKey) return;
    ev.preventDefault();
    closeBubble();
    var z = setZoom((state.ui.zoom || 1) + (ev.deltaY > 0 ? -0.05 : 0.05));
    flash(Math.round(z * 100) + "%", "");
  }

  /* Resting on a cut title for a moment sends every control away and gives
     the title the whole row; leaving it puts them back. A title that already
     shows in full has nothing to gain, so it does not peek. */
  var PEEK_DELAY = 200, peekTimer = null;

  function wirePeek() {
    var header = doc.querySelector("header");
    var title = header && header.querySelector(".doc-title");
    if (!title) return;
    title.addEventListener("mouseenter", function () {
      clearTimeout(peekTimer);
      if (finishOpen()) return;
      peekTimer = setTimeout(function () {
        if (title.scrollWidth <= title.clientWidth + 1) return;
        header.classList.add("title-peek");
      }, PEEK_DELAY);
    });
    title.addEventListener("mouseleave", function () {
      clearTimeout(peekTimer);
      if (finishOpen()) return;
      header.classList.remove("title-peek");
    });
  }

  /* One tooltip for the whole page, drawn in the page's own ink rather than
     the browser's grey box. Anything with data-tip gets it. It waits 300ms so
     sweeping the pointer across the header does not flash labels, but once
     one is showing the next appears at once: you are reading them now.
     Keyboard focus shows it straight away. Mouse events are listened for on
     the document, because a disabled button (a counter at zero, Request
     changes before anything is marked) never fires its own. */
  var TIP_DELAY = 300, TIP_WARM_MS = 400;
  var tipEl = null, tipFor = null, tipTimer = null, tipHiddenAt = 0;

  /* Tooltips are a setting. Off means none at all, focus included; every
     button still has its aria-label, so nothing is lost to a screen reader. */
  var tipsOn = true;

  function applyTipsSetting(s) {
    tipsOn = !s || s.show_tips !== false;
    if (!tipsOn) hideTip();
  }

  function tipTarget(node) {
    while (node && node !== doc.body) {
      if (node.nodeType === 1 && node.getAttribute("data-tip")) return node;
      node = node.parentNode;
    }
    return null;
  }

  function placeTip(el) {
    var r = el.getBoundingClientRect();
    tipEl.classList.remove("is-above");
    var w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    var vw = doc.documentElement.clientWidth, vh = doc.documentElement.clientHeight;
    var cx = r.left + r.width / 2;
    var left = Math.max(8, Math.min(vw - w - 8, cx - w / 2));
    var top = r.bottom + 9;
    if (top + h > vh - 8) { top = r.top - h - 9; tipEl.classList.add("is-above"); }
    tipEl.style.left = Math.round(left) + "px";
    tipEl.style.top = Math.round(top) + "px";
    tipEl.style.setProperty("--arrow-x", Math.round(cx - left) + "px");
  }

  function showTip(el) {
    if (!tipsOn) return;
    if (!tipEl) {
      tipEl = doc.createElement("div");
      tipEl.className = "tip";
      tipEl.setAttribute("role", "tooltip");
      doc.body.appendChild(tipEl);
    }
    tipFor = el;
    tipEl.textContent = el.getAttribute("data-tip");
    placeTip(el);
    tipEl.classList.add("is-on");
  }

  function hideTip() {
    clearTimeout(tipTimer);
    if (tipEl && tipEl.classList.contains("is-on")) {
      tipEl.classList.remove("is-on");
      tipHiddenAt = Date.now();
    }
    tipFor = null;
  }

  function wireTips() {
    doc.addEventListener("mouseover", function (ev) {
      var el = tipTarget(ev.target);
      if (el === tipFor) return;
      clearTimeout(tipTimer);
      if (!el) { hideTip(); return; }
      var warm = (tipEl && tipEl.classList.contains("is-on")) ||
                 Date.now() - tipHiddenAt < TIP_WARM_MS;
      if (tipEl) tipEl.classList.remove("is-on");
      tipFor = el;
      tipTimer = setTimeout(function () { showTip(el); }, warm ? 0 : TIP_DELAY);
    });
    doc.documentElement.addEventListener("mouseleave", hideTip);
    doc.addEventListener("focusin", function (ev) {
      var el = tipTarget(ev.target);
      if (el && el.matches && el.matches(":focus-visible")) { clearTimeout(tipTimer); showTip(el); }
    });
    doc.addEventListener("focusout", hideTip);
    doc.addEventListener("mousedown", hideTip, true);
    doc.addEventListener("keydown", function (ev) { if (ev.key === "Escape") hideTip(); });
    docEl.addEventListener("scroll", hideTip, { passive: true });
    window.addEventListener("resize", hideTip);
  }

  function togglePrompt() {
    state.ui.prompt = !state.ui.prompt;
    applyPromptVisibility();
    persist();
  }

  /* Marks are expired before they are loaded, and how old is too old is a
     setting, so the page asks first. On localhost the answer takes a few
     milliseconds; nothing is clickable in that time that would lose work. */
  function wire() {
    fetchSettings().then(function (s) {
      applyTipsSetting(s || { show_tips: cachedShowTips() });
      start(s ? s.stale_hours : cachedStaleHours());
    });
  }

  function start(staleHours) {
    collectEditables();
    collectTables();
    expireOld(hoursMs(staleHours));
    load();
    if (promoteRound(state.data, D.meta.sourceMtime)) { freshRound = true; persist(); }
    baseline = JSON.stringify(state.data);
    applyDataToDoc();
    setMode(state.mode);
    applyPromptVisibility();
    setZoom(state.ui.zoom || 1);
    syncVerdict();
    updatePrompt();
    syncHistButtons();

    docEl.addEventListener("mouseup", function (ev) {
      if (state.mode !== "comment") return;
      if (ev.target.closest && ev.target.closest(".sec-tools, .pick-row, .credit, .glance-fact")) return;
      setTimeout(function () {
        var sel = doc.getSelection();
        if (!sel || sel.isCollapsed) return;
        if (sel.toString().trim().length < 2) return;
        if (!docEl.contains(sel.anchorNode)) return;
        /* The credit line is chrome. A drag from the last paragraph into it
           would otherwise quote its text. */
        /* The fact rows in At a glance are chrome too (1.1.5). */
        var chrome = function (n) {
          var el = n && (n.nodeType === 1 ? n : n.parentElement);
          return !!(el && el.closest && el.closest(".credit, .glance-fact"));
        };
        if (chrome(sel.anchorNode) || chrome(sel.focusNode)) return;
        askForComment(sel);
      }, 10);
    });

    docEl.addEventListener("click", function (ev) {
      var t = ev.target;

      var dec = t.closest ? t.closest(".dec") : null;
      if (dec) {
        ev.preventDefault();
        var id = dec.getAttribute("data-for");
        var cur = (state.data.steps[id] || {}).decision || "";
        var next = cur === "" ? "ok" : (cur === "ok" ? "skip" : "");
        if (!state.data.steps[id]) state.data.steps[id] = {};
        state.data.steps[id].decision = next;
        delete state.data.steps[id].auto;   // clicked by hand, so no longer cascaded
        if (!next && !state.data.steps[id].comment) delete state.data.steps[id];
        paintDecision(dec);

        var sec = sectionFor(id);
        if (sec && (sec.steps || []).length) cascade(sec, next);

        save("dec:" + id);
        updatePrompt();
        if (next === "skip") noteFor(id, dec);   // a decline usually wants a reason
        return;
      }

      var pickRow = t.closest ? t.closest(".pick-row") : null;
      if (pickRow) { ev.preventDefault(); pickChoice(pickRow.getAttribute("data-pick")); return; }

      var note = t.closest ? t.closest(".note-btn") : null;
      if (note) { ev.preventDefault(); noteFor(note.getAttribute("data-for"), note); return; }

      /* An earlier round's mark, unless a current comment or rewrite sits
         around it: the current one keeps its own bubble, and its Revert. In
         edit mode a click inside an editable places the caret, so no bubble
         there either. */
      var pm = t.closest ? t.closest("[data-prev]") : null;
      if (pm && !(t.closest && (t.closest("mark.has-comment") || t.closest("mark.edited")))
          && !(state.mode === "edit" && pm.closest("[data-edit-id]"))) {
        ev.preventDefault(); showEarlier(pm); return;
      }

      var mk = t.closest ? t.closest("mark.has-comment") : null;
      if (mk) { ev.preventDefault(); showComment(mk); return; }

      /* In edit mode a click inside an edited element places the caret, so a
         bubble would fight the cursor. Only offer it while commenting. */
      if (state.mode === "comment") {
        var em = t.closest ? t.closest("mark.edited") : null;
        var ed = t.closest ? t.closest("[data-edit-id]") : null;
        if (ed && state.data.edits[ed.getAttribute("data-edit-id")]) {
          ev.preventDefault();
          showEdit(ed, em || ed);
          return;
        }
      }
    });

    var general = doc.getElementById("general");
    if (general) {
      general.value = state.data.general || "";
      general.addEventListener("input", function () {
        state.data.general = general.value;
        save("general");
        updatePrompt();
      });
    }

    var modes = doc.querySelectorAll(".modes button");
    for (var i = 0; i < modes.length; i++) {
      modes[i].addEventListener("click", function (ev) { setMode(ev.currentTarget.getAttribute("data-mode")); });
    }

    var vs = doc.querySelectorAll(".verdict");
    for (var v = 0; v < vs.length; v++) {
      vs[v].addEventListener("click", function (ev) {
        finish(ev.currentTarget.getAttribute("data-verdict"));
      });
    }

    var counters = doc.querySelectorAll(".counter");
    for (var c = 0; c < counters.length; c++) {
      counters[c].addEventListener("click", function (ev) {
        jumpTo(ev.currentTarget.getAttribute("data-kind"));
      });
    }

    bind("cycle-scope", onScope);
    bind("undo", undo);
    bind("redo", redo);
    bind("reset", onReset);
    bind("t-prompt", togglePrompt);
    bind("finish-cancel", onFinishCancel);
    bind("finish-close", onFinishClose);
    bind("finish-recopy", onFinishRecopy);

    doc.addEventListener("keydown", historyKeys, true);
    doc.addEventListener("keydown", trapFinishFocus, true);
    doc.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && finishOpen()) {
        ev.preventDefault();
        if (closeArmed()) disarmClose(); else onFinishCancel();
        return;
      }
      if (ev.key === "Escape" && resetArmed()) { ev.preventDefault(); disarmReset(); return; }
      if (ev.key === "Escape" && bubble) { ev.preventDefault(); closeBubble(); }
    });
    doc.addEventListener("mousedown", function (ev) {
      /* The settings button toggles its own panel. Closing here first would
         make its click open the panel again. */
      if (ev.target.closest && ev.target.closest("#open-settings")) return;
      if (bubble && !bubble.contains(ev.target)) closeBubble();
    });
    window.addEventListener("resize", closeBubble);
    docEl.addEventListener("scroll", closeBubble);

    /* The table toolbar follows focus: shown while a cell of a stamped table
       has it, gone when focus leaves the table. */
    docEl.addEventListener("focusin", function (ev) {
      var c = ev.target.closest ? ev.target.closest("td, th") : null;
      if (!c || !c.closest("table[data-table-id]")) return;
      /* Same as a cell with an original (see collectEditables): marks fight
         the caret while typing, and leaving puts them back. */
      if (c.hasAttribute("data-new-cell")) unwrapMarksIn(c);
      curCell = c;
      showTableBar();
    });
    docEl.addEventListener("focusout", function (ev) {
      if (ev.target.hasAttribute && ev.target.hasAttribute("data-new-cell")) {
        applyDataToDoc();
        updatePrompt();
      }
      setTimeout(function () {
        var a = doc.activeElement;
        if (!(a && a.closest && a.closest("table[data-table-id]"))) hideTableBar();
      }, 0);
    });
    docEl.addEventListener("scroll", placeTableBar, { passive: true });
    window.addEventListener("resize", placeTableBar);
    wirePeek();
    wireTips();
    watchSource();
    wireSettings();
    /* passive:false, or preventDefault cannot stop the browser page zoom. */
    docEl.addEventListener("wheel", onZoomWheel, { passive: false });
    doc.addEventListener("keydown", function (ev) {
      if ((ev.ctrlKey || ev.metaKey) && (ev.key === "0")) {
        ev.preventDefault();
        setZoom(1);
        flash("100%", "");
      }
    });
  }

  /* ------------------------------------------------- waiting for Claude */

  /* While the Waiting box is up, and only then, the page asks every two
     seconds whether its source changed. Claude applies a change request in
     several edits, seconds apart, and renders the page once after the last
     one. So a newer source alone is not the signal: the page waits until the
     built page is newer than this load and the source has held for one more
     poll. A source that changed but was never rendered again still reloads,
     once it has been quiet for QUIET_FALLBACK_POLLS polls (30 seconds). */
  var POLL_MS = 2000;
  var QUIET_FALLBACK_POLLS = 15;
  var loadedAt = Date.now();
  var pollTimer = null, settle = null, pollGen = 0;

  /* Every start and stop moves pollGen on. A fetch that was already in flight
     when the box closed or reopened carries the old number and so cannot touch
     the new session or arm a second timeout chain. */

  /* Pure: st is the previous step, mtime the source time now, built the source
     time this page was built from, page the built page file's time (null when
     it is missing) and loaded when this page was loaded. */
  function settleStep(st, mtime, built, page, loaded) {
    if (!(mtime > built)) return { last: mtime, quiet: 0, reload: false };
    var quiet = mtime === st.last ? st.quiet + 1 : 0;
    var rebuilt = typeof page === "number" && page > loaded;
    return { last: mtime, quiet: quiet,
             reload: (rebuilt && quiet >= 1) || quiet >= QUIET_FALLBACK_POLLS };
  }

  function waitNote(extra) {
    var el = doc.getElementById("finish-text");
    if (el && extra && el.textContent.indexOf(extra) < 0) el.textContent += " " + extra;
  }

  function startWaiting() {
    stopWaiting();
    if (!onServer() || typeof D.meta.sourceMtime !== "number") {
      doc.getElementById("finish-text").textContent =
        "Your change request has been copied. Paste it back to Claude, then reload this page when the revision is in.";
      return;
    }
    settle = { last: null, quiet: 0 };
    var gen = pollGen;
    pollTimer = setTimeout(function () { poll(gen); }, POLL_MS);
  }

  function stopWaiting() {
    clearTimeout(pollTimer);
    pollTimer = null;
    settle = null;
    pollGen++;
  }

  function poll(gen) {
    if (gen !== pollGen) return;
    fetch("/api/review-source?slug=" + encodeURIComponent(D.meta.slug), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (got) {
        if (gen !== pollGen) return;
        if (!got || typeof got.mtime !== "number") {
          stopWaiting();
          waitNote("The page could not be reached. Reload it once Claude is done.");
          return;
        }
        settle = settleStep(settle, got.mtime, D.meta.sourceMtime, got.page, loadedAt);
        if (settle.reload) { stopWaiting(); persist(); location.reload(); return; }
        pollTimer = setTimeout(function () { poll(gen); }, POLL_MS);
      })
      .catch(function () {
        if (gen !== pollGen) return;
        stopWaiting();
        waitNote("The page could not be reached. Reload it once Claude is done.");
      });
  }

  /* ---------------------------------------------------------- stale source */

  /* Asks the review server whether the Markdown behind this page has changed
     since it was built. Silent when there is no server (file://, stopped) or no
     source time in the page: then there is simply no banner. */
  function checkSource() {
    var built = D.meta.sourceMtime;
    if (typeof built !== "number" || !/^https?:$/.test(location.protocol)) return;
    if (!window.fetch) return;
    fetch("/api/review-source?slug=" + encodeURIComponent(D.meta.slug), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (got) {
        if (!got || typeof got.mtime !== "number") return;
        var strip = doc.getElementById("stale");
        if (strip) strip.hidden = !(got.mtime > built);
      })
      .catch(function () { /* no server: no banner */ });
  }

  function watchSource() {
    checkSource();
    doc.addEventListener("visibilitychange", function () {
      if (doc.visibilityState === "visible") checkSource();
    });
    /* The server rebuilds a page whose source is newer before serving it, and
       the marks re-anchor on the new text, so reloading is all it takes. */
    bind("stale-reload", function () { persist(); location.reload(); });
  }

  function bind(id, fn) {
    var el = doc.getElementById(id);
    if (el) el.addEventListener("click", fn);
  }

  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", wire);
  else wire();
})();
