import subprocess
import json
import os
from typing import List, Dict, Any, Optional

class SDDeviceDetector:
    @staticmethod
    def list_candidate_devices() -> List[Dict[str, Any]]:
        """
        Uses lsblk JSON output to discover removable media and SD/MMC devices.
        """
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
            print(f"[!] Error inspecting block devices: {e}")
            return []

    @staticmethod
    def find_device(device_query: Optional[str] = None) -> Optional[Dict[str, Any]]:
        devs = SDDeviceDetector.list_candidate_devices()
        if not devs:
            return None
        if not device_query or device_query == "auto":
            return devs[0] # Return the first matching candidate
        for d in devs:
            if device_query in (d["name"], d["path"], d.get("label")):
                return d
        return None
