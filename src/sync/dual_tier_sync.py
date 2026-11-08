"""
Dual-Tier Knowledge Repository Synchronization Engine (src/sync/dual_tier_sync.py)

Manages synchronization between:
1. On-Device Local Knowledge Repo (on each device's main storage):
   - Mac mini: Samsung 990 PRO NVMe (/Volumes/990_PRO/KnowRepo_Local)
   - MacBook Pro / other Macs: Internal NVMe SSD (~/KnowRepo_Local)
2. Portable Removable 1TB Drive (Universal Main Know Repo):
   - Single dedicated partition on the portable drive shared across all devices
     (Mac mini, MacBook Pro, and any other device).

Key Features:
- Host-adaptive storage resolution (auto-detects Mac mini 990 PRO vs MacBook internal storage).
- Single-partition targeting on the portable 1TB drive for canonical cross-device knowledge.
- Cryptographic SHA-256 verification, atomic swaps, and storage-saving stub offloading.
- Preserves sibling partitions on the portable drive untouched.
- Bidirectional metadata reconciliation between SQLite databases with device provenance tracking.
"""

import os
import sys
import json
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import repo_manager
from src.store.db import MetadataDB
from src.storage_devices.mac_disk import MacDiskManager
from src.storage_devices.drive_guard import DriveSafetyGuard
from src.storage_devices.device_profile import DeviceProfileManager


class DualTierSyncEngine:
    """Orchestrates on-device local repositories and the shared portable 1TB Main Know Repo partition."""

    def __init__(self, local_path: Optional[str] = None, archive_path: Optional[str] = None):
        if local_path:
            self.local_root = Path(os.path.abspath(os.path.expanduser(local_path)))
        else:
            self.local_root = DeviceProfileManager.resolve_preferred_local_repo_path()

        self._custom_archive_path = Path(os.path.abspath(os.path.expanduser(archive_path))) if archive_path else None
        self.categories = list(repo_manager.CATEGORIES.values())
        self.host_device = DeviceProfileManager.detect_host_device()

    def resolve_portable_knowrepo_partition(self) -> Optional[Dict[str, Any]]:
        """
        Locates the single partition dedicated to KnowRepo on the portable removable 1TB drive,
        explicitly skipping host storage (internal SSD and 990_PRO host extension).
        """
        if MacDiskManager.is_macos():
            return MacDiskManager.find_portable_knowrepo_partition()
        return None

    def resolve_archive_root(self) -> Optional[Path]:
        """
        Dynamically locates the target Main Know Repo on the single dedicated partition
        of the portable removable 1TB drive.
        Priority:
        1. Explicit custom path passed by user (--archive-repo).
        2. Mounted KnowRepo partition on the portable removable 1TB drive.
        3. Unmounted KnowRepo partition on portable drive (mounts on demand).
        """
        if self._custom_archive_path and self._custom_archive_path.exists():
            return self._custom_archive_path

        # Locate the single dedicated KnowRepo partition on the connected portable 1TB drive
        part_info = self.resolve_portable_knowrepo_partition()
        if part_info:
            part = part_info.get("partition", {})
            mount_pt = part.get("mount_point")
            if not mount_pt:
                # Attempt safe mount
                ok, res_mount = MacDiskManager.mount_volume(part["device_identifier"])
                if ok:
                    mount_pt = res_mount

            if mount_pt:
                target_mount = Path(mount_pt)
                # Check for standard subfolder or use partition root
                for sub in ["KnowRepo_Main_Archive", "KnowRepo1", "KnowRepo"]:
                    candidate = target_mount / sub
                    if candidate.exists():
                        return candidate
                return target_mount / "KnowRepo_Main_Archive"

        if self._custom_archive_path:
            return self._custom_archive_path

        return None

    def get_tier_status(self) -> Dict[str, Any]:
        """
        Gathers comprehensive dual-tier status tailored to the active host device:
        - Host Device info (Mac mini vs MacBook Pro)
        - Tier 1: On-Device Local Know Repo (on device's main storage)
        - Tier 2: Portable 1TB Drive (Single KnowRepo partition holding the Main Archive)
        - Sync deltas
        """
        portable_part_info = self.resolve_portable_knowrepo_partition()
        archive_root = self.resolve_archive_root()
        archive_attached = archive_root is not None and archive_root.parent.exists()

        local_files = self._scan_repo_files(self.local_root) if self.local_root.exists() else []
        archive_files = self._scan_repo_files(archive_root) if (archive_attached and archive_root.exists()) else []

        local_hashes = {f["sha256"]: f for f in local_files if f.get("sha256")}
        archive_hashes = {f["sha256"]: f for f in archive_files if f.get("sha256")}

        pending_push = [f for f in local_files if f.get("sha256") and f["sha256"] not in archive_hashes and not f.get("is_stub")]
        pending_pull = [f for f in archive_files if f.get("sha256") and f["sha256"] not in local_hashes]
        stubs_count = sum(1 for f in local_files if f.get("is_stub"))

        local_bytes = sum(f["size"] for f in local_files)
        archive_bytes = sum(f["size"] for f in archive_files)
        local_free = DriveSafetyGuard.get_available_bytes(self.local_root)

        portable_info = {}
        if portable_part_info:
            part = portable_part_info.get("partition", {})
            siblings = portable_part_info.get("sibling_partitions", [])
            avail_bytes = DriveSafetyGuard.get_available_bytes(archive_root) if archive_root else 0

            portable_info = {
                "is_connected": True,
                "parent_disk": portable_part_info.get("parent_disk"),
                "parent_size_human": self._format_bytes(portable_part_info.get("parent_size", 0)),
                "bus_protocol": portable_part_info.get("bus_protocol", "USB"),
                "knowrepo_partition": {
                    "device_identifier": part.get("device_identifier"),
                    "device_node": part.get("device_node"),
                    "partition_label": part.get("partition_label"),
                    "mount_point": part.get("mount_point"),
                    "filesystem": part.get("filesystem"),
                    "size_human": self._format_bytes(part.get("size", 0)),
                    "free_human": self._format_bytes(avail_bytes),
                    "archive_path": str(archive_root)
                },
                "sibling_partitions": [
                    {
                        "device_identifier": s.get("device_identifier"),
                        "partition_label": s.get("partition_label"),
                        "mount_point": s.get("mount_point"),
                        "filesystem": s.get("filesystem"),
                        "size_human": self._format_bytes(s.get("size", 0))
                    }
                    for s in siblings
                ],
                "total_files": len(archive_files),
                "total_bytes": archive_bytes,
                "total_human": self._format_bytes(archive_bytes)
            }
        else:
            portable_info = {
                "is_connected": False,
                "message": "Portable 1TB removable drive is not connected. Local captures buffer safely on this device."
            }

        return {
            "host_device": self.host_device,
            "local_repo": {
                "path": str(self.local_root),
                "exists": self.local_root.exists(),
                "free_bytes": local_free,
                "free_human": self._format_bytes(local_free),
                "total_files": len(local_files),
                "total_bytes": local_bytes,
                "total_human": self._format_bytes(local_bytes),
                "active_stubs": stubs_count,
                "storage_description": self.host_device.get("preferred_storage_description")
            },
            "portable_drive": portable_info,
            "archive_repo": {
                "path": str(archive_root) if archive_root else "Not connected",
                "is_mounted": archive_attached,
                "total_files": len(archive_files),
                "total_human": self._format_bytes(archive_bytes)
            },
            "sync_delta": {
                "pending_push_count": len(pending_push),
                "pending_push_bytes": sum(f["size"] for f in pending_push),
                "pending_pull_count": len(pending_pull),
                "pending_pull_bytes": sum(f["size"] for f in pending_pull),
            }
        }

    def init_local_repo(self) -> Path:
        """Initializes Dewey taxonomy structure in this device's on-device local repository."""
        self.local_root.mkdir(parents=True, exist_ok=True)
        repo_manager.cmd_init(self.local_root)
        return self.local_root

    def init_archive_repo(self, target_path: Optional[Path] = None) -> Path:
        """Initializes Dewey taxonomy structure on the portable 1TB drive's single KnowRepo partition."""
        dest = target_path or self.resolve_archive_root()
        if not dest:
            raise RuntimeError("Cannot initialize archive: Portable 1TB drive KnowRepo partition not found or not mounted.")
        dest.mkdir(parents=True, exist_ok=True)
        repo_manager.cmd_init(dest)
        return dest

    def push_to_archive(
        self,
        dry_run: bool = False,
        offload: bool = False,
        offload_threshold_bytes: int = 25 * 1024 * 1024 # 25MB default threshold
    ) -> Dict[str, Any]:
        """
        Pushes new or updated files from this device's local repo to the portable 1TB Main Know Repo.
        - Verifies headroom and uses atomic copy with SHA-256 validation.
        - Automatically sanitizes macOS artifacts (.DS_Store, ._*).
        - Optionally replaces large local files with stubs on this device's main drive.
        """
        archive_root = self.resolve_archive_root()
        if not archive_root or not archive_root.parent.exists():
            return {
                "success": False,
                "error": "Portable 1TB drive KnowRepo partition is not connected or mounted. Cannot push to archive."
            }

        archive_root.mkdir(parents=True, exist_ok=True)
        if not (archive_root / "00_Index_and_Manifests").exists():
            repo_manager.cmd_init(archive_root)

        local_files = self._scan_repo_files(self.local_root)
        archive_files = self._scan_repo_files(archive_root)
        archive_hash_map = {f["sha256"]: f for f in archive_files if f.get("sha256")}

        pushed_count = 0
        pushed_bytes = 0
        offloaded_count = 0
        skipped_count = 0
        errors = []

        MacDiskManager.clean_macos_artifacts(str(self.local_root))

        for item in local_files:
            if item.get("is_stub"):
                skipped_count += 1
                continue

            rel_path = item["rel_path"]
            src_file = Path(item["full_path"])
            dst_file = archive_root / rel_path
            sha = item["sha256"]
            size = item["size"]

            if "00_Index_and_Manifests" in str(rel_path):
                continue

            already_in_archive = (dst_file.exists() and dst_file.stat().st_size == size) or (sha in archive_hash_map)

            if already_in_archive:
                skipped_count += 1
            else:
                if dry_run:
                    pushed_count += 1
                    pushed_bytes += size
                else:
                    ok, comp_sha, err = DriveSafetyGuard.atomic_copy_and_verify(
                        src_path=src_file,
                        dst_path=dst_file,
                        expected_hash=sha
                    )
                    if ok:
                        pushed_count += 1
                        pushed_bytes += size
                    else:
                        errors.append({"file": rel_path, "error": err})
                        continue

            if offload and not dry_run and size >= offload_threshold_bytes:
                if dst_file.exists():
                    archive_sha = DriveSafetyGuard.calculate_sha256(dst_file)
                    if archive_sha == sha:
                        self._create_stub_file(src_file, item, str(dst_file))
                        offloaded_count += 1

        if not dry_run:
            self._reconcile_databases(self.local_root, archive_root)
            MacDiskManager.clean_macos_artifacts(str(archive_root))
            repo_manager.cmd_index(archive_root)

        return {
            "success": True,
            "dry_run": dry_run,
            "pushed_files": pushed_count,
            "pushed_bytes": pushed_bytes,
            "pushed_human": self._format_bytes(pushed_bytes),
            "offloaded_stubs": offloaded_count,
            "skipped_already_present": skipped_count,
            "errors": errors
        }

    def pull_from_archive(
        self,
        categories: Optional[List[str]] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Pulls master index, catalogs, and selected category documents from the portable 1TB drive
        into this device's local repository.
        """
        archive_root = self.resolve_archive_root()
        if not archive_root or not archive_root.exists():
            return {
                "success": False,
                "error": "Portable 1TB drive KnowRepo partition is not connected or mounted. Cannot pull from archive."
            }

        self.local_root.mkdir(parents=True, exist_ok=True)
        if not (self.local_root / "00_Index_and_Manifests").exists():
            repo_manager.cmd_init(self.local_root)

        archive_files = self._scan_repo_files(archive_root)
        local_files = self._scan_repo_files(self.local_root)
        local_hash_map = {f["sha256"]: f for f in local_files if f.get("sha256")}

        pulled_count = 0
        pulled_bytes = 0
        skipped_count = 0
        errors = []

        cat_prefixes = tuple(categories) if categories else None

        for item in archive_files:
            rel_path = item["rel_path"]
            src_file = Path(item["full_path"])
            dst_file = self.local_root / rel_path
            sha = item["sha256"]
            size = item["size"]

            is_index = "00_Index_and_Manifests" in str(rel_path)
            if cat_prefixes and not is_index:
                matched = any(str(rel_path).startswith(c) for c in cat_prefixes)
                if not matched:
                    continue

            already_local = (dst_file.exists() and dst_file.stat().st_size == size) or (sha in local_hash_map)
            if already_local and not is_index:
                skipped_count += 1
                continue

            if dry_run:
                pulled_count += 1
                pulled_bytes += size
            else:
                ok, _, err = DriveSafetyGuard.atomic_copy_and_verify(
                    src_path=src_file,
                    dst_path=dst_file,
                    expected_hash=sha if not is_index else None
                )
                if ok:
                    pulled_count += 1
                    pulled_bytes += size
                else:
                    errors.append({"file": rel_path, "error": err})

        if not dry_run:
            self._reconcile_databases(archive_root, self.local_root)
            repo_manager.cmd_index(self.local_root)

        return {
            "success": True,
            "dry_run": dry_run,
            "pulled_files": pulled_count,
            "pulled_bytes": pulled_bytes,
            "pulled_human": self._format_bytes(pulled_bytes),
            "skipped_already_present": skipped_count,
            "errors": errors
        }

    def hydrate_stub(self, stub_rel_or_path: str) -> Tuple[bool, str]:
        """
        Rehydrates a local stub file on this device back to its full content from the portable 1TB drive.
        """
        stub_path = Path(stub_rel_or_path)
        if not stub_path.is_absolute():
            stub_path = self.local_root / stub_path

        if not stub_path.exists():
            return False, f"Stub file not found: {stub_path}"

        if not str(stub_path).endswith(".stub.json"):
            return False, f"Not a valid stub file: {stub_path}"

        try:
            with open(stub_path, "r", encoding="utf-8") as f:
                stub_meta = json.load(f)
        except Exception as e:
            return False, f"Failed to parse stub JSON: {e}"

        archive_root = self.resolve_archive_root()
        if not archive_root or not archive_root.exists():
            return False, "Portable 1TB drive archive is not connected. Rehydration requires the portable drive."

        rel_path = stub_meta.get("rel_path")
        expected_sha = stub_meta.get("sha256")
        archive_src = archive_root / rel_path

        if not archive_src.exists():
            return False, f"Target file not found in archive: {archive_src}"

        restored_path = stub_path.with_suffix("")
        if restored_path.name.endswith(".stub"):
            restored_path = restored_path.with_suffix("")

        ok, _, err = DriveSafetyGuard.atomic_copy_and_verify(
            src_path=archive_src,
            dst_path=restored_path,
            expected_hash=expected_sha
        )
        if not ok:
            return False, f"Rehydration copy failed: {err}"

        stub_path.unlink()
        return True, f"Successfully rehydrated {restored_path.name} ({self._format_bytes(restored_path.stat().st_size)})"

    def _create_stub_file(self, full_file: Path, item_meta: dict, archive_target: str):
        """Creates a lean stub file and unlinks the local heavy original."""
        stub_path = full_file.with_name(f"{full_file.name}.stub.json")
        stub_data = {
            "_type": "KGS_OFFLOADED_STUB",
            "title": item_meta.get("title", full_file.name),
            "rel_path": item_meta.get("rel_path"),
            "sha256": item_meta.get("sha256"),
            "original_size": item_meta.get("size"),
            "original_size_human": self._format_bytes(item_meta.get("size", 0)),
            "archive_location": archive_target,
            "offloaded_at": repo_manager.datetime.datetime.now().isoformat(),
            "offloaded_by_device": self.host_device.get("computer_name")
        }
        DriveSafetyGuard.atomic_write_text(stub_path, json.dumps(stub_data, indent=2))
        full_file.unlink()

    def _reconcile_databases(self, src_root: Path, dst_root: Path):
        """Copies or merges SQLite metadata records from src to dst without duplicate clashes."""
        src_db_file = src_root / "00_Index_and_Manifests" / "kgs_metadata.db"
        dst_db_file = dst_root / "00_Index_and_Manifests" / "kgs_metadata.db"

        if not src_db_file.exists():
            return

        dst_db_file.parent.mkdir(parents=True, exist_ok=True)
        src_db = MetadataDB(str(src_db_file))
        dst_db = MetadataDB(str(dst_db_file))

        device_tag = f"device:{self.host_device.get('device_type', 'mac')}"

        try:
            items = src_db.search_items("")
            for itm in items:
                content_hash = itm["content_hash"]
                if not dst_db.item_exists(content_hash):
                    tags = list(itm.get("tags") or [])
                    if device_tag not in tags:
                        tags.append(device_tag)

                    dst_db.record_item(
                        content_hash=content_hash,
                        source_type=itm.get("source_type", "synced"),
                        vault_rel_path=itm.get("vault_rel_path", ""),
                        title=itm.get("title", ""),
                        category=itm.get("category", "document"),
                        source_path=itm.get("source_path", ""),
                        tags=tags,
                        metadata=itm.get("metadata", {})
                    )
        except Exception as e:
            print(f"[WARN] Failed to merge metadata DBs: {e}", file=sys.stderr)

    def _scan_repo_files(self, root_path: Path) -> List[Dict[str, Any]]:
        """Scans content repository files (01-07), skipping manifests and computing hashes."""
        results = []
        if not root_path or not root_path.exists():
            return results

        for root, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "00_Index_and_Manifests"]
            rel_dir = os.path.relpath(root, root_path)
            if rel_dir.startswith("00_Index_and_Manifests") or rel_dir.startswith("."):
                continue

            for f in files:
                if f.startswith(".") or f.startswith("._") or f == ".DS_Store" or f == "README.md":
                    continue
                full_f = Path(root) / f
                rel_f = full_f.relative_to(root_path)

                is_stub = f.endswith(".stub.json")
                size = full_f.stat().st_size
                sha = ""

                if is_stub:
                    try:
                        with open(full_f, "r", encoding="utf-8") as sfp:
                            sdata = json.load(sfp)
                            sha = sdata.get("sha256", "")
                            size = sdata.get("original_size", size)
                    except Exception:
                        pass
                else:
                    try:
                        sha = DriveSafetyGuard.calculate_sha256(full_f)
                    except OSError:
                        pass

                results.append({
                    "name": f,
                    "rel_path": str(rel_f),
                    "full_path": str(full_f),
                    "size": size,
                    "sha256": sha,
                    "is_stub": is_stub
                })
        return results

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:3.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"
