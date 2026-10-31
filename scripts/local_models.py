# 로컬 문단 번역과 저장된 번역 열기 및 다국어 검색의 작은 비교 평가를 실행한다.
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holy_naju.search import search
from holy_naju.storage import Library
from holy_naju.translation import get_translation, translate_passage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/library")
    commands = parser.add_subparsers(dest="command", required=True)
    translate = commands.add_parser("translate")
    translate.add_argument("passage_id")
    translate.add_argument("--model", default="qwen3.5:9b")
    translate.add_argument("--refresh", action="store_true")
    saved = commands.add_parser("show")
    saved.add_argument("translation_id")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--model", default="qwen3-embedding:0.6b")
    evaluate.add_argument("--dataset", default="config/retrieval-evaluation.json")
    evaluate.add_argument("--output", default="data/evaluation/qwen-small.json")
    args = parser.parse_args()
    try:
        with Library(args.root) as library:
            if args.command == "translate":
                result = translate_passage(library, args.passage_id, model=args.model, refresh=args.refresh)
            elif args.command == "show":
                result = get_translation(library, args.translation_id)
            else:
                results = []
                for question in json.loads(Path(args.dataset).read_text(encoding="utf-8"))["questions"]:
                    measurements = {}
                    for retrieval in ("keyword", "hybrid"):
                        started = time.perf_counter()
                        run = search(library, question["query"], source=question["source"], limit=5,
                                     retrieval=retrieval, embedding_model=args.model)
                        hits = run["hits"]
                        correct = any((h["canonical_url"] == question.get("expected_url")) if question.get("expected_url")
                                      else h["source"] == question["expected_source"] for h in hits)
                        measurements[retrieval] = {"correct_at_5": correct, "run_id": run["id"],
                                                   "actual_retrieval": run["retrieval"], "model_profile": run["model_profile"],
                                                   "elapsed_seconds": round(time.perf_counter() - started, 3),
                                                   "reused": run["reused"], "diagnostics": run.get("diagnostics"),
                                                   "top_documents": [{"title": h["title"], "url": h["canonical_url"],
                                                                      "passage_id": h["passage_id"]} for h in hits]}
                    results.append({"query": question["query"], **measurements})
                    print(json.dumps({"query": question["query"], "keyword": measurements["keyword"]["correct_at_5"],
                                      "hybrid": measurements["hybrid"]["correct_at_5"]}, ensure_ascii=False), flush=True)
                result = {"model": args.model, "reference_status": "draft_needs_human_review", "questions": results}
                output = Path(args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                result = {"model": args.model, "count": len(results),
                          "keyword_at_5": sum(r["keyword"]["correct_at_5"] for r in results),
                          "hybrid_at_5": sum(r["hybrid"]["correct_at_5"] for r in results),
                          "semantic_available": all(r["hybrid"]["actual_retrieval"] == "hybrid" for r in results), "report": str(output)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
