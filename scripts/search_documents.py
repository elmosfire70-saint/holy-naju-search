# 키워드·구절 검색과 필터 및 검색 기록·과거 결과 열기를 실행한다.
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holy_naju.search import get_run, history, search
from holy_naju.storage import Library


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/library")
    commands = parser.add_subparsers(dest="command", required=True)
    finder = commands.add_parser("search")
    finder.add_argument("query")
    finder.add_argument("--source", choices=["vatican", "naju", "user_import"])
    finder.add_argument("--language")
    finder.add_argument("--document-type")
    finder.add_argument("--issued-from")
    finder.add_argument("--issued-to")
    finder.add_argument("--mode", choices=["keyword", "phrase"], default="keyword")
    finder.add_argument("--limit", type=int, default=20)
    finder.add_argument("--refresh", action="store_true")
    finder.add_argument("--retrieval", choices=["keyword", "hybrid"], default="keyword")
    finder.add_argument("--embedding-model", default="qwen3-embedding:0.6b")
    records = commands.add_parser("history")
    records.add_argument("--limit", type=int, default=20)
    show = commands.add_parser("show")
    show.add_argument("run_id")
    args = parser.parse_args()
    try:
        with Library(args.root) as library:
            options = vars(args).copy()
            options.pop("root")
            options.pop("command")
            if args.command == "search":
                result = search(library, **options)
            elif args.command == "history":
                result = history(library, **options)
            else:
                result = get_run(library, args.run_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError) as error:
        print(json.dumps({"status": "failed", "error": f"{type(error).__name__}:{error}"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
