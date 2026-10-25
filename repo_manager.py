#!/usr/bin/env python3
"""
Local Knowledge Repository Manager (repo_manager.py)
Zero-bloat local staging, sanitization, conversion (.md, .txt, .pdf, .epub),
Dewey-style taxonomy management, SHA-256 manifest, and offline searchable catalog.
"""

import argparse
import datetime
import hashlib
import html
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_REPO_ROOT = os.path.expanduser("~/KnowRepo1")
STAGING_DIR = "/tmp/knowrepo_stage"

CATEGORIES = {
    "00": "00_Index_and_Manifests",
    "01": "01_Medical_and_Health",
    "02": "02_Survival_and_Food",
    "03": "03_Engineering_and_Repair",
    "04": "04_Science_and_Reference",
    "05": "05_Computing_and_Comms",
    "06": "06_History_Law_and_Civics",
    "07": "07_Uncategorized_Inbox",
}

CATEGORY_DESCRIPTIONS = {
    "00_Index_and_Manifests": "Master catalogs (INDEX.md, index.html), SHA-256 integrity manifests, and metadata registry.",
    "01_Medical_and_Health": "First aid, clinical guides, pharmacology, sanitation, dentistry, and emergency medicine.",
    "02_Survival_and_Food": "Water purification, agriculture, foraging, food preservation, shelter, and wilderness skills.",
    "03_Engineering_and_Repair": "Mechanical, electrical, solar/off-grid power, construction, tools, and equipment maintenance.",
    "04_Science_and_Reference": "Chemistry, physics, mathematics, biology, maps, and general encyclopedic references.",
    "05_Computing_and_Comms": "Linux, networking, radio/SDR, programming, cybersecurity, and hardware documentation.",
    "06_History_Law_and_Civics": "History, philosophy, legal references, governance, and classic literature.",
    "07_Uncategorized_Inbox": "Landing zone for multi-topic batches awaiting review and classification.",
}


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """
    Sanitize filename to be 100% compatible with FAT32, exFAT, NTFS, ext4, APFS.
    Removes illegal characters, normalizes whitespace, and limits length.
    """
    # Unescape HTML entities if any
    name = html.unescape(name)
    # Replace colons, slashes, and illegal FAT32 chars with underscores or hyphens
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name)
    # Replace sequences of whitespace with a single underscore
    name = re.sub(r'\s+', '_', name)
    # Remove any non-ASCII printable characters for strict flash drive portability
    name = re.sub(r'[^\x20-\x7E]', '', name)
    # Collapse multiple underscores or hyphens
    name = re.sub(r'[-_]{2,}', '_', name)
    name = name.strip('._- ')
    if not name:
        name = "untitled_document"
    return name[:max_len].strip('._- ')


class CleanHTMLConverter(html.parser.HTMLParser):
    """
    Zero-dependency HTML to clean Markdown / Plain Text converter.
    Strips scripts, styles, nav, footer, ads, and tracking elements.
    """

    IGNORE_TAGS = {
        "script", "style", "noscript", "iframe", "svg", "canvas",
        "nav", "footer", "header", "aside", "form", "button", "select", "option"
    }
    BLOCK_TAGS = {
        "p", "div", "section", "article", "main", "blockquote",
        "ul", "ol", "li", "table", "tr", "hr", "pre",
        "h1", "h2", "h3", "h4", "h5", "h6"
    }

    def __init__(self, to_markdown: bool = True, base_url: str = ""):
        super().__init__(convert_charrefs=True)
        self.to_markdown = to_markdown
        self.base_url = base_url
        self.ignore_depth = 0
        self.in_pre = False
        self.in_code = False
        self.in_title = False
        self.title = ""
        self.chunks = []
        self.current_href = None
        self.link_text = []
        self.list_stack = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.IGNORE_TAGS:
            self.ignore_depth += 1
            return
        if self.ignore_depth > 0:
            return

        attr_dict = dict(attrs)
        if tag == "title":
            self.in_title = True
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.chunks.append("\n\n" + ("#" * level + " " if self.to_markdown else "\n"))
        elif tag == "p" or tag == "div" or tag == "section" or tag == "article":
            self.chunks.append("\n\n")
        elif tag == "br":
            self.chunks.append("\n")
        elif tag == "hr":
            self.chunks.append("\n\n---\n\n")
        elif tag == "blockquote":
            self.chunks.append("\n\n> " if self.to_markdown else "\n\n  ")
        elif tag == "ul":
            self.list_stack.append("ul")
            self.chunks.append("\n")
        elif tag == "ol":
            self.list_stack.append(1)
            self.chunks.append("\n")
        elif tag == "li":
            indent = "  " * max(0, len(self.list_stack) - 1)
            if self.list_stack and isinstance(self.list_stack[-1], int):
                num = self.list_stack[-1]
                self.list_stack[-1] += 1
                bullet = f"{num}. "
            else:
                bullet = "- " if self.to_markdown else "* "
            self.chunks.append(f"\n{indent}{bullet}")
        elif tag == "pre":
            self.in_pre = True
            self.chunks.append("\n\n```\n" if self.to_markdown else "\n\n")
        elif tag == "code":
            self.in_code = True
            if not self.in_pre and self.to_markdown:
                self.chunks.append("`")
        elif tag in ("strong", "b") and self.to_markdown:
            self.chunks.append("**")
        elif tag in ("em", "i") and self.to_markdown:
            self.chunks.append("*")
        elif tag == "a" and self.to_markdown:
            href = attr_dict.get("href", "").strip()
            if href and not href.startswith(("javascript:", "mailto:", "#")):
                if self.base_url:
                    href = urllib.parse.urljoin(self.base_url, href)
                self.current_href = href
                self.link_text = []
        elif tag == "tr":
            self.chunks.append("\n")
        elif tag in ("td", "th"):
            self.chunks.append(" | " if self.to_markdown else "\t")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.IGNORE_TAGS:
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth > 0:
            return

        if tag == "title":
            self.in_title = False
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.chunks.append("\n\n")
        elif tag in ("p", "div", "section", "article", "blockquote"):
            self.chunks.append("\n\n")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self.chunks.append("\n")
        elif tag == "pre":
            self.in_pre = False
            self.chunks.append("\n```\n\n" if self.to_markdown else "\n\n")
        elif tag == "code":
            if not self.in_pre and self.to_markdown:
                self.chunks.append("`")
            self.in_code = False
        elif tag in ("strong", "b") and self.to_markdown:
            self.chunks.append("**")
        elif tag in ("em", "i") and self.to_markdown:
            self.chunks.append("*")
        elif tag == "a" and self.to_markdown:
            if self.current_href is not None:
                text = "".join(self.link_text).strip()
                if text:
                    self.chunks.append(f"[{text}]({self.current_href})")
                self.current_href = None
                self.link_text = []

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.ignore_depth > 0:
            return
        if not self.in_pre:
            data = re.sub(r'[ \t\r\n]+', ' ', data)
        if self.current_href is not None:
            self.link_text.append(data)
        else:
            self.chunks.append(data)

    def get_output(self) -> str:
        raw = "".join(self.chunks)
        # Clean up excessive blank lines and trailing spaces
        lines = [line.rstrip() for line in raw.splitlines()]
        cleaned = "\n".join(lines)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned + "\n"


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0 or unit == "TB":
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def resolve_category(cat_input: str) -> str:
    cat_input = cat_input.strip()
    if cat_input in CATEGORIES:
        return CATEGORIES[cat_input]
    for code, folder in CATEGORIES.items():
        if cat_input.lower() == folder.lower() or cat_input.lower() in folder.lower():
            return folder
    # Allow custom subfolders under a matched category if formatted like 01/FirstAid
    if "/" in cat_input:
        prefix, rest = cat_input.split("/", 1)
        base = resolve_category(prefix)
        safe_sub = "/".join(sanitize_filename(p) for p in rest.split("/") if p.strip())
        return f"{base}/{safe_sub}" if safe_sub else base
    return CATEGORIES["07"]


def cmd_init(repo_root: Path):
    """Initialize directory taxonomy and index files on the target repository drive."""
    if not repo_root.exists():
        print(f"[ERROR] Target repository path does not exist: {repo_root}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Initializing Knowledge Repository at: {repo_root}")
    for code, folder in sorted(CATEGORIES.items()):
        folder_path = repo_root / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        readme_path = folder_path / "README.md"
        if not readme_path.exists() and code != "00":
            desc = CATEGORY_DESCRIPTIONS.get(folder, "")
            readme_path.write_text(
                f"# {folder.replace('_', ' ')}\n\n{desc}\n",
                encoding="utf-8"
            )
        print(f"  [+] Ready: {folder}/")

    cmd_index(repo_root)
    print("[+] Initialization complete.")


def cmd_index(repo_root: Path):
    """Scan repository, compute SHA-256 manifest, and generate INDEX.md and offline index.html."""
    index_dir = repo_root / CATEGORIES["00"]
    index_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = index_dir / "catalog.json"
    existing_catalog = {}
    if catalog_path.exists():
        try:
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
            for item in data.get("files", []):
                existing_catalog[item["rel_path"]] = item
        except Exception:
            pass

    entries = []
    manifest_lines = []
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Walk all directories in sorted order
    for root, dirs, files in os.walk(repo_root):
        dirs.sort()
        files.sort()
        rel_dir = os.path.relpath(root, repo_root)
        if rel_dir.startswith(CATEGORIES["00"]) or rel_dir.startswith("."):
            continue

        for fname in files:
            if fname.startswith(".") or fname == "README.md":
                continue
            fpath = Path(root) / fname
            if not fpath.is_file():
                continue

            rel_path = fpath.relative_to(repo_root).as_posix()
            stat = fpath.stat()
            size_bytes = stat.st_size
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")

            # Reuse hash if file size and mtime haven't changed
            prev = existing_catalog.get(rel_path)
            if prev and prev.get("size_bytes") == size_bytes and prev.get("mtime") == mtime and prev.get("sha256"):
                sha256 = prev["sha256"]
                source_url = prev.get("source_url", "")
                title = prev.get("title", fname)
            else:
                sha256 = compute_sha256(fpath)
                source_url = prev.get("source_url", "") if prev else ""
                title = prev.get("title", fname) if prev else fname

            category = rel_path.split("/")[0]
            ext = fpath.suffix.lower().lstrip(".") or "file"

            entry = {
                "rel_path": rel_path,
                "filename": fname,
                "title": title,
                "category": category,
                "format": ext.upper(),
                "size_bytes": size_bytes,
                "size_human": human_size(size_bytes),
                "mtime": mtime,
                "sha256": sha256,
                "source_url": source_url,
            }
            entries.append(entry)
            manifest_lines.append(f"{sha256}  ../{rel_path}")

    # Save catalog.json
    total_bytes = sum(e["size_bytes"] for e in entries)
    catalog_data = {
        "updated_at": now_iso,
        "total_files": len(entries),
        "total_size_bytes": total_bytes,
        "total_size_human": human_size(total_bytes),
        "files": entries,
    }
    catalog_path.write_text(json.dumps(catalog_data, indent=2), encoding="utf-8")

    # Save MANIFEST.sha256
    manifest_path = index_dir / "MANIFEST.sha256"
    manifest_path.write_text("\n".join(manifest_lines) + ("\n" if manifest_lines else ""), encoding="utf-8")

    # Generate INDEX.md
    md_lines = [
        "# Local Knowledge Repository — Master Catalog",
        "",
        f"- **Last Updated**: `{now_iso}`",
        f"- **Total Files**: `{len(entries)}`",
        f"- **Total Repository Size**: `{human_size(total_bytes)}`",
        f"- **Integrity Manifest**: [`MANIFEST.sha256`](./MANIFEST.sha256)",
        "",
        "## Category Overview",
        "",
        "| Category | Description | Files | Size |",
        "| :--- | :--- | :---: | :---: |",
    ]

    for code, folder in sorted(CATEGORIES.items()):
        if code == "00":
            continue
        cat_files = [e for e in entries if e["category"] == folder]
        cat_size = sum(e["size_bytes"] for e in cat_files)
        desc = CATEGORY_DESCRIPTIONS.get(folder, "")
        md_lines.append(f"| [`{folder}`](../{folder}/) | {desc} | {len(cat_files)} | {human_size(cat_size)} |")

    md_lines.extend(["", "---", "", "## Complete File Index", ""])
    if not entries:
        md_lines.append("_No files ingested yet. Ready for first section download._")
    else:
        for code, folder in sorted(CATEGORIES.items()):
            if code == "00":
                continue
            cat_files = [e for e in entries if e["category"] == folder]
            if not cat_files:
                continue
            md_lines.append(f"### {folder.replace('_', ' ')} ({len(cat_files)})")
            md_lines.append("")
            md_lines.append("| Title / File | Format | Size | Date | SHA-256 (prefix) |")
            md_lines.append("| :--- | :---: | :---: | :---: | :---: |")
            for e in cat_files:
                md_lines.append(
                    f"| [{e['title']}](../{e['rel_path']}) | `{e['format']}` | {e['size_human']} | {e['mtime']} | `{e['sha256'][:12]}` |"
                )
            md_lines.append("")

    (index_dir / "INDEX.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # Generate standalone offline searchable index.html
    entries_json = json.dumps(entries)
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Local Knowledge Repository — Offline Catalog</title>
<style>
  :root {{
    --bg: #0f172a; --panel: #1e293b; --text: #f8fafc; --muted: #94a3b8;
    --accent: #38bdf8; --border: #334155; --badge: #0284c7;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); margin: 0; padding: 24px; line-height: 1.5;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  header {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 20px 24px; margin-bottom: 20px; display: flex; flex-wrap: wrap;
    justify-content: space-between; align-items: center; gap: 16px;
  }}
  h1 {{ margin: 0; font-size: 1.4rem; color: var(--accent); }}
  .stats {{ color: var(--muted); font-size: 0.9rem; }}
  .controls {{
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px;
  }}
  input, select {{
    background: var(--panel); color: var(--text); border: 1px solid var(--border);
    padding: 10px 14px; border-radius: 8px; font-size: 0.95rem;
  }}
  input {{ flex: 1; min-width: 260px; }}
  table {{
    width: 100%; border-collapse: collapse; background: var(--panel);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
  }}
  th, td {{
    text-align: left; padding: 12px 16px; border-bottom: 1px solid var(--border);
    font-size: 0.92rem;
  }}
  th {{ background: rgba(255,255,255,0.03); color: var(--muted); font-weight: 600; }}
  tr:hover {{ background: rgba(56, 189, 248, 0.06); }}
  a {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.78rem; font-weight: 600; background: var(--badge); color: #fff;
  }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.82rem; color: var(--muted); }}
  .empty {{ padding: 32px; text-align: center; color: var(--muted); }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>Local Knowledge Repository</h1>
      <div class="stats">Offline Portable Edition &bull; Updated: {now_iso}</div>
    </div>
    <div class="stats">
      <strong>{len(entries)}</strong> Files &bull; <strong>{human_size(total_bytes)}</strong> Total
    </div>
  </header>

  <div class="controls">
    <input type="search" id="search" placeholder="Search by title, filename, category, format, or URL...">
    <select id="catFilter">
      <option value="">All Categories</option>
      <option value="01_Medical_and_Health">01 Medical &amp; Health</option>
      <option value="02_Survival_and_Food">02 Survival &amp; Food</option>
      <option value="03_Engineering_and_Repair">03 Engineering &amp; Repair</option>
      <option value="04_Science_and_Reference">04 Science &amp; Reference</option>
      <option value="05_Computing_and_Comms">05 Computing &amp; Comms</option>
      <option value="06_History_Law_and_Civics">06 History, Law &amp; Civics</option>
      <option value="07_Uncategorized_Inbox">07 Uncategorized Inbox</option>
    </select>
    <select id="fmtFilter">
      <option value="">All Formats</option>
      <option value="MD">MD</option>
      <option value="TXT">TXT</option>
      <option value="PDF">PDF</option>
      <option value="EPUB">EPUB</option>
    </select>
  </div>

  <table>
    <thead>
      <tr>
        <th>Title / File</th>
        <th>Category</th>
        <th>Format</th>
        <th>Size</th>
        <th>Date</th>
        <th>SHA-256</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<script>
const FILES = {entries_json};
const tbody = document.getElementById('tbody');
const searchInput = document.getElementById('search');
const catFilter = document.getElementById('catFilter');
const fmtFilter = document.getElementById('fmtFilter');

function render() {{
  const q = searchInput.value.toLowerCase().trim();
  const cat = catFilter.value;
  const fmt = fmtFilter.value;
  const filtered = FILES.filter(f => {{
    if (cat && f.category !== cat) return false;
    if (fmt && f.format !== fmt) return false;
    if (q) {{
      const hay = (f.title + ' ' + f.filename + ' ' + f.category + ' ' + f.format + ' ' + (f.source_url || '')).toLowerCase();
      return hay.includes(q);
    }}
    return true;
  }});

  if (!filtered.length) {{
    tbody.innerHTML = '<tr><td colspan="6" class="empty">No matching files found in repository.</td></tr>';
    return;
  }}

  tbody.innerHTML = filtered.map(f => `
    <tr>
      <td>
        <a href="../${{f.rel_path}}" target="_blank">${{f.title}}</a>
        <div class="mono">${{f.rel_path}}</div>
      </td>
      <td>${{f.category.replace(/_/g, ' ')}}</td>
      <td><span class="badge">${{f.format}}</span></td>
      <td>${{f.size_human}}</td>
      <td>${{f.mtime}}</td>
      <td class="mono" title="${{f.sha256}}">${{f.sha256.slice(0, 12)}}</td>
    </tr>
  `).join('');
}}

searchInput.addEventListener('input', render);
catFilter.addEventListener('change', render);
fmtFilter.addEventListener('change', render);
render();
</script>
</body>
</html>
"""
    (index_dir / "index.html").write_text(html_content, encoding="utf-8")
    print(f"[+] Indexed {len(entries)} files ({human_size(total_bytes)}) -> INDEX.md, index.html, MANIFEST.sha256")


def cmd_ingest(repo_root: Path, url: str, category: str, fmt: str, custom_title: str = ""):
    """
    Download a URL to local staging (/tmp/knowrepo_stage), convert/verify format,
    move to target category on ~/KnowRepo1, update metadata, and purge local temp files.
    """
    target_rel_folder = resolve_category(category)
    target_dir = repo_root / target_rel_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    os.makedirs(STAGING_DIR, exist_ok=True)
    stage_path = Path(tempfile.mkdtemp(prefix="ingest_", dir=STAGING_DIR))

    try:
        print(f"[*] Fetching: {url}")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            raw_bytes = resp.read()

        # Determine requested or auto-detected format
        fmt = fmt.lower().lstrip(".")
        parsed_url = urllib.parse.urlparse(url)
        url_basename = os.path.basename(urllib.parse.unquote(parsed_url.path))
        url_stem, url_ext = os.path.splitext(url_basename)
        url_ext = url_ext.lower().lstrip(".")

        if fmt == "auto":
            if "application/pdf" in content_type or url_ext == "pdf" or raw_bytes[:4] == b"%PDF":
                fmt = "pdf"
            elif "application/epub" in content_type or url_ext == "epub":
                fmt = "epub"
            else:
                fmt = "md"

        date_str = datetime.date.today().isoformat()

        if fmt in ("pdf", "epub"):
            # Verify binary signature for PDF/EPUB
            if fmt == "pdf" and not raw_bytes.startswith(b"%PDF"):
                print("[!] Warning: File does not start with %PDF magic header.", file=sys.stderr)
            elif fmt == "epub" and not raw_bytes.startswith(b"PK"):
                print("[!] Warning: File does not start with ZIP/EPUB (PK) magic header.", file=sys.stderr)

            title = custom_title or url_stem or "Document"
            safe_name = f"{ sanitize_filename(title) }.{fmt}"
            staged_file = stage_path / safe_name
            staged_file.write_bytes(raw_bytes)
        elif fmt in ("md", "txt"):
            text_content = raw_bytes.decode("utf-8", errors="replace")
            if "<html" in text_content.lower() or "<body" in text_content.lower() or "text/html" in content_type:
                parser = CleanHTMLConverter(to_markdown=(fmt == "md"), base_url=url)
                parser.feed(text_content)
                converted = parser.get_output()
                detected_title = parser.title.strip()
            else:
                converted = text_content
                detected_title = ""

            title = custom_title or detected_title or url_stem or parsed_url.netloc
            safe_name = f"{ sanitize_filename(title) }.{fmt}"
            staged_file = stage_path / safe_name

            if fmt == "md":
                header = (
                    "---\n"
                    f"title: \"{title.replace('\"', '')}\"\n"
                    f"source_url: \"{url}\"\n"
                    f"date_saved: \"{date_str}\"\n"
                    f"category: \"{target_rel_folder}\"\n"
                    "---\n\n"
                    f"# {title}\n\n"
                )
                staged_file.write_text(header + converted, encoding="utf-8")
            else:
                header = (
                    f"TITLE: {title}\n"
                    f"SOURCE: {url}\n"
                    f"DATE SAVED: {date_str}\n"
                    f"CATEGORY: {target_rel_folder}\n"
                    + ("=" * 72) + "\n\n"
                )
                staged_file.write_text(header + converted, encoding="utf-8")
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        # Compute hash in staging, move to destination drive
        sha256 = compute_sha256(staged_file)
        dest_file = target_dir / staged_file.name
        shutil.copy2(staged_file, dest_file)

        # Verify integrity on destination drive before deleting local staging
        dest_sha256 = compute_sha256(dest_file)
        if dest_sha256 != sha256:
            raise RuntimeError(f"Checksum mismatch after copy to {dest_file}!")

        print(f"[+] Saved & Verified: {dest_file.relative_to(repo_root)} ({human_size(dest_file.stat().st_size)})")
        print(f"    SHA-256: {sha256}")

        # Update catalog metadata with title & source_url before re-indexing
        index_dir = repo_root / CATEGORIES["00"]
        index_dir.mkdir(parents=True, exist_ok=True)
        catalog_path = index_dir / "catalog.json"
        if catalog_path.exists():
            try:
                cat_data = json.loads(catalog_path.read_text(encoding="utf-8"))
            except Exception:
                cat_data = {"files": []}
        else:
            cat_data = {"files": []}

        rel_p = dest_file.relative_to(repo_root).as_posix()
        files_list = [f for f in cat_data.get("files", []) if f.get("rel_path") != rel_p]
        files_list.append({
            "rel_path": rel_p,
            "filename": dest_file.name,
            "title": title,
            "category": rel_p.split("/")[0],
            "format": fmt.upper(),
            "size_bytes": dest_file.stat().st_size,
            "size_human": human_size(dest_file.stat().st_size),
            "mtime": datetime.datetime.fromtimestamp(dest_file.stat().st_mtime).strftime("%Y-%m-%d"),
            "sha256": sha256,
            "source_url": url,
        })
        cat_data["files"] = files_list
        catalog_path.write_text(json.dumps(cat_data, indent=2), encoding="utf-8")

        cmd_index(repo_root)

    finally:
        # Always purge local staging directory to keep local disk clean
        if stage_path.exists():
            shutil.rmtree(stage_path, ignore_errors=True)
            print(f"[*] Purged local staging buffer: {stage_path}")


def cmd_verify(repo_root: Path):
    """Verify all files in repository against MANIFEST.sha256."""
    manifest_path = repo_root / CATEGORIES["00"] / "MANIFEST.sha256"
    if not manifest_path.exists():
        print("[ERROR] MANIFEST.sha256 not found. Run 'index' first.", file=sys.stderr)
        sys.exit(1)

    lines = [l.strip() for l in manifest_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        print("[*] Manifest is empty (0 files to verify).")
        return

    ok = 0
    failed = 0
    index_dir = repo_root / CATEGORIES["00"]
    for line in lines:
        expected_hash, rel_ref = line.split("  ", 1)
        target_path = (index_dir / rel_ref).resolve()
        if not target_path.exists():
            print(f"[FAIL] Missing file: {rel_ref}")
            failed += 1
            continue
        actual_hash = compute_sha256(target_path)
        if actual_hash == expected_hash:
            ok += 1
        else:
            print(f"[FAIL] Checksum mismatch: {rel_ref}")
            failed += 1

    print(f"[+] Verification complete: {ok} OK, {failed} FAILED.")
    if failed > 0:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Local Knowledge Repository Manager")
    parser.add_argument("--repo", default=DEFAULT_REPO_ROOT, help="Path to repository root (default: ~/KnowRepo1)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Initialize repository folder structure and catalog")
    sub.add_parser("index", help="Rebuild INDEX.md, index.html, and MANIFEST.sha256")
    sub.add_parser("verify", help="Verify all files against MANIFEST.sha256")

    p_ingest = sub.add_parser("ingest", help="Download, sanitize, convert, and store a URL onto the repository")
    p_ingest.add_argument("url", help="Source URL to download")
    p_ingest.add_argument("-c", "--category", default="07", help="Category code (01-07) or folder/subfolder")
    p_ingest.add_argument("-f", "--format", default="auto", choices=["auto", "md", "txt", "pdf", "epub"], help="Output format")
    p_ingest.add_argument("-t", "--title", default="", help="Custom title for the file")

    args = parser.parse_args()
    repo_root = Path(os.path.expanduser(args.repo)).resolve()

    if args.cmd == "init":
        cmd_init(repo_root)
    elif args.cmd == "index":
        cmd_index(repo_root)
    elif args.cmd == "verify":
        cmd_verify(repo_root)
    elif args.cmd == "ingest":
        cmd_ingest(repo_root, args.url, args.category, args.format, args.title)


if __name__ == "__main__":
    main()
