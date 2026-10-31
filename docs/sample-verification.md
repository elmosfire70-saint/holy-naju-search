# 대표 문헌 수집·추출 검증

2026-10-31 한국 시간 13:37~13:38의 직접 수집 결과. 전체 수집이나 검색 정확도 평가가 아닌 추출 기준선 검증이다.
공식 웹 자료의 조사 진입점과 대표 URL은 `config/source-catalog.json`에 기록했다.

## 실제 자료

| 샘플 | 본문 문자 수 | 추출 블록 | 결과 |
|---|---:|---:|---|
| 제2차 바티칸 Dei Verbum 영어 | 33,886 | 116 | 본문·핵심어 검증 통과 |
| 제1차 바티칸 Dei Filius 이탈리아어 | 25,866 | 65 | 본문·핵심어 검증 통과 |
| 교리서 IntraText 계시 문단 영어 | 1,525 | 11 | 탐색 메뉴 제외·각주 보존 검증 통과 |
| Ecclesia de Eucharistia 영어 | 104,844 | 252 | 본문·핵심어 검증 통과 |
| 나주 메시지 상세 | 3,050 | 23 | 본문 영역·핵심어 검증 통과 |
| 교황청 보도실 PDF 기술 샘플 | 374,282 | 1,414 | 104페이지 본문·좌표 추출 검증 통과 |
| 같은 회칙 이름의 PDF 음성 샘플 | 101 | 5 | 본문 부족으로 정상 거부 |

총 7건의 기대 판정을 통과했다. 보도실 PDF는 PDF 처리 기술 검증용이며 회칙·공의회 첫 수집 대상에 자동 편입하지 않았다. 블록 번호는 검색용 분할 번호이며 공식 문단 번호의 의미를 부여하지 않았다.
명령은 `python -X utf8 scripts/probe_sources.py`와 추가 PDF에 대한 `--sample press-pdf-technical --output data/probes-pdf`였다. 원본·추출 JSON·SHA256·UTC 수집 시각·최종 URL은 로컬 `data/probes/report.json` 및 `data/probes-pdf/report.json`에 있다. 원문 본문은 GitHub에 올리지 않았다.

## 로컬 OCR 및 회귀 검증

명령. `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v`.

최종 실행 결과는 8개 테스트 전부 통과이며 OCR 테스트가 생략되지 않았음을 확인했다.

- 한국어로 생성한 스캔 PDF에서 사랑·기도 검색용 텍스트 인식.
- 영어 이미지와 기존 텍스트가 같은 페이지에 있는 PDF에서 본문 인식·헤더 중복 방지·페이지/영역 좌표 보존.
- OCR 데이터가 없으면 성공이나 빈 결과가 아닌 부분 처리 상태 반환.
- 나주 본문과 다른 위젯·댓글 분리, h5로 작성된 본문 보존.
- 교황청 구형/현행 템플릿, 교리서 본문/각주 보존.
- TXT의 원래 줄 위치 및 DOCX 문단·표 추출.
- 허용한 HTTPS 공식 호스트 외 주소·자격 증명이 있는 URL 거부.

생성한 한국어 스캔을 PNG로 렌더링해 글자가 잘리지 않는 것도 시각 확인했다. 이 테스트는 깨끗한 합성 스캔의 기능 검증이며, 실제 오래된 인쇄물·라틴어·기울어짐·낮은 해상도의 인식률을 보증하지 않는다. 실제 스캔 품질 평가는 후속 과제다.

## 실행 환경과 선택

- Python 3.12, PyMuPDF 1.28.2, BeautifulSoup 4.15.0, python-docx 1.2.0, curl_cffi 0.17.0.
- PC에서 메모리 약 32GiB, RTX 3060 12GB를 확인했다. OCR은 CPU에서 동작했으며 GPU 성능 평가가 아니다.
- Ollama에 qwen3.5:9b와 nomic-embed-text가 설치되어 있다. 설치 여부만 확인했고 이 단계에서 번역·임베딩 정확도를 판정하지 않았다.
- PyMuPDF 내장 Tesseract OCR을 사용해 외부 Tesseract 실행 파일 없이 검증했다. OCR 스킬의 helper는 외부 실행 파일 의존성이 충족되지 않아 직접 실행하지 못했다.
- 영·한 인식 데이터는 tesseract-ocr/tessdata_best의 고정 커밋과 SHA256으로 검증한다. 다운로드 위치와 해시는 `scripts/setup-local.ps1`에 있다.
- 네트워크 진단에서 나주 urllib 요청이 403이었던 반면 Insane Search의 curl_cffi 경로로 본문이 확인됐다. 최종 검증 실행은 urllib로 성공했다. 앱에는 관찰된 403에만 한정한 대체 전송을 둔다.
- Insane Search 진단은 처음 stdout cp949 오류로 종료됐다. 본문이 없었다는 판정과 구분했고, 후속 실행 출력은 UTF-8로 처리했다.
- 초기 가상환경/테스트는 샌드박스 임시 폴더 권한으로 실패해 권한이 있는 실행으로 재검증했다.

기술 근거. [PyMuPDF OCR API](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_textpage_ocr), [Tesseract 언어 데이터](https://github.com/tesseract-ocr/tessdata_best).

## 남은 범위

- 트리엔트와 그 이전 공의회의 안정적인 공식 원문 진입점은 이번 조사에서 확인하지 못했다. 문헌의 부재로 해석하지 않는다.
- 수집 목록 전체 열거·중단 재개·갱신 처리·DB 저장·검색 UI는 아직 구현하지 않았다.
- HTML 추출은 현재 확인한 템플릿을 대상으로 하며 새 문헌 형식은 샘플을 추가해 검증해야 한다.
- 검색용 정규화 텍스트와 원본 HTML을 함께 보존한다. 공식 문단 번호·원문 오프셋 대응의 완전성 검증은 DB 연결 단계에 수행한다.
