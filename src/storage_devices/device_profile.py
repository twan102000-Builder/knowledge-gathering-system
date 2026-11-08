"""
Host Device and Storage Profile Engine (src/storage_devices/device_profile.py)
Automatically identifies host hardware (Mac mini vs MacBook Pro vs other devices)
and dynamically determines the preferred local repository root:
- On Mac mini: Samsung 990 PRO NVMe is the main storage -> /Volumes/990_PRO/KnowRepo_Local
- On MacBook Pro / other Macs: Internal NVMe drive is main storage -> ~/KnowRepo_Local
- On any device: The portable removable 1TB drive holds the universal Main Know Repo
  on its single dedicated KnowRepo partition.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional


class DeviceProfileManager:
    """Manages cross-device hardware profiles and adaptive local repository pathing."""

    DEFAULT_MAC_MINI_PATH = Path("/Volumes/990_PRO/KnowRepo_Local")
    DEFAULT_MACBOOK_PATH = Path(os.path.expanduser("~/KnowRepo_Local"))

    @classmethod
    def get_computer_name(cls) -> str:
        """Retrieves user-facing computer name on macOS or falls back to hostname."""
        if sys.platform == "darwin" and shutil.which("scutil"):
            try:
                res = subprocess.run(
                    ["scutil", "--get", "ComputerName"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass
        import socket
        return socket.gethostname()

    @classmethod
    def get_hardware_model(cls) -> str:
        """Retrieves Apple hardware model identifier (e.g., 'Mac16,10' or 'MacBookPro18,1')."""
        if sys.platform == "darwin" and shutil.which("sysctl"):
            try:
                res = subprocess.run(
                    ["sysctl", "-n", "hw.model"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass
        return ""

    @classmethod
    def detect_host_device(cls) -> Dict[str, Any]:
        """
        Detects whether current machine is Mac mini, MacBook Pro/Air, or another device.
        """
        model = cls.get_hardware_model()
        computer_name = cls.get_computer_name()
        cname_lower = computer_name.lower()
        model_lower = model.lower()

        # Check for 990_PRO attachment as primary evidence of Mac mini main storage setup
        has_990_pro = os.path.exists("/Volumes/990_PRO")

        is_mac_mini = (
            "mini" in cname_lower
            or "macmini" in model_lower
            or model in ("Mac16,10", "Mac16,11", "Mac16,15", "Mac14,3", "Mac14,12") # Apple Silicon Mac mini identifiers
            or (has_990_pro and "macbook" not in cname_lower)
        )

        is_macbook_pro = (
            "macbook pro" in cname_lower
            or "macbookpro" in model_lower
            or "mbp" in cname_lower
            or (not is_mac_mini and ("macbook" in cname_lower or "macbook" in model_lower) and "air" not in cname_lower)
        )

        is_macbook_air = (
            "macbook air" in cname_lower
            or "macbookair" in model_lower
            or "mba" in cname_lower
        )

        if is_mac_mini:
            device_type = "mac_mini"
            display_name = "Mac mini"
            preferred_storage = "Samsung 990 PRO NVMe (Main Storage)" if has_990_pro else "Internal Storage"
        elif is_macbook_pro:
            device_type = "macbook_pro"
            display_name = "MacBook Pro"
            preferred_storage = "Internal NVMe SSD (Main Storage)"
        elif is_macbook_air:
            device_type = "macbook_air"
            display_name = "MacBook Air"
            preferred_storage = "Internal NVMe SSD (Main Storage)"
        elif sys.platform == "darwin":
            device_type = "mac_other"
            display_name = "Mac Workstation"
            preferred_storage = "Samsung 990 PRO NVMe" if has_990_pro else "Internal Storage"
        else:
            device_type = "linux"
            display_name = "Linux Host"
            preferred_storage = "Local Main Drive"

        return {
            "device_type": device_type,
            "display_name": display_name,
            "computer_name": computer_name,
            "model_id": model,
            "has_990_pro": has_990_pro,
            "preferred_storage_description": preferred_storage
        }

    @classmethod
    def resolve_preferred_local_repo_path(cls, config: Optional[Dict[str, Any]] = None) -> Path:
        """
        Dynamically determines the local repository location based on the host device:
        - If Mac mini and 990 PRO is mounted -> /Volumes/990_PRO/KnowRepo_Local
        - If MacBook Pro or 990 PRO not mounted -> ~/KnowRepo_Local
        - Respects explicit config if specified.
        """
        if config:
            # Check explicit config overrides
            cfg_local = config.get("tier_architecture", {}).get("local_repo_path")
            if cfg_local and cfg_local != "auto":
                return Path(os.path.abspath(os.path.expanduser(cfg_local)))

        host_info = cls.detect_host_device()

        # On Mac mini with 990 PRO: preferred local storage is on the 990 PRO
        if host_info["has_990_pro"]:
            if host_info["device_type"] in ("mac_mini", "mac_other") or not Path(os.path.expanduser("~/KnowRepo_Local")).exists():
                return cls.DEFAULT_MAC_MINI_PATH

        # On MacBook Pro or any device without 990 PRO: preferred local storage is internal SSD
        return cls.DEFAULT_MACBOOK_PATH

    @classmethod
    def get_host_summary(cls) -> str:
        """Provides a user-friendly summary of host device and storage assignment."""
        host = cls.detect_host_device()
        local_path = cls.resolve_preferred_local_repo_path()
        return (
            f"Host: {host['display_name']} ('{host['computer_name']}') | "
            f"Main Storage: {host['preferred_storage_description']} | "
            f"Local Repo: {local_path}"
        )
