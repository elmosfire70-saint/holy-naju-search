# 문헌 파일에서 본문과 원문 위치를 추출하고 스캔 PDF를 로컬 OCR로 처리한다.
import hashlib
import re
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
import pymupdf

EXTRACTOR_REVISION = "extract-2"


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def extract_html(raw, source="user_import"):
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.select_one(".view_tit") if source == "naju" else soup.title
    if source == "naju":
        body = soup.select_one(".board_txt_area")
        if body is None:
            raise ValueError("naju_body_missing")
    elif source == "vatican":
        body = soup.select_one(".container.vaticanrichtext, .testo")
        if body is None and soup.select("p.MsoNormal"):
            body = soup.new_tag("main")
            for node in soup.select("p.MsoNormal"):
                body.append(node.extract())
            for anchor in soup.select('a[name^="$"]'):
                number = anchor.find_parent("font")
                note = number.find_next_sibling("font") if number else None
                if note:
                    paragraph = soup.new_tag("p")
                    paragraph.string = clean(anchor.get_text() + " " + note.get_text(" "))
                    body.append(paragraph)
        if body is None:
            # ponytail: 구형 문헌의 가장 큰 본문 셀을 사용하며 새 템플릿은 샘플 검증 후 추가한다.
            cells = soup.select("td")
            body = max(cells, key=lambda n: len(n.get_text()), default=None)
        body = body if body is not None else soup.body
    else:
        body = soup.select_one("main, article")
        body = body if body is not None else soup.body
    if body is None:
        raise ValueError("html_body_missing")
    for node in body.select("script,style,nav,header,footer,.share,.copyright"):
        node.decompose()
    tags = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"]
    texts = [clean(n.get_text(" ")) for n in body.find_all(tags)
             if n.find_parent(tags) is None]
    texts = [t for t in texts if t]
    if not texts:
        texts = [clean(t) for t in body.stripped_strings if clean(t)]
    return {
        "title": clean(title.get_text(" ")) if title else "",
        "pages": [],
        "passages": [{"ordinal": i + 1, "locator": {"block": i + 1}, "text": t}
                     for i, t in enumerate(texts)],
    }


def extract_pdf(path, languages="eng+kor", tessdata=None):
    pages, passages = [], []
    with pymupdf.open(path) as document:
        if document.needs_pass:
            raise ValueError("encrypted_pdf")
        title = document.metadata.get("title", "")
        for page in document:
            textpage = page.get_textpage()
            needs_ocr = bool(page.get_images()) or not page.get_text().strip()
            info = {"page": page.number + 1, "method": "text", "status": "succeeded",
                    "engine_revision": pymupdf.VersionBind, "review_status": "unreviewed"}
            if needs_ocr:
                info.update(method="ocr", languages=languages)
                missing = [lang for lang in languages.split("+")
                           if not tessdata or not (Path(tessdata) / f"{lang}.traineddata").is_file()]
                if missing:
                    info.update(status="ocr_required", error="missing_tessdata:" + "+".join(missing))
                else:
                    try:
                        textpage = page.get_textpage_ocr(
                            language=languages, dpi=300, full=False, tessdata=str(tessdata))
                    except (RuntimeError, ValueError) as error:
                        info.update(status="ocr_failed", error=str(error))
            for block in page.get_text("blocks", textpage=textpage, sort=True):
                text = clean(block[4])
                if text:
                    passages.append({"ordinal": len(passages) + 1,
                                     "locator": {"page": page.number + 1,
                                                 "bbox": [round(v, 2) for v in block[:4]]},
                                     "text": text})
            info["raw_text"] = page.get_text(textpage=textpage)
            info["characters"] = len(info["raw_text"])
            pages.append(info)
    return {"title": title, "pages": pages, "passages": passages}


def extract_file(path, source="user_import", languages="eng+kor", tessdata=None):
    path = Path(path)
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        result = extract_html(raw, source)
    elif suffix == ".pdf":
        result = extract_pdf(path, languages, tessdata)
    elif suffix == ".txt":
        text = raw.decode("utf-8-sig")
        result = {"title": path.stem, "pages": [], "passages": [
            {"ordinal": i + 1, "locator": {"line": i + 1}, "text": clean(t)}
            for i, t in enumerate(text.splitlines()) if clean(t)]}
    elif suffix == ".docx":
        document = Document(path)
        texts = []
        for block in document.iter_inner_content():
            if hasattr(block, "rows"):
                texts.extend(" | ".join(c.text for c in row.cells) for row in block.rows)
            else:
                texts.append(block.text)
        result = {"title": path.stem, "pages": [], "passages": [
            {"ordinal": i + 1, "locator": {"block": i + 1}, "text": clean(t)}
            for i, t in enumerate(texts) if clean(t)]}
    else:
        raise ValueError(f"unsupported_format:{suffix}")
    result.update(sha256=hashlib.sha256(raw).hexdigest(), extractor_revision=EXTRACTOR_REVISION)
    result["characters"] = sum(len(p["text"]) for p in result["passages"])
    result["status"] = "partial" if any(p["status"] != "succeeded" for p in result["pages"]) else "extracted"
    if not result["characters"]:
        result["status"] = "empty" if result["status"] == "extracted" else "partial"
    return result
