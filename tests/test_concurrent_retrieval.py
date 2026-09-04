"""Regression test for concurrent SQLite/FAISS retrieval.

The first production-shaped load drill exposed a shared-connection failure:
parallel read-only searches intermittently raised ``sqlite3.InterfaceError``.
This test keeps that failure mode in the suite without using a model or network.
"""
from __future__ import annotations

import importlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


store_module = importlib.import_module("app.store")


class ConcurrentRetrieval(unittest.TestCase):
    def test_parallel_hybrid_searches_use_isolated_reader_connections(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = SimpleNamespace(
                db_path=root / "store.db",
                index_path=root / "faiss.index",
                upload_dir=root / "uploads",
            )
            settings.upload_dir.mkdir()

            with patch.object(store_module, "settings", settings):
                store = store_module.Store()
                try:
                    document_count = 48
                    vectors = np.eye(document_count, dtype="float32")
                    doc_ids = []
                    for i in range(document_count):
                        token = f"locator{i:04d}"
                        doc_id = store.add_document(
                            f"Synthetic Agreement {i}", f"synthetic-{i}.txt", token
                        )
                        store.add_chunks(
                            doc_id,
                            [{
                                "page": 1,
                                "section": "Locator",
                                "chunk_index": 0,
                                "text": f"Contract reference {token} applies.",
                            }],
                            vectors[i:i + 1],
                        )
                        doc_ids.append(doc_id)

                    def retrieve(task: int) -> bool:
                        i = task % document_count
                        hits = store.search(
                            vectors[i], k=3, query_text=f"locator{i:04d}"
                        )
                        return bool(hits and hits[0]["doc_id"] == doc_ids[i])

                    with ThreadPoolExecutor(max_workers=16) as pool:
                        outcomes = list(pool.map(retrieve, range(384)))

                    self.assertEqual(len(outcomes), 384)
                    self.assertTrue(all(outcomes))
                    self.assertTrue(store.health_snapshot()["ready"])
                finally:
                    store.close()


if __name__ == "__main__":
    unittest.main()
