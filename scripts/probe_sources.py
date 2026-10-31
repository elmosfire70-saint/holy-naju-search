# 공식 자료 샘플을 제한적으로 내려받고 본문과 근거 위치를 로컬 검증 결과로 저장한다.
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holy_naju.extraction import extract_file

HOSTS = {"www.vatican.va", "vatican.va", "press.vatican.va", "najumary.or.kr", "www.najumary.or.kr"}
MAX_BYTES = 25 * 1024 * 1024


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.port not in (None, 443):
        raise ValueError("outside_public_source_scope")
    if parsed.username or parsed.password:
        raise ValueError("credentials_not_allowed")


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download(url):
    validate_url(url)
    try:
        request = Request(url, headers={"User-Agent": "HolyNajuSearch/0.1 (personal research)"})
        with build_opener(PublicRedirect).open(request, timeout=30) as response:
            raw = response.read(MAX_BYTES + 1)
            final_url = response.url
        transport = "urllib"
    except HTTPError as error:
        if error.code != 403 or urlparse(url).hostname not in {"najumary.or.kr", "www.najumary.or.kr"}:
            raise
        # 공개 페이지의 관찰된 403에만 제한된 TLS 전송을 사용한다. 로그인·CAPTCHA는 처리하지 않는다.
        from curl_cffi import requests
        current = url
        for _ in range(5):
            validate_url(current)
            response = requests.get(current, impersonate="safari", allow_redirects=False, timeout=30)
            if response.status_code in {301, 302, 303, 307, 308}:
                from urllib.parse import urljoin
                current = urljoin(current, response.headers["Location"])
                continue
            if response.status_code != 200:
                raise ValueError(f"access_limited_http_{response.status_code}")
            raw, final_url = response.content, current
            break
        else:
            raise ValueError("redirect_limit")
        transport = "curl_cffi_safari"
    if len(raw) > MAX_BYTES:
        raise ValueError("sample_too_large")
    validate_url(final_url)
    return raw, final_url, transport


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="config/source-catalog.json")
    parser.add_argument("--output", default="data/probes")
    parser.add_argument("--tessdata", default="data/models/tessdata")
    parser.add_argument("--sample", help="전체 재수집 대신 특정 샘플 ID만 검증")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    samples = [s for s in catalog["samples"] if not args.sample or s["id"] == args.sample]
    if not samples:
        parser.error("unknown_sample")
    results = []
    for sample in samples:
        started = time.monotonic()
        item = {"id": sample["id"], "url": sample["url"],
                "retrieved_at": datetime.now(timezone.utc).isoformat()}
        try:
            raw, final_url, transport = download(sample["url"])
            suffix = ".pdf" if raw.startswith(b"%PDF-") else ".html"
            path = output / (hashlib.sha256(raw).hexdigest() + suffix)
            path.write_bytes(raw)
            extracted = extract_file(path, sample["source"], sample.get("languages", "eng"), args.tessdata)
            text = extracted["title"] + " " + " ".join(p["text"] for p in extracted["passages"])
            valid = extracted["status"] == "extracted" and extracted["characters"] >= sample.get("min_characters", 100)
            valid = valid and all(word.casefold() in text.casefold() for word in sample.get("expected_contains", []))
            status = "validated" if valid else "content_rejected"
            item.update(status=status, expected=sample.get("expected", "validated"),
                        passed=status == sample.get("expected", "validated"),
                        final_url=final_url, transport=transport, raw_file=path.name,
                        characters=extracted["characters"], passages=len(extracted["passages"]),
                        pages=len(extracted["pages"]), sha256=extracted["sha256"])
            (output / (path.name + ".json")).write_text(
                json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError, RuntimeError) as error:
            item.update(status=f"access_limited_http_{error.code}" if isinstance(error, HTTPError) else "failed",
                        error=str(error), passed=False)
        item["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results.append(item)
        print(json.dumps(item, ensure_ascii=True), flush=True)
        # 교황청 robots의 최소 2초 간격을 포함해 모든 샘플을 직렬 수집한다.
        time.sleep(2)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "samples": results}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
