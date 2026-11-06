# Holy Naju Search

교황청 공식 문헌, 나주 사랑의 메시지, 사용자가 가져온 문서를 한국어 중심으로 검색하는 개인 PC용 연구 앱.

현재는 A 연구실형 로컬 화면에서 문헌 SQLite DB, 파일 가져오기·OCR, 키워드·다국어 검색, 문단 한국어 번역과 검색 기록·재사용을 연결했다. 기존 CLI도 사용할 수 있다. 전체 수집과 번역의 인간 검토·대규모 품질 평가는 아직 남아 있다.

1차는 제2차 바티칸 공의회 이전을 포함하는 공의회 문헌 검색, 스캔 PDF 로컬 OCR, 원문/한국어 번역, 검색 기록을 완성한다. 여러 문헌을 종합하는 로컬 LLM 답변은 1차 완료 후 2차로 진행한다.

- [구현 계획](docs/plan.md)
- [DB와 GraphDB 확장 설계](docs/database-design.md)
- [작업 체크리스트](checklist.md)
- [결정과 남은 질문](context-notes.md)
- [용어](GLOSSARY.md)
- [샘플 검증 보고](docs/sample-verification.md)
- [문헌 DB 검증 보고](docs/database-verification.md)
- [키워드 검색 검증 보고](docs/search-verification.md)
- [로컬 다국어 검색·번역 검증 보고](docs/local-model-verification.md)
- [A 연구실형 UI 검증 보고](docs/ui-verification.md)
- [발견 목록·제한 수집 검증](docs/collection-verification.md)
- [발견 원문 이어 수집·확대 보관소 검증](docs/corpus-fill-verification.md)
- [50문항 검색·번역 평가와 인간 검토 방법](docs/quality-evaluation.md)
- [긴 문단 임베딩 수정·50/42문항 재검증](docs/long-passage-verification.md)
- [공식 공개 목록 조사](docs/source-discovery-research.md)

## A 연구실형 앱 실행

### 교황청 실시간 검색 · 결과 보관 CLI

새 경로는 아직 아래 화면의 검색 버튼에 연결하지 않았다. 명령행에서 자체 검색1페이지와 신앙교리부 영어 목록을 확인하고 최대5개 원문을 검증한다. 일치한 문헌만 보관하며 전체 사이트 본문을 미리 수집하지 않는다. 용어 일치는 내용의 승인이나 인간 관련성 검토를 뜻하지 않는다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m holy_naju.live_store --query "공동 구속자"
.\.venv\Scripts\python.exe -X utf8 -m holy_naju.live_store --run "출력된-검색-ID"
```

기본 보관소는 기존 연구 자료와 다른 `data/live-library`다. `--root`로 바꿀 수 있다. 새 질의는 매번 온라인 확인하고 `--run`은 네트워크/모델 없이 당시 결과를 연다. `matched`는 제목/용어 일치, `no_match`는 미일치, `failed`는 검증/보관 실패다. 현재 전체 웹 검색·일반 한국어 번역 확장·공식 문단 번호 추출·웹 화면 연결은 미완료이며 추출 블록/문자 위치를 근거로 기록한다.

새 Library는 스키마5로 자동 전환한다. **기존 연구 보관소를 새 코드로 열거나 서버를 재시작하기 전 일관된 DB+assets 백업을 먼저 확보한다.** 이번 검증은 별도/임시 보관소에서 수행했고 실행 연구 DB는 전환하지 않았다. 전원 장애 후 running 실행의 자동 복구와 저장 중 실패 시 자산 정리는 후속 운영 검증 대상이다.

Windows에서는 바탕화면의 **성문헌 연구실** 바로가기를 더블클릭한다. 프로젝트의 `.venv/Scripts/pythonw.exe`로 `scripts/launch_app.py`를 실행해 콘솔 없이 서버를 켜고 기본 브라우저를 연다. 이미 실행 중이면 기존 서버를 재사용한다. 프로젝트 폴더를 옮기면 바로가기 대상/작업 폴더도 다시 지정해야 한다.

브라우저를 닫아도 서버는 백그라운드에서 유지된다. 시작 오류는 알림과 `data/launcher.log`를 확인한다. 다른 서비스가8766포트를 사용하면 강제로 종료하거나 교체하지 않는다. 모델/자료 다운로드는 수행하지 않으며 신규 의미 검색·번역에는 기존처럼 로컬 Ollama가 필요하다.

아래 환경 준비를 마친 뒤 저장소 루트의 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/serve.py
```

[로컬 앱 열기](http://127.0.0.1:8766/). 종료는 실행한 터미널에서 Ctrl+C다. 다른 보관소나 포트는 `--root data/another-library --port 8768`로 지정한다. 서버는 항상 `127.0.0.1`에만 바인딩한다. 공용 서버·원격 접속·포트 포워딩 용도가 아니다.

- 검색 조건을 입력하고 결과를 선택하면 원문과 한국어 번역을 대조한다. 저장된 번역은 모델 없이 표시하며 새 생성은 번역 버튼으로 요청한다. 번역 이력의 프롬프트/모델·미검토 상태를 확인한다.
- 자료실은 브라우저에서 선택한 최대 50MiB의 PDF·TXT·HTML·DOCX를 기존 가져오기 DB에 연결한다. 파일 언어를 선택한다. 스캔 OCR은 현재 영어·한국어다. 부분 추출과 OCR 미검토 상태를 확인한다.
- 기록의 당시 결과 열기와 현재 보관 자료로 재검색을 구분한다. 재검색은 사이트 재수집이 아니다. 당시 원문/문단을 보존하고, 번역은 별도 이력이다.
- 주소의 run·passage·translation ID로 특정 보관 근거와 번역을 다시 연다. 같은 PC·보관소에서 유효하며 다른 PC로 자료를 전송하는 공개 링크가 아니다. 근거 복사에는 원문·버전·문단·번역 ID와 주소가 포함된다.
- 원본 HTML을 앱 안에서 실행하지 않는다. 보관 파일은 다운로드로 제공하며 PDF 페이지 번호는 원문 영역에서 확인한다. PDF 내부 페이지 뷰어는 아직 없다.

모델이 꺼져 있으면 새 의미 검색은 진단과 함께 키워드로 대체될 수 있고 새 번역은 실패할 수 있다. 원문과 저장 기록/번역은 계속 열 수 있다. 전체 수집은 별도 단계이며 화면에 보이는 보관 건수가 전체 문헌 수를 뜻하지 않는다.

## 공식 자료 발견과 제한 수집

자료실의 **공식 자료 수집 범위·상태**를 열면 범위별 발견 URL·보관 연결·대기·문제와 미확인 진입점을 볼 수 있다. `제한 수집 이어가기`는 한 번에 목록 1개·문헌 1개를 순차 처리하고 멈춘다. `상태 목록`에서 URL과 문제를 확인하고 해당 보관 버전을 연다. `문제 재시도`는 이전 실패/보류/부분 상태를 다시 대기열에 넣는다.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/collect_sources.py status
.\.venv\Scripts\python.exe -X utf8 scripts/collect_sources.py tasks naju-messages
.\.venv\Scripts\python.exe -X utf8 scripts/collect_sources.py run naju-messages --pages 2 --documents 3
.\.venv\Scripts\python.exe -X utf8 scripts/collect_sources.py run vatican-ii-en --pages 1 --documents 2 --retry
```

CLI는 각 실행의 목록/문헌 상한을 0~20개로 제한한다. 기본은 각각 1개다. `--refresh`는 해당 범위의 처리 완료 항목을 다시 대기열에 넣어 현재 파일을 확인한다. 기존 보관 버전/과거 검색은 지우지 않지만 상한 이후 항목은 계속 대기하므로 한 번의 명령이 전체 갱신 완료를 뜻하지 않는다.

현재 자동 경로는 나주 한국어 목록, 제2차 공의회 영어 HTML, 제1차 공의회 이탈리아어 HTML, 영어 교리서 본문, 기존 영어 회칙 후보 3개다. 다른 언어/PDF와 트리엔트 이전의 공식 전체 진입점은 자동 편입하지 않는다. 목록에 있는 서문·절 단위 URL을 하나의 독립된 메시지/저작물로 단정하지 않는다.

실행마다 robots를 확인하고 최소 2초 간격을 지킨다. HTTP 접근 제한·robots 실패·차단 화면에서는 멈추며 인증/캡차를 우회하지 않는다. 리디렉션은 자동 추종하지 않고 검토 대상으로 남긴다. 목록 스냅샷·시각·해시는 로컬 `data/library/collection-evidence/`와 DB 시도 기록에 보존한다. 새 번역이나 임베딩은 수집 중 만들지 않아, 자료 추가 후 첫 의미 검색에 임베딩 생성 시간이 들 수 있다.

## 로컬 추출 검증

Windows PowerShell에서 Python 3.12 경로를 지정해 프로젝트 전용 환경과 영어·한국어 OCR 데이터를 준비한다. 시스템 OCR 설치는 필요하지 않다.

```powershell
.\scripts\setup-local.ps1 -Python 'C:\path\to\python.exe'
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 scripts/probe_sources.py
```

특정 샘플만 확인하려면 `--sample dei-verbum --output data/probes-single`을 사용한다. 원본 파일·추출 본문·수집 시각·해시·실행 보고는 `data/`에만 저장된다. OCR 테스트가 skipped로 나오면 언어 데이터를 먼저 준비한다.

## 문헌 DB와 파일 가져오기

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/import_documents.py import 'C:\Documents\sample.pdf' --language ko --title '연구 자료'
.\.venv\Scripts\python.exe -X utf8 scripts/import_documents.py list
.\.venv\Scripts\python.exe -X utf8 scripts/import_documents.py check
```

DB 기본 위치는 `data/library/library.sqlite3`, 보관 파일은 `data/library/assets`다. 사용자 원본은 수정하지 않는다. `--root`를 명령 앞에 주면 다른 로컬 보관소를 사용할 수 있다.

- `import` 결과의 `version_id`를 `show VERSION_ID`에 전달하면 당시 본문·페이지·문단을 확인한다.
- 공식 사이트에서 내려받은 파일은 `--source vatican` 또는 `--source naju`와 `--url`을 함께 지정한다. 출처 메타데이터는 입력자의 선언이며 공식 발행 여부를 자동 보증하지 않는다.
- 기존 문헌판에 다른 파일을 명시적으로 연결하거나 재처리하려면 `--edition-id`를 사용한다. 제목 유사성으로 자동 병합하지 않는다.
- 동일 파일·추출기·OCR 설정의 정상 결과는 재사용한다. 파일이나 처리 설정이 바뀌면 새 버전을 보존하며 이전 버전을 다시 가져와도 최신 버전 포인터를 되돌리지 않는다.
- OCR 데이터가 없거나 일부 페이지가 실패하면 `partial`로 저장한다. 보완 후 같은 문헌판에 다시 가져올 수 있다.
- 실패한 파일과 작업 상태도 남긴다. `check`는 DB 외래 키, 파일 해시, 미등록 파일과 중단된 작업을 점검하며 자동 삭제하지 않는다.

## 검색과 검색 기록

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/search_documents.py search '성체' --source naju
.\.venv\Scripts\python.exe -X utf8 scripts/search_documents.py search 'Eucharist' --source vatican --language en
.\.venv\Scripts\python.exe -X utf8 scripts/search_documents.py search '하루를 시작합니다' --mode phrase
.\.venv\Scripts\python.exe -X utf8 scripts/search_documents.py history
```

반환된 검색 `id`로 `show RUN_ID`를 실행하면 당시 결과를 연다. `--refresh`는 같은 자료에 대해 검색을 다시 실행하며 사이트를 재수집하지 않는다. 문헌이나 검색용 메타데이터가 바뀌면 자동으로 새 색인 세대에서 검색한다.

기본 검색은 모든 단어가 제목 또는 같은 문단에 있는 결과를 찾는다. 구절 모드는 연속된 문자열을 찾는다. FTS 연산자는 지원하지 않고 입력 문자열을 그대로 검색한다. `--document-type`, `--issued-from`, `--issued-to`, `--limit` 필터도 제공한다. 발표일 필터는 발표일을 알고 있는 문헌만 포함한다.

같은 단어 조건·필터·방식·결과 상한·자료 세대·검색 버전은 결과를 재사용한다. 검색할 때마다 이력은 추가한다. 결과는 근거 발췌와 문자 범위로 강조 위치를 반환하며, 원문에 HTML 표시 코드를 삽입하지 않는다.

## 로컬 다국어 검색과 문단 번역

Ollama를 PC에서 실행한 상태에서 모델을 준비한다. 모델 다운로드에는 인터넷이 필요하지만 추론은 `127.0.0.1:11434`에서만 수행한다. 클라우드 모델·원격 별칭·HTTP 리다이렉트는 거부한다.

```powershell
ollama pull qwen3-embedding:0.6b
ollama pull qwen3.5:9b
.\.venv\Scripts\python.exe -X utf8 scripts/search_documents.py search '성경과 성전의 관계' --source vatican --retrieval hybrid
.\.venv\Scripts\python.exe -X utf8 scripts/local_models.py translate PASSAGE_ID
.\.venv\Scripts\python.exe -X utf8 scripts/local_models.py show TRANSLATION_ID
.\.venv\Scripts\python.exe -X utf8 scripts/local_models.py evaluate
```

`PASSAGE_ID`는 검색 결과의 `passage_id`다. 번역 결과에는 원문·문단/버전 ID·위치·모델 digest·프롬프트 버전과 `review_status=unreviewed`가 함께 반환된다. 생성 번역은 공식 번역이 아니며, 반드시 원문과 대조한다. 현재 이탈리아어 샘플에서 오역·제3언어 혼입이 관찰되어 번역 품질을 출시 통과로 판정하지 않았다.

`hybrid`는 키워드와 로컬 의미 검색 순위를 결합한다. 구절 모드와 함께 사용할 수 없다. 같은 질의 순서·필터·자료·모델/알고리즘 버전이면 결과를 재사용하며, 임베딩도 입력 해시로 재사용한다. 처음에는 문단 임베딩 생성 시간이 들고 이후 검색은 이를 재사용한다. 모델을 사용할 수 없으면 `diagnostics`와 함께 키워드 검색으로 대체하므로 `retrieval`을 확인한다.

번역은 같은 원문·모델·프롬프트의 정상 결과만 재사용한다. `translate --refresh`로 다시 생성할 수 있다. 모델이 꺼져 있어도 저장한 번역 ID의 `show` 및 검색 실행 ID의 `show`는 동작한다. 원문이 한국어면 모델 호출 없이 원문임을 표시해 반환한다. 여러 문헌을 종합하는 AI 답변은 구현하지 않았다.

작업은 [설계 추적 이슈 #1](https://github.com/elmosfire70-saint/holy-naju-search/issues/1)에서 시작한다. 수집 문서·가져온 파일·검색 기록·모델·DB는 개인 PC의 로컬 데이터로 보관한다.

- [1차 출시 작업 #2](https://github.com/elmosfire70-saint/holy-naju-search/issues/2)
- [2차 로컬 LLM 종합 답변 #3](https://github.com/elmosfire70-saint/holy-naju-search/issues/3). 1차 완료 후 진행한다.
