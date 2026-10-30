#!/usr/bin/env python3
"""
Sequential batch downloader and catalog updater for Kiwix ZIM archives.
Monitors disk space before each download and updates repo_manager index after each completion.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("KGS_REPO_ROOT", Path.home() / "KnowRepo1")).expanduser()
MANAGER_PY = BASE_DIR / "repo_manager.py"

DOWNLOAD_QUEUE = [
    # 1. TruePrepper (Survival & Preparedness)
    (
        "TruePrepper (All Articles & Guides)",
        "02_Survival_and_Food",
        "https://download.kiwix.org/zim/other/trueprepper.com_en_all_2026-05.zim",
        "trueprepper.com_en_all_2026-05.zim",
        1.36,  # GB
    ),
    # 2. FreeCodeCamp (Full offline programming curricula)
    (
        "FreeCodeCamp (Full Courses)",
        "05_Computing_and_Comms",
        "https://download.kiwix.org/zim/freecodecamp/freecodecamp_en_all_2026-08.zim",
        "freecodecamp_en_all_2026-08.zim",
        0.008,  # GB (~7.9 MB)
    ),
    # 3. Gutenberg Class K (Law & Civics)
    (
        "Project Gutenberg Class K (Law)",
        "06_History_Law_and_Civics",
        "https://download.kiwix.org/zim/gutenberg/gutenberg_en_lcc-k_2026-03.zim",
        "gutenberg_en_lcc-k_2026-03.zim",
        0.23,  # GB (~235 MB)
    ),
    # 4. TED Talks - WorkLife
    (
        "TED Talks - WorkLife",
        "06_History_Law_and_Civics",
        "https://download.kiwix.org/zim/ted/ted_mul_worklife_2026-09.zim",
        "ted_mul_worklife_2026-09.zim",
        0.35,  # GB (~354 MB)
    ),
    # 5. TED Talks - Competition
    (
        "TED Talks - Competition",
        "06_History_Law_and_Civics",
        "https://download.kiwix.org/zim/ted/ted_mul_competition_2026-09.zim",
        "ted_mul_competition_2026-09.zim",
        0.11,  # GB (~114 MB)
    ),
    # 6. Gutenberg Class L (Education)
    (
        "Project Gutenberg Class L (Education)",
        "04_Science_and_Reference",
        "https://download.kiwix.org/zim/gutenberg/gutenberg_en_lcc-l_2026-03.zim",
        "gutenberg_en_lcc-l_2026-03.zim",
        0.59,  # GB (~600 MB)
    ),
    # 7. Gutenberg Class T (Technology & Engineering)
    (
        "Project Gutenberg Class T (Technology)",
        "03_Engineering_and_Repair",
        "https://download.kiwix.org/zim/gutenberg/gutenberg_en_lcc-t_2026-03.zim",
        "gutenberg_en_lcc-t_2026-03.zim",
        12.25,  # GB
    ),
    # 8. Gutenberg Class Q (Science)
    (
        "Project Gutenberg Class Q (Science)",
        "04_Science_and_Reference",
        "https://download.kiwix.org/zim/gutenberg/gutenberg_en_lcc-q_2026-03.zim",
        "gutenberg_en_lcc-q_2026-03.zim",
        16.51,  # GB
    ),
]


def check_disk_space_gb() -> float:
    stat = shutil.disk_usage(REPO_ROOT)
    return stat.free / (1024 ** 3)


def main():
    print("=" * 70)
    print("Starting Automated Knowledge Repository Batch Downloader")
    print(f"Target repository: {REPO_ROOT}")
    print("=" * 70)

    for idx, (title, category, url, filename, est_gb) in enumerate(DOWNLOAD_QUEUE, 1):
        target_dir = REPO_ROOT / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / filename

        free_gb = check_disk_space_gb()
        print(f"\n[{idx}/{len(DOWNLOAD_QUEUE)}] Processing: {title}")
        print(f"  Category: {category}")
        print(f"  Target File: {target_file}")
        print(f"  Estimated Size: {est_gb:.2f} GB | Current Drive Free Space: {free_gb:.2f} GB")

        if free_gb < (est_gb + 2.0):
            print(f"  [ERROR] Insufficient disk space! Required ~{est_gb + 2.0:.1f} GB, available {free_gb:.2f} GB.")
            print("  Halting queue to prevent drive fill.")
            sys.exit(1)

        # Download with curl resumable (-C -)
        cmd = [
            "curl",
            "-L",
            "-C", "-",
            "--retry", "5",
            "--retry-delay", "3",
            "-o", str(target_file),
            url,
        ]

        print(f"  [+] Starting transfer...")
        start_time = time.time()
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print(f"  [ERROR] Download failed with code {res.returncode}")
            sys.exit(res.returncode)

        elapsed = time.time() - start_time
        actual_size_gb = target_file.stat().st_size / (1024 ** 3)
        print(f"  [+] Download completed in {elapsed/60:.1f} min ({actual_size_gb:.2f} GB downloaded).")

        # Run index after each completed file
        print(f"  [+] Updating repository catalog & SHA-256 manifest...")
        idx_res = subprocess.run([sys.executable, str(MANAGER_PY), "--repo", str(REPO_ROOT), "index"])
        if idx_res.returncode == 0:
            print(f"  [+] Catalog & SHA-256 updated.")
        else:
            print(f"  [!] Indexing warning: exit code {idx_res.returncode}")

        free_after = check_disk_space_gb()
        print(f"  [+] Remaining Free Space on Target Drive: {free_after:.2f} GB")

    print("\n" + "=" * 70)
    print("ALL QUEUED ARCHIVES SUCCESSFULLY DOWNLOADED AND CATALOGED!")
    print(f"Final Free Space: {check_disk_space_gb():.2f} GB")
    print("=" * 70)


if __name__ == "__main__":
    main()
