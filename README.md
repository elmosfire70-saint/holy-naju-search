# Holy Naju Search

교황청 공식 문헌, 나주 사랑의 메시지, 사용자가 가져온 문서를 한국어 중심으로 검색하는 개인 PC용 연구 앱.

현재는 문헌 SQLite DB, 파일 가져오기, 로컬 OCR, 키워드 검색·필터·검색 기록과 결과 재사용까지 구현했다. 다국어 의미 검색·번역과 UI는 다음 단계다.

1차는 제2차 바티칸 공의회 이전을 포함하는 공의회 문헌 검색, 스캔 PDF 로컬 OCR, 원문/한국어 번역, 검색 기록을 완성한다. 여러 문헌을 종합하는 로컬 LLM 답변은 1차 완료 후 2차로 진행한다.

- [구현 계획](docs/plan.md)
- [DB와 GraphDB 확장 설계](docs/database-design.md)
- [작업 체크리스트](checklist.md)
- [결정과 남은 질문](context-notes.md)
- [용어](GLOSSARY.md)
- [샘플 검증 보고](docs/sample-verification.md)
- [문헌 DB 검증 보고](docs/database-verification.md)
- [키워드 검색 검증 보고](docs/search-verification.md)

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

이 단계는 원문 키워드 검색이다. 한국어가 없는 외국어 문헌을 한국어 의미로 찾는 기능과 번역은 아직 없다.

작업은 [설계 추적 이슈 #1](https://github.com/elmosfire70-saint/holy-naju-search/issues/1)에서 시작한다. 수집 문서·가져온 파일·검색 기록·모델·DB는 개인 PC의 로컬 데이터로 보관한다.

- [1차 출시 작업 #2](https://github.com/elmosfire70-saint/holy-naju-search/issues/2)
- [2차 로컬 LLM 종합 답변 #3](https://github.com/elmosfire70-saint/holy-naju-search/issues/3). 1차 완료 후 진행한다.
