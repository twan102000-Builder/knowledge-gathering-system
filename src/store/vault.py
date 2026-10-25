import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

class VaultManager:
    def __init__(self, root_path: str):
        self.root_path = Path(os.path.abspath(root_path))
        self.inbox_dir = self.root_path / "07_Uncategorized_Inbox"
        self.snippets_dir = self.inbox_dir / "snippets"
        self.media_dir = self.inbox_dir / "media"
        self.daily_dir = self.inbox_dir / "daily"
        self.sd_imports_dir = self.inbox_dir / "sd_imports"
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in [self.snippets_dir, self.media_dir, self.daily_dir, self.sd_imports_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def save_snippet_markdown(
        self,
        title: str,
        content: str,
        category: str,
        tags: list,
        metadata: dict
    ) -> str:
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in title[:40])
        filename = f"{date_str}_{safe_title}.md"
        filepath = self.snippets_dir / filename

        # Format YAML Frontmatter + Markdown
        frontmatter = [
            "---",
            f"title: \"{title}\"",
            f"category: {category}",
            f"captured_at: {datetime.now().isoformat()}",
            f"tags: [{', '.join(tags)}]",
        ]
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                frontmatter.append(f"{k}: {v}")
        frontmatter.append("---\n")

        body = "\n".join(frontmatter) + content + "\n"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(body)

        return str(filepath.relative_to(self.root_path))

    def save_media_file(self, data: bytes, ext: str, prefix: str = "clip") -> str:
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{date_str}.{ext.lstrip('.')}"
        dest = self.media_dir / filename
        with open(dest, "wb") as f:
            f.write(data)
        return str(dest.relative_to(self.root_path))

    def copy_into_sd_imports(self, src_file: str, subfolder: str = "") -> str:
        dest_dir = self.sd_imports_dir / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = os.path.basename(src_file)
        dest_path = dest_dir / filename

        shutil.copy2(src_file, dest_path)
        return str(dest_path.relative_to(self.root_path))
