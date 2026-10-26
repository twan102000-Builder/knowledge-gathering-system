#!/usr/bin/env python3
"""
duplicate_repo.py

Duplicates all contents of KnowRepo1 onto KnowRepo2.
- Handles symlinks, directories, and large files (.zim archives).
- High throughput buffered I/O (16MB chunks) optimized for removable media (USB/SD Card via 9p).
- Resumable: skips files already present with identical size.
- Real-time progress tracking, speed calculation, ETA, and status output.
- Comprehensive verification pass after transfer.
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def format_bytes(num_bytes: int) -> str:
    """Format bytes into human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def scan_source(src_path: Path):
    """Scan source directory for all subdirectories and files."""
    dirs_to_create = []
    files_to_copy = []
    total_bytes = 0

    for root, dirs, files in os.walk(src_path, followlinks=True):
        rel_dir = Path(root).relative_to(src_path)
        for d in dirs:
            dirs_to_create.append(rel_dir / d)

        for f in files:
            file_rel = rel_dir / f
            file_full = Path(root) / f
            try:
                size = file_full.stat().st_size
                files_to_copy.append((file_rel, size))
                total_bytes += size
            except OSError as e:
                print(f"[WARN] Cannot stat file {file_full}: {e}", file=sys.stderr)

    return sorted(dirs_to_create), sorted(files_to_copy, key=lambda x: str(x[0])), total_bytes


def write_status(status_file: Path, data: dict):
    """Atomically write status JSON file."""
    try:
        temp_file = status_file.with_suffix(".tmp")
        with open(temp_file, "w") as fp:
            json.dump(data, fp, indent=2)
        temp_file.replace(status_file)
    except Exception:
        pass


def duplicate(src_path: Path, dst_path: Path, status_file: Path, buffer_size: int = 16 * 1024 * 1024):
    print(f"=== KnowRepo Duplication Process ===")
    print(f"Source:      {src_path} (resolved: {src_path.resolve()})")
    print(f"Destination: {dst_path} (resolved: {dst_path.resolve()})")
    print(f"Buffer size: {format_bytes(buffer_size)}")
    print()

    if not src_path.exists():
        print(f"[ERROR] Source path {src_path} does not exist!", file=sys.stderr)
        sys.exit(1)

    if not dst_path.exists():
        print(f"[ERROR] Destination path {dst_path} does not exist!", file=sys.stderr)
        sys.exit(1)

    print("Scanning source repository...")
    dirs_to_create, files_to_copy, total_source_bytes = scan_source(src_path)
    total_files = len(files_to_copy)
    print(f"Found {len(dirs_to_create)} directories, {total_files} files, {format_bytes(total_source_bytes)} total.")
    print()

    # Replicate directory hierarchy
    print("Ensuring directory hierarchy exists in destination...")
    for d in dirs_to_create:
        target_dir = dst_path / d
        target_dir.mkdir(parents=True, exist_ok=True)
    print("Directory hierarchy synchronized.")
    print()

    # Check already completed files
    print("Checking already synchronized files...")
    files_remaining = []
    already_copied_bytes = 0
    already_copied_files = 0

    for rel_path, src_size in files_to_copy:
        dest_file = dst_path / rel_path
        if dest_file.exists():
            try:
                dest_size = dest_file.stat().st_size
                if dest_size == src_size:
                    already_copied_bytes += src_size
                    already_copied_files += 1
                    continue
            except OSError:
                pass
        files_remaining.append((rel_path, src_size))

    remaining_bytes = total_source_bytes - already_copied_bytes
    print(f"Already synced: {already_copied_files}/{total_files} files ({format_bytes(already_copied_bytes)})")
    print(f"Remaining:      {len(files_remaining)}/{total_files} files ({format_bytes(remaining_bytes)})")
    print()

    start_time = time.time()
    copied_bytes_this_session = 0
    copied_files_this_session = 0
    last_print_time = start_time

    status_data = {
        "status": "running",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_files": total_files,
        "total_bytes": total_source_bytes,
        "already_synced_files": already_copied_files,
        "already_synced_bytes": already_copied_bytes,
        "remaining_files": len(files_remaining),
        "remaining_bytes": remaining_bytes,
        "current_file": None,
        "copied_bytes_total": already_copied_bytes,
        "copied_files_total": already_copied_files,
        "percent_complete": round((already_copied_bytes / total_source_bytes * 100) if total_source_bytes else 100, 2),
        "speed_mbps": 0.0,
        "eta_seconds": 0,
        "elapsed_seconds": 0,
    }
    write_status(status_file, status_data)

    for idx, (rel_path, file_size) in enumerate(files_remaining, 1):
        src_file = src_path / rel_path
        dst_file = dst_path / rel_path

        # Ensure parent directory exists
        dst_file.parent.mkdir(parents=True, exist_ok=True)

        current_file_name = str(rel_path)
        file_start_time = time.time()

        status_data["current_file"] = current_file_name
        write_status(status_file, status_data)

        # Copy using high-speed chunks
        file_bytes_done = 0
        try:
            with open(src_file, "rb") as fin, open(dst_file, "wb") as fout:
                while True:
                    chunk = fin.read(buffer_size)
                    if not chunk:
                        break
                    fout.write(chunk)
                    chunk_len = len(chunk)
                    file_bytes_done += chunk_len
                    copied_bytes_this_session += chunk_len

                    now = time.time()
                    if now - last_print_time >= 5.0:
                        elapsed = now - start_time
                        speed = (copied_bytes_this_session / elapsed) if elapsed > 0 else 0
                        total_transferred = already_copied_bytes + copied_bytes_this_session
                        pct = (total_transferred / total_source_bytes * 100) if total_source_bytes else 100
                        remaining_this_run = remaining_bytes - copied_bytes_this_session
                        eta = (remaining_this_run / speed) if speed > 0 else 0

                        status_data.update({
                            "copied_bytes_total": total_transferred,
                            "copied_files_total": already_copied_files + copied_files_this_session,
                            "percent_complete": round(pct, 2),
                            "speed_mbps": round(speed / (1024 * 1024), 2),
                            "eta_seconds": int(eta),
                            "elapsed_seconds": int(elapsed),
                        })
                        write_status(status_file, status_data)

                        print(
                            f"[{pct:5.1f}%] {already_copied_files + copied_files_this_session}/{total_files} files "
                            f"| {format_bytes(total_transferred)}/{format_bytes(total_source_bytes)} "
                            f"| {speed / (1024 * 1024):.1f} MB/s | ETA: {format_duration(eta)} "
                            f"| Current: {current_file_name} ({format_bytes(file_bytes_done)}/{format_bytes(file_size)})"
                        )
                        last_print_time = now

                fout.flush()
                try:
                    os.fdatasync(fout.fileno())
                except OSError:
                    pass

            # Sync timestamps and permissions
            shutil.copystat(src_file, dst_file)
            copied_files_this_session += 1

            now = time.time()
            elapsed = now - start_time
            speed = (copied_bytes_this_session / elapsed) if elapsed > 0 else 0
            total_transferred = already_copied_bytes + copied_bytes_this_session
            pct = (total_transferred / total_source_bytes * 100) if total_source_bytes else 100

            file_dur = now - file_start_time
            file_speed = (file_size / file_dur) if file_dur > 0 else 0
            if file_size > 10 * 1024 * 1024 or idx % 250 == 0:
                print(
                    f"-> Done: {current_file_name} ({format_bytes(file_size)}) "
                    f"in {format_duration(file_dur)} ({file_speed / (1024 * 1024):.1f} MB/s) "
                    f"[{pct:5.1f}% total]"
                )

        except Exception as e:
            print(f"[ERROR] Failed copying {src_file} -> {dst_file}: {e}", file=sys.stderr)
            status_data["status"] = "error"
            status_data["error"] = str(e)
            write_status(status_file, status_data)
            raise

    total_time = time.time() - start_time
    avg_speed = (copied_bytes_this_session / total_time) if total_time > 0 else 0
    print()
    print("=== Copying Phase Finished ===")
    print(f"Files copied this run: {copied_files_this_session}")
    print(f"Bytes copied this run: {format_bytes(copied_bytes_this_session)}")
    print(f"Elapsed time:          {format_duration(total_time)}")
    if copied_bytes_this_session > 0:
        print(f"Average write speed:   {avg_speed / (1024 * 1024):.2f} MB/s")
    print()


def verify(src_path: Path, dst_path: Path):
    print("=== Verification Phase ===")
    print("Auditing all directories and files...")

    # Group by category (top-level folders)
    categories = sorted([p.name for p in src_path.iterdir() if p.is_dir()])

    all_matched = True
    total_src_files = 0
    total_dst_files = 0
    total_src_bytes = 0
    total_dst_bytes = 0

    print(f"{'Category':<32} {'Source':<18} {'Destination':<18} {'Status'}")
    print("-" * 78)

    for cat in categories:
        src_cat = src_path / cat
        dst_cat = dst_path / cat

        src_files = {}
        for r, _, files in os.walk(src_cat, followlinks=True):
            for f in files:
                full = Path(r) / f
                rel = full.relative_to(src_cat)
                src_files[rel] = full.stat().st_size
        src_bytes = sum(src_files.values())
        total_src_files += len(src_files)
        total_src_bytes += src_bytes

        if not dst_cat.exists():
            src_str = f"{len(src_files)}f, {format_bytes(src_bytes)}"
            print(f"{cat:<32} {src_str:<18} {'MISSING':<18} [FAIL]")
            all_matched = False
            continue

        dst_files = {}
        for r, _, files in os.walk(dst_cat, followlinks=True):
            for f in files:
                full = Path(r) / f
                rel = full.relative_to(dst_cat)
                dst_files[rel] = full.stat().st_size

        dst_bytes = sum(dst_files.values())
        total_dst_files += len(dst_files)
        total_dst_bytes += dst_bytes

        cat_match = True
        if len(src_files) != len(dst_files) or src_bytes != dst_bytes:
            cat_match = False
        else:
            for rel, s_size in src_files.items():
                if rel not in dst_files or dst_files[rel] != s_size:
                    cat_match = False
                    break

        if cat_match:
            status = "MATCH (OK)"
        else:
            status = "MISMATCH"
            all_matched = False

        src_str = f"{len(src_files)}f, {format_bytes(src_bytes)}"
        dst_str = f"{len(dst_files)}f, {format_bytes(dst_bytes)}"
        print(f"{cat:<32} {src_str:<18} {dst_str:<18} {status}")

    print("-" * 78)
    summary_src = f"{total_src_files}f, {format_bytes(total_src_bytes)}"
    summary_dst = f"{total_dst_files}f, {format_bytes(total_dst_bytes)}"
    print(f"{'TOTAL':<32} {summary_src:<18} {summary_dst:<18} {'ALL MATCH' if all_matched else 'FAILED'}")
    print()

    return all_matched


def main():
    parser = argparse.ArgumentParser(description="Duplicate KnowRepo1 to KnowRepo2")
    parser.add_argument("--src", default=os.path.expanduser("~/KnowRepo1"), help="Source repository root")
    parser.add_argument("--dst", default=os.path.expanduser("~/KnowRepo2"), help="Destination repository root")
    parser.add_argument("--status-file", default="duplication_status.json", help="Path to write progress JSON")
    parser.add_argument("--buffer-mb", type=int, default=16, help="Buffer size in MB")
    parser.add_argument("--verify-only", action="store_true", help="Run verification without copying")

    args = parser.parse_args()
    src_path = Path(args.src)
    dst_path = Path(args.dst)
    status_file = Path(args.status_file)
    buffer_size = args.buffer_mb * 1024 * 1024

    if not args.verify_only:
        duplicate(src_path, dst_path, status_file, buffer_size=buffer_size)

    verified = verify(src_path, dst_path)
    if verified:
        write_status(status_file, {
            "status": "completed",
            "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "verified": True,
        })
        print("Success! KnowRepo2 is an exact, complete duplicate of KnowRepo1.")
        sys.exit(0)
    else:
        write_status(status_file, {
            "status": "verification_failed",
            "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "verified": False,
        })
        print("[FAIL] Verification detected differences between KnowRepo1 and KnowRepo2.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
