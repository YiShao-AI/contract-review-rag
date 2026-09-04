"""Isolated storage and failure-recovery drills; no model or network calls."""
from __future__ import annotations

import hashlib
import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


store_module = importlib.import_module("app.store")


class IsolatedStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = SimpleNamespace(
            db_path=self.root / "store.db",
            index_path=self.root / "faiss.index",
            upload_dir=self.root / "uploads",
        )
        self.settings.upload_dir.mkdir()
        self.patch = patch.object(store_module, "settings", self.settings)
        self.patch.start()
        self.store = store_module.Store()

    def tearDown(self):
        self.store.close()
        self.patch.stop()
        self.temp.cleanup()

    def test_empty_store_is_ready(self):
        snapshot = self.store.health_snapshot()
        self.assertTrue(snapshot["ready"])
        self.assertEqual((snapshot["chunks"], snapshot["fts_rows"], snapshot["vectors"]),
                         (0, 0, 0))

    def test_delete_propagates_to_file_rows_fts_and_vectors(self):
        upload = self.settings.upload_dir / "synthetic.txt"
        upload.write_text("Synthetic clause", encoding="utf-8")
        doc_id = self.store.add_document("Synthetic", upload.name, "abc123")
        chunks = [{"page": None, "section": "1", "chunk_index": 0,
                   "text": "Synthetic clause"}]
        vectors = np.array([[1.0, 0.0]], dtype="float32")
        self.store.add_chunks(doc_id, chunks, vectors)

        self.assertTrue(self.store.delete_document(doc_id))
        snapshot = self.store.health_snapshot()
        self.assertTrue(snapshot["ready"])
        self.assertEqual((snapshot["documents"], snapshot["chunks"],
                          snapshot["fts_rows"], snapshot["vectors"]), (0, 0, 0, 0))
        self.assertFalse(upload.exists())

    def test_interrupted_index_write_preserves_last_good_index(self):
        doc_id = self.store.add_document("Synthetic", "synthetic.txt", "abc123")
        chunks = [{"page": None, "section": "1", "chunk_index": 0,
                   "text": "Synthetic clause"}]
        self.store.add_chunks(doc_id, chunks,
                              np.array([[1.0, 0.0]], dtype="float32"))
        before = hashlib.sha256(self.settings.index_path.read_bytes()).hexdigest()

        def fail_after_partial_write(_index, path):
            Path(path).write_bytes(b"partial index")
            raise OSError("simulated interrupted write")

        with patch.object(store_module.faiss, "write_index",
                          side_effect=fail_after_partial_write):
            with self.assertRaises(OSError):
                self.store._persist_index()

        after = hashlib.sha256(self.settings.index_path.read_bytes()).hexdigest()
        self.assertEqual(after, before)


class CorruptIndexRecovery(unittest.TestCase):
    def test_corrupt_index_is_quarantined_and_nonempty_store_is_not_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = SimpleNamespace(
                db_path=root / "store.db", index_path=root / "faiss.index",
                upload_dir=root / "uploads",
            )
            settings.upload_dir.mkdir()
            with patch.object(store_module, "settings", settings):
                seeded = store_module.Store()
                doc_id = seeded.add_document("Synthetic", "synthetic.txt", "abc123")
                seeded.add_chunks(
                    doc_id,
                    [{"page": None, "section": "1", "chunk_index": 0,
                      "text": "Synthetic clause"}],
                    np.array([[1.0, 0.0]], dtype="float32"),
                )
                seeded.close()
                settings.index_path.write_bytes(b"not a faiss index")

                recovered = store_module.Store()
                try:
                    self.assertFalse(settings.index_path.exists())
                    self.assertTrue(settings.index_path.with_suffix(".corrupt").exists())
                    snapshot = recovered.health_snapshot()
                    self.assertFalse(snapshot["ready"])
                    self.assertEqual(snapshot["vector_index"], "inconsistent")
                    self.assertEqual((snapshot["chunks"], snapshot["vectors"]), (1, 0))
                finally:
                    recovered.close()


if __name__ == "__main__":
    unittest.main()
