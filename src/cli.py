#!/usr/bin/env python3
import sys
import os
import argparse
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import repo_manager
from src.store.db import MetadataDB
from src.store.vault import VaultManager
from src.clipboard.handlers import ClipboardService
from src.storage_devices.detector import SDDeviceDetector
from src.storage_devices.mounter import SafeDeviceMounter
from src.storage_devices.sync import SDCardSyncPipeline

DEFAULT_REPO_ROOT = os.path.expanduser("~/KnowRepo1")
DEFAULT_DB_PATH = os.path.join(DEFAULT_REPO_ROOT, "00_Index_and_Manifests", "kgs_metadata.db")


def init_services(repo_path: str = DEFAULT_REPO_ROOT):
    vault = VaultManager(repo_path)
    db_path = os.path.join(str(vault.root_path), "00_Index_and_Manifests", "kgs_metadata.db")
    db = MetadataDB(db_path)
    return db, vault


def handle_clip(args):
    db, vault = init_services(args.repo)
    clip_service = ClipboardService(db, vault)
    tags = [t.strip() for t in args.tag.split(",")] if args.tag else None
    res = clip_service.capture_once(explicit_tags=tags, explicit_note=args.note)
    
    status = res.get("status")
    if status == "captured":
        print(f"Captured ({res.get('category')}): {res.get('title')}")
        print(f"Vault path: {res.get('path')}")
        # Re-index repository manifests
        repo_manager.cmd_index(vault.root_path)
    elif status == "duplicate":
        print(f"Item already exists in vault (hash: {res.get('hash')[:10]}...)")
    elif status == "empty":
        print("Clipboard is empty or unsupported format.")


def handle_clip_watch(args):
    db, vault = init_services(args.repo)
    clip_service = ClipboardService(db, vault)
    clip_service.watch(interval=args.interval)


def handle_sd_list(args):
    devices = SDDeviceDetector.list_candidate_devices()
    if not devices:
        print("No SD cards or removable storage detected via lsblk.")
        return
    print(f"Found {len(devices)} candidate device(s):")
    for d in devices:
        mount_info = f" (Mounted at {d['mountpoint']})" if d['mountpoint'] else " (Not mounted)"
        print(f" - {d['path']} [{d['fstype'] or 'unknown'}] {d['size']} Label: '{d['label'] or ''}'{mount_info}")


def handle_sd_import(args):
    db, vault = init_services(args.repo)
    dev = SDDeviceDetector.find_device(args.device)
    if not dev:
        print(f"Could not locate matching device for '{args.device}'.")
        return

    dev_path = dev["path"]
    mount_point = dev.get("mountpoint")
    was_auto_mounted = False
    mounter = SafeDeviceMounter()

    if not mount_point:
        print(f"Device {dev_path} is not mounted. Attempting safe read-only mount...")
        ok, m_res = mounter.mount_read_only(dev_path)
        if not ok:
            print(f"Failed to mount {dev_path}: {m_res}")
            return
        mount_point = m_res
        was_auto_mounted = True
        print(f"Mounted at {mount_point} (read-only)")
    else:
        print(f"Using active mount point at {mount_point}")

    try:
        pipeline = SDCardSyncPipeline(db, vault)
        label = dev.get("label") or dev.get("name") or "sd_card"
        print(f"Syncing files from {mount_point} into vault...")
        summary = pipeline.sync_from_mount(mount_point, device_label=label)
        print("--- Ingest Summary ---")
        print(f"Scanned files : {summary['scanned']}")
        print(f"Imported new  : {summary['imported']}")
        print(f"Duplicates    : {summary['skipped_duplicates']}")
        print(f"Errors        : {summary['errors']}")
        # Refresh master manifests
        repo_manager.cmd_index(vault.root_path)
    finally:
        if was_auto_mounted and args.unmount:
            print("Cleaning up mount point...")
            mounter.unmount(mount_point)


def handle_sd_eject(args):
    mounter = SafeDeviceMounter()
    ok, msg = mounter.unmount(args.device)
    if ok:
        print(f"Device {args.device} safely unmounted. You can now remove the SD card.")
    else:
        print(f"Eject failed: {msg}")


def handle_ingest(args):
    repo_root = Path(os.path.expanduser(args.repo)).resolve()
    repo_manager.cmd_ingest(repo_root, args.url, args.category, args.format, args.title)
    
    # Also record into SQLite DB for full unified search
    db, vault = init_services(args.repo)
    # The file is already indexed in catalog.json & INDEX.md by repo_manager
    catalog_path = repo_root / "00_Index_and_Manifests" / "catalog.json"
    if catalog_path.exists():
        import json
        cat = json.loads(catalog_path.read_text(encoding="utf-8"))
        for f in cat.get("files", []):
            if f.get("source_url") == args.url and not db.item_exists(f["sha256"]):
                db.record_item(
                    content_hash=f["sha256"],
                    source_type="web_url",
                    vault_rel_path=f["rel_path"],
                    title=f["title"],
                    category=f["format"].lower(),
                    source_path=args.url,
                    tags=[f["category"]],
                    metadata={"size_bytes": f["size_bytes"], "source_url": args.url}
                )


def handle_init(args):
    repo_root = Path(os.path.expanduser(args.repo)).resolve()
    repo_manager.cmd_init(repo_root)


def handle_index(args):
    repo_root = Path(os.path.expanduser(args.repo)).resolve()
    repo_manager.cmd_index(repo_root)


def handle_verify(args):
    repo_root = Path(os.path.expanduser(args.repo)).resolve()
    repo_manager.cmd_verify(repo_root)


def handle_status(args):
    repo_root = Path(os.path.expanduser(args.repo)).resolve()
    db, vault = init_services(args.repo)
    stats = db.stats()
    print("=== Knowledge Gathering System (KGS) Status ===")
    print(f"Vault Root  : {vault.root_path}")
    print(f"SQLite DB   : {db.db_path}")
    print(f"Indexed DB  : {stats['total_items']} items")
    for source, count in stats["by_source"].items():
        print(f" - {source}: {count} items")
    print("\n--- Storage Taxonomy Status ---")
    repo_manager.cmd_index(repo_root)


def handle_search(args):
    db, _ = init_services(args.repo)
    results = db.search_items(args.query)
    if not results:
        print(f"No database items found matching '{args.query}'.")
        # Fallback search in catalog.json
        repo_root = Path(os.path.expanduser(args.repo)).resolve()
        cat_file = repo_root / "00_Index_and_Manifests" / "catalog.json"
        if cat_file.exists():
            import json
            cat = json.loads(cat_file.read_text(encoding="utf-8"))
            matches = [f for f in cat.get("files", []) if args.query.lower() in (f['title'] + ' ' + f['rel_path']).lower()]
            if matches:
                print(f"Found {len(matches)} item(s) in repository catalog:")
                for m in matches:
                    print(f" - [{m['format']}] {m['title']} -> {m['rel_path']} ({m['size_human']})")
        return

    print(f"Found {len(results)} item(s):")
    for r in results:
        print(f"[{r['id']}] [{r['source_type']}] {r['title']} -> {r['vault_rel_path']} ({r['created_at'][:10]})")


def main():
    parser = argparse.ArgumentParser(prog="kgs", description="Knowledge Gathering System (KGS) CLI")
    parser.add_argument("--repo", default=DEFAULT_REPO_ROOT, help=f"Path to knowledge repository (default: {DEFAULT_REPO_ROOT})")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # init
    init_p = subparsers.add_parser("init", help="Initialize Dewey-style taxonomy & manifests on target repository drive")
    init_p.set_defaults(func=handle_init)

    # ingest (URL downloader & converter)
    ingest_p = subparsers.add_parser("ingest", help="Download, sanitize, convert, and store a web source onto target drive")
    ingest_p.add_argument("url", help="Source URL to download")
    ingest_p.add_argument("-c", "--category", default="07", help="Category code (01-07) or folder name")
    ingest_p.add_argument("-f", "--format", default="auto", choices=["auto", "md", "txt", "pdf", "epub"], help="Output format")
    ingest_p.add_argument("-t", "--title", default="", help="Custom title for the file")
    ingest_p.set_defaults(func=handle_ingest)

    # index & verify
    index_p = subparsers.add_parser("index", help="Rebuild INDEX.md, index.html, and MANIFEST.sha256")
    index_p.set_defaults(func=handle_index)

    verify_p = subparsers.add_parser("verify", help="Verify all repository files against MANIFEST.sha256")
    verify_p.set_defaults(func=handle_verify)

    # clip command
    clip_p = subparsers.add_parser("clip", help="Capture content from clipboard")
    clip_p.add_argument("--tag", "-t", help="Comma-separated tags")
    clip_p.add_argument("--note", "-n", help="Optional user note or citation")
    clip_p.set_defaults(func=handle_clip)

    # clipboard watch command
    clip_watch_p = subparsers.add_parser("clipboard-watch", help="Watch clipboard continuously")
    clip_watch_p.add_argument("--interval", "-i", type=float, default=1.0, help="Poll interval in seconds")
    clip_watch_p.set_defaults(func=handle_clip_watch)

    # sd subcommands
    sd_p = subparsers.add_parser("sd", help="SD Port & Removable media operations")
    sd_subs = sd_p.add_subparsers(dest="sd_action", required=True)

    sd_list = sd_subs.add_parser("list", help="List detected SD and removable block devices")
    sd_list.set_defaults(func=handle_sd_list)

    sd_import = sd_subs.add_parser("import", help="Import contents of an SD card")
    sd_import.add_argument("--device", "-d", default="auto", help="Device name/path (e.g. /dev/mmcblk0p1 or 'auto')")
    sd_import.add_argument("--unmount", action="store_true", default=True, help="Unmount automatically after import if mounted by kgs")
    sd_import.set_defaults(func=handle_sd_import)

    sd_eject = sd_subs.add_parser("eject", help="Safely sync and unmount an SD card")
    sd_eject.add_argument("device", help="Device path or mount path")
    sd_eject.set_defaults(func=handle_sd_eject)

    # status command
    status_p = subparsers.add_parser("status", help="Display system stats and repository summary")
    status_p.set_defaults(func=handle_status)

    # search command
    search_p = subparsers.add_parser("search", help="Search knowledge base metadata")
    search_p.add_argument("query", help="Keyword or search query")
    search_p.set_defaults(func=handle_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
