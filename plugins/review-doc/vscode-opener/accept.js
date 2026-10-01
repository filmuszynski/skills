// Which links the opener may open: review pages on this machine's review-doc
// server, nothing else. Kept apart from extension.js so it can be tested with
// plain node, without VS Code.

const HOSTS = new Set(["localhost", "127.0.0.1"]);
const PAGE = /^\/review\/[A-Za-z0-9._-]+\.html$/;

function acceptable(target) {
  let u;
  try { u = new URL(String(target)); } catch (e) { return null; }
  if (u.protocol !== "http:" || !HOSTS.has(u.hostname)) return null;
  // The server always runs on an explicit port; a default port is not ours.
  if (!u.port || u.username || u.password || u.search || u.hash) return null;
  // URL() has already resolved any ../ segments, so this sees the real path.
  if (!PAGE.test(u.pathname)) return null;
  return u.toString();
}

module.exports = { acceptable };
