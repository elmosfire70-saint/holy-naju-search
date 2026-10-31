# 미검토 근거·잘못된 등급·모델 대체가 정확도 통과로 계산되지 않는지 검증한다.
from contextlib import redirect_stdout
from io import StringIO
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from holy_naju.evaluation import evaluate, metrics
from holy_naju.search import search
from holy_naju.storage import Library


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(self.root / 'library')
        self.addCleanup(self.library.db.close)
        path = self.root / 'document.txt'
        path.write_text('성체와 기도에 관한 첫 근거.\n\n성체와 교회에 관한 두 번째 근거.', encoding='utf-8')
        self.library.import_file(path, language='ko')
        self.dataset = {'questions': [{'id': 'Q1', 'query': '성체', 'filters': {'source': 'user_import'}}]}

    def run_eval(self, name, **options):
        with redirect_stdout(StringIO()):
            return evaluate(self.library, self.dataset, self.root / name, **options)

    def review(self):
        self.run_eval('draft', hybrid=False)
        review = json.loads((self.root / 'draft/review.json').read_text(encoding='utf-8'))
        q = review['questions'][0]
        q.update(status='reviewed', reviewed_by='synthetic-test-reviewer', reviewed_at='2026-10-31T12:00:00+09:00')
        for j in q['judgments']:
            j['grade'] = 2
        return review

    def test_metrics_known_grades_and_empty_denominator(self):
        result = metrics(['z', 'a'], {'a': 2, 'b': 1, 'z': 0})
        self.assertEqual(result['pooled_recall_at_20'], 0.5)
        self.assertAlmostEqual(result['pooled_ndcg_at_10'], (3/math.log2(3))/(3+1/math.log2(3)))
        self.assertIsNone(metrics(['z'], {'z': 0}))
        self.assertEqual(metrics(['a', 'b'], {'a': 2, 'b': 1})['pooled_ndcg_at_10'], 1)
        self.assertEqual(metrics([], {'a': 2})['pooled_recall_at_20'], 0)

    def test_invalid_grades_duplicate_and_unjudged_rankings_rejected(self):
        for grades in ({'a': None}, {'a': True}, {'a': 3}):
            with self.assertRaises(ValueError):
                metrics(['a'], grades)
        with self.assertRaises(ValueError):
            metrics(['a', 'a'], {'a': 2})
        with self.assertRaisesRegex(ValueError, 'unjudged_results'):
            metrics(['new'], {'a': 2})

    def test_pending_review_never_produces_quality_scores(self):
        report = self.run_eval('pending', hybrid=False)
        self.assertEqual(report['summary']['keyword']['scored_questions'], 0)
        self.assertIsNone(report['summary']['keyword']['mean_scores'])
        self.assertFalse(report['release_passed'])
        self.assertIsNone(report['paired_mean_scores'])
        review = json.loads((self.root / 'pending/review.json').read_text(encoding='utf-8'))
        self.assertTrue(review['questions'][0]['judgments'])
        self.assertTrue(all(j['grade'] is None for j in review['questions'][0]['judgments']))

    def test_reviewed_grades_score_and_new_unjudged_results_do_not(self):
        review = self.review()
        report = self.run_eval('scored', review=review, hybrid=False)
        self.assertEqual(report['summary']['keyword']['mean_scores']['pooled_recall_at_20'], 1)
        review['questions'][0]['judgments'].pop()
        report = self.run_eval('unjudged', review=review, hybrid=False)
        self.assertEqual(report['questions'][0]['runs']['keyword']['score_status'], 'unjudged_results')
        self.assertIsNone(report['questions'][0]['runs']['keyword']['scores'])

    def test_changed_evidence_questions_and_missing_reviewer_rejected_before_search(self):
        review = self.review()
        variants = []
        for field in ('corpus_hash', 'questions_hash'):
            altered = json.loads(json.dumps(review))
            altered[field] = 'changed'
            variants.append(altered)
        altered = json.loads(json.dumps(review))
        altered['questions'][0]['judgments'][0]['text_hash'] = 'changed'
        variants.append(altered)
        altered = json.loads(json.dumps(review))
        altered['questions'][0]['judgments'][0]['text'] = '변경된 원문'
        variants.append(altered)
        altered = json.loads(json.dumps(review))
        altered['questions'][0]['query'] = '변경된 질문'
        variants.append(altered)
        altered = json.loads(json.dumps(review))
        altered['questions'][0]['filters'] = {}
        variants.append(altered)
        altered = json.loads(json.dumps(review))
        altered['questions'][0]['reviewed_by'] = ''
        variants.append(altered)
        altered = json.loads(json.dumps(review))
        altered['questions'][0]['reviewed_by'] = None
        variants.append(altered)
        altered = json.loads(json.dumps(review))
        altered['questions'][0]['reviewed_at'] = '2026-10-31T12:00:00'
        variants.append(altered)
        with patch('holy_naju.evaluation.search', side_effect=AssertionError('must validate first')):
            for index, candidate in enumerate(variants):
                with self.assertRaises(ValueError):
                    self.run_eval('bad'+str(index), review=candidate, hybrid=False)

    def test_fallback_is_not_hybrid_success_and_stops_repeated_model_calls(self):
        self.dataset['questions'].append({'id': 'Q2', 'query': '기도'})
        def fallback(library, query, **options):
            requested = options.pop('retrieval')
            result = search(library, query, **options)
            if requested == 'hybrid':
                result['diagnostics'] = {'reason': 'synthetic_model_unavailable'}
            return result
        with patch('holy_naju.evaluation.search', side_effect=fallback) as finder:
            report = self.run_eval('fallback')
        self.assertEqual(finder.call_count, 3)
        self.assertEqual(report['summary']['hybrid']['completed'], 0)
        self.assertEqual(report['summary']['hybrid']['fallback'], 1)
        self.assertEqual(report['summary']['hybrid']['scored_questions'], 0)
        self.assertEqual(report['questions'][1]['runs']['hybrid']['status'], 'not_run')

    def test_fifty_draft_questions_cover_sources_languages_and_phrase_mode(self):
        dataset = json.loads(Path('config/quality-evaluation.json').read_text(encoding='utf-8'))
        self.assertEqual(len(dataset['questions']), 50)
        self.assertEqual(len({q['id'] for q in dataset['questions']}), 50)
        self.assertIn('draft', dataset['reference_status'])
        self.assertEqual({q.get('filters', {}).get('source') for q in dataset['questions']}, {None, 'naju', 'vatican', 'user_import'})
        self.assertIn('it', {q.get('filters', {}).get('language') for q in dataset['questions']})
        self.assertTrue(any(q.get('mode') == 'phrase' for q in dataset['questions']))


if __name__ == '__main__':
    unittest.main()
