// Opens a review-doc page in VS Code's built-in browser, the way a Ctrl+click in
// the terminal does.
//
// `code --open-url` only accepts vscode:// links, so the renderer hands a page
// over as vscode://filmuszynski.review-doc-opener/open?url=<page>. Only review
// pages on this machine are opened (accept.js). Anything else is ignored without
// a message, so no other vscode:// link can use this to open or show anything.

const vscode = require("vscode");
const { acceptable } = require("./accept");

function activate(context) {
  context.subscriptions.push(
    vscode.window.registerUriHandler({
      handleUri(uri) {
        if (uri.path !== "/open") return;
        const url = acceptable(new URLSearchParams(uri.query).get("url") || "");
        if (!url) return;
        // Straight to the integrated browser. openExternal goes to the system
        // browser: the localhost rule that catches a Ctrl+click does not apply to
        // extension-originated opens. reuseUrlFilter makes a regenerated page
        // reload in its existing tab instead of stacking a new one.
        Promise.resolve(vscode.commands.executeCommand("workbench.action.browser.open",
          { url, reuseUrlFilter: url }))
          .catch(() => vscode.env.openExternal(vscode.Uri.parse(url, true)));
      },
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
