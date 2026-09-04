"""Metadata extraction receives the same redacted text as embeddings."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ingest


class IngestPrivacy(unittest.TestCase):
    def test_metadata_input_is_redacted_before_cloud_capable_extraction(self):
        raw = "Checking account number: 123456789. Routing number: 021000021."
        seen = {"embedded": [], "metadata": None, "chunks": []}

        def fake_embed(texts):
            seen["embedded"].extend(texts)
            return np.zeros((len(texts), 2), dtype=np.float32)

        def fake_metadata(text):
            seen["metadata"] = text
            return {}

        def fake_add_chunks(_doc_id, chunks, _vectors):
            seen["chunks"].extend(chunks)

        with (
            patch.object(ingest, "extract_segments", return_value=([{"page": 1, "section": None, "text": raw}], 0)),
            patch.object(ingest, "chunk_segment", return_value=[{"page": 1, "section": None, "text": raw}]),
            patch.object(ingest, "embed_texts", side_effect=fake_embed),
            patch.object(ingest, "extract_metadata", side_effect=fake_metadata),
            patch.object(ingest.store, "add_document", return_value=7),
            patch.object(ingest.store, "add_chunks", side_effect=fake_add_chunks),
            patch.object(ingest.store, "update_meta"),
            patch.object(ingest.store, "delete_document"),
        ):
            result = ingest.ingest_file(Path("synthetic.txt"), "Synthetic agreement")

        checked = [*seen["embedded"], seen["metadata"], *(c["text"] for c in seen["chunks"])]
        for text in checked:
            self.assertNotIn("123456789", text)
            self.assertNotIn("021000021", text)
            self.assertIn("[REDACTED]", text)
        self.assertTrue(result["pii_redacted"])

    def test_failed_chunk_persistence_rolls_back_document_row(self):
        raw = "Synthetic agreement clause."
        with (
            patch.object(ingest, "extract_segments", return_value=([{"page": 1, "section": "1", "text": raw}], 0)),
            patch.object(ingest, "chunk_segment", return_value=[{"page": 1, "section": "1", "text": raw}]),
            patch.object(ingest, "embed_texts", return_value=np.zeros((1, 2), dtype=np.float32)),
            patch.object(ingest.store, "add_document", return_value=41),
            patch.object(ingest.store, "add_chunks", side_effect=OSError("simulated disk failure")),
            patch.object(ingest.store, "delete_document") as rollback,
        ):
            with self.assertRaises(OSError):
                ingest.ingest_file(Path("synthetic.txt"), "Synthetic agreement",
                                   include_metadata=False)
        rollback.assert_called_once_with(41)


if __name__ == "__main__":
    unittest.main()
