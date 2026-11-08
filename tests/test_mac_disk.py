import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.storage_devices.mac_disk import MacDiskManager
from src.storage_devices.drive_guard import DriveSafetyGuard
from src.storage_devices.detector import SDDeviceDetector
from src.storage_devices.mounter import SafeDeviceMounter


class TestMacDiskManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_clean_macos_artifacts(self):
        # Create mock directory structure with macOS clutter
        cat_dir = self.test_path / "01_Medical"
        cat_dir.mkdir(parents=True)
        (cat_dir / "valid_doc.md").write_text("# Real content", encoding="utf-8")
        (cat_dir / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
        (cat_dir / "._valid_doc.md").write_bytes(b"\x00\x05\x16\x07AppleDouble")

        removed = MacDiskManager.clean_macos_artifacts(str(self.test_path))
        self.assertEqual(removed, 2)
        self.assertTrue((cat_dir / "valid_doc.md").exists())
        self.assertFalse((cat_dir / ".DS_Store").exists())
        self.assertFalse((cat_dir / "._valid_doc.md").exists())

    def test_semipermanent_volume_identification(self):
        self.assertTrue(MacDiskManager.is_semipermanent_volume("990_PRO"))
        self.assertTrue(MacDiskManager.is_semipermanent_volume("TimeMachine_Backup"))
        self.assertFalse(MacDiskManager.is_semipermanent_volume("KnowRepo"))
        self.assertFalse(MacDiskManager.is_semipermanent_volume("KnowRepo_Archive"))
        self.assertFalse(MacDiskManager.is_semipermanent_volume("Portable_1TB_Data"))

    @patch.object(MacDiskManager, "is_macos", return_value=True)
    @patch.object(MacDiskManager, "list_disks_plist")
    @patch.object(MacDiskManager, "get_disk_info")
    def test_multi_partition_portable_drive_classification(self, mock_info, mock_plist, mock_is_mac):
        # Mock diskutil plist with disk0 (internal), disk4 (semi-permanent 990_PRO), and disk6 (portable 1TB drive)
        mock_plist.return_value = {
            "AllDisksAndPartitions": [
                {
                    "DeviceIdentifier": "disk0",
                    "Size": 250000000000,
                    "OSInternal": True,
                    "Partitions": [{"DeviceIdentifier": "disk0s1", "Content": "Apple_APFS"}]
                },
                {
                    "DeviceIdentifier": "disk4",
                    "Size": 1000000000000,
                    "OSInternal": False,
                    "Partitions": [
                        {"DeviceIdentifier": "disk4s1", "Content": "EFI", "VolumeName": "EFI"},
                        {"DeviceIdentifier": "disk4s2", "Content": "Apple_APFS"}
                    ]
                },
                {
                    "DeviceIdentifier": "disk5",
                    "Content": "Apple_APFS_Container",
                    "APFSPhysicalStores": [{"DeviceIdentifier": "disk4s2"}],
                    "APFSVolumes": [
                        {"DeviceIdentifier": "disk5s1", "VolumeName": "990_PRO", "MountPoint": "/Volumes/990_PRO"},
                        {"DeviceIdentifier": "disk5s2", "VolumeName": "TimeMachine_Backup", "MountPoint": "/Volumes/TimeMachine_Backup"}
                    ]
                },
                # Portable Removable 1TB drive with multiple partitions!
                {
                    "DeviceIdentifier": "disk6",
                    "Size": 1000204886016, # 1.0 TB
                    "OSInternal": False,
                    "Partitions": [
                        {
                            "DeviceIdentifier": "disk6s1",
                            "Content": "Apple_HFS",
                            "VolumeName": "KnowRepo_Archive",
                            "Size": 500000000000
                        },
                        {
                            "DeviceIdentifier": "disk6s2",
                            "Content": "ExFAT",
                            "VolumeName": "Field_Data",
                            "Size": 500000000000
                        }
                    ]
                }
            ]
        }

        def mock_info_side_effect(dev_id):
            if dev_id == "disk0":
                return {"Internal": True, "Ejectable": False, "RemovableMediaOrExternalDevice": False}
            elif dev_id in ("disk4", "disk5s1", "disk5s2"):
                return {"Internal": False, "Ejectable": True, "RemovableMediaOrExternalDevice": True, "BusProtocol": "USB", "MountPoint": f"/Volumes/{dev_id}"}
            elif dev_id == "disk6":
                return {"Internal": False, "Ejectable": True, "RemovableMediaOrExternalDevice": True, "BusProtocol": "USB"}
            elif dev_id == "disk6s1":
                return {"MountPoint": "/Volumes/KnowRepo_Archive", "FilesystemType": "hfs+", "Internal": False, "Ejectable": True}
            elif dev_id == "disk6s2":
                return {"MountPoint": "/Volumes/Field_Data", "FilesystemType": "exfat", "Internal": False, "Ejectable": True}
            return {}

        mock_info.side_effect = mock_info_side_effect

        drives = MacDiskManager.list_physical_drives_with_partitions()
        drive_types = {d["device_identifier"]: d["drive_type"] for d in drives}
        self.assertEqual(drive_types["disk0"], "internal")
        self.assertEqual(drive_types["disk4"], "host_extension")
        self.assertEqual(drive_types["disk6"], "portable_removable")

        # Verify KnowRepo partition detection on portable drive
        portable_know = MacDiskManager.find_portable_knowrepo_partition()
        self.assertIsNotNone(portable_know)
        self.assertEqual(portable_know["parent_disk"], "disk6")
        self.assertEqual(portable_know["partition"]["partition_label"], "KnowRepo_Archive")
        self.assertEqual(portable_know["partition"]["mount_point"], "/Volumes/KnowRepo_Archive")

        # Verify sibling partition is recognized
        siblings = portable_know["sibling_partitions"]
        self.assertEqual(len(siblings), 1)
        self.assertEqual(siblings[0]["partition_label"], "Field_Data")

    @patch("src.storage_devices.mac_disk.subprocess.run")
    def test_mount_volume_darwin(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Volume disk6s1 on disk6s1 mounted"
        mock_run.return_value = mock_proc

        with patch.object(MacDiskManager, "is_macos", return_value=True):
            with patch.object(MacDiskManager, "get_disk_info", return_value={"MountPoint": "/Volumes/KnowRepo"}):
                ok, mount_pt = MacDiskManager.mount_volume("disk6s1", read_only=True)
                self.assertTrue(ok)
                self.assertEqual(mount_pt, "/Volumes/KnowRepo")

    @patch("src.storage_devices.mac_disk.subprocess.run")
    def test_unmount_volume_darwin(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Volume disk6s1 on disk6s1 unmounted"
        mock_run.return_value = mock_proc

        with patch.object(MacDiskManager, "is_macos", return_value=True):
            ok, msg = MacDiskManager.unmount_volume("disk6s1")
            self.assertTrue(ok)
            self.assertEqual(msg, "Safely unmounted")

    def test_drive_safety_guard_atomic_copy_and_verify(self):
        src_file = self.test_path / "source.txt"
        dst_file = self.test_path / "subdir" / "dest.txt"
        src_file.write_text("Integrity-critical repository data payload", encoding="utf-8")

        expected_hash = DriveSafetyGuard.calculate_sha256(src_file)
        ok, sha, err = DriveSafetyGuard.atomic_copy_and_verify(src_file, dst_file, expected_hash=expected_hash)

        self.assertTrue(ok)
        self.assertEqual(sha, expected_hash)
        self.assertTrue(dst_file.exists())
        self.assertEqual(dst_file.read_text(encoding="utf-8"), "Integrity-critical repository data payload")

    def test_drive_safety_guard_corrupt_mismatch(self):
        src_file = self.test_path / "source2.txt"
        dst_file = self.test_path / "dest2.txt"
        src_file.write_text("Original payload", encoding="utf-8")

        ok, sha, err = DriveSafetyGuard.atomic_copy_and_verify(
            src_file,
            dst_file,
            expected_hash="0000000000000000000000000000000000000000000000000000000000000000"
        )
        self.assertFalse(ok)
        self.assertIn("Integrity check failed", err)
        self.assertFalse(dst_file.exists())


if __name__ == "__main__":
    unittest.main()
