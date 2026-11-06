# 공식 신앙교리부 목록에서 관련 문헌 후보를 찾되 본문과 DB는 저장하지 않는다.
import argparse
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from holy_naju.public_fetch import PublicClient

CATALOG_URL = 'https://www.vatican.va/roman_curia/congregations/cfaith/doc_doc_index.htm'
# 용어 대응 근거 및 관련어/동의어 구분은 docs/live-search-redesign.md에 기록한다.
ALIASES = {'공동구속자', 'co-redemptrix', 'coredemptrix', 'corredentrice'}


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


def catalog_candidates(raw, query):
    if not isinstance(query, str) or not query.strip() or len(query) > 200 or any(ord(c) < 32 for c in query):
        raise ValueError('invalid_query')
    normalized = normalize(query)
    related = normalized.replace(' ', '') in ALIASES
    soup = BeautifulSoup(raw, 'html.parser')
    candidates = {}
    recognized = 0
    for anchor in soup.select('a[href]'):
        url = urljoin(CATALOG_URL, anchor['href'])
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'www.vatican.va'
                or parsed.query or parsed.fragment or not re.fullmatch(
                    r'/roman_curia/congregations/cfaith/documents/[a-zA-Z0-9_-]+_en\.html', parsed.path)):
            continue
        recognized += 1
        title = anchor.get_text(' ', strip=True)
        title_normal = normalize(title)
        exact = normalized in title_normal
        broad = related and ('marian titles' in title_normal or 'co-redemptrix' in title_normal)
        if not exact and not broad:
            continue
        candidates.setdefault(url, {
            'url': url, 'title': title, 'language': 'en',
            'discovered_from': CATALOG_URL, 'discovery_method': 'official_catalog',
            'match_kind': 'title_phrase' if exact else 'related_term',
            'verification_status': 'body_unverified',
        })
    if not recognized:
        raise ValueError('empty_or_unrecognized_catalog')
    return sorted(candidates.values(), key=lambda c: (c['match_kind'] != 'title_phrase', c['title']))


def discover(query, client):
    # ponytail: 확인된 영어 목록 한 페이지만 지원한다. 다른 부서/언어는 경로 검증 후 추가한다.
    hits = catalog_candidates(client.fetch(CATALOG_URL), query)
    return {'query': query, 'candidates': hits, 'coverage': 'ddf_english_catalog_only',
            'body_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='공식 목록 후보 발견. 본문 검색/보관은 수행하지 않습니다.')
    parser.add_argument('query')
    args = parser.parse_args()
    print(json.dumps(discover(args.query, PublicClient('data/discovery-evidence')), ensure_ascii=False, indent=2))
