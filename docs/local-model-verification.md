# 로컬 다국어 검색·문단 번역 초기 검증

2026-10-31, 이슈 #7의 구현과 작은 실제 자료 평가다. 1차 출시의 전체 품질 통과 보고가 아니다.

## 구현 범위

- SQLite 버전 3에 임베딩·문단 연결·번역을 추가하고 기존 검색 실행을 보존했다.
- 로컬 Ollama만 사용한다. 프록시·리다이렉트를 차단하고 클라우드 모델 및 원격 모델 별칭을 거부한다.
- 제목/문단 임베딩과 질의 임베딩을 입력 해시·모델 digest·런타임/옵션으로 재사용한다.
- 필터를 먼저 적용하고 코사인 순위와 키워드 순위를 RRF로 결합한다. 학습형 재정렬기는 아직 없다.
- 번역에는 원문 문단/버전·위치·입력 해시·모델·프롬프트 버전과 미검토 표시를 보존한다.
- 모델 비가용 시 검색은 진단을 포함한 키워드 경로로 대체한다. 신규 번역은 오류이며 실패를 성공 캐시로 재사용하지 않는다.

## 장비와 모델

Windows, RAM 약 32GiB, RTX 3060 12GB, Ollama 0.40.13에서 확인했다. Qwen 임베딩 모델만 새로 다운로드했고 기존 번역 모델을 재사용했다. 외부 모델 API로 원문을 보내지 않았다.

| 용도 | 모델 | 확인한 digest |
|---|---|---|
| 기본 임베딩 | qwen3-embedding:0.6b | ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d |
| 비교 임베딩 | nomic-embed-text:latest | 0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f |
| 한국어 번역 | qwen3.5:9b | 56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90 |

임베딩은 num_ctx=4096, truncate=false로 호출한다. 문맥 초과를 조용히 잘라내지 않는다. 번역은 num_ctx=8192, num_predict=4096, temperature=0, seed=0, think=false와 JSON 출력을 사용한다. 현재 프롬프트는 ko-faithful-json-3이다.

## 검색의 작은 비교

보관 문헌 6건·문단 468개를 대상으로 같은 질문·출처 필터·상한 5를 사용했다. 참조 후보는 `config/retrieval-evaluation.json`에 사전에 기록했다. 사람의 관련성 등급 판정이 없는 초기 문헌 후보이며, 문단 자체의 정답 판정이나 Recall/nDCG가 아니다.

| 한국어 질문 | 참조 문헌 후보 | 키워드 | nomic 결합 | Qwen 결합 |
|---|---|---|---|---|
| 성체와 교회의 일치 | Ecclesia de Eucharistia | 미적중 | 적중 | 적중 |
| 성경과 성전의 관계 | Dei Verbum | 미적중 | 적중 | 적중 |
| 신앙과 이성은 어떻게 조화를 이루는가 | Dei Filius 이탈리아어 | 미적중 | 미적중 | 적중 |
| 하느님은 인간에게 자신의 생명을 나누어 주신다 | 교리서 계시 절 | 미적중 | 미적중 | 적중 |
| 기도 봉헌 | 나주 메시지 샘플 | 미적중 | 적중 | 적중 |
| 사랑 기도 | 합성 한국어 OCR 파일 | 적중 | 적중 | 적중 |
| 상위 5개 내 참조 후보 적중 | 6문항 | 1/6 | 4/6 | 6/6 |

교황청 자료도 4문헌뿐이며 나주/가져온 파일은 해당 출처에 각 1건뿐이다. 특히 뒤 두 질문은 실질적인 관련성 경쟁을 검증하지 못한다. 이 수치를 전체 문헌 정확도나 정답률 100%로 해석하지 않는다. 작은 비교에서 Qwen이 더 나아 기본 임베딩 후보로 선택했다.

Qwen 첫 질문은 교황청 문단의 최초 임베딩 생성 포함 68.102초였다. 이후 신규 질문은 0.308~0.910초, 동일 6질문 재사용은 0.123~0.153초였고 모두 같은 실행 ID를 반환했다. 단일 소규모 실행의 API 시간이며 p95·대규모 부하 목표 달성이 아니다.

실행 명령은 다음과 같다. 원시 결과는 개인 데이터인 `data/evaluation/`에만 보관한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/local_models.py evaluate --model qwen3-embedding:0.6b --output data/evaluation/qwen-small.json
.\.venv\Scripts\python.exe -X utf8 scripts/local_models.py evaluate --model nomic-embed-text:latest --output data/evaluation/nomic.json
.\.venv\Scripts\python.exe -X utf8 scripts/local_models.py evaluate --model qwen3-embedding:0.6b --output data/evaluation/qwen-reused.json
```

## 번역에서 확인한 것과 실패

Dei Verbum 영어 문단을 실제 번역했다. 초안의 어색한 가톨릭 용어를 관찰해 성전·성경·하느님·성령·교도권 지침을 추가했다. 최종 버전에서 용어와 원문/문단/버전 연결을 확인했으나 사람이 승인한 공식 번역은 아니다. 같은 문단을 다시 요청하면 모델 추론 없이 같은 번역 ID를 재사용했다. 실제 재사용 1회는 약 147ms였다.

Dei Filius 이탈리아어 문단에서는 소유격·문장 의미의 오류와 원문에 없는 아랍어 혼입을 관찰했다. 프롬프트 보완 후에도 혼입이 재현됐다. 원문에 없는 아랍어 혼입 출력은 `unexpected_script_in_translation` 실패로 거부하고 성공 캐시에 넣지 않는다. 이는 관찰된 오류의 제한적인 방어일 뿐 모든 언어 혼입이나 오역을 검출하지 않는다. 이전 프롬프트의 초안은 이력으로 남지만 현재 프롬프트의 캐시로 재사용하지 않는다.

모든 정상 생성도 `review_status=unreviewed`다. 특히 이탈리아어를 포함한 번역 품질은 출시 통과가 아니며, 인간 검토와 모델/프롬프트 비교가 더 필요하다. 오류를 숨기려고 번역 결과를 자동 교정하거나 원문을 수정하지 않았다.

## 데이터 보존과 회귀 검증

전환 전 `data/backups/before-local-models-v3.sqlite3`에 SQLite backup API로 백업했다. 전환 후 문헌·언어판·파일·원문 버전 각 6개, 문단 468개를 그대로 보존했다. 기존 검색 실행 4개와 모든 결과 snapshot이 백업과 같았다.

- 동일 실제 검색/번역은 추론 메서드를 호출하면 실패하도록 주입한 상태에서도 캐시를 재사용했다.
- 저장 검색/번역 ID 열기는 모델 HTTP 호출을 금지한 상태에서도 동작했다.
- 실제 미설치 모델 이름으로 요청해 키워드 대체와 명시적 진단을 확인했다.
- 합성 테스트에서 모델/원문 변경, 실패 번역 재시도, 빈/비정상 벡터, 클라우드·원격 별칭, 불완전 번역을 검증했다.
- 실제 버전 2 스키마에 저장된 검색을 버전 3으로 옮겨 같은 ID/결과를 재사용하는 회귀 테스트를 추가했다.

최종 검증은 다음과 같이 통과했다. 생략된 테스트는 없다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
# 38 tests, OK
.\.venv\Scripts\python.exe -X utf8 scripts/import_documents.py check
# ok=true, problems=[]
git diff --check
```

변경한 Markdown 6개 파일의 로컬 링크가 유효했다. DB·원문 보관소·평가 원시 결과·백업·가상 환경은 Git 제외 대상임을 확인했다.

## 남은 범위

인간 검토 50문항 이상, 문단 관련성 Recall/nDCG, 가톨릭 용어·주어·부정·참조 보존 평가, 실제 역사 스캔 OCR, 전체 수집, 대규모 속도 측정과 새 UI는 남아 있다. 벡터는 현재 직접 순회하며 ANN·학습형 재정렬기는 측정된 필요성에 따라 비교한다. 여러 문헌을 종합하는 AI 답변은 2차 범위로 구현하지 않았다.

공식 기술 근거. [Qwen 임베딩 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [Ollama Qwen 배포](https://ollama.com/library/qwen3-embedding), [임베딩 API](https://docs.ollama.com/api/embed), [채팅 API](https://docs.ollama.com/api/chat).
