#!/usr/bin/env python3
"""Build docs/SIPHON-confluence-paste.html from README.md.

The page holds the whole SIPHON guide with a "Copy for Confluence" button, for
pasting straight into a Confluence page (no Markup option needed). GitHub
references are removed (the page is for an internal Confluence space), except the
script link in the header block at the top.

Usage:  python3 docs/build-confluence-paste.py      (needs pandoc)
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "SIPHON-confluence-paste.html"


def swap(md, old, new):
    if old not in md:
        raise SystemExit("README changed; update build-confluence-paste.py: " + old[:60])
    return md.replace(old, new)


def paste_markdown():
    md = (REPO / "README.md").read_text(encoding="utf-8")
    md = re.sub(r"\A# [^\n]*\n", "", md)                                    # title is in the toolbar
    md = re.sub(r"## Contents\n.*?\n---\n", "", md, flags=re.S)              # Confluence /toc replaces it
    md = re.sub(r"^(\*\*S\.I\.P\.H\.O\.N\.[^\n]*\*\*)\n", r"\1<br>\n", md, flags=re.M)  # keep subtitle on its own line
    md = swap(md, "and please [report any problems](https://github.com/vjason1/hs-siphon/issues).",
              "and please report any problems to the SIPHON maintainers.")
    md = re.sub(r"\n *Project homepage: <https://github\.com/hammer-space/hstk>", "", md)
    md = re.sub(r"## Installation\n.*?(?=\nOn macOS and Linux you can also)",
                "## Installation\n\nCopy `hs-siphon.py` to the host you'll run it from. "
                "It's a single file; it needs only Python and the Hammerspace Toolkit.\n",
                md, flags=re.S)
    md = re.sub(r"## Confluence\n.*?(?=\n## )", "", md, flags=re.S)       # repo-only section
    md = swap(md, "([LICENSE-APACHE](LICENSE-APACHE))", "(see `LICENSE-APACHE`)")
    md = swap(md, "([LICENSE-MIT](LICENSE-MIT))", "(see `LICENSE-MIT`)")
    md = re.sub(r"\[([^\]]+)\]\(#[^)]+\)", r"\1", md)                       # section links don't survive a paste
    # The only GitHub reference kept is the script link in the header block
    check = md.replace("https://github.com/vjason1/hs-siphon/blob/main/hs-siphon.py", "")
    if re.search(r"github", check, re.I):
        raise SystemExit("A GitHub reference is left in the paste page: " +
                         re.search(r".*github.*", check, re.I).group(0))
    return md


def version():
    m = re.search(r'^VERSION = "([^"]+)"', (REPO / "hs-siphon.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


TEMPLATE = """<meta charset="utf-8">
<title>SIPHON Confluence Guide</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: a single white document column under a slim copy toolbar.
   Deliberately one light theme: the page imitates the Confluence page it is
   pasted into, and hand-copied text then never carries dark-theme colors. */
:root {
  --paper: #ffffff;
  --ink: #1b2630;
  --muted: #586776;
  --rule: #d6dde5;
  --wash: #f0f4f7;
  --accent: #0a6a86;
  --accent-ink: #ffffff;
  --ok: #1f7a4d;
  --font-body: "IBM Plex Sans", "Segoe UI", Helvetica, Arial, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  color-scheme: light;
}
body { background: var(--paper); color: var(--ink); font-family: var(--font-body); font-size: 15px; line-height: 1.6; }
.bar { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--wash); border-bottom: 1px solid var(--rule);
  padding-block: 12px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--wash); }
.bar-inner { max-width: 880px; margin: 0 auto; display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center; }
.bar h1 { font-size: 16px; margin: 0; font-weight: 700; }
.bar .ver { color: var(--muted); font-weight: 400; }
.bar .spacer { flex: 1 1 auto; }
button { font: 600 14px/1 var(--font-body); background: var(--accent); color: var(--accent-ink); border: 0; border-radius: 6px; padding: 10px 16px; cursor: pointer; }
button.secondary { background: var(--paper); color: var(--accent); border: 1px solid var(--accent); }
button:focus-visible { outline: 3px solid var(--ink); outline-offset: 2px; }
#status { min-height: 1.2em; color: var(--ok); font-weight: 600; }
.wrap { max-width: 880px; margin: 0 auto; padding-block: 24px 64px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.how { border: 1px solid var(--rule); border-radius: 8px; background: var(--wash); padding: 16px 20px; margin-bottom: 32px; }
.how h2 { font-size: 15px; margin: 0 0 8px; }
.how ol { margin: 0; padding-left: 20px; display: grid; gap: 4px; }
.how kbd { font-family: var(--font-mono); font-size: 12px; border: 1px solid var(--rule); border-bottom-width: 2px; border-radius: 4px; padding: 0 5px; background: var(--paper); }
article { min-width: 0; overflow-wrap: anywhere; }
article pre, article table { overflow-wrap: normal; }
article h2 { font-size: 24px; line-height: 1.25; margin: 40px 0 12px; text-wrap: balance; }
article h3 { font-size: 18px; margin: 28px 0 8px; text-wrap: balance; }
article p, article li { max-width: 72ch; }
article a { color: var(--accent); }
article hr { border: 0; border-top: 2px solid var(--rule); margin: 40px 0 0; }
article blockquote { margin: 16px 0; padding: 10px 16px; border-left: 4px solid var(--accent); background: var(--wash); }
article blockquote p { margin: 0; }
article code { font-family: var(--font-mono); font-size: 0.88em; background: var(--wash); padding: 1px 4px; border-radius: 3px; }
article pre { font-family: var(--font-mono); font-size: 13px; line-height: 1.45; background: var(--wash); border: 1px solid var(--rule); border-radius: 6px; padding: 12px 14px; overflow-x: auto; }
article pre code { background: none; padding: 0; font-size: inherit; }
article table { border-collapse: collapse; margin: 12px 0; font-size: 14px; display: block; overflow-x: auto; max-width: 100%; }
article th, article td { border: 1px solid var(--rule); padding: 6px 10px; text-align: left; vertical-align: top; }
article th { background: var(--wash); }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>

<div class="bar"><div class="bar-inner">
  <h1>SIPHON <span class="ver">v{{VERSION}} · guide for Confluence</span></h1>
  <span class="spacer"></span>
  <span id="status" role="status" aria-live="polite"></span>
  <button id="copy" type="button">Copy for Confluence</button>
  <button id="select" type="button" class="secondary">Select all</button>
</div></div>

<div class="wrap">
  <section class="how" aria-label="How to paste into Confluence">
    <h2>Put this guide into Confluence</h2>
    <ol>
      <li>Click <strong>Copy for Confluence</strong>. (If it says copying isn't allowed, click <strong>Select all</strong>, then press <kbd>Ctrl</kbd>+<kbd>C</kbd> or <kbd>⌘</kbd>+<kbd>C</kbd>.)</li>
      <li>In Confluence, create a page and give it a title, for example <em>SIPHON</em>.</li>
      <li>Click in the page body and paste with <kbd>Ctrl</kbd>+<kbd>V</kbd> or <kbd>⌘</kbd>+<kbd>V</kbd>.</li>
      <li>Optional: put the cursor at the top of the page, type <kbd>/toc</kbd> and choose <strong>Table of contents</strong>.</li>
      <li>Publish.</li>
    </ol>
  </section>

  <article id="doc">
{{CONTENT}}
  </article>
</div>

<script>
(function () {
  var doc = document.getElementById("doc");
  var status = document.getElementById("status");
  function say(msg) { status.textContent = msg; }
  function selectDoc() {
    var sel = window.getSelection();
    sel.removeAllRanges();
    var r = document.createRange();
    r.selectNodeContents(doc);
    sel.addRange(r);
  }
  document.getElementById("select").addEventListener("click", function () {
    selectDoc();
    say("Selected. Press Ctrl+C or ⌘+C to copy.");
  });
  document.getElementById("copy").addEventListener("click", function () {
    var html = doc.innerHTML, text = doc.innerText;
    var fallback = function () {
      selectDoc();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      if (ok) { window.getSelection().removeAllRanges(); say("Copied. Paste it into your Confluence page."); }
      else { say("Copying isn't allowed here. The guide is selected: press Ctrl+C or ⌘+C."); }
    };
    try {
      if (navigator.clipboard && window.ClipboardItem) {
        var item = new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" })
        });
        navigator.clipboard.write([item]).then(function () {
          say("Copied. Paste it into your Confluence page.");
        }, fallback);
      } else { fallback(); }
    } catch (e) { fallback(); }
  });
})();
</script>
"""


def main():
    html = subprocess.run(["pandoc", "-f", "gfm", "-t", "html5", "--wrap=none", "--no-highlight"],
                          input=paste_markdown(), stdout=subprocess.PIPE, universal_newlines=True,
                          check=True).stdout
    OUT.write_text(TEMPLATE.replace("{{VERSION}}", version()).replace("{{CONTENT}}", html), encoding="utf-8")
    print("wrote", OUT.relative_to(REPO))


if __name__ == "__main__":
    main()
