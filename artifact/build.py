"""Build the self-contained demo page.

Embeds the sample catalog and every project source file into template.html so the
page can show the full code. Run from anywhere:  python artifact/build.py
Output: artifact/dermastyle-demo.html
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "node_modules", ".next", "__pycache__", ".pytest_cache", "artifact"}
SKIP_FILES = {"package-lock.json", "tsconfig.tsbuildinfo", "next-env.d.ts"}
ORDER = ["README.md", "docker-compose.yml", ".env.example", "backend/app/youcam", "backend/app/agent", "backend/app/catalog",
         "backend/app/media", "backend/app/api", "backend/app", "backend/tests", "backend", "frontend"]


def rank(p: str) -> tuple:
    for i, prefix in enumerate(ORDER):
        if p == prefix or p.startswith(prefix + "/") or p.startswith(prefix):
            return (i, p)
    return (len(ORDER), p)


def collect() -> list[dict]:
    files = []
    for f in ROOT.rglob("*"):
        rel = f.relative_to(ROOT)
        if f.is_dir() or set(rel.parts) & SKIP_DIRS or f.name in SKIP_FILES or f.suffix in {".pyc"}:
            continue
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        files.append({"path": rel.as_posix(), "text": text})
    files.sort(key=lambda x: rank(x["path"]))
    return files


def js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def main() -> None:
    catalog = json.loads((ROOT / "backend/data/catalog.json").read_text())
    html = (ROOT / "artifact/template.html").read_text()
    html = html.replace("__CATALOG__", js(catalog)).replace("__SOURCE__", js({"files": collect()}))
    out = ROOT / "artifact/dermastyle-demo.html"
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
