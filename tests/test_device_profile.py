import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.storage_devices.device_profile import DeviceProfileManager


class TestDeviceProfileManager(unittest.TestCase):

    @patch.object(DeviceProfileManager, "get_hardware_model", return_value="Mac16,10")
    @patch.object(DeviceProfileManager, "get_computer_name", return_value="Anthony’s Mac mini")
    @patch("os.path.exists")
    def test_mac_mini_profile_detection(self, mock_exists, mock_name, mock_model):
        mock_exists.side_effect = lambda p: str(p) == "/Volumes/990_PRO"

        info = DeviceProfileManager.detect_host_device()
        self.assertEqual(info["device_type"], "mac_mini")
        self.assertTrue(info["has_990_pro"])
        self.assertIn("990 PRO", info["preferred_storage_description"])

        preferred_path = DeviceProfileManager.resolve_preferred_local_repo_path()
        self.assertEqual(str(preferred_path), "/Volumes/990_PRO/KnowRepo_Local")

    @patch.object(DeviceProfileManager, "get_hardware_model", return_value="MacBookPro18,1")
    @patch.object(DeviceProfileManager, "get_computer_name", return_value="Anthony’s MacBook Pro")
    @patch("os.path.exists", return_value=False)
    def test_macbook_pro_profile_detection(self, mock_exists, mock_name, mock_model):
        info = DeviceProfileManager.detect_host_device()
        self.assertEqual(info["device_type"], "macbook_pro")
        self.assertFalse(info["has_990_pro"])
        self.assertIn("Internal NVMe", info["preferred_storage_description"])

        preferred_path = DeviceProfileManager.resolve_preferred_local_repo_path()
        expected = Path(os.path.expanduser("~/KnowRepo_Local"))
        self.assertEqual(preferred_path, expected)

    @patch.object(DeviceProfileManager, "get_hardware_model", return_value="MacBookAir10,1")
    @patch.object(DeviceProfileManager, "get_computer_name", return_value="Anthony's MacBook Air")
    @patch("os.path.exists", return_value=False)
    def test_macbook_air_profile_detection(self, mock_exists, mock_name, mock_model):
        info = DeviceProfileManager.detect_host_device()
        self.assertEqual(info["device_type"], "macbook_air")
        preferred_path = DeviceProfileManager.resolve_preferred_local_repo_path()
        expected = Path(os.path.expanduser("~/KnowRepo_Local"))
        self.assertEqual(preferred_path, expected)

    def test_explicit_config_override(self):
        custom_cfg = {
            "tier_architecture": {
                "local_repo_path": "/tmp/custom_knowrepo"
            }
        }
        resolved = DeviceProfileManager.resolve_preferred_local_repo_path(custom_cfg)
        self.assertEqual(str(resolved), "/tmp/custom_knowrepo")


if __name__ == "__main__":
    unittest.main()
