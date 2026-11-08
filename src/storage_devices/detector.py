import subprocess
import json
import os
import sys
from typing import List, Dict, Any, Optional
from .mac_disk import MacDiskManager

class SDDeviceDetector:
    @staticmethod
    def _format_size_bytes(bytes_num: int) -> str:
        for unit in ["B", "K", "M", "G", "T"]:
            if abs(bytes_num) < 1024.0:
                return f"{bytes_num:3.1f}{unit}"
            bytes_num /= 1024.0
        return f"{bytes_num:.1f}P"

    @classmethod
    def list_candidate_devices(cls) -> List[Dict[str, Any]]:
        """
        Discovers removable media, SD/MMC devices, and portable drives.
        Uses native diskutil on macOS, and lsblk on Linux.
        """
        if sys.platform == "darwin":
            return cls._list_macos_devices()
        return cls._list_linux_devices()

    @classmethod
    def _list_macos_devices(cls) -> List[Dict[str, Any]]:
        """Native macOS device detection via MacDiskManager."""
        candidates = []
        volumes = MacDiskManager.list_all_volumes()

        for v in volumes:
            # Include removable, ejectable, or USB/Thunderbolt drives
            is_external = v.get("is_removable") or v.get("is_ejectable") or v.get("bus_protocol", "").upper() in ("USB", "THUNDERBOLT", "SD")
            if is_external and not v.get("is_internal"):
                size_str = cls._format_size_bytes(v.get("total_size", 0))
                candidates.append({
                    "name": v.get("device_identifier"),
                    "path": v.get("device_node"),
                    "fstype": v.get("filesystem"),
                    "size": size_str,
                    "mountpoint": v.get("mount_point"),
                    "label": v.get("volume_name"),
                    "model": f"{v.get('bus_protocol', 'External')} Storage",
                    "is_mmc": "sd" in v.get("volume_name", "").lower() or "mmc" in v.get("device_identifier", "").lower()
                })
        return candidates

    @classmethod
    def _list_linux_devices(cls) -> List[Dict[str, Any]]:
        """Linux device detection using lsblk JSON output."""
        try:
            cmd = ["lsblk", "-J", "-o", "NAME,PATH,RM,RO,SIZE,TYPE,FSTYPE,MOUNTPOINT,LABEL,MODEL,TRAN"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if res.returncode != 0:
                return []
            
            data = json.loads(res.stdout)
            candidates = []

            def inspect_node(node: dict, parent_model: str = "", parent_tran: str = ""):
                name = node.get("name", "")
                path = node.get("path", f"/dev/{name}")
                rm = bool(node.get("rm"))
                tran = node.get("tran") or parent_tran
                model = node.get("model") or parent_model
                node_type = node.get("type", "")

                is_mmc = "mmcblk" in name
                is_removable_usb = (tran == "usb" and rm)
                is_sd_candidate = is_mmc or is_removable_usb or "sd" in (model or "").lower()

                if node_type == "part" and is_sd_candidate:
                    candidates.append({
                        "name": name,
                        "path": path,
                        "fstype": node.get("fstype"),
                        "size": node.get("size"),
                        "mountpoint": node.get("mountpoint"),
                        "label": node.get("label"),
                        "model": model,
                        "is_mmc": is_mmc
                    })

                for child in node.get("children", []):
                    inspect_node(child, parent_model=model, parent_tran=tran)

            for root_device in data.get("blockdevices", []):
                inspect_node(root_device)

            return candidates
        except Exception as e:
            print(f"[!] Error inspecting block devices: {e}", file=sys.stderr)
            return []

    @classmethod
    def find_device(cls, device_query: Optional[str] = None) -> Optional[Dict[str, Any]]:
        devs = cls.list_candidate_devices()
        if not devs:
            return None
        if not device_query or device_query == "auto":
            return devs[0] # Return the first matching candidate
        for d in devs:
            if device_query in (d["name"], d["path"], d.get("label")):
                return d
        return None
