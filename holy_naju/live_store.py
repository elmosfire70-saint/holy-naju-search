# 실시간 검색에 채택한 원문만 보관하고 당시 결과를 네트워크 없이 다시 연다.
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from holy_naju.discovery import live_search, validate_query
from holy_naju.public_fetch import PublicClient
from holy_naju.storage import Library, encode, now


def get_live_run(library, run_id):
    row = library.db.execute('SELECT * FROM live_search_runs WHERE id=?', (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    result = json.loads(row['snapshot'])
    result.update(id=row['id'], status=row['status'], started_at=row['started_at'], finished_at=row['finished_at'])
    result['results'] = [json.loads(r[0]) for r in library.db.execute(
        'SELECT snapshot FROM live_search_results WHERE run_id=? ORDER BY rank', (run_id,))]
    return result


def save_matched(library, hit, raw):
    if hashlib.sha256(raw).hexdigest() != hit['raw_sha256']:
        raise ValueError('verified_bytes_changed')
    with tempfile.TemporaryDirectory(prefix='live-', dir=library.root) as folder:
        path = Path(folder) / 'source.html'
        path.write_bytes(raw)
        stored = library.import_file(path, source='vatican', origin_url=hit['url'], language=hit['language'],
                                     origin_kind='download', title=hit['verified_title'] or hit['title'])
    version = library.get_version(stored['version_id'])
    passages = {p['ordinal']: p for p in version['passages']}
    evidence = []
    for block in hit['evidence']:
        passage = passages.get(block['ordinal'])
        if passage is None or passage['text'] != block['text']:
            raise ValueError('stored_evidence_changed')
        for start, end in block['ranges']:
            if not 0 <= start < end <= len(passage['text']):
                raise ValueError('invalid_evidence_range')
            evidence.append({'passage_id': passage['id'], 'version_id': stored['version_id'],
                             'start': start, 'end': end, 'excerpt': passage['text'][start:end]})
    return {**hit, 'version_id': stored['version_id'], 'asset_id': stored['asset_id'], 'stored_evidence': evidence}


def search_and_store(library, query, client):
    validate_query(query)
    run_id = str(uuid4())
    with library.db:
        library.db.execute('INSERT INTO live_search_runs VALUES (?,?,?,NULL,?,?)',
                           (run_id, query, now(), 'running', encode({'query': query, 'pipeline_revision': 'live-1'})))
    # ponytail: 최대5개/개당25MiB 원문을 메모리에 유지한다. 동시 작업 확장 시 임시 파일로 전환한다.
    raw_by_url = {}
    try:
        result = live_search(query, client, capture=lambda url, raw: raw_by_url.__setitem__(url, raw))
        for rank, hit in enumerate(result['results'], 1):
            if hit['verification_status'] == 'matched':
                try:
                    hit = save_matched(library, hit, raw_by_url.pop(hit['url']))
                except (OSError, ValueError) as error:
                    hit = {**hit, 'verification_status': 'failed', 'error': 'storage_failed:' + str(error)}
                    result['errors'].append({'stage': 'storage', 'url': hit['url'], 'error': str(error)})
                    result['status'] = 'partial'
            result_id = str(uuid4())
            hit.update(result_id=result_id, checked_at=now())
            with library.db:
                library.db.execute('INSERT INTO live_search_results VALUES (?,?,?,?,?,?,?,?)',
                                   (result_id, run_id, rank, hit['url'], hit['language'], hit.get('version_id'),
                                    hit['verification_status'], encode(hit)))
                for ordinal, evidence in enumerate(hit.get('stored_evidence', []), 1):
                    library.db.execute('INSERT INTO live_search_evidence VALUES (?,?,?,?,?,?,?)',
                                       (result_id, ordinal, evidence['version_id'], evidence['passage_id'],
                                        evidence['start'], evidence['end'], evidence['excerpt']))
        result.pop('results')
        result['pipeline_revision'] = 'live-1'
        with library.db:
            library.db.execute('UPDATE live_search_runs SET status=?,finished_at=?,snapshot=? WHERE id=?',
                               (result['status'], now(), encode(result), run_id))
    except Exception as error:
        with library.db:
            library.db.execute('UPDATE live_search_runs SET status=?,finished_at=?,snapshot=? WHERE id=?',
                               ('failed', now(), encode({'query': query, 'error': str(error)}), run_id))
        raise
    return get_live_run(library, run_id)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='교황청 실시간 검색 결과만 별도 보관소에 저장합니다.')
    parser.add_argument('--root', default='data/live-library')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--query')
    action.add_argument('--run', help='네트워크 없이 당시 결과를 엽니다.')
    args = parser.parse_args()
    with Library(args.root) as library:
        result = (get_live_run(library, args.run) if args.run else search_and_store(
            library, args.query, PublicClient(Path(args.root) / 'discovery-evidence')))
        print(json.dumps(result, ensure_ascii=False, indent=2))
