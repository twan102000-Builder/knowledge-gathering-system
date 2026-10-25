import unittest
import tempfile
import os
import shutil
from src.store.db import MetadataDB
from src.store.vault import VaultManager
from src.pipeline.metadata import ContentClassifier
from src.storage_devices.sync import SDCardSyncPipeline

class TestKnowledgeSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.db = MetadataDB(self.db_path)
        self.vault = VaultManager(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_classifier(self):
        cat, title, meta = ContentClassifier.classify_text("https://example.com/research")
        self.assertEqual(cat, "url")

        cat, title, meta = ContentClassifier.classify_text("def my_func():\n    return 42")
        self.assertEqual(cat, "code")

        cat, title, meta = ContentClassifier.classify_text("Regular meeting notes on KGS architecture.")
        self.assertEqual(cat, "text")

    def test_db_and_deduplication(self):
        chash = ContentClassifier.compute_hash(b"hello world")
        self.assertFalse(self.db.item_exists(chash))
        
        self.db.record_item(
            content_hash=chash,
            source_type="clipboard",
            vault_rel_path="snippets/test.md",
            title="Hello World",
            category="text"
        )
        self.assertTrue(self.db.item_exists(chash))

        stats = self.db.stats()
        self.assertEqual(stats["total_items"], 1)
        self.assertEqual(stats["by_source"]["clipboard"], 1)

    def test_sd_sync_pipeline(self):
        # Create simulated SD card mount directory
        mock_sd = os.path.join(self.test_dir, "mock_sd")
        os.makedirs(mock_sd, exist_ok=True)
        with open(os.path.join(mock_sd, "photo.jpg"), "wb") as f:
            f.write(b"\xFF\xD8\xFF\xE0\x00\x10JFIFdummyphoto")
        with open(os.path.join(mock_sd, "notes.txt"), "w") as f:
            f.write("Field research notes from SD card.")

        pipeline = SDCardSyncPipeline(self.db, self.vault)
        summary = pipeline.sync_from_mount(mock_sd, device_label="mock_sd")
        self.assertEqual(summary["scanned"], 2)
        self.assertEqual(summary["imported"], 2)
        self.assertEqual(summary["skipped_duplicates"], 0)

        # Re-run to test idempotency and deduplication
        summary2 = pipeline.sync_from_mount(mock_sd, device_label="mock_sd")
        self.assertEqual(summary2["scanned"], 2)
        self.assertEqual(summary2["imported"], 0)
        self.assertEqual(summary2["skipped_duplicates"], 2)

if __name__ == "__main__":
    unittest.main()
