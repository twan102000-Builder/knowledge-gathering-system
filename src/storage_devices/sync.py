import os
import hashlib
from typing import List, Dict, Any
from ..store.db import MetadataDB
from ..store.vault import VaultManager

class SDCardSyncPipeline:
    def __init__(self, db: MetadataDB, vault: VaultManager):
        self.db = db
        self.vault = vault

    @staticmethod
    def file_hash(filepath: str, blocksize: int = 65536) -> str:
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            for block in iter(lambda: f.read(blocksize), b""):
                hasher.update(block)
        return hasher.hexdigest()

    def sync_from_mount(
        self,
        mount_path: str,
        device_label: str = "sd_card",
        extensions: List[str] = None
    ) -> Dict[str, Any]:
        """
        Recursively scans mount_path, hashes files, and copies new files into vault.
        """
        scanned = 0
        imported = 0
        skipped = 0
        errors = 0

        ext_set = {e.lower().lstrip(".") for e in extensions} if extensions else None

        for root, _, files in os.walk(mount_path):
            for file in files:
                scanned += 1
                full_path = os.path.join(root, file)

                if ext_set:
                    file_ext = os.path.splitext(file)[1].lower().lstrip(".")
                    if file_ext not in ext_set:
                        continue

                try:
                    chash = self.file_hash(full_path)
                    if self.db.item_exists(chash):
                        skipped += 1
                        continue

                    # Copy to vault
                    rel_subfolder = os.path.relpath(root, mount_path)
                    vault_rel = self.vault.copy_into_sd_imports(
                        src_file=full_path,
                        subfolder=os.path.join(device_label, rel_subfolder)
                    )

                    file_stat = os.stat(full_path)
                    category = "media" if file.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4', '.wav', '.mp3')) else "document"

                    self.db.record_item(
                        content_hash=chash,
                        source_type="sd_card",
                        vault_rel_path=vault_rel,
                        title=file,
                        category=category,
                        source_path=full_path,
                        tags=["sd_card", device_label, category],
                        metadata={
                            "original_name": file,
                            "size_bytes": file_stat.st_size,
                            "device_label": device_label
                        }
                    )
                    imported += 1
                except Exception as e:
                    errors += 1

        return {
            "scanned": scanned,
            "imported": imported,
            "skipped_duplicates": skipped,
            "errors": errors
        }
