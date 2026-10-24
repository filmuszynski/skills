# -*- coding: utf-8 -*-
"""The frame listener's pure parts: CSP nonce, probe injection, paths, ranges (1.2)."""
import os
import sys

from harness import test, new_home, HERE

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))
import frame_server  # noqa: E402
import pages  # noqa: E402

N = "abc123"
TAG = '<script src="/__review-doc/probe.js" nonce="abc123"></script>'


@test
def test_html_slug_is_a_dns_label():
    for ok in ("a", "site-index-1a2b3c", "x" * 63, "9"):
        assert pages.HTML_SLUG_RE.match(ok), ok
    for bad in ("", "-a", "a-", "A", "a_b", "a.b", "x" * 64, "a b", "über", "a\n"):
        assert not pages.HTML_SLUG_RE.match(bad), bad


@test
def test_nonce_goes_into_script_src():
    got = frame_server.add_nonce("default-src 'self'; script-src 'self' https://cdn.example", N)
    assert got == "default-src 'self'; script-src 'self' https://cdn.example 'nonce-abc123'", got


@test
def test_nonce_goes_into_default_src_without_script_src():
    got = frame_server.add_nonce("default-src 'self'; img-src *", N)
    assert got == "default-src 'self' 'nonce-abc123'; img-src *", got


@test
def test_policy_without_script_rules_is_untouched():
    for p in ("img-src *; frame-ancestors 'none'", "", "upgrade-insecure-requests"):
        assert frame_server.add_nonce(p, N) == p, p


@test
def test_script_src_elem_and_script_src_both_get_the_nonce():
    got = frame_server.add_nonce("script-src-elem 'nonce-p'; script-src 'nonce-p'; default-src 'none'", N)
    assert got == ("script-src-elem 'nonce-p' 'nonce-abc123'; script-src 'nonce-p' 'nonce-abc123'; "
                   "default-src 'none'"), got


@test
def test_unsafe_inline_without_nonce_gets_self_not_a_nonce():
    # A nonce would switch 'unsafe-inline' off and stop the page's own inline scripts.
    assert frame_server.add_nonce("script-src 'unsafe-inline'", N) == "script-src 'unsafe-inline' 'self'"
    assert frame_server.add_nonce("script-src 'self' 'unsafe-inline'", N) == "script-src 'self' 'unsafe-inline'"
    assert frame_server.add_nonce("script-src 'unsafe-inline' 'sha256-abc='", N) == \
        "script-src 'unsafe-inline' 'sha256-abc=' 'nonce-abc123'"


@test
def test_unsafe_inline_beside_a_nonce_or_strict_dynamic_still_gets_ours():
    assert frame_server.add_nonce("script-src 'unsafe-inline' 'nonce-p'", N) == \
        "script-src 'unsafe-inline' 'nonce-p' 'nonce-abc123'"
    assert frame_server.add_nonce("script-src 'unsafe-inline' 'strict-dynamic'", N) == \
        "script-src 'unsafe-inline' 'strict-dynamic' 'nonce-abc123'"


@test
def test_none_is_replaced_not_combined():
    assert frame_server.add_nonce("script-src 'none'", N) == "script-src 'nonce-abc123'"


@test
def test_every_policy_in_a_list_and_only_the_first_of_a_repeat():
    got = frame_server.add_nonce("script-src 'self', script-src 'nonce-p'", N)
    assert got == "script-src 'self' 'nonce-abc123', script-src 'nonce-p' 'nonce-abc123'", got
    # Browsers honour the first of a repeated directive and ignore the rest.
    got = frame_server.add_nonce("script-src 'self'; script-src 'nonce-p'", N)
    assert got == "script-src 'self' 'nonce-abc123'; script-src 'nonce-p'", got


@test
def test_meta_policy_rewritten_by_its_own_quote():
    page = ('<head><meta http-equiv="Content-Security-Policy" '
            'content="script-src \'nonce-p\' \'strict-dynamic\'"></head>')
    got = frame_server.rewrite_meta_csp(page, N)
    assert "content=\"script-src 'nonce-p' 'strict-dynamic' 'nonce-abc123'\"" in got, got


@test
def test_meta_single_quoted_with_entities():
    page = "<meta content='script-src &#39;self&#39;' http-equiv='content-security-policy'>"
    got = frame_server.rewrite_meta_csp(page, N)
    assert got == ("<meta content=\"script-src 'self' 'nonce-abc123'\" "
                   "http-equiv='content-security-policy'>"), got


@test
def test_other_metas_and_report_only_untouched():
    page = ('<meta name="description" content="script-src x">'
            '<meta http-equiv="Content-Security-Policy-Report-Only" content="script-src \'self\'">')
    assert frame_server.rewrite_meta_csp(page, N) == page


@test
def test_probe_goes_right_after_head():
    for head in ("<head>", "<HEAD>", '<head lang="en">'):
        page = "<!DOCTYPE html><html>" + head + "<title>t</title></head><body><header>x</header></body></html>"
        got = frame_server.inject_probe(page, N)
        assert got == page.replace(head, head + TAG, 1), got


@test
def test_header_is_not_head():
    page = "<body><header>x</header></body>"
    assert frame_server.inject_probe(page, N) == TAG + page


@test
def test_no_head_keeps_doctype_first():
    # A script before the doctype would put the page into quirks mode.
    page = "\ufeff<!DOCTYPE html>\n<html lang=\"en\"><body>x</body></html>"
    want = "\ufeff<!DOCTYPE html>\n<html lang=\"en\">" + TAG + "<body>x</body></html>"
    assert frame_server.inject_probe(page, N) == want
    page = "<!-- note --><!doctype html><p>x</p>"
    assert frame_server.inject_probe(page, N) == "<!-- note --><!doctype html>" + TAG + "<p>x</p>"


@test
def test_head_in_comment_or_script_is_skipped():
    page = "<!-- <head> --><html><head><title>x</title>"
    assert frame_server.inject_probe(page, N) == page.replace("<html><head>", "<html><head>" + TAG, 1)
    page = '<html><script>var s="<head>"</script><head><title>x</title>'
    want = '<html><script>var s="<head>"</script><head>' + TAG + "<title>x</title>"
    assert frame_server.inject_probe(page, N) == want
    page = "<html><style>/* <head> */</style><HEAD><title>x</title>"
    assert frame_server.inject_probe(page, N) == page.replace("<HEAD>", "<HEAD>" + TAG, 1)
    page = '<!doctype html><html><script>var s="<head>"</script><body>x</body>'
    assert frame_server.inject_probe(page, N) == "<!doctype html><html>" + TAG + page[len("<!doctype html><html>"):]


@test
def test_rewrite_html_keeps_the_encoding():
    text = "<head><title>Grüße</title></head>"
    out, ctype = frame_server.rewrite_html(text.encode("utf-8"), N)
    assert ctype == "text/html; charset=utf-8"
    assert out.decode("utf-8") == "<head>" + TAG + "<title>Grüße</title></head>"
    out, ctype = frame_server.rewrite_html(text.encode("latin-1"), N)
    assert ctype == "text/html"
    assert out == ("<head>" + TAG + "<title>Grüße</title></head>").encode("latin-1")


@test
def test_sniff_charset():
    import charset
    assert charset.sniff(b"\xef\xbb\xbf<p>x</p>") == ("utf-8", 3)
    assert charset.sniff(b"\xff\xfe" + "<p>x</p>".encode("utf-16-le")) == ("utf-16-le", 2)
    assert charset.sniff(b"\xfe\xff" + "<p>x</p>".encode("utf-16-be")) == ("utf-16-be", 2)
    assert charset.sniff(b'<meta charset="windows-1252"><p>x') == ("cp1252", 0)
    assert charset.sniff(b'<meta http-equiv="Content-Type" content="text/html; charset=ISO-8859-2">') == ("iso8859-2", 0)
    assert charset.sniff(b'<meta charset="utf-16"><p>x') == ("utf-8", 0), "a declared utf-16 needs a BOM"
    assert charset.sniff(b'<meta charset="nonsense">') == ("utf-8", 0)
    assert charset.sniff(b"<!--" + b"x" * 1100 + b'--><meta charset="windows-1252">') == ("utf-8", 0)
    assert charset.sniff(b"") == ("utf-8", 0)


@test
def test_rewrite_html_keeps_utf16_and_declared_charsets():
    with open(os.path.join(HERE, "fixtures", "site_utf16.html"), "rb") as fh:
        out, ctype = frame_server.rewrite_html(fh.read(), N)
    assert out.startswith(b"\xff\xfe") and ctype == "text/html; charset=utf-16-le", ctype
    text = out[2:].decode("utf-16-le")
    assert "<head>" + TAG in text and "<title>Grüße</title>" in text
    with open(os.path.join(HERE, "fixtures", "site_cp1252.html"), "rb") as fh:
        data = fh.read()
    out, ctype = frame_server.rewrite_html(data, N)
    assert ctype == "text/html; charset=cp1252", ctype
    assert out.count(b"\x80") == data.count(b"\x80") == 2
    assert out.decode("cp1252") == data.decode("cp1252").replace("<head>", "<head>" + TAG, 1)


def _site():
    root = os.path.join(new_home(), "site")
    for rel, text in (("index.html", "<h1>i</h1>"), ("about.html", "a"), ("css/site.css", "b{}"),
                      ("img/dot.svg", "<svg/>"), ("sub/index.html", "s"), (".env", "SECRET=1"),
                      (".git/config", "[core]"), ("notes.txt", "n"), ("img/.hidden.png", "x"),
                      ("nested/.cache/a.css", "x")):
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    with open(os.path.join(os.path.dirname(root), "secret.html"), "w", encoding="utf-8", newline="") as fh:
        fh.write("outside")
    return root


@test
def test_resolve_serves_web_files_inside_the_root():
    root = _site()
    real = os.path.realpath(root)
    r = lambda p: frame_server.resolve(root, p)  # noqa: E731
    assert r("/index.html") == os.path.join(real, "index.html")
    assert r("/css/site.css") == os.path.join(real, "css", "site.css")
    assert r("/sub/") == os.path.join(real, "sub", "index.html")
    assert r("/sub%2F") == os.path.join(real, "sub", "index.html")
    assert r("/img/dot%2Esvg") == os.path.join(real, "img", "dot.svg")
    # Without the slash the index file's links would resolve against the parent:
    # resolve refuses, and the handler redirects (needs_slash).
    assert r("/sub") is None
    assert r("/index.html/") is None, "a file is never a folder"


@test
def test_needs_slash_only_for_folders_resolve_would_serve():
    root = _site()
    os.makedirs(os.path.join(root, "noindex"))
    ns = lambda p: frame_server.needs_slash(root, p)  # noqa: E731
    assert ns("/sub") and ns("/%73ub")
    for p in ("/sub/", "/sub%2F", "/.git", "/nested/.cache", "/noindex", "/missing", "/index.html",
              "/notes.txt", "/../" + os.path.basename(os.path.dirname(root)), "", "/%ff"):
        assert not ns(p), p


@test
def test_resolve_refuses_escapes_dotfiles_and_other_types():
    root = _site()
    for p in ("/../secret.html", "/%2e%2e/secret.html", "/css/../../secret.html", "/..%5csecret.html",
              "/.env", "/.git/config", "/img/.hidden.png", "/nested/.cache/a.css", "/%2eenv",
              "/notes.txt", "/missing.html", "/C:/Windows/win.ini", "/index.html%00.png",
              "/about.html::$DATA", "/%ff.html", "/./index.html", "/"):
        assert frame_server.resolve(root, p) is None, p


@test
def test_resolve_refuses_a_link_that_leaves_the_root():
    root = _site()
    outside = os.path.join(os.path.dirname(root), "elsewhere")
    os.makedirs(outside)
    with open(os.path.join(outside, "page.html"), "w", encoding="utf-8", newline="") as fh:
        fh.write("x")
    link = os.path.join(root, "linked")
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(outside, link)
        else:
            os.symlink(outside, link)
    except (OSError, AttributeError) as exc:
        print("  (skip) cannot create a link here: %s" % exc)
        return
    assert frame_server.resolve(root, "/linked/page.html") is None


@test
def test_content_types_cover_exactly_the_allowlist():
    want = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".map", ".wasm", ".png", ".jpg", ".jpeg",
            ".gif", ".webp", ".avif", ".ico", ".svg", ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".ogg",
            ".wav", ".mp4", ".webm"}
    assert set(frame_server.TYPES) == want
    assert frame_server.TYPES[".js"] == "text/javascript"
    assert frame_server.TYPES[".css"] == "text/css"
    assert frame_server.TYPES[".svg"] == "image/svg+xml"


@test
def test_byte_ranges():
    pr = frame_server.parse_range
    assert pr(None, 100) is None and pr("", 100) is None
    assert pr("bytes=0-9", 100) == (0, 9)
    assert pr("bytes=90-", 100) == (90, 99)
    assert pr("bytes=-10", 100) == (90, 99)
    assert pr("bytes=50-500", 100) == (50, 99)
    assert pr("bytes=100-", 100) == "bad" and pr("bytes=9-3", 100) == "bad" and pr("bytes=-0", 100) == "bad"
    assert pr("bytes=0-1,5-6", 100) is None and pr("items=0-1", 100) is None
    assert pr("bytes=0-0", 0) == "bad"


@test
def test_file_target_only_for_html_file_pages():
    root = _site()
    good = {"kind": "html", "target": {"type": "file", "root": root, "entry": "index.html"}}
    assert frame_server.file_target(good) == {"root": root, "entry": "index.html"}
    t = good["target"]
    for bad in (None, {}, {"kind": "doc", "target": t},
                {"kind": "html", "target": {"type": "proxy", "origin": "http://localhost:5173"}},
                {"kind": "html", "target": dict(t, root="relative/dir")},
                {"kind": "html", "target": dict(t, entry="../x.html")},
                {"kind": "html", "target": dict(t, entry="sub/index.html")},
                {"kind": "html", "target": dict(t, entry=".env")},
                {"kind": "html", "target": dict(t, root=os.path.join(root, "nope"))}):
        assert frame_server.file_target(bad) is None, bad


@test
def test_resolve_refuses_an_index_file_link_and_a_directory_link_out_of_the_root():
    root = _site()
    outside = os.path.join(os.path.dirname(root), "elsewhere2")
    os.makedirs(outside)
    with open(os.path.join(outside, "index.html"), "w", encoding="utf-8", newline="") as fh:
        fh.write("outside")
    d = os.path.join(root, "linkdir")
    os.makedirs(d)
    try:
        os.symlink(os.path.join(outside, "index.html"), os.path.join(d, "index.html"))
    except (OSError, AttributeError, NotImplementedError) as exc:
        print("  (skip) cannot create a file link here: %s" % exc)
    else:
        assert frame_server.resolve(root, "/linkdir/") is None
    link = os.path.join(root, "linked")
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(outside, link)
        else:
            os.symlink(outside, link)
    except (OSError, AttributeError) as exc:
        print("  (skip) cannot create a link here: %s" % exc)
        return
    assert frame_server.resolve(root, "/linked/") is None


@test
def test_sniff_charset_skips_codecs_that_are_not_text():
    # Final review M1: codecs.lookup accepts hex, base64 and rot13, which do not decode bytes.
    import charset
    for label in ("hex", "base64", "rot13", "zip"):
        assert charset.sniff(('<meta charset="%s">' % label).encode()) == ("utf-8", 0), label
    assert charset.decode(b'<meta charset="hex"><title>x</title>')[0].endswith("<title>x</title>")


@test
def test_rewrite_html_keeps_a_damaged_utf16_page_utf16():
    # Final review M2: a trailing odd byte or a lone surrogate must not drop the page to latin-1.
    import codecs
    body = "<html><head><title>Grüße</title></head><body>x</body></html>".encode("utf-16-le")
    for data in (codecs.BOM_UTF16_LE + body + b"\n", codecs.BOM_UTF16_LE + b"\x00\xd8" + body):
        out, ctype = frame_server.rewrite_html(data, N)
        assert ctype == "text/html; charset=utf-16-le", ctype
        assert out.startswith(codecs.BOM_UTF16_LE) and len(out) % 2 == 0, out[:40]
        assert "<head>" + TAG + "<title>Grüße</title>" in out[2:].decode("utf-16-le", "replace")
