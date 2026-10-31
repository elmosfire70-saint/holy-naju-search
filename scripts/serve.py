# 로컬 자료실과 A 연구실형 검색 화면을 루프백 주소에서 실행한다.
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holy_naju.server import LocalServer


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/library")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with LocalServer(args.root, args.port) as server:
        print(f"Holy Naju Search: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
