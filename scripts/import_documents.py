# 로컬 파일 가져오기와 문헌 목록·원문 버전·보관소 무결성 확인을 실행한다.
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holy_naju.storage import Library


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/library")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import")
    importer.add_argument("path")
    importer.add_argument("--source", choices=["user_import", "vatican", "naju"], default="user_import")
    importer.add_argument("--url", dest="origin_url")
    importer.add_argument("--language", default="und")
    importer.add_argument("--origin-kind", choices=["user_import", "download"], default="user_import")
    importer.add_argument("--title")
    importer.add_argument("--edition-id")
    importer.add_argument("--ocr-languages", default="eng+kor")
    importer.add_argument("--tessdata", default="data/models/tessdata")
    commands.add_parser("list")
    commands.add_parser("check")
    show = commands.add_parser("show")
    show.add_argument("version_id")
    args = parser.parse_args()
    try:
        with Library(args.root) as library:
            if args.command == "import":
                options = vars(args).copy()
                for key in ("root", "command", "path"):
                    options.pop(key)
                result = library.import_file(args.path, **options)
            elif args.command == "list":
                result = library.list_documents()
            elif args.command == "show":
                result = library.get_version(args.version_id)
            else:
                result = library.check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.command == "check" and not result["ok"] else 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError) as error:
        print(json.dumps({"error": f"{type(error).__name__}:{error}"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
