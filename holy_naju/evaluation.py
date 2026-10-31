# 검색 후보의 근거를 보존하고 인간 검토된 문항만 후보 풀 상대 지표로 평가한다.
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import time

from holy_naju.search import search
from holy_naju.storage import encode, now


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def corpus_hash(library):
    return digest([list(r) for r in library.db.execute(
        "SELECT e.id,e.current_version_id,e.language,e.canonical_url,d.title,d.document_type,d.issued_on,"
        "s.kind,v.body_sha256 FROM editions e JOIN documents d ON d.id=e.document_id "
        "JOIN sources s ON s.id=e.source_id JOIN document_versions v ON v.id=e.current_version_id ORDER BY e.id")])


def metrics(ranked_ids, grades):
    if len(ranked_ids) != len(set(ranked_ids)) or any(type(g) is not int or g not in (0, 1, 2) for g in grades.values()):
        raise ValueError('invalid_relevance_grades_or_ranking')
    if any(pid not in grades for pid in ranked_ids):
        raise ValueError('unjudged_results')
    relevant = {pid for pid, grade in grades.items() if grade > 0}
    if not relevant:
        return None
    dcg = lambda values: sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(values))
    ideal = dcg(sorted(grades.values(), reverse=True)[:10])
    return {'pooled_recall_at_20': len(set(ranked_ids[:20]) & relevant) / len(relevant),
            'pooled_ndcg_at_10': dcg([grades[pid] for pid in ranked_ids[:10]]) / ideal,
            'passage_hit_at_20': bool(set(ranked_ids[:20]) & relevant)}


def _score(question, ranked, actual, requested):
    if actual != requested:
        return None, 'retrieval_unavailable'
    if question.get('status') != 'reviewed':
        return None, 'needs_human_review'
    if not isinstance(question.get('reviewed_by'), str) or not question['reviewed_by'].strip():
        raise ValueError('reviewer_required')
    try:
        timestamp = datetime.fromisoformat(question['reviewed_at'])
        if timestamp.tzinfo is None:
            raise ValueError('review_time_requires_timezone')
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('invalid_review_time') from error
    grades = {j['passage_id']: j['grade'] for j in question['judgments']}
    try:
        result = metrics(ranked, grades)
    except ValueError as error:
        if str(error) == 'unjudged_results':
            return None, 'unjudged_results'
        raise
    return result, 'scored' if result else 'no_known_relevant_passages'


def evaluate(library, dataset, output, *, model='qwen3-embedding:0.6b', review=None, hybrid=True):
    questions = dataset['questions']
    if not isinstance(questions, list) or not questions or not all(isinstance(q, dict) and isinstance(q.get('id'), str) and q['id'].strip() for q in questions):
        raise ValueError('invalid_evaluation_questions')
    ids = [q['id'] for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate_or_empty_questions')
    allowed = {'source', 'language', 'document_type', 'issued_from', 'issued_to'}
    for q in questions:
        if not isinstance(q.get('query'), str) or not q['query'].strip() or len(q['query']) > 500 or not isinstance(q.get('filters', {}), dict) or set(q.get('filters', {})) - allowed or q.get('mode', 'keyword') not in ('keyword', 'phrase'):
            raise ValueError('invalid_evaluation_question')
    signature, question_hash = corpus_hash(library), digest(questions)
    previous = {}
    if review is not None:
        if review['corpus_hash'] != signature or review['questions_hash'] != question_hash:
            raise ValueError('review_corpus_or_questions_changed')
        previous = {q['id']: q for q in review['questions']}
        if set(previous) != set(ids) or len(previous) != len(review['questions']):
            raise ValueError('review_questions_mismatch')
        originals = {q['id']: q for q in questions}
        for q in previous.values():
            original = originals[q['id']]
            if q['query'] != original['query'] or q.get('filters', {}) != original.get('filters', {}) or q.get('mode', 'keyword') != original.get('mode', 'keyword'):
                raise ValueError('review_question_conditions_changed')
            seen = set()
            for j in q['judgments']:
                row = library.db.execute('SELECT version_id,text FROM passages WHERE id=?', (j['passage_id'],)).fetchone()
                if row is None or row['version_id'] != j['version_id'] or row['text'] != j['text'] or digest(row['text']) != j['text_hash'] or j['passage_id'] in seen:
                    raise ValueError('review_evidence_changed_or_duplicated')
                seen.add(j['passage_id'])
            # 검토 메타데이터와 등급을 모델 호출 전에 검증한다.
            _score(q, [], 'keyword', 'keyword')
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=False)
    report = {'created_at': now(), 'corpus_hash': signature, 'questions_hash': question_hash,
              'model': model, 'questions': [], 'release_passed': False}
    review_out = {'corpus_hash': signature, 'questions_hash': question_hash, 'questions': []}
    model_failure = None
    for q in questions:
        pool = {j['passage_id']: dict(j) for j in previous.get(q['id'], {}).get('judgments', [])}
        record = {'id': q['id'], 'query': q['query'], 'filters': q.get('filters', {}), 'mode': q.get('mode', 'keyword'), 'runs': {}}
        for retrieval in ('keyword', 'hybrid'):
            if retrieval == 'hybrid' and (not hybrid or q.get('mode') == 'phrase' or model_failure):
                record['runs'][retrieval] = {'status': 'not_run', 'reason': model_failure or 'disabled_or_phrase_mode'}
                continue
            started = time.perf_counter()
            result = search(library, q['query'], **q.get('filters', {}), mode=q.get('mode', 'keyword'), limit=20,
                            retrieval=retrieval, embedding_model=model)
            actual = result['retrieval']
            if retrieval == 'hybrid' and actual != 'hybrid':
                model_failure = result.get('diagnostics', {}).get('reason', 'hybrid_unavailable')
            score, score_status = _score(previous.get(q['id'], {}), [h['passage_id'] for h in result['hits']], actual, retrieval)
            record['runs'][retrieval] = {'status': 'completed' if actual == retrieval else 'fallback',
                'elapsed_seconds': round(time.perf_counter() - started, 4), 'score_status': score_status,
                'scores': score, 'result': result}
            for hit in result['hits']:
                p = library.db.execute('SELECT * FROM passages WHERE id=?', (hit['passage_id'],)).fetchone()
                pool.setdefault(p['id'], {'passage_id': p['id'], 'version_id': p['version_id'], 'text_hash': digest(p['text']),
                    'title': hit['title'], 'source': hit['source'], 'language': hit['language'], 'url': hit['canonical_url'],
                    'locator': json.loads(p['locator']), 'text': p['text'], 'grade': None})
        report['questions'].append(record)
        reviewed = previous.get(q['id'], {})
        review_out['questions'].append({'id': q['id'], 'query': q['query'], 'filters': q.get('filters', {}), 'mode': q.get('mode', 'keyword'), 'status': 'pending',
            'reviewed_by': '', 'reviewed_at': '', 'judgments': list(pool.values()),
            'previous_review_status': reviewed.get('status')})
        (folder / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (folder / 'review.json').write_text(json.dumps(review_out, ensure_ascii=False, indent=2), encoding='utf-8')
        print(encode({'id': q['id'], 'completed': len(report['questions']), 'hybrid_failure': model_failure}), flush=True)
    if corpus_hash(library) != signature:
        raise ValueError('corpus_changed_during_evaluation')
    report['summary'] = {}
    for method in ('keyword', 'hybrid'):
        runs = [q['runs'][method] for q in report['questions']]
        scored = [r['scores'] for r in runs if r.get('scores') is not None]
        report['summary'][method] = {'completed': sum(r['status'] == 'completed' for r in runs),
            'fallback': sum(r['status'] == 'fallback' for r in runs), 'scored_questions': len(scored),
            'mean_scores': {k: sum(s[k] for s in scored)/len(scored) for k in scored[0]} if scored else None}
    report['paired_scored_questions'] = sum(all(q['runs'][m].get('scores') is not None for m in ('keyword', 'hybrid')) for q in report['questions'])
    paired = [q for q in report['questions'] if all(q['runs'][m].get('scores') is not None for m in ('keyword', 'hybrid'))]
    report['paired_mean_scores'] = {m: {k: sum(q['runs'][m]['scores'][k] for q in paired)/len(paired)
        for k in paired[0]['runs'][m]['scores']} for m in ('keyword', 'hybrid')} if paired else None
    report['finished_at'] = now()
    (folder / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    translations = []
    for row in library.db.execute('SELECT t.*,p.text AS original,p.version_id,p.locator FROM translations t JOIN passages p ON p.id=t.passage_id ORDER BY t.created_at'):
        translations.append({**dict(row), 'quality_review': {'faithfulness': None, 'subjects_negations': None,
            'catholic_terms': None, 'numbers_references': None, 'omissions_additions': None, 'reviewed_by': '', 'reviewed_at': ''}})
    (folder / 'translation-review.json').write_text(json.dumps(translations, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 검색·번역 인간 검토 자료', '', '자동 후보이며 정답/번역 승인 자료가 아닙니다. 판정은 review.json의 문항별 judgments.grade에0/1/2를 기록합니다.', '',
             '0은 무관, 1은 보조 관련, 2는 질문에 직접 답하는 근거입니다. 후보를 모두 대조한 뒤 status를 reviewed로 바꾸고 reviewed_by와 시간대가 있는 reviewed_at을 기록합니다.', '',
             '관련 문단이 후보 풀 밖에 있으면 version_id/text_hash를 함께 추가해야 합니다. 새 순위의 미검토 문단은 지표에서 제외됩니다. 지표는 후보 풀 기준이며 전체 문헌의 완전한 정답 재현율이 아닙니다.', '',
             '원문 링크는 현재 PC의 연구 앱을 엽니다. 원문이 갱신돼도 당시 문단 ID로 확인합니다. 저장 번역 판정은 translation-review.json에서 별도로 진행합니다.', '']
    for q in review_out['questions']:
        lines.extend(['## ' + q['id'] + ' · ' + q['query'], '', '조건 ' + encode(q['filters']) + ' · 방식 ' + q['mode'] + '.', '', str(len(q['judgments'])) + '개 근거 후보. 모두 미확정입니다.', '',
            ' '.join('[원문' + str(i+1) + '](http://127.0.0.1:8766/#passage=' + j['passage_id'] + ')' for i, j in enumerate(q['judgments'])), ''])
    (folder / 'review.md').write_text('\n'.join(lines), encoding='utf-8')
    return report
