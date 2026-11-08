"""
Storage & Drive Safety Guard (src/storage_devices/drive_guard.py)
Provides safety checks, pre-flight capacity validations, atomic writes,
and integrity safeguards for removable portable storage and local vaults.
"""

import os
import sys
import shutil
import hashlib
from pathlib import Path
from typing import Tuple, Optional


class DriveSafetyGuard:
    """Safeguards filesystem operations against corruption, disk exhaustion, and partial writes."""

    @staticmethod
    def get_available_bytes(path: Path) -> int:
        """Returns available free disk space in bytes for given directory path."""
        target = path if path.exists() else path.parent
        while not target.exists() and target != target.parent:
            target = target.parent
        try:
            usage = shutil.disk_usage(str(target))
            return usage.free
        except Exception:
            return 0

    @classmethod
    def check_capacity_headroom(cls, target_dir: Path, required_bytes: int, safety_margin_mb: int = 100) -> Tuple[bool, str]:
        """
        Ensures target directory has enough free space plus a safety margin.
        Prevents filling an external drive or Mac volume to 100%.
        """
        margin_bytes = safety_margin_mb * 1024 * 1024
        total_needed = required_bytes + margin_bytes
        available = cls.get_available_bytes(target_dir)

        if available < total_needed:
            avail_mb = available / (1024 * 1024)
            need_mb = total_needed / (1024 * 1024)
            return False, f"Insufficient disk headroom on {target_dir}. Available: {avail_mb:.1f}MB, Needed: {need_mb:.1f}MB (incl. {safety_margin_mb}MB margin)."
        return True, "Headroom verified."

    @staticmethod
    def calculate_sha256(filepath: Path, blocksize: int = 65536) -> str:
        """Computes SHA-256 digest of a file with streaming chunks."""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            for block in iter(lambda: f.read(blocksize), b""):
                hasher.update(block)
        return hasher.hexdigest()

    @classmethod
    def atomic_copy_and_verify(
        cls,
        src_path: Path,
        dst_path: Path,
        expected_hash: Optional[str] = None,
        chunk_size: int = 4 * 1024 * 1024 # 4MB chunk size
    ) -> Tuple[bool, str, str]:
        """
        Copies src_path to dst_path atomically:
        1. Writes to temporary file dst_path.with_suffix('.tmp_<rand>')
        2. Computes and validates SHA-256 hash.
        3. Atomically replaces dst_path.
        Returns: (success: bool, final_sha256: str, error_msg: str)
        """
        if not src_path.exists():
            return False, "", f"Source file does not exist: {src_path}"

        src_size = src_path.stat().st_size
        dst_dir = dst_path.parent
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Capacity check
        ok, cap_err = cls.check_capacity_headroom(dst_dir, src_size)
        if not ok:
            return False, "", cap_err

        rand_suffix = os.urandom(4).hex()
        temp_dst = dst_dir / f"{dst_path.name}.tmp_{rand_suffix}"

        hasher = hashlib.sha256()
        try:
            with open(src_path, "rb") as fsrc, open(temp_dst, "wb") as fdst:
                while True:
                    buf = fsrc.read(chunk_size)
                    if not buf:
                        break
                    fdst.write(buf)
                    hasher.update(buf)
                fdst.flush()
                os.fsync(fdst.fileno())

            computed_hash = hasher.hexdigest()
            if expected_hash and computed_hash != expected_hash:
                if temp_dst.exists():
                    temp_dst.unlink()
                return False, "", f"Integrity check failed: expected {expected_hash}, computed {computed_hash}"

            # Preserve metadata timestamps
            shutil.copystat(src_path, temp_dst)
            # Atomic rename / replace
            temp_dst.replace(dst_path)
            return True, computed_hash, ""

        except Exception as e:
            if temp_dst.exists():
                try:
                    temp_dst.unlink()
                except OSError:
                    pass
            return False, "", f"Atomic copy failed: {e}"

    @classmethod
    def atomic_write_text(cls, dst_path: Path, content: str, encoding: str = "utf-8") -> bool:
        """Atomically writes text to file using temporary swap."""
        dst_dir = dst_path.parent
        dst_dir.mkdir(parents=True, exist_ok=True)
        rand_suffix = os.urandom(4).hex()
        temp_file = dst_dir / f"{dst_path.name}.tmp_{rand_suffix}"

        try:
            with open(temp_file, "w", encoding=encoding) as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            temp_file.replace(dst_path)
            return True
        except Exception:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            return False
