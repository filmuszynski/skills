/* review-doc probe (1.2). Runs inside the reviewed page, on the page's own origin.
 * Phase 1 only records that it ran. The probe proper (pick, marks, anchors and the
 * postMessage channel to the shell) arrives in Phase 3. */
(function () {
  "use strict";
  window.__reviewDocProbe = {phase: 1};
})();
