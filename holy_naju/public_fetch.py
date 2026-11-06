# 허용된 공개 출처에서 robots와 요청 간격을 지켜 제한된 HTML을 내려받는다.
import hashlib
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

HOSTS = {"naju": "najumary.or.kr", "vatican": "www.vatican.va"}
USER_AGENT = "HolyNajuSearch/0.1 (personal research)"
MAX_BYTES = 25 * 1024 * 1024


class CollectionBlocked(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise CollectionBlocked("redirect_requires_review")


class PublicClient:
    def __init__(self, evidence_dir):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.robots = {}
        self.last_request = {host: time.monotonic() for host in HOSTS.values()}
        self.delays = {}

    def _get(self, url, maximum=MAX_BYTES):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in HOSTS.values() or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.fragment):
            raise ValueError("outside_collection_hosts")
        host = parsed.hostname
        time.sleep(max(0, self.delays.get(host, 2) - (time.monotonic() - self.last_request.get(host, 0))))
        self.last_request[host] = time.monotonic()
        try:
            with self.opener.open(Request(url, headers={"User-Agent": USER_AGENT}), timeout=25) as response:
                raw = response.read(maximum + 1)
                media_type = response.headers.get_content_type()
        except HTTPError as error:
            if error.code in (401, 403, 429):
                raise CollectionBlocked(f"access_limited_http_{error.code}") from error
            raise
        if len(raw) > maximum:
            raise ValueError("collection_response_too_large")
        return raw, media_type

    def fetch(self, url, *, media_types=("text/html", "application/xhtml+xml")):
        host = urlsplit(url).hostname
        if host not in HOSTS.values():
            raise ValueError("outside_collection_hosts")
        if host not in self.robots:
            try:
                raw, media = self._get(f"https://{host}/robots.txt", 65536)
                text = raw.decode("utf-8-sig")
                if media != "text/plain" or "user-agent:" not in text.lower() or "<html" in text.lower():
                    raise ValueError("invalid_robots_response")
                (self.evidence_dir / (hashlib.sha256(raw).hexdigest() + ".robots.txt")).write_bytes(raw)
                policy = RobotFileParser()
                policy.parse(text.splitlines())
                self.delays[host] = max(2, policy.crawl_delay(USER_AGENT) or policy.crawl_delay("*") or 2)
                self.robots[host] = policy
            except (OSError, ValueError, RuntimeError) as error:
                raise CollectionBlocked("robots_unavailable:" + str(error)) from error
        if not self.robots[host].can_fetch(USER_AGENT, url):
            raise CollectionBlocked("robots_disallowed")
        raw, media = self._get(url)
        if media not in media_types:
            raise ValueError("expected_html_collection")
        return raw
