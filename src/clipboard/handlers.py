import time
import os
from typing import Optional, List
from .listener import ClipboardBackend
from ..pipeline.metadata import ContentClassifier
from ..store.db import MetadataDB
from ..store.vault import VaultManager

class ClipboardService:
    def __init__(self, db: MetadataDB, vault: VaultManager):
        self.backend = ClipboardBackend()
        self.db = db
        self.vault = vault

    def capture_once(self, explicit_tags: Optional[List[str]] = None, explicit_note: Optional[str] = None) -> Optional[dict]:
        # 1. Try Image
        img_info = self.backend.get_image()
        if img_info:
            img_data, ext = img_info
            chash = ContentClassifier.compute_hash(img_data)
            if self.db.item_exists(chash):
                return {"status": "duplicate", "hash": chash, "category": "image"}

            rel_path = self.vault.save_media_file(img_data, ext, prefix="clip")
            tags = explicit_tags or ["clipboard", "screenshot"]
            item_id = self.db.record_item(
                content_hash=chash,
                source_type="clipboard",
                vault_rel_path=rel_path,
                title="Clipboard Screenshot",
                category="image",
                tags=tags,
                metadata={"size_bytes": len(img_data), "format": ext, "note": explicit_note}
            )
            return {"status": "captured", "id": item_id, "path": rel_path, "category": "image"}

        # 2. Try Text
        text = self.backend.get_text()
        if text and text.strip():
            encoded = text.encode("utf-8")
            chash = ContentClassifier.compute_hash(encoded)
            if self.db.item_exists(chash):
                return {"status": "duplicate", "hash": chash, "category": "text"}

            category, title, meta = ContentClassifier.classify_text(text)
            if explicit_note:
                meta["user_note"] = explicit_note

            tags = explicit_tags or ["clipboard", category]
            rel_path = self.vault.save_snippet_markdown(
                title=title,
                content=text,
                category=category,
                tags=tags,
                metadata=meta
            )
            item_id = self.db.record_item(
                content_hash=chash,
                source_type="clipboard",
                vault_rel_path=rel_path,
                title=title,
                category=category,
                tags=tags,
                metadata=meta
            )
            return {"status": "captured", "id": item_id, "path": rel_path, "category": category, "title": title}

        return {"status": "empty"}

    def watch(self, interval: float = 1.0, callback=None):
        print(f"[*] Clipboard watcher active (polling every {interval}s)... Press Ctrl+C to stop.")
        last_hash = None
        while True:
            try:
                res = self.capture_once()
                if res and res.get("status") == "captured":
                    if callback:
                        callback(res)
                    else:
                        print(f"[+] Ingested new {res.get('category')}: {res.get('path')} ({res.get('title', '')})")
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\n[*] Stopping clipboard watcher.")
                break
            except Exception as e:
                print(f"[!] Error polling clipboard: {e}")
                time.sleep(interval)
