"""PDF : libellé énorme et logo absent/corrompu ne cassent jamais un document."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pypdf  # noqa: E402

from app import pdfs  # noqa: E402


def _build(path):
    long = "Plaque BA13 " + "X" * 400 + " " + "mot " * 80
    pdfs.build_document_pdf(Path(path), company={}, doc_label="Devis", number="UC-2026-0714-OD", title="t", status="draft",
        meta_lines=[], party_left=("Client", "A"), party_right=("Client", "B"),
        headers=["N°", "Désignation", "Qté", "Unité", "PU", "Total"],
        rows=[["1", long, "1,00", "m2", "100,00", "100,00"]], col_widths=[10, 90, 15, 15, 25, 25], totals=[("Total", "100,00")])
    return pypdf.PdfReader(str(path))


def test_very_long_label_wraps(tmp_path):
    assert len(_build(tmp_path / "a.pdf").pages) >= 1


def test_missing_or_corrupt_logo_falls_back(tmp_path, monkeypatch):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG garbage")
    monkeypatch.setattr(pdfs, "LOGO", bad)
    assert _build(tmp_path / "b.pdf").pages
    monkeypatch.setattr(pdfs, "LOGO", tmp_path / "absent.png")
    assert _build(tmp_path / "c.pdf").pages


def test_money_round_is_commercial():
    from app.services import money_round
    assert money_round(2.675) == 2.68 and round(2.675, 2) == 2.67
    assert money_round(1.005) == 1.01 and money_round(1000.0) == 1000.0
