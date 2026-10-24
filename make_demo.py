"""Builds the online demo. Run from your Study-Sloth folder with:  python make_demo.py
Copies your real UI (app/static/index.html) into docs/index.html with the demo shim added,
and keeps the old landing page as docs/about.html."""
import pathlib, shutil
docs = pathlib.Path("docs"); docs.mkdir(exist_ok=True)
src = pathlib.Path("app/static/index.html").read_text(encoding="utf-8")
assert "<body>" in src, "app/static/index.html has no <body> tag"
old, about = docs / "index.html", docs / "about.html"
if old.exists() and not about.exists():
    text = old.read_text(encoding="utf-8")
    if "Hacktoberfest 2026" in text:                       # it is the landing page, keep it
        text = text.replace('<a class="btn alt" href="#run">', '<a class="btn alt" href="./">Open the live demo</a><a class="btn alt" href="#run">', 1)
        about.write_text(text, encoding="utf-8")
out = src.replace("<body>", '<body>\n<script src="demo-shim.js"></script>', 1)
out = out.replace("<title>Study Sloth", "<title>Study Sloth demo", 1)
(docs / "index.html").write_text(out, encoding="utf-8")
print("Done: docs/index.html (demo), docs/about.html (landing page). Needs docs/logo.png and docs/demo-shim.js.")