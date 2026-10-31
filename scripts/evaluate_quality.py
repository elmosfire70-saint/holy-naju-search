# 연구 보관소를 복제해 검색 평가를 실행하고 개인 원문·판정 자료를 로컬에만 보관한다.
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holy_naju.evaluation import evaluate
from holy_naju.storage import Library, now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='data/library')
    parser.add_argument('--dataset', default='config/quality-evaluation.json')
    parser.add_argument('--review')
    parser.add_argument('--keyword-only', action='store_true')
    parser.add_argument('--model', default='qwen3-embedding:0.6b')
    args = parser.parse_args()
    destination = Path('data/evaluation') / ('quality-' + now().replace(':', '-') + '-' + uuid4().hex[:8])
    try:
        dataset = json.loads(Path(args.dataset).read_text(encoding='utf-8'))
        review = json.loads(Path(args.review).read_text(encoding='utf-8')) if args.review else None
        source = Path(args.root).resolve()
        if not (source / 'library.sqlite3').is_file():
            raise ValueError('source_library_missing')
        clone = destination / 'library'
        clone.mkdir(parents=True, exist_ok=False)
        with sqlite3.connect((source / 'library.sqlite3').as_uri() + '?mode=ro', uri=True) as old, sqlite3.connect(clone / 'library.sqlite3') as new:
            old.backup(new)
        shutil.copytree(source / 'assets', clone / 'assets')
        print(json.dumps({'evaluation_root': str(destination)}, ensure_ascii=False), flush=True)
        with Library(clone) as library:
            if not library.check()['ok']:
                raise ValueError('evaluation_snapshot_integrity_failed')
            report = evaluate(library, dataset, destination / 'report', model=args.model, review=review, hybrid=not args.keyword_only)
        print(json.dumps({'report': str(destination / 'report'), 'summary': report['summary'],
                          'paired_scored_questions': report['paired_scored_questions'], 'release_passed': False}, ensure_ascii=False), flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error) as error:
        print(json.dumps({'status': 'failed', 'error': str(error), 'artifacts': str(destination)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
