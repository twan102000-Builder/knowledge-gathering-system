import os
import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List

class MetadataDB:
    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT UNIQUE NOT NULL,
                    source_type TEXT NOT NULL,  -- 'clipboard', 'sd_card', 'manual_file'
                    title TEXT,
                    category TEXT,             -- 'text', 'code', 'url', 'image', 'document'
                    source_path TEXT,
                    vault_rel_path TEXT NOT NULL,
                    tags TEXT,                 -- Comma-separated or JSON list
                    metadata_json TEXT,        -- Extra structured payload (EXIF, URL headers, etc.)
                    created_at TIMESTAMP NOT NULL,
                    ingested_at TIMESTAMP NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_content_hash ON items(content_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_source_type ON items(source_type)
            """)
            conn.commit()

    def item_exists(self, content_hash: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM items WHERE content_hash = ?", (content_hash,))
            return cursor.fetchone() is not None

    def record_item(
        self,
        content_hash: str,
        source_type: str,
        vault_rel_path: str,
        title: Optional[str] = None,
        category: str = "text",
        source_path: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None
    ) -> int:
        tags_str = ",".join(tags) if tags else ""
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        c_at = (created_at or datetime.now()).isoformat()
        i_at = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO items (
                    content_hash, source_type, title, category,
                    source_path, vault_rel_path, tags, metadata_json,
                    created_at, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                content_hash, source_type, title, category,
                source_path, vault_rel_path, tags_str, meta_json,
                c_at, i_at
            ))
            conn.commit()
            return cursor.lastrowid

    def list_items(self, limit: int = 50, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if source_type:
                cursor.execute(
                    "SELECT * FROM items WHERE source_type = ? ORDER BY id DESC LIMIT ?",
                    (source_type, limit)
                )
            else:
                cursor.execute(
                    "SELECT * FROM items ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def search_items(self, query: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            wildcard = f"%{query}%"
            cursor.execute("""
                SELECT * FROM items
                WHERE title LIKE ? OR tags LIKE ? OR metadata_json LIKE ?
                ORDER BY id DESC LIMIT 50
            """, (wildcard, wildcard, wildcard))
            return [dict(r) for r in cursor.fetchall()]

    def stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), source_type FROM items GROUP BY source_type")
            counts = {row[1]: row[0] for row in cursor.fetchall()}
            cursor.execute("SELECT COUNT(*) FROM items")
            total = cursor.fetchone()[0]
            return {"total_items": total, "by_source": counts}
