import os
import shutil
import tempfile
import unittest
from pathlib import Path

import repo_manager
from src.store.db import MetadataDB
from src.store.vault import VaultManager

class TestRepoManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_root = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sanitize_filename(self):
        # Removes illegal characters for FAT32/exFAT/APFS
        name = 'Test: File / With * Illegal ? Chars & "Quotes"!'
        sanitized = repo_manager.sanitize_filename(name)
        self.assertNotIn(":", sanitized)
        self.assertNotIn("/", sanitized)
        self.assertNotIn("*", sanitized)
        self.assertNotIn("?", sanitized)
        self.assertNotIn('"', sanitized)

        # Truncates excessively long names
        long_name = "a" * 200
        self.assertLessEqual(len(repo_manager.sanitize_filename(long_name)), 120)

        # Handles empty or special names
        self.assertEqual(repo_manager.sanitize_filename(""), "untitled_document")

    def test_html_converter(self):
        html_input = """
        <html>
        <head><title>Guide to First Aid</title></head>
        <body>
            <script>alert('bad');</script>
            <h1>Emergency Care</h1>
            <p>Treat <strong>wounds</strong> immediately.</p>
            <ul>
                <li>Wash with water</li>
                <li>Apply bandage</li>
            </ul>
        </body>
        </html>
        """
        parser = repo_manager.CleanHTMLConverter(to_markdown=True)
        parser.feed(html_input)
        output = parser.get_output()

        self.assertEqual(parser.title.strip(), "Guide to First Aid")
        self.assertNotIn("alert", output)
        self.assertIn("# Emergency Care", output)
        self.assertIn("**wounds**", output)
        self.assertIn("Wash with water", output)

    def test_resolve_category(self):
        self.assertEqual(repo_manager.resolve_category("01"), "01_Medical_and_Health")
        self.assertEqual(repo_manager.resolve_category("05"), "05_Computing_and_Comms")
        self.assertEqual(repo_manager.resolve_category("medical"), "01_Medical_and_Health")
        self.assertEqual(repo_manager.resolve_category("01/FirstAid"), "01_Medical_and_Health/FirstAid")

    def test_cmd_init_and_index_and_verify(self):
        # Initialize repository structure
        repo_manager.cmd_init(self.repo_root)

        # Verify folders exist
        for code, folder in repo_manager.CATEGORIES.items():
            self.assertTrue((self.repo_root / folder).exists())

        # Create a sample document in 01_Medical_and_Health
        doc = self.repo_root / "01_Medical_and_Health" / "sample.md"
        doc.write_text("# Sample Medical Guide\nTreat burns with cool water.", encoding="utf-8")

        # Re-index
        repo_manager.cmd_index(self.repo_root)

        # Verify index artifacts were created
        index_dir = self.repo_root / "00_Index_and_Manifests"
        self.assertTrue((index_dir / "catalog.json").exists())
        self.assertTrue((index_dir / "INDEX.md").exists())
        self.assertTrue((index_dir / "MANIFEST.sha256").exists())
        self.assertTrue((index_dir / "index.html").exists())

        # Verify index.html escapes XSS safely
        html_content = (index_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("escapeHtml", html_content)
        self.assertIn("safeRelPath", html_content)

        # Verify manifest matches
        repo_manager.cmd_verify(self.repo_root)

        # Corrupt file and verify detection
        doc.write_text("# Corrupted Content", encoding="utf-8")
        with self.assertRaises(SystemExit):
            repo_manager.cmd_verify(self.repo_root)


class TestVaultAndDBSecurity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.db = MetadataDB(self.db_path)
        self.vault = VaultManager(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_frontmatter_escaping(self):
        # Test title with quotes, colons, newlines
        dangerous_title = 'Injection: "Quote" \n---\nmalicious_key: true'
        rel_path = self.vault.save_snippet_markdown(
            title=dangerous_title,
            content="Snippet content here.",
            category="text",
            tags=['safe_tag', 'tag "with" quote'],
            metadata={"source": "cli", "user_note": "Important: check this\nagain"}
        )
        saved_file = Path(self.test_dir) / rel_path
        self.assertTrue(saved_file.exists())
        content = saved_file.read_text(encoding="utf-8")

        # Check that YAML frontmatter is properly enclosed
        self.assertTrue(content.startswith("---\n"))
        # Header should have valid quoted title
        self.assertIn('title: "Injection: \\"Quote\\" \\n---\\nmalicious_key: true"', content)

    def test_like_query_escaping(self):
        # Insert test item with special characters
        self.db.record_item(
            content_hash="hash1",
            source_type="clipboard",
            vault_rel_path="snippets/item1.md",
            title="100% discount on 1_000 items",
            category="text"
        )
        self.db.record_item(
            content_hash="hash2",
            source_type="clipboard",
            vault_rel_path="snippets/item2.md",
            title="Regular note without percentages",
            category="text"
        )

        # Searching for literal "%" should only match item1
        res = self.db.search_items("%")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["content_hash"], "hash1")

        # Searching for literal "_" should only match item1
        res_underscore = self.db.search_items("_")
        self.assertEqual(len(res_underscore), 1)
        self.assertEqual(res_underscore[0]["content_hash"], "hash1")

    def test_idempotent_db_record(self):
        # Re-recording with same content_hash updates rather than raising IntegrityError
        id1 = self.db.record_item(
            content_hash="same_hash",
            source_type="clipboard",
            vault_rel_path="path1.md",
            title="Initial Title"
        )
        id2 = self.db.record_item(
            content_hash="same_hash",
            source_type="clipboard",
            vault_rel_path="path2.md",
            title="Updated Title"
        )
        items = self.db.list_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Updated Title")


if __name__ == "__main__":
    unittest.main()
