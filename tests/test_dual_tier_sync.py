import os
import sys
import json
import unittest
import tempfile
from pathlib import Path

from src.sync.dual_tier_sync import DualTierSyncEngine
from src.storage_devices.drive_guard import DriveSafetyGuard
import repo_manager


class TestDualTierSync(unittest.TestCase):
    def setUp(self):
        self.tmp_local_dir = tempfile.TemporaryDirectory()
        self.tmp_archive_dir = tempfile.TemporaryDirectory()
        self.local_path = Path(self.tmp_local_dir.name)
        self.archive_path = Path(self.tmp_archive_dir.name)

        self.engine = DualTierSyncEngine(
            local_path=str(self.local_path),
            archive_path=str(self.archive_path)
        )
        self.engine.init_local_repo()
        self.engine.init_archive_repo(self.archive_path)

    def tearDown(self):
        self.tmp_local_dir.cleanup()
        self.tmp_archive_dir.cleanup()

    def test_tier_status_initialized(self):
        status = self.engine.get_tier_status()
        self.assertTrue(status["local_repo"]["exists"])
        self.assertTrue(status["archive_repo"]["is_mounted"])
        self.assertEqual(status["sync_delta"]["pending_push_count"], 0)
        self.assertEqual(status["sync_delta"]["pending_pull_count"], 0)

    def test_push_and_verify(self):
        # Create a document in local repository
        doc_path = self.local_path / "01_Medical_and_Health" / "field_guide.md"
        doc_path.write_text("# Emergency Field Medicine Guide\nDetailed procedures...", encoding="utf-8")
        repo_manager.cmd_index(self.local_path)

        # Check pending push delta
        status = self.engine.get_tier_status()
        self.assertEqual(status["sync_delta"]["pending_push_count"], 1)

        # Push to archive
        res = self.engine.push_to_archive(dry_run=False)
        self.assertTrue(res["success"])
        self.assertEqual(res["pushed_files"], 1)

        # Verify file exists on archive partition
        archive_doc = self.archive_path / "01_Medical_and_Health" / "field_guide.md"
        self.assertTrue(archive_doc.exists())
        self.assertEqual(archive_doc.read_text(encoding="utf-8"), doc_path.read_text(encoding="utf-8"))

        # Verify archive index and manifest exist
        manifest = self.archive_path / "00_Index_and_Manifests" / "MANIFEST.sha256"
        self.assertTrue(manifest.exists())
        sha = DriveSafetyGuard.calculate_sha256(doc_path)
        self.assertIn(sha, manifest.read_text(encoding="utf-8"))

        # Post-sync status should report 0 pending
        status2 = self.engine.get_tier_status()
        self.assertEqual(status2["sync_delta"]["pending_push_count"], 0)

    def test_pull_from_archive(self):
        # Create a document on the archive partition
        archive_doc = self.archive_path / "05_Computing_and_Comms" / "linux_kernel.md"
        archive_doc.write_text("# Linux Kernel & Networking Architecture", encoding="utf-8")
        repo_manager.cmd_index(self.archive_path)

        # Pull into local
        res = self.engine.pull_from_archive(dry_run=False)
        self.assertTrue(res["success"])
        self.assertEqual(res["pulled_files"], 1)

        local_doc = self.local_path / "05_Computing_and_Comms" / "linux_kernel.md"
        self.assertTrue(local_doc.exists())
        self.assertEqual(local_doc.read_text(encoding="utf-8"), archive_doc.read_text(encoding="utf-8"))

    def test_offload_and_rehydrate(self):
        # Create a large document locally
        large_doc = self.local_path / "04_Science_and_Reference" / "heavy_manual.txt"
        large_doc.write_text("X" * 1024, encoding="utf-8") # sample text
        orig_sha = DriveSafetyGuard.calculate_sha256(large_doc)
        repo_manager.cmd_index(self.local_path)

        # Push with offload (setting threshold low to trigger offload)
        res = self.engine.push_to_archive(dry_run=False, offload=True, offload_threshold_bytes=512)
        self.assertTrue(res["success"])
        self.assertEqual(res["offloaded_stubs"], 1)

        # Local full file should now be removed and replaced with a stub
        self.assertFalse(large_doc.exists())
        stub_file = self.local_path / "04_Science_and_Reference" / "heavy_manual.txt.stub.json"
        self.assertTrue(stub_file.exists())

        # Check stub content
        stub_data = json.loads(stub_file.read_text(encoding="utf-8"))
        self.assertEqual(stub_data["sha256"], orig_sha)
        self.assertEqual(stub_data["_type"], "KGS_OFFLOADED_STUB")

        # Verify repo_manager verification passes with stub
        repo_manager.cmd_index(self.local_path)
        # Should not raise
        repo_manager.cmd_verify(self.local_path)

        # Now rehydrate from archive back to local
        ok, msg = self.engine.hydrate_stub(str(stub_file))
        self.assertTrue(ok)
        self.assertTrue(large_doc.exists())
        self.assertFalse(stub_file.exists())
        self.assertEqual(DriveSafetyGuard.calculate_sha256(large_doc), orig_sha)


if __name__ == "__main__":
    unittest.main()
