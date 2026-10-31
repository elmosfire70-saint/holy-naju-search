# Holy Naju Search

교황청 공식 문헌, 나주 사랑의 메시지, 사용자가 가져온 문서를 한국어 중심으로 검색하는 개인 PC용 연구 앱.

현재는 대표 문헌의 수집·추출·로컬 OCR 검증까지 구현했다. 검색 UI와 문헌 DB는 다음 단계다.

1차는 제2차 바티칸 공의회 이전을 포함하는 공의회 문헌 검색, 스캔 PDF 로컬 OCR, 원문/한국어 번역, 검색 기록을 완성한다. 여러 문헌을 종합하는 로컬 LLM 답변은 1차 완료 후 2차로 진행한다.

- [구현 계획](docs/plan.md)
- [DB와 GraphDB 확장 설계](docs/database-design.md)
- [작업 체크리스트](checklist.md)
- [결정과 남은 질문](context-notes.md)
- [용어](GLOSSARY.md)
- [샘플 검증 보고](docs/sample-verification.md)

## 로컬 추출 검증

Windows PowerShell에서 Python 3.12 경로를 지정해 프로젝트 전용 환경과 영어·한국어 OCR 데이터를 준비한다. 시스템 OCR 설치는 필요하지 않다.

```powershell
.\scripts\setup-local.ps1 -Python 'C:\path\to\python.exe'
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 scripts/probe_sources.py
```

특정 샘플만 확인하려면 `--sample dei-verbum --output data/probes-single`을 사용한다. 원본 파일·추출 본문·수집 시각·해시·실행 보고는 `data/`에만 저장된다. OCR 테스트가 skipped로 나오면 언어 데이터를 먼저 준비한다.

작업은 [설계 추적 이슈 #1](https://github.com/elmosfire70-saint/holy-naju-search/issues/1)에서 시작한다. 수집 문서·가져온 파일·검색 기록·모델·DB는 개인 PC의 로컬 데이터로 보관한다.

- [1차 출시 작업 #2](https://github.com/elmosfire70-saint/holy-naju-search/issues/2)
- [2차 로컬 LLM 종합 답변 #3](https://github.com/elmosfire70-saint/holy-naju-search/issues/3). 1차 완료 후 진행한다.
