"""Focused citation previews and clause-sized ingestion chunks."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingest import chunk_segment
from app.rag import _citation_excerpt, _citations


CONTRACT_TEXT = """GETCOINS
This Agreement is between GetCoins and Owner's Market, operating at
3167 Mount Pleasant Street NW, Washington, DC 20010 (the \"Location\").

2. Rent
Rent for the Leased Space will equal 15.5% of Kiosk Transaction Fees attributable
to completed transactions at the Location. No fixed monthly rent is due.

3. Term
The agreement renews for successive three-year terms unless either party gives
ninety days' written notice.
"""


def hit(**extra):
    base = {
        "id": 9,
        "doc_id": 2,
        "doc_name": "agreement.pdf",
        "doc_title": "Mount Pleasant Laundry Agreement",
        "page": 1,
        "section": "2. Rent",
        "score": 1.0,
        "text": CONTRACT_TEXT,
    }
    return {**base, **extra}


class CitationPreviews(unittest.TestCase):
    def test_exact_commission_value_selects_only_the_supporting_sentence(self):
        excerpt = _citation_excerpt(
            hit(_citation_terms=["15.5%"]),
            "What commission rate does Mount Pleasant Laundry receive?",
        )
        self.assertIn("15.5%", excerpt)
        self.assertIn("Kiosk Transaction Fees", excerpt)
        self.assertNotIn("3167 Mount Pleasant", excerpt)
        self.assertNotIn("three-year terms", excerpt)

    def test_exact_address_selects_only_the_location_sentence(self):
        excerpt = _citation_excerpt(
            hit(_citation_terms=["3167 Mount Pleasant Street NW"]),
            "What is the street address of Mount Pleasant Laundry?",
        )
        self.assertIn("3167 Mount Pleasant Street NW", excerpt)
        self.assertNotIn("15.5%", excerpt)

    def test_hover_text_is_the_focused_preview_not_the_full_chunk(self):
        citation = _citations(
            [hit(_citation_terms=["15.5%"])],
            "What is the commission rate?",
        )[0]
        self.assertEqual(citation["text"], citation["excerpt"])
        self.assertLess(len(citation["text"]), len(CONTRACT_TEXT))
        self.assertEqual(citation["highlights"], ["15.5% of Kiosk Transaction Fees"])

    def test_notice_highlight_is_the_decisive_phrase_not_the_whole_clause(self):
        source = (
            "The Agreement automatically renews for successive terms unless either party gives "
            "the other at least ninety (90) days' written notice of nonrenewal before expiry."
        )
        citation = _citations(
            [hit(text=source, _citation_terms=["90", "ninety"])],
            "What is the notice period?",
        )[0]
        self.assertEqual(
            citation["highlights"],
            ["at least ninety (90) days' written notice of nonrenewal"],
        )

    def test_non_adjacent_support_fields_remain_separate_highlights(self):
        source = """Owner Information
Full Name: Lucia Torres
Title: Managing Member
Phone Number: 202-555-0124
E-mail Address: lucia.torres@example.test
"""
        citation = _citations(
            [hit(text=source, _citation_terms=["Lucia Torres", "lucia.torres@example.test"])],
            "Who is the notice contact?",
        )[0]
        self.assertEqual(
            citation["highlights"],
            ["Full Name: Lucia Torres", "E-mail Address: lucia.torres@example.test"],
        )

    def test_numbered_contract_clauses_remain_separate_chunks(self):
        chunks = chunk_segment(
            {"page": 1, "section": None, "text": CONTRACT_TEXT},
            size=1000,
            overlap=150,
        )
        joined = [chunk["text"] for chunk in chunks]
        self.assertGreaterEqual(len(joined), 3)
        self.assertTrue(any("15.5%" in text and "three-year" not in text for text in joined))
        self.assertTrue(any("three-year" in text and "15.5%" not in text for text in joined))


if __name__ == "__main__":
    unittest.main()
