# 실행 중인 연구실을 재사용하거나 로컬 서버를 숨김 실행한 뒤 기본 브라우저를 연다.
from http.client import HTTPConnection, HTTPException
from pathlib import Path
import subprocess
import time
import webbrowser

PROJECT = Path(__file__).resolve().parents[1]
PORT = 8766
TITLE = '<title>성문헌 연구실 · Holy Naju Search</title>'.encode('utf-8')


def ready():
    connection = HTTPConnection('127.0.0.1', PORT, timeout=1)
    try:
        connection.request('GET', '/')
        response = connection.getresponse()
        if response.status != 200 or TITLE not in response.read(4096):
            raise RuntimeError(f'{PORT} 포트의 응답이 성문헌 연구실이 아닙니다. 기존 프로그램을 확인하세요.')
        return True
    except OSError:
        return False
    except HTTPException as error:
        raise RuntimeError(f'{PORT} 포트에서 올바른 HTTP 응답을 받지 못했습니다.') from error
    finally:
        connection.close()


def launch():
    if not ready():
        python = PROJECT / '.venv/Scripts/python.exe'
        server = PROJECT / 'scripts/serve.py'
        if not python.is_file() or not server.is_file():
            raise RuntimeError('실행 파일이 없습니다. 프로젝트 위치와 .venv 환경을 확인하세요.')
        log = PROJECT / 'data/launcher.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('ab') as output:
            child = subprocess.Popen([str(python), '-X', 'utf8', str(server), '--port', str(PORT),
                '--root', str(PROJECT / 'data/library')], cwd=PROJECT, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 15
        while not ready():
            if child.poll() is not None:
                raise RuntimeError(f'서버가 시작되지 않았습니다. 로그를 확인하세요.\n{log}')
            if time.monotonic() >= deadline:
                raise RuntimeError(f'서버 준비 시간이 초과됐습니다. 로그를 확인하세요.\n{log}')
            time.sleep(0.2)
    url = f'http://127.0.0.1:{PORT}/'
    if not webbrowser.open(url):
        raise RuntimeError(f'브라우저를 열지 못했습니다. 다음 주소를 직접 여세요.\n{url}')


if __name__ == '__main__':
    try:
        launch()
    except (OSError, RuntimeError, webbrowser.Error) as error:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), '성문헌 연구실 실행 오류', 0x10)
        raise SystemExit(1)
