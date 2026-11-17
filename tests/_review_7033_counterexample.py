import io
from PIL import Image
from pypdf import PdfReader, PdfWriter
from src import document_processor as dp


def _pdf_with_image(tmp_path, name, text_layer):
    """One page holding one embedded image; optionally a long text layer (via pypdfium2 page text insert is
    awkward, so the text-heavy case is built with PIL->PDF and a monkeypatched extract_text)."""
    img = Image.new("RGB", (400, 300), "white")
    p = tmp_path / name
    img.save(p, "PDF")
    return p


def test_scanned_page_text_is_not_duplicated(tmp_path, monkeypatch):
    pdf = _pdf_with_image(tmp_path, "scan.pdf", False)
    calls = []
    monkeypatch.setattr(dp, "_local_ocr_text", lambda path: calls.append(path) or "INVOICE 4471 TOTAL 12.00")
    monkeypatch.setattr(dp, "analyze_image_with_vl", lambda *a, **k: "[Vision model unavailable]")
    out = dp._process_pdf(str(pdf))
    print("OCR calls:", len(calls)); print(out)
    assert out.count("INVOICE 4471") == 1


def test_text_heavy_page_with_logo_skips_vl(tmp_path, monkeypatch):
    pdf = _pdf_with_image(tmp_path, "report.pdf", True)
    monkeypatch.setattr("pypdf._page.PageObject.extract_text", lambda self, *a, **k: "Quarterly report. " * 40)
    vl = []
    monkeypatch.setattr(dp, "analyze_image_with_vl", lambda path, **k: vl.append(path) or "a logo")
    dp._process_pdf(str(pdf))
    print("VL calls on a 720-char text page:", len(vl))
    assert vl == []
