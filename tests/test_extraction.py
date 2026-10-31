# 문헌 본문 분리와 파일 추출 및 스캔·혼합 PDF의 로컬 OCR을 검증한다.
from pathlib import Path
import tempfile
import unittest

from docx import Document
import pymupdf

from holy_naju.extraction import extract_file, extract_html
from scripts.probe_sources import validate_url

TESSDATA = Path("data/models/tessdata")


def scan_image(text, korean=False):
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=180)
        page.insert_text((25, 65), text, fontsize=22, fontname="korea" if korean else "helv")
        return page.get_pixmap(dpi=300).tobytes("png")


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_public_source_boundary(self):
        validate_url("https://www.vatican.va/archive/ccc/index.htm")
        for url in ["http://www.vatican.va/", "https://www.vatican.va.evil.example/",
                    "https://127.0.0.1/", "https://user:secret@www.vatican.va/"]:
            with self.assertRaises(ValueError):
                validate_url(url)

    def test_naju_excludes_other_widgets_and_comments(self):
        raw = '<title>site</title><div class="fr-view">메뉴</div><h1 class="view_tit">제목</h1><div class="board_txt_area fr-view"><h5>본문 <b>사랑</b></h5><p>각주</p></div><div>댓글</div>'
        result = extract_html(raw, "naju")
        self.assertEqual([p["text"] for p in result["passages"]], ["본문 사랑", "각주"])
        self.assertEqual(result["title"], "제목")
        with self.assertRaisesRegex(ValueError, "naju_body_missing"):
            extract_html('<div class="fr-view">로그인</div>', "naju")

    def test_vatican_old_and_new_templates(self):
        for raw in ['<body><table><td>Menu</td><td><p>1. Revelation and Scripture.</p><p>Footnote.</p></td></table></body>',
                    '<body><nav>Menu</nav><div class="container vaticanrichtext"><p>1. Revelation and Scripture.</p><p>Footnote.</p></div></body>']:
            result = extract_html(raw, "vatican")
            self.assertEqual(len(result["passages"]), 2)
            self.assertNotIn("Menu", str(result))

    def test_intratext_body_outside_navigation_table_and_footnotes(self):
        raw = '<body><table><td>Navigation menu</td></table><p class="MsoNormal">51 Revelation of God</p><font><a name="$13">2</a></font><font>Reference DV 2</font></body>'
        result = extract_html(raw, "vatican")
        self.assertEqual([p["text"] for p in result["passages"]],
                         ["51 Revelation of God", "2 Reference DV 2"])

    def test_text_docx_and_table(self):
        path = self.root / "sample.txt"
        path.write_text("첫 문단\n\n둘째 문단", encoding="utf-8-sig")
        self.assertEqual(extract_file(path)["passages"][1]["locator"]["line"], 3)
        document = Document()
        document.add_paragraph("기도와 사랑")
        document.add_table(rows=1, cols=1).cell(0, 0).text = "표의 본문"
        path = self.root / "sample.docx"
        document.save(path)
        result = extract_file(path)
        self.assertEqual([p["text"] for p in result["passages"]], ["기도와 사랑", "표의 본문"])

    def test_missing_ocr_is_partial_not_empty_success(self):
        path = self.root / "scan.pdf"
        with pymupdf.open() as document:
            page = document.new_page(width=600, height=180)
            page.insert_image(page.rect, stream=scan_image("HOLY NAJU SEARCH 31415"))
            document.save(path)
        result = extract_file(path, tessdata=None)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["pages"][0]["status"], "ocr_required")
        self.assertEqual(result["characters"], 0)

    @unittest.skipUnless((TESSDATA / "eng.traineddata").exists(), "영어 OCR 데이터 필요")
    def test_scanned_and_mixed_page_preserves_positions_without_duplicates(self):
        path = self.root / "mixed.pdf"
        with pymupdf.open() as document:
            page = document.new_page(width=600, height=360)
            page.insert_text((25, 40), "Digital header 12345", fontsize=20)
            page.insert_image(pymupdf.Rect(0, 100, 600, 280),
                              stream=scan_image("The Eucharist unites the Church 31415"))
            document.save(path)
        result = extract_file(path, languages="eng", tessdata=TESSDATA)
        text = " ".join(p["text"] for p in result["passages"])
        self.assertEqual(result["status"], "extracted")
        self.assertEqual(text.count("Digital header"), 1)
        self.assertEqual(text.count("Eucharist"), 1)
        self.assertIn("31415", text)
        self.assertTrue(all(p["locator"]["page"] == 1 and len(p["locator"]["bbox"]) == 4
                            for p in result["passages"]))

    @unittest.skipUnless((TESSDATA / "kor.traineddata").exists(), "한국어 OCR 데이터 필요")
    def test_korean_scan(self):
        path = self.root / "korean.pdf"
        with pymupdf.open() as document:
            page = document.new_page(width=600, height=180)
            page.insert_image(page.rect, stream=scan_image("사랑과 기도로 하루를 시작합니다.", korean=True))
            document.save(path)
        result = extract_file(path, languages="kor+eng", tessdata=TESSDATA)
        text = "".join(p["text"] for p in result["passages"]).replace(" ", "")
        self.assertEqual(result["status"], "extracted")
        self.assertIn("사랑", text)
        self.assertIn("기도", text)


if __name__ == "__main__":
    unittest.main()
