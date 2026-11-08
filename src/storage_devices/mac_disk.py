"""
Mac Disk and Removable Media Manager (src/storage_devices/mac_disk.py)
Provides native macOS disk, partition, and APFS volume management using diskutil plists.

Architecture:
- Mac mini Host Storage: Internal SSD and semi-permanent hardware extension (Samsung 990 PRO).
- Portable Removable 1TB Drive: External plug-and-play multi-partition drive with a dedicated KnowRepo partition.
- Isolates host hardware extensions from portable media detection.
- Safe multi-partition unmount and eject for the portable removable drive.
- Automatic macOS metadata artifact cleanup (.DS_Store and ._* AppleDouble files).
"""

import os
import sys
import plistlib
import subprocess
import shutil
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path


class MacDiskManager:
    """Native macOS diskutil, APFS container, and multi-partition volume manager."""

    # Storage volumes treated strictly as local hardware extensions of the Mac mini host
    MAC_HOST_EXTENSION_LABELS: Set[str] = {
        "990_pro",
        "timemachine_backup"
    }

    # Recognized keywords for knowledge repository partitions on portable media
    KNOWREPO_PARTITION_KEYWORDS: List[str] = [
        "knowrepo",
        "knowrepo1",
        "knowrepo_archive",
        "knowrepo_main",
        "know_repo",
        "know_repo_archive",
        "knowledge_repo",
        "knowrepovault"
    ]

    @staticmethod
    def is_macos() -> bool:
        return sys.platform == "darwin" and shutil.which("diskutil") is not None

    @classmethod
    def list_disks_plist(cls) -> Dict[str, Any]:
        """Runs `diskutil list -plist` and parses the output."""
        if not cls.is_macos():
            return {}
        try:
            res = subprocess.run(
                ["diskutil", "list", "-plist"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=10
            )
            return plistlib.loads(res.stdout)
        except Exception as e:
            print(f"[WARN] Failed to list macOS disks via diskutil: {e}", file=sys.stderr)
            return {}

    @classmethod
    def get_disk_info(cls, disk_id_or_path: str) -> Dict[str, Any]:
        """Runs `diskutil info -plist <disk>` and parses the output."""
        if not cls.is_macos():
            return {}
        try:
            device = disk_id_or_path.replace("/dev/", "").strip()
            res = subprocess.run(
                ["diskutil", "info", "-plist", device],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=10
            )
            return plistlib.loads(res.stdout)
        except Exception:
            return {}

    @classmethod
    def is_host_extension(cls, volume_name: str, host_labels: Optional[Set[str]] = None) -> bool:
        """
        Determines if a volume is a local storage extension of the Mac mini (e.g. 990_PRO).
        Host extensions are part of the Mac mini host environment, NOT a KnowRepo archive vault.
        """
        labels = host_labels if host_labels is not None else cls.MAC_HOST_EXTENSION_LABELS
        clean_name = (volume_name or "").strip().lower()
        return any(clean_name == lbl.lower() or lbl.lower() in clean_name for lbl in labels)

    # Alias for compatibility
    is_semipermanent_volume = is_host_extension

    @classmethod
    def list_all_volumes(cls) -> List[Dict[str, Any]]:
        """
        Enumerates all physical and synthesized volumes across all disks.
        Returns a structured list of volumes with metadata.
        """
        plist_data = cls.list_disks_plist()
        if not plist_data:
            return []

        volumes: List[Dict[str, Any]] = []
        raw_disks = plist_data.get("AllDisksAndPartitions", [])

        for disk_entry in raw_disks:
            parent_id = disk_entry.get("DeviceIdentifier", "")
            parent_size = disk_entry.get("Size", 0)
            is_internal = disk_entry.get("OSInternal", False)

            # Check APFS Volumes inside container
            for apfs_vol in disk_entry.get("APFSVolumes", []):
                dev_id = apfs_vol.get("DeviceIdentifier", "")
                vol_name = apfs_vol.get("VolumeName", "")
                mount_point = apfs_vol.get("MountPoint")
                size = apfs_vol.get("Size", parent_size)
                capacity_in_use = apfs_vol.get("CapacityInUse", 0)

                info = cls.get_disk_info(dev_id)
                is_removable = info.get("RemovableMediaOrExternalDevice", not is_internal)
                is_ejectable = info.get("Ejectable", False)
                bus_protocol = info.get("BusProtocol", "")
                fstype = info.get("FilesystemType", "apfs")
                is_encrypted = info.get("Encryption", False) or info.get("FileVault", False)
                free_space = info.get("APFSContainerFree", 0)

                volumes.append({
                    "device_identifier": dev_id,
                    "device_node": f"/dev/{dev_id}",
                    "volume_name": vol_name,
                    "mount_point": mount_point,
                    "total_size": size,
                    "used_size": capacity_in_use,
                    "free_size": free_space,
                    "filesystem": fstype,
                    "is_removable": is_removable,
                    "is_ejectable": is_ejectable,
                    "is_internal": is_internal,
                    "is_host_extension": cls.is_host_extension(vol_name),
                    "is_semipermanent": cls.is_host_extension(vol_name),
                    "is_encrypted": is_encrypted,
                    "bus_protocol": bus_protocol,
                    "parent_disk": parent_id
                })

            # Check standard partitions (e.g. FAT32, exFAT, HFS+)
            for part in disk_entry.get("Partitions", []):
                part_id = part.get("DeviceIdentifier", "")
                vol_name = part.get("VolumeName", "")
                size = part.get("Size", 0)
                content = part.get("Content", "")

                if content in ("Apple_APFS", "Apple_APFS_Container", "GUID_partition_scheme"):
                    continue

                info = cls.get_disk_info(part_id)
                mount_point = info.get("MountPoint")
                fstype = info.get("FilesystemType") or content
                is_removable = info.get("RemovableMediaOrExternalDevice", not is_internal)
                is_ejectable = info.get("Ejectable", False)
                bus_protocol = info.get("BusProtocol", "")
                is_encrypted = info.get("Encryption", False)
                free_space = info.get("FreeSpace", 0)

                volumes.append({
                    "device_identifier": part_id,
                    "device_node": f"/dev/{part_id}",
                    "volume_name": vol_name or part_id,
                    "mount_point": mount_point,
                    "total_size": size,
                    "used_size": size - free_space if free_space else 0,
                    "free_size": free_space,
                    "filesystem": fstype,
                    "is_removable": is_removable,
                    "is_ejectable": is_ejectable,
                    "is_internal": is_internal,
                    "is_host_extension": cls.is_host_extension(vol_name),
                    "is_semipermanent": cls.is_host_extension(vol_name),
                    "is_encrypted": is_encrypted,
                    "bus_protocol": bus_protocol,
                    "parent_disk": parent_id
                })

        return volumes

    @classmethod
    def get_host_extension_drive(cls) -> Optional[Dict[str, Any]]:
        """
        Locates the Mac mini host storage extension (Samsung 990 PRO).
        """
        volumes = cls.list_all_volumes()
        for v in volumes:
            if cls.is_host_extension(v.get("volume_name", "")):
                return v
        return None

    # Alias for compatibility
    get_semipermanent_drive = get_host_extension_drive

    @classmethod
    def list_physical_drives_with_partitions(cls) -> List[Dict[str, Any]]:
        """
        Groups all connected storage by physical disk and lists all of its partitions/volumes.
        Classifies each physical drive as:
        - 'internal' (Mac internal SSD)
        - 'host_extension' (Mac mini hardware extension: 990_PRO)
        - 'portable_removable' (additional plug-and-play removable drives)
        """
        plist_data = cls.list_disks_plist()
        if not plist_data:
            return []

        all_volumes = cls.list_all_volumes()
        vol_by_dev = {v["device_identifier"]: v for v in all_volumes}

        drives: List[Dict[str, Any]] = []

        for disk_entry in plist_data.get("AllDisksAndPartitions", []):
            disk_id = disk_entry.get("DeviceIdentifier", "")
            disk_size = disk_entry.get("Size", 0)
            content = disk_entry.get("Content", "")

            # Only process physical root disks (e.g. disk0, disk4, disk6)
            if content == "Apple_APFS_Container":
                continue

            info = cls.get_disk_info(disk_id)
            is_internal = (
                disk_entry.get("OSInternal", False)
                or info.get("Internal", False)
                or (not info.get("Ejectable", False) and not info.get("RemovableMediaOrExternalDevice", False))
            )

            # Gather all partitions and APFS volumes belonging to this physical drive
            partitions: List[Dict[str, Any]] = []
            has_host_extension_vol = False

            for part in disk_entry.get("Partitions", []):
                pid = part.get("DeviceIdentifier", "")
                p_content = part.get("Content", "")
                p_size = part.get("Size", 0)
                p_volname = part.get("VolumeName") or pid

                if p_content == "Apple_APFS":
                    for c_entry in plist_data.get("AllDisksAndPartitions", []):
                        if any(ps.get("DeviceIdentifier") == pid for ps in c_entry.get("APFSPhysicalStores", [])):
                            for avol in c_entry.get("APFSVolumes", []):
                                avid = avol.get("DeviceIdentifier", "")
                                avolname = avol.get("VolumeName", "")
                                v_info = vol_by_dev.get(avid, {})
                                is_ext = cls.is_host_extension(avolname)
                                if is_ext:
                                    has_host_extension_vol = True

                                is_know = any(k in avolname.lower() for k in cls.KNOWREPO_PARTITION_KEYWORDS)

                                partitions.append({
                                    "device_identifier": avid,
                                    "device_node": f"/dev/{avid}",
                                    "partition_label": avolname,
                                    "size": avol.get("Size", c_entry.get("Size", p_size)),
                                    "filesystem": "apfs",
                                    "mount_point": avol.get("MountPoint"),
                                    "is_knowrepo": is_know,
                                    "is_host_extension": is_ext,
                                    "is_semipermanent": is_ext,
                                    "is_encrypted": v_info.get("is_encrypted", False),
                                    "free_bytes": v_info.get("free_size", 0)
                                })
                elif p_content not in ("GUID_partition_scheme", "Apple_APFS_Container"):
                    v_info = vol_by_dev.get(pid, {})
                    is_ext = cls.is_host_extension(p_volname)
                    if is_ext:
                        has_host_extension_vol = True
                    is_know = any(k in p_volname.lower() for k in cls.KNOWREPO_PARTITION_KEYWORDS)

                    partitions.append({
                        "device_identifier": pid,
                        "device_node": f"/dev/{pid}",
                        "partition_label": p_volname,
                        "size": p_size,
                        "filesystem": v_info.get("filesystem", p_content),
                        "mount_point": v_info.get("mount_point"),
                        "is_knowrepo": is_know,
                        "is_host_extension": is_ext,
                        "is_semipermanent": is_ext,
                        "is_encrypted": v_info.get("is_encrypted", False),
                        "free_bytes": v_info.get("free_size", 0)
                    })

            # Classification
            if is_internal:
                drive_type = "internal"
            elif has_host_extension_vol or cls.is_host_extension(disk_id):
                drive_type = "host_extension"
            else:
                drive_type = "portable_removable"

            bus_protocol = info.get("BusProtocol", "USB" if not is_internal else "Internal")

            drives.append({
                "device_identifier": disk_id,
                "device_node": f"/dev/{disk_id}",
                "drive_type": drive_type,
                "total_size": disk_size,
                "bus_protocol": bus_protocol,
                "partitions": partitions
            })

        return drives

    @classmethod
    def list_portable_removable_drives(cls) -> List[Dict[str, Any]]:
        """
        Lists only portable removable external drives (EXCLUDING internal SSD and Mac host extension 990_PRO).
        """
        drives = cls.list_physical_drives_with_partitions()
        return [d for d in drives if d["drive_type"] == "portable_removable"]

    @classmethod
    def find_portable_knowrepo_partition(cls) -> Optional[Dict[str, Any]]:
        """
        Locates the specific partition dedicated to KnowRepo on a portable removable drive.
        Ensures 990_PRO is excluded from consideration as it is Mac host extension storage.
        """
        portable_drives = cls.list_portable_removable_drives()
        for drive in portable_drives:
            for part in drive.get("partitions", []):
                if part.get("is_knowrepo"):
                    return {
                        "parent_disk": drive["device_identifier"],
                        "parent_size": drive["total_size"],
                        "bus_protocol": drive["bus_protocol"],
                        "partition": part,
                        "sibling_partitions": [p for p in drive["partitions"] if p["device_identifier"] != part["device_identifier"]]
                    }

        # Check if a 1TB portable removable drive is connected with multiple partitions
        ONE_TB_MIN = 850 * (1024 ** 3)
        ONE_TB_MAX = 1150 * (1024 ** 3)

        for drive in portable_drives:
            if ONE_TB_MIN <= drive.get("total_size", 0) <= ONE_TB_MAX:
                parts = drive.get("partitions", [])
                if parts:
                    valid_parts = [p for p in parts if p.get("partition_label") != "EFI"]
                    target = valid_parts[0] if valid_parts else parts[0]
                    return {
                        "parent_disk": drive["device_identifier"],
                        "parent_size": drive["total_size"],
                        "bus_protocol": drive["bus_protocol"],
                        "partition": target,
                        "sibling_partitions": [p for p in drive["partitions"] if p["device_identifier"] != target["device_identifier"]]
                    }

        return None

    @classmethod
    def safe_eject_multi_partition_drive(cls, disk_identifier: str) -> Tuple[bool, str]:
        """
        Safely unmounts ALL mounted partitions belonging to a physical portable drive,
        flushes system write buffers (sync), and ejects the entire physical enclosure.
        Protects all partitions sharing the portable drive.
        """
        if not cls.is_macos():
            return False, "Not running on macOS"

        drives = cls.list_physical_drives_with_partitions()
        target_drive = None
        for d in drives:
            if d["device_identifier"] == disk_identifier or any(p["device_identifier"] == disk_identifier for p in d["partitions"]):
                target_drive = d
                break

        if not target_drive:
            subprocess.run(["sync"])
            return cls.eject_disk(disk_identifier)

        subprocess.run(["sync"])

        for part in target_drive["partitions"]:
            if part.get("mount_point"):
                cls.unmount_volume(part["device_identifier"])

        parent_disk = target_drive["device_identifier"]
        return cls.eject_disk(parent_disk)

    @classmethod
    def mount_volume(cls, device_or_volume: str, read_only: bool = False) -> Tuple[bool, str]:
        """
        Mounts a macOS disk or APFS volume using diskutil.
        Returns (success: bool, mount_point_or_error: str).
        """
        if not cls.is_macos():
            return False, "Not running on macOS"

        dev_id = device_or_volume.replace("/dev/", "").strip()
        cmd = ["diskutil", "mount"]
        if read_only:
            cmd.append("readOnly")
        cmd.append(dev_id)

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            if res.returncode == 0:
                info = cls.get_disk_info(dev_id)
                mount_point = info.get("MountPoint")
                if mount_point:
                    return True, mount_point
                return True, res.stdout.strip()
            return False, f"diskutil mount failed: {res.stderr.strip() or res.stdout.strip()}"
        except Exception as e:
            return False, str(e)

    @classmethod
    def unmount_volume(cls, device_or_path: str, force: bool = False) -> Tuple[bool, str]:
        """
        Safely flushes system disk buffers and unmounts a macOS volume.
        """
        if not cls.is_macos():
            return False, "Not running on macOS"

        subprocess.run(["sync"])
        cmd = ["diskutil", "unmount"]
        if force:
            cmd.append("force")
        cmd.append(device_or_path)

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            if res.returncode == 0:
                return True, "Safely unmounted"
            return False, f"diskutil unmount failed: {res.stderr.strip() or res.stdout.strip()}"
        except Exception as e:
            return False, str(e)

    @classmethod
    def eject_disk(cls, disk_or_volume: str) -> Tuple[bool, str]:
        """
        Safely flushes system buffers and ejects the entire physical disk/enclosure.
        """
        if not cls.is_macos():
            return False, "Not running on macOS"

        subprocess.run(["sync"])
        cmd = ["diskutil", "eject", disk_or_volume]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
            if res.returncode == 0:
                return True, "Safely ejected"
            return False, f"diskutil eject failed: {res.stderr.strip() or res.stdout.strip()}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def clean_macos_artifacts(directory_path: str) -> int:
        """
        Cleans .DS_Store, AppleDouble '._*' metadata files, and .Trashes
        to ensure clean cross-device portability without cluttering archive manifests.
        Returns count of removed artifact files.
        """
        target = Path(directory_path)
        if not target.exists() or not target.is_dir():
            return 0

        removed_count = 0
        for root, dirs, files in os.walk(target):
            for f in files:
                if f == ".DS_Store" or f.startswith("._"):
                    full_f = os.path.join(root, f)
                    try:
                        os.remove(full_f)
                        removed_count += 1
                    except OSError:
                        pass
        return removed_count
