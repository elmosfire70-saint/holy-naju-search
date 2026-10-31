# 공식 문헌의 발견 목록과 제한 수집·실패 재시도·상태 조회를 실행한다.
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holy_naju.collections import collect, initialize, summary, task_list
from holy_naju.storage import Library


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/library")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    tasks = commands.add_parser("tasks")
    tasks.add_argument("scope_id")
    worker = commands.add_parser("run")
    worker.add_argument("scope_id")
    worker.add_argument("--pages", type=int, default=1)
    worker.add_argument("--documents", type=int, default=1)
    worker.add_argument("--retry", action="store_true")
    worker.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    try:
        with Library(args.root) as library:
            initialize(library)
            if args.command == "run":
                result = collect(library, args.scope_id, pages=args.pages, documents=args.documents,
                                 retry=args.retry, refresh=args.refresh)
            elif args.command == "tasks":
                result = task_list(library, args.scope_id)
            else:
                result = summary(library)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.command == "run" and any(t["state"] in {"failed", "blocked", "partial"} for t in result["results"]) else 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
