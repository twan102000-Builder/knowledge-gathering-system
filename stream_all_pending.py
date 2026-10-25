#!/usr/bin/env python3
"""
Continuous streaming ingest for all Kiwix ZIM archives.
Monitors free space on ~/KnowRepo1 before every download.
Tracks progress in batch_progress.json and re-indexes the repository continuously.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(os.path.expanduser("~/KnowRepo1"))
MANAGER_PY = Path("/home/twan102000/Knowledge Gathering for Local Repository/repo_manager.py")
QUEUE_FILE = Path("/home/twan102000/Knowledge Gathering for Local Repository/pending_batch_queue.json")
PROGRESS_FILE = Path("/home/twan102000/Knowledge Gathering for Local Repository/batch_progress.json")


def check_disk_space_gb() -> float:
    stat = shutil.disk_usage(REPO_ROOT)
    return stat.free / (1024 ** 3)


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_progress(p):
    PROGRESS_FILE.write_text(json.dumps(p, indent=2))


def main():
    if not QUEUE_FILE.exists():
        print("Queue file not found!")
        sys.exit(1)

    items = json.loads(QUEUE_FILE.read_text())
    progress = load_progress()

    print(f"Loaded {len(items)} items from queue.")

    for idx, item in enumerate(items, 1):
        item_id = item["id"]
        filename = item["filename"]
        category = item["category"]
        url = item["url"]

        target_dir = REPO_ROOT / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / filename

        # Skip if already completed and file exists
        if progress.get(item_id, {}).get("status") == "completed" and target_file.exists():
            continue

        free_gb = check_disk_space_gb()
        if free_gb < 5.0:
            print(f"[ALERT] Free disk space is low ({free_gb:.2f} GB). Pausing queue to prevent drive fill.")
            break

        print(f"\n[{idx}/{len(items)}] Ingesting {item_id} -> {category}/")
        print(f"  Target Drive Free Space: {free_gb:.2f} GB")

        cmd = [
            "curl",
            "-sL",
            "-C", "-",
            "--retry", "3",
            "--retry-delay", "2",
            "-o", str(target_file),
            url,
        ]

        start = time.time()
        res = subprocess.run(cmd)

        if res.returncode == 0 and target_file.exists() and target_file.stat().st_size > 2048:
            elapsed = time.time() - start
            sz_mb = target_file.stat().st_size / (1024 * 1024)
            print(f"  [+] Complete ({sz_mb:.1f} MB in {elapsed:.1f}s)")
            progress[item_id] = {
                "status": "completed",
                "size_mb": round(sz_mb, 2),
                "category": category,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_progress(progress)

            # Rebuild index periodically
            if idx % 10 == 0 or sz_mb > 250:
                print("  [+] Syncing repository catalog & SHA-256 manifest...")
                subprocess.run(
                    [sys.executable, str(MANAGER_PY), "--repo", str(REPO_ROOT), "index"],
                    stdout=subprocess.DEVNULL,
                )
        else:
            print(f"  [!] Failed or invalid response for {url}. Skipping...")
            if target_file.exists() and target_file.stat().st_size <= 2048:
                target_file.unlink()
            progress[item_id] = {
                "status": "failed",
                "url": url,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_progress(progress)

    print("\n[+] Ingestion cycle finished. Running final catalog sync...")
    subprocess.run([sys.executable, str(MANAGER_PY), "--repo", str(REPO_ROOT), "index"])
    print(f"[+] Final available drive space: {check_disk_space_gb():.2f} GB")


if __name__ == "__main__":
    main()
