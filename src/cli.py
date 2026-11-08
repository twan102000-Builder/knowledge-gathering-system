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
from src.config import load_kgs_config
from src.store.db import MetadataDB
from src.store.vault import VaultManager
from src.clipboard.handlers import ClipboardService
from src.storage_devices.detector import SDDeviceDetector
from src.storage_devices.mounter import SafeDeviceMounter
from src.storage_devices.sync import SDCardSyncPipeline
from src.storage_devices.mac_disk import MacDiskManager
from src.storage_devices.device_profile import DeviceProfileManager
from src.sync.dual_tier_sync import DualTierSyncEngine

CONFIG = load_kgs_config()
DEFAULT_REPO_ROOT = str(DeviceProfileManager.resolve_preferred_local_repo_path(CONFIG))


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
        print("No SD cards or removable storage detected.")
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
        repo_manager.cmd_index(vault.root_path)
    finally:
        if was_auto_mounted and args.unmount:
            print("Cleaning up mount point...")
            mounter.unmount(mount_point)


def handle_sd_eject(args):
    mounter = SafeDeviceMounter()
    ok, msg = mounter.eject(args.device)
    if ok:
        print(f"Device {args.device} safely flushed and unmounted/ejected.")
    else:
        print(f"Eject failed: {msg}")


def handle_ingest(args):
    repo_root = Path(os.path.expanduser(args.repo)).resolve()
    repo_manager.cmd_ingest(repo_root, args.url, args.category, args.format, args.title)

    db, vault = init_services(args.repo)
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
                    category=f.get("category", "document"),
                    source_path=args.url,
                    tags=[f["category"], f.get("format", "").lower()],
                    metadata={"size_bytes": f["size_bytes"], "source_url": args.url, "format": f.get("format")}
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


# =========================================================================
# Mac Device & Storage Management Handlers
# =========================================================================

def handle_mac_list(args):
    if not MacDiskManager.is_macos():
        print("[!] Native Mac disk management is only available on macOS.")
        return

    print("================================================================================")
    print("                    macOS Physical Disks & Partitions Layout")
    print("================================================================================")
    drives = MacDiskManager.list_physical_drives_with_partitions()
    if not drives:
        print("No disks detected via diskutil.")
        return

    host_ext = MacDiskManager.get_host_extension_drive()
    portable_know = MacDiskManager.find_portable_knowrepo_partition()

    for d in drives:
        dtype = d["drive_type"]
        size_h = DualTierSyncEngine._format_bytes(d["total_size"])
        dtype_badge = {
            "internal": "[INTERNAL MAC STORAGE]",
            "host_extension": "[MAC HOST HARDWARE EXTENSION: 990_PRO]",
            "portable_removable": "[PORTABLE REMOVABLE DRIVE]"
        }.get(dtype, "[EXTERNAL STORAGE]")

        print(f"\n{dtype_badge} Physical Disk {d['device_node']} ({size_h}, {d['bus_protocol']}):")
        if not d["partitions"]:
            print("   (No volumes or raw partition)")
            continue

        for p in d["partitions"]:
            p_size = DualTierSyncEngine._format_bytes(p.get("size", 0))
            mount = f" -> {p['mount_point']}" if p.get("mount_point") else " (Unmounted)"
            tags = [p.get("filesystem", "")]
            if p.get("is_encrypted"):
                tags.append("FileVault")
            if p.get("is_host_extension"):
                tags.append("Mac Mini Extension")
            if p.get("is_knowrepo"):
                tags.append("★ KNOWREPO VAULT")

            tag_str = f" [{', '.join(t for t in tags if t)}]"
            print(f"   • {p['device_node']}: '{p['partition_label']}' ({p_size}){mount}{tag_str}")

    print("\n--------------------------------------------------------------------------------")
    if host_ext:
        print(f"[+] Mac Host Extension : {host_ext['device_node']} ('{host_ext['volume_name']}') mounted at {host_ext['mount_point']} (Extension of Mac mini)")
    if portable_know:
        part = portable_know["partition"]
        print(f"[+] Portable KnowRepo  : {part['device_node']} ('{part['partition_label']}') on {portable_know['parent_disk']} ({portable_know['bus_protocol']})")
    else:
        print("[*] Portable 1TB Drive : Not connected (or waiting for connection). Host storage 990_PRO is preserved.")
    print("================================================================================")


def handle_mac_info(args):
    info = MacDiskManager.get_disk_info(args.device)
    if not info:
        print(f"Could not retrieve diskutil info for {args.device}")
        return
    print(f"=== Disk Info: {args.device} ===")
    for k in ["VolumeName", "DeviceNode", "MountPoint", "FilesystemType", "TotalSize", "APFSContainerFree", "Encryption", "BusProtocol", "Ejectable"]:
        if k in info:
            print(f" {k:22}: {info[k]}")


def handle_mac_mount(args):
    ok, msg = MacDiskManager.mount_volume(args.device, read_only=args.readonly)
    if ok:
        print(f"[+] Mounted {args.device} at: {msg} (read_only={args.readonly})")
    else:
        print(f"[!] Mount failed: {msg}")


def handle_mac_unmount(args):
    ok, msg = MacDiskManager.unmount_volume(args.device, force=args.force)
    if ok:
        print(f"[+] Safely unmounted {args.device}")
    else:
        print(f"[!] Unmount failed: {msg}")


def handle_mac_eject(args):
    ok, msg = MacDiskManager.eject_disk(args.device)
    if ok:
        print(f"[+] Safely flushed buffers and ejected {args.device}")
    else:
        print(f"[!] Eject failed: {msg}")


def handle_mac_eject_portable(args):
    port_drives = MacDiskManager.list_portable_removable_drives()
    if not port_drives:
        print("[!] No portable removable drive detected to eject. Semi-permanent 990_PRO is preserved.")
        return
    for d in port_drives:
        print(f"[*] Flushing write buffers and unmounting all partitions on {d['device_node']}...")
        ok, msg = MacDiskManager.safe_eject_multi_partition_drive(d["device_identifier"])
        if ok:
            print(f"[+] Safely ejected portable drive {d['device_node']} with all partitions.")
        else:
            print(f"[!] Eject failed for {d['device_node']}: {msg}")


def handle_mac_clean(args):
    count = MacDiskManager.clean_macos_artifacts(args.path)
    print(f"[+] Cleaned {count} macOS artifact file(s) (.DS_Store / ._*) from {args.path}")


# =========================================================================
# Dual-Tier Sync Handlers (Local Repo <--> 1TB Removable Main Archive)
# =========================================================================

def _get_sync_engine(args) -> DualTierSyncEngine:
    local_p = getattr(args, "local_repo", None)
    if not local_p or local_p == "auto":
        local_p = getattr(args, "repo", None)
        if local_p in (DEFAULT_REPO_ROOT, "auto", "~/KnowRepo_Local", "~/KnowRepo1"):
            local_p = None
    archive_p = getattr(args, "archive_repo", None)
    return DualTierSyncEngine(local_path=local_p, archive_path=archive_p)


def handle_tier_status(args):
    engine = _get_sync_engine(args)
    status = engine.get_tier_status()
    host = status.get("host_device", {})
    loc = status["local_repo"]
    port = status["portable_drive"]
    arc = status["archive_repo"]
    delta = status["sync_delta"]

    print("================================================================================")
    print("         Knowledge Gathering System — Cross-Device Architecture")
    print("================================================================================")
    print(f" [HOST DEVICE ENVIRONMENT]:")
    print(f"   • Device Model  : {host.get('display_name', 'Mac')} ('{host.get('computer_name')}')")
    print(f"   • Main Storage  : {loc.get('storage_description')}")
    print()
    print(f" [TIER 1] On-Device Local Knowledge Repo (Host Main Storage):")
    print(f"   • Path          : {loc['path']} ({'Active' if loc['exists'] else 'Not Initialized'})")
    print(f"   • Files / Size  : {loc['total_files']} files ({loc['total_human']})")
    print(f"   • Free Space    : {loc['free_human']}")
    print(f"   • Archived Stubs: {loc['active_stubs']} offloaded stub(s)")
    print()
    print(f" [TIER 2] Portable Removable 1TB Drive (Universal Main Know Repo):")
    if port.get("is_connected"):
        kpart = port.get("knowrepo_partition", {})
        print(f"   • Physical Drive: /dev/{port.get('parent_disk')} ({port.get('parent_size_human')}, {port.get('bus_protocol')})")
        print(f"   • Drive Status  : [CONNECTED & MOUNTED]")
        print(f"   • KnowRepo Vault: '{kpart.get('partition_label')}' ({kpart.get('device_node')}) -> {kpart.get('mount_point')}")
        print(f"   • Vault Files   : {port.get('total_files')} files ({port.get('total_human')}, Free: {kpart.get('free_human')})")
        if port.get("sibling_partitions"):
            print("   • Other Sibling Partitions on Portable Drive (Preserved):")
            for sib in port["sibling_partitions"]:
                sib_mnt = f" -> {sib['mount_point']}" if sib.get("mount_point") else " (Unmounted)"
                print(f"     - {sib['device_identifier']}: '{sib['partition_label']}' ({sib['size_human']}, {sib['filesystem']}){sib_mnt}")
    else:
        print(f"   • Drive Status  : [DISCONNECTED / WAITING FOR CONNECTION]")
        print(f"   • Note          : {port.get('message')}")
        print(f"   • Single Vault  : Only one partition on the 1TB drive is targeted for KnowRepo.")
        print(f"   • Active Archive: {arc.get('path')}")
    print()
    print(f" [SYNC DELTA]:")
    print(f"   • Pending Push  : {delta['pending_push_count']} file(s) ({DualTierSyncEngine._format_bytes(delta['pending_push_bytes'])}) awaiting sync to portable 1TB drive")
    print(f"   • Pending Pull  : {delta['pending_pull_count']} file(s) ({DualTierSyncEngine._format_bytes(delta['pending_pull_bytes'])}) in archive not on this device")
    print("================================================================================")


def handle_tier_init(args):
    engine = _get_sync_engine(args)
    print(f"[*] Initializing local repo at: {engine.local_root}")
    engine.init_local_repo()
    print("[+] Local repository initialized with Dewey taxonomy.")

    arc_root = engine.resolve_archive_root()
    if arc_root and arc_root.parent.exists():
        print(f"[*] Initializing 1TB archive partition at: {arc_root}")
        engine.init_archive_repo(arc_root)
        print("[+] 1TB Portable Removable Main Archive initialized with Dewey taxonomy.")
    else:
        print("[!] 1TB portable removable drive partition not currently mounted. Archive init deferred until drive connection.")


def handle_tier_push(args):
    engine = _get_sync_engine(args)
    threshold = (args.threshold_mb or 25) * 1024 * 1024
    print(f"[*] Starting push from local repo ({engine.local_root}) -> 1TB archive...")
    if args.dry_run:
        print("    [DRY RUN MODE ENABLED]")
    if args.offload:
        print(f"    [STORAGE CONSERVATION: Offloading files >= {args.threshold_mb}MB to stubs after archive verify]")

    res = engine.push_to_archive(dry_run=args.dry_run, offload=args.offload, offload_threshold_bytes=threshold)
    if not res.get("success"):
        print(f"[!] Push failed: {res.get('error')}")
        return

    print("--- Push Results ---")
    print(f"Pushed files    : {res['pushed_files']} ({res['pushed_human']})")
    print(f"Offloaded stubs : {res['offloaded_stubs']}")
    print(f"Already synced  : {res['skipped_already_present']}")
    if res['errors']:
        print(f"Errors ({len(res['errors'])}):")
        for e in res['errors']:
            print(f" - {e['file']}: {e['error']}")
    else:
        print("[+] Push completed successfully with SHA-256 verification and clean manifests.")


def handle_tier_pull(args):
    engine = _get_sync_engine(args)
    cats = [c.strip() for c in args.categories.split(",")] if args.categories else None
    print(f"[*] Starting pull from 1TB archive -> local repo ({engine.local_root})...")
    res = engine.pull_from_archive(categories=cats, dry_run=args.dry_run)
    if not res.get("success"):
        print(f"[!] Pull failed: {res.get('error')}")
        return

    print("--- Pull Results ---")
    print(f"Pulled files    : {res['pulled_files']} ({res['pulled_human']})")
    print(f"Already local   : {res['skipped_already_present']}")
    if res['errors']:
        print(f"Errors ({len(res['errors'])}):")
        for e in res['errors']:
            print(f" - {e['file']}: {e['error']}")
    else:
        print("[+] Pull completed successfully.")


def handle_tier_hydrate(args):
    engine = _get_sync_engine(args)
    ok, msg = engine.hydrate_stub(args.stub_file)
    if ok:
        print(f"[+] {msg}")
    else:
        print(f"[!] Rehydration failed: {msg}")


def handle_tier_verify(args):
    engine = _get_sync_engine(args)
    print(f"=== Verifying Local Knowledge Repo ({engine.local_root}) ===")
    if engine.local_root.exists():
        repo_manager.cmd_verify(engine.local_root)
    else:
        print("[!] Local repository does not exist.")

    arc_root = engine.resolve_archive_root()
    print(f"\n=== Verifying 1TB Portable Removable Main Archive ({arc_root}) ===")
    if arc_root and arc_root.exists():
        repo_manager.cmd_verify(arc_root)
    else:
        print("[!] 1TB archive drive is not currently connected/mounted.")


def main():
    parser = argparse.ArgumentParser(prog="kgs", description="Knowledge Gathering System (KGS) CLI")
    parser.add_argument("--repo", default=DEFAULT_REPO_ROOT, help="Path to knowledge repository (defaults to host-preferred local repo, e.g. /Volumes/990_PRO/KnowRepo_Local or ~/KnowRepo_Local)")
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
    sd_import.add_argument("--unmount", action=argparse.BooleanOptionalAction, default=True, help="Unmount automatically after import if mounted by kgs")
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

    # mac command (macOS Device & Volume Management)
    mac_p = subparsers.add_parser("mac", help="macOS Native Device & Storage Management (APFS, 1TB drive, diskutil)")
    mac_subs = mac_p.add_subparsers(dest="mac_action", required=True)

    mac_list_p = mac_subs.add_parser("list", help="List all Mac disks, partitions, APFS containers, and 1TB drives")
    mac_list_p.set_defaults(func=handle_mac_list)

    mac_info_p = mac_subs.add_parser("info", help="Display detailed diskutil info for a disk/volume")
    mac_info_p.add_argument("device", help="Device identifier or node (e.g. disk5s1 or /dev/disk5s1)")
    mac_info_p.set_defaults(func=handle_mac_info)

    mac_mount_p = mac_subs.add_parser("mount", help="Safely mount a disk or APFS volume via diskutil")
    mac_mount_p.add_argument("device", help="Device identifier (e.g. disk5s1)")
    mac_mount_p.add_argument("--readonly", "-r", action="store_true", help="Mount read-only")
    mac_mount_p.set_defaults(func=handle_mac_mount)

    mac_unmount_p = mac_subs.add_parser("unmount", help="Safely flush buffers and unmount a volume")
    mac_unmount_p.add_argument("device", help="Device identifier or mount point")
    mac_unmount_p.add_argument("--force", "-f", action="store_true", help="Force unmount")
    mac_unmount_p.set_defaults(func=handle_mac_unmount)

    mac_eject_p = mac_subs.add_parser("eject", help="Safely flush buffers and eject an entire disk enclosure")
    mac_eject_p.add_argument("device", help="Device identifier (e.g. disk4 or disk5)")
    mac_eject_p.set_defaults(func=handle_mac_eject)

    mac_eject_port_p = mac_subs.add_parser("eject-portable", help="Safely flush and eject portable removable drive with all partitions without affecting 990_PRO")
    mac_eject_port_p.set_defaults(func=handle_mac_eject_portable)

    mac_clean_p = mac_subs.add_parser("clean", help="Clean .DS_Store and ._* metadata artifacts from repository")
    mac_clean_p.add_argument("path", help="Target directory path to clean")
    mac_clean_p.set_defaults(func=handle_mac_clean)

    # tier command (Dual-Tier On-Device Local Repo <--> 1TB Portable Removable Main Archive)
    tier_p = subparsers.add_parser("tier", help="Dual-Tier Storage Sync (On-Device Local Mac Repo <--> 1TB Portable Archive)")
    tier_p.add_argument("--local-repo", help="Path to on-device local repository (default: ~/KnowRepo_Local)")
    tier_p.add_argument("--archive-repo", help="Path to 1TB portable removable main archive")
    tier_subs = tier_p.add_subparsers(dest="tier_action", required=True)

    tier_status_p = tier_subs.add_parser("status", help="Show status and sync deltas across both tiers")
    tier_status_p.set_defaults(func=handle_tier_status)

    tier_init_p = tier_subs.add_parser("init", help="Initialize Dewey taxonomy on both local and 1TB archive tiers")
    tier_init_p.set_defaults(func=handle_tier_init)

    tier_push_p = tier_subs.add_parser("push", help="Push local new documents, snippets, and imports to 1TB archive")
    tier_push_p.add_argument("--dry-run", action="store_true", help="Simulate push without modifying archive")
    tier_push_p.add_argument("--offload", action="store_true", help="Conserve Mac internal storage by replacing large verified files with stubs")
    tier_push_p.add_argument("--threshold-mb", type=int, default=25, help="Size threshold in MB for offloading (default: 25MB)")
    tier_push_p.set_defaults(func=handle_tier_push)

    tier_pull_p = tier_subs.add_parser("pull", help="Pull archive catalog and documents down to local Mac repository")
    tier_pull_p.add_argument("--categories", "-c", help="Comma-separated categories to pull (e.g. '01,05')")
    tier_pull_p.add_argument("--dry-run", action="store_true", help="Simulate pull")
    tier_pull_p.set_defaults(func=handle_tier_pull)

    tier_hydrate_p = tier_subs.add_parser("hydrate", help="Restore an offloaded stub file back to full content from 1TB archive")
    tier_hydrate_p.add_argument("stub_file", help="Path to .stub.json file to rehydrate")
    tier_hydrate_p.set_defaults(func=handle_tier_hydrate)

    tier_verify_p = tier_subs.add_parser("verify", help="Verify SHA-256 integrity manifests across both tiers")
    tier_verify_p.set_defaults(func=handle_tier_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
