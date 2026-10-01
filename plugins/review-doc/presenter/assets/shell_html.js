/* review-doc: the shell side of an HTML page (1.2). Loaded after shell.js, in its
 * own <script> block, only on pages of kind html.
 *
 * The reviewed page runs on http://<slug>.localhost:<review port + 100>/, an origin
 * of its own (ADR 0016). The review server binds both ports as a pair, so the
 * frame port follows from the port this page was served from.
 *
 * Phase 1 only points the frame there. Widths, modes, marks and the postMessage
 * channel to the probe arrive in Phase 3. */
(function () {
  "use strict";

  function frameSrc(meta, loc) {
    if (!meta || !meta.target || meta.target.type !== "file") return "";
    if (loc.protocol !== "http:" || !loc.port) return "";
    var port = Number(loc.port) + 100;
    return "http://" + meta.slug + ".localhost:" + port + "/" + encodeURIComponent(meta.target.entry);
  }

  var frame = document.getElementById("review-frame");
  var src = frameSrc(window.PRESENTER_DATA.meta, window.location);
  if (frame && src) frame.src = src;
})();
