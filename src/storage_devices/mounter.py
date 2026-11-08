import subprocess
import os
import sys
import shutil
from typing import Optional, Tuple
from .mac_disk import MacDiskManager

class SafeDeviceMounter:
    def __init__(self, base_mount_dir: str = "/tmp/kgs_mounts"):
        self.base_mount_dir = base_mount_dir
        os.makedirs(self.base_mount_dir, exist_ok=True)
        self.is_macos = sys.platform == "darwin" and shutil.which("diskutil") is not None
        self.has_udisksctl = shutil.which("udisksctl") is not None

    def mount_read_only(self, device_path: str) -> Tuple[bool, str]:
        """
        Safely mounts device read-only.
        Returns (success: bool, mount_path_or_error: str)
        """
        # macOS native mounting via diskutil
        if self.is_macos:
            return MacDiskManager.mount_volume(device_path, read_only=True)

        # Linux user-space non-root mount via udisksctl
        if self.has_udisksctl:
            try:
                res = subprocess.run(
                    ["udisksctl", "mount", "-b", device_path, "--options", "ro"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15
                )
                if res.returncode == 0:
                    parts = res.stdout.strip().split(" at ")
                    if len(parts) > 1:
                        mount_point = parts[1].strip().rstrip(".")
                        return True, mount_point
            except Exception:
                pass

        # Direct mount point directory fallback (Linux root or fstab)
        dev_name = os.path.basename(device_path)
        target_dir = os.path.join(self.base_mount_dir, dev_name)
        os.makedirs(target_dir, exist_ok=True)

        try:
            res = subprocess.run(
                ["mount", "-o", "ro,noexec,nosuid,nodev", device_path, target_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15
            )
            if res.returncode == 0:
                return True, target_dir
            return False, f"Mount failed: {res.stderr.strip()}"
        except Exception as e:
            return False, str(e)

    def unmount(self, device_or_mount_path: str) -> Tuple[bool, str]:
        """
        Unmounts safely and flushes write buffers to prevent corruption.
        """
        # Flush buffers
        subprocess.run(["sync"])

        # macOS native unmount
        if self.is_macos:
            return MacDiskManager.unmount_volume(device_or_mount_path)

        # Linux udisksctl unmount
        if self.has_udisksctl and device_or_mount_path.startswith("/dev/"):
            try:
                res = subprocess.run(
                    ["udisksctl", "unmount", "-b", device_or_mount_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15
                )
                if res.returncode == 0:
                    return True, "Safely unmounted with udisksctl"
            except Exception:
                pass

        # Standard Linux umount
        try:
            res = subprocess.run(
                ["umount", device_or_mount_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15
            )
            if res.returncode == 0:
                return True, "Safely unmounted"
            return False, f"Unmount failed: {res.stderr.strip()}"
        except Exception as e:
            return False, str(e)

    def eject(self, device_or_disk: str) -> Tuple[bool, str]:
        """
        Safely flushes and ejects the physical disk or media.
        """
        subprocess.run(["sync"])
        if self.is_macos:
            return MacDiskManager.eject_disk(device_or_disk)

        # Linux ejection
        if shutil.which("eject"):
            try:
                res = subprocess.run(["eject", device_or_disk], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode == 0:
                    return True, "Safely ejected"
            except Exception:
                pass
        return self.unmount(device_or_disk)
