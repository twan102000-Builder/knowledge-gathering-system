import subprocess
import os
import shutil
from typing import Optional, Tuple

class SafeDeviceMounter:
    def __init__(self, base_mount_dir: str = "/tmp/kgs_mounts"):
        self.base_mount_dir = base_mount_dir
        os.makedirs(self.base_mount_dir, exist_ok=True)
        self.has_udisksctl = shutil.which("udisksctl") is not None

    def mount_read_only(self, device_path: str) -> Tuple[bool, str]:
        """
        Safely mounts device read-only.
        Returns (success: bool, mount_path_or_error: str)
        """
        # If udisksctl is available (user-space non-root mount)
        if self.has_udisksctl:
            try:
                res = subprocess.run(
                    ["udisksctl", "mount", "-b", device_path, "--options", "ro"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                if res.returncode == 0:
                    # Output: "Mounted /dev/sdX1 at /media/user/label"
                    parts = res.stdout.strip().split(" at ")
                    if len(parts) > 1:
                        mount_point = parts[1].strip().rstrip(".")
                        return True, mount_point
            except Exception as e:
                pass

        # Direct mount point directory
        dev_name = os.path.basename(device_path)
        target_dir = os.path.join(self.base_mount_dir, dev_name)
        os.makedirs(target_dir, exist_ok=True)

        # Fallback to standard mount (requires sudo or fstab permission)
        try:
            res = subprocess.run(
                ["mount", "-o", "ro,noexec,nosuid,nodev", device_path, target_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode == 0:
                return True, target_dir
            return False, f"Mount failed: {res.stderr.strip()}"
        except Exception as e:
            return False, str(e)

    def unmount(self, device_or_mount_path: str) -> Tuple[bool, str]:
        """
        Unmounts safely and syncs buffers.
        """
        # Flush buffers
        subprocess.run(["sync"])

        if self.has_udisksctl and device_or_mount_path.startswith("/dev/"):
            try:
                res = subprocess.run(
                    ["udisksctl", "unmount", "-b", device_or_mount_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                if res.returncode == 0:
                    return True, "Safely unmounted with udisksctl"
            except Exception:
                pass

        try:
            res = subprocess.run(
                ["umount", device_or_mount_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode == 0:
                return True, "Safely unmounted"
            return False, f"Unmount failed: {res.stderr.strip()}"
        except Exception as e:
            return False, str(e)
