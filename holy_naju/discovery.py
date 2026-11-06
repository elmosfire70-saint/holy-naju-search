# 공식 신앙교리부 목록에서 관련 문헌 후보를 찾되 본문과 DB는 저장하지 않는다.
import argparse
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from holy_naju.public_fetch import CollectionBlocked, PublicClient
from holy_naju.extraction import extract_html

CATALOG_URL = 'https://www.vatican.va/roman_curia/congregations/cfaith/doc_doc_index.htm'
# 용어 대응 근거 및 관련어/동의어 구분은 docs/live-search-redesign.md에 기록한다.
ALIASES = {'공동구속자', 'co-redemptrix', 'coredemptrix', 'corredentrice'}


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


def validate_query(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 200 or any(ord(c) < 32 for c in query):
        raise ValueError('invalid_query')


def catalog_candidates(raw, query):
    validate_query(query)
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
    validate_query(query)
    # ponytail: 확인된 영어 목록 한 페이지만 지원한다. 다른 부서/언어는 경로 검증 후 추가한다.
    hits = catalog_candidates(client.fetch(CATALOG_URL), query)
    return {'query': query, 'candidates': hits, 'coverage': 'ddf_english_catalog_only',
            'body_verified': False}


def document_url(value):
    if not isinstance(value, str):
        raise ValueError('invalid_result_url')
    url = urljoin('https://www.vatican.va/', value)
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc != 'www.vatican.va' or p.query or p.fragment
            or not re.fullmatch(r'/(?:content|roman_curia|archive)/[A-Za-z0-9_/-]+\.html?', p.path)
            or '/documents/' not in p.path):
        raise ValueError('invalid_result_url')
    return url


def search_candidates(payload, request_url):
    if not isinstance(payload, dict) or not isinstance(payload.get('response'), dict):
        raise ValueError('invalid_search_response')
    response = payload['response']
    docs, total = response.get('docs'), response.get('numFound')
    if not isinstance(docs, list) or type(total) is not int or total < len(docs) or len(docs) > 10:
        raise ValueError('invalid_search_response')
    hits = []
    for row in docs:
        if not isinstance(row, dict):
            raise ValueError('invalid_search_result')
        try:
            url = document_url(row.get('id'))
        except ValueError:
            continue
        title = row.get('title_txt_en')
        if not isinstance(title, str) or not title.strip():
            continue
        hits.append({'url': url, 'title': title, 'language': 'en',
                     'discovered_from': request_url, 'discovery_method': 'official_search',
                     'match_kind': 'search_candidate', 'verification_status': 'body_unverified'})
    return hits, total


def verify_candidate(candidate, query, client, capture=None):
    url = document_url(candidate['url'])
    raw = client.fetch(url)
    if re.search(rb'captcha|verify you are human|access denied|just a moment', raw, re.I):
        raise CollectionBlocked('challenge_page')
    extracted = extract_html(raw, 'vatican')
    if sum(len(p['text']) for p in extracted['passages']) < 100:
        raise ValueError('empty_or_short_document')
    alias = normalize(query).replace(' ', '') in ALIASES
    pattern = re.compile(r'co[\s\-\u2010-\u2015]*redemptrix|corredentrice' if alias else re.escape(query.strip()), re.I)
    evidence = []
    for passage in extracted['passages']:
        matches = list(pattern.finditer(passage['text']))
        if matches:
            evidence.append({**passage, 'ranges': [[m.start(), m.end()] for m in matches]})
    title_match = normalize(query) in normalize(extracted['title'])
    if capture is not None and (evidence or title_match):
        capture(url, raw)
    return {**candidate, 'verification_status': 'matched' if evidence or title_match else 'no_match',
            'raw_sha256': hashlib.sha256(raw).hexdigest(), 'evidence': evidence,
            'verified_title': extracted['title'], 'title_match': title_match,
            'review_status': 'unreviewed'}


def live_search(query, client, *, capture=None):
    validate_query(query)
    # 검색 연산자를 전달하지 않는다. 별칭은 정확 구절로 요청해 하이픈의 잡음을 줄인다.
    alias = normalize(query).replace(' ', '') in ALIASES
    words = re.findall(r'[^\W_]+', query, re.UNICODE)
    if not words:
        raise ValueError('invalid_query')
    remote_query = '"Co-redemptrix"' if alias else ' AXNXD '.join(words)
    request_url = 'https://www.vatican.va/bin/servlet/solr/search?' + urlencode({
        'queryroute': 'vatican_va-search-main', 'q': remote_query, 'fq': 'lang_s:en',
        'sort': 'score desc,id asc', 'rows': 10, 'start': 0})
    errors, hits, total = [], [], None
    try:
        hits, total = search_candidates(json.loads(client.fetch(request_url, media_types=('application/json',))), request_url)
    except CollectionBlocked:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        errors.append({'stage': 'search', 'error': str(error)})
    try:
        hits = discover(query, client)['candidates'] + hits
    except CollectionBlocked:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        errors.append({'stage': 'catalog', 'error': str(error)})
    unique = {}
    for hit in hits:
        unique.setdefault(hit['url'], hit)
    results = []
    for hit in list(unique.values())[:5]:
        try:
            results.append(verify_candidate(hit, query, client, capture))
        except CollectionBlocked:
            raise
        except (OSError, ValueError, RuntimeError) as error:
            results.append({**hit, 'verification_status': 'failed', 'error': str(error)})
            errors.append({'stage': 'body', 'url': hit['url'], 'error': str(error)})
    results.sort(key=lambda h: h['verification_status'] != 'matched')
    return {'query': query, 'remote_query': remote_query, 'results': results, 'errors': errors,
            'status': ('failed' if not results else 'partial') if errors else 'completed', 'remote_total': total,
            'coverage': 'english_search_first_page_and_ddf_catalog',
            'candidate_count': len(unique), 'verification_limit': 5, 'complete_coverage': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='공식 목록 후보 발견. 본문 검색/보관은 수행하지 않습니다.')
    parser.add_argument('query')
    parser.add_argument('--live', action='store_true', help='자체 검색과 최대5개 원문 확인. DB 저장 없음')
    args = parser.parse_args()
    action = live_search if args.live else discover
    print(json.dumps(action(args.query, PublicClient('data/discovery-evidence')), ensure_ascii=False, indent=2))
