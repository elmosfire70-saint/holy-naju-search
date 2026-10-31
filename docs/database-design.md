# 문헌·파일·검색 기록 DB 설계

목표 논리 설계와 현재 구현 범위를 함께 기록한다. 개인 PC용 원본 DB는 SQLite이며 초기 마이그레이션은 `holy_naju/migrations/001_documents.sql`에 구현했다. GraphDB는 같은 ID와 근거를 사용하는 후속 검색·탐색 저장소로 확장한다.

스키마 버전 1은 sources, documents, editions, assets, ingestion_jobs, acquisitions, document_versions, extraction_pages, passages다. 버전 2에서 index_generations, search_state, passage_fts, search_runs, search_hits, search_history를 추가했다. 버전 3은 embeddings, passage_embeddings, translations 및 search_runs의 retrieval/model_profile을 추가한다. 교정 관련 추가 필드는 해당 기능 구현 시 확장한다. 지원하지 않는 DB 버전은 수정하지 않고 거부한다.

## 식별과 버전

- 공개·내보내기용 ID는 생성 후 바뀌지 않는 UUID로 부여한다. DB 내부 rowid나 URL을 영구 ID로 사용하지 않는다.
- 문헌은 저작물, 문헌판은 언어·발행 형태, 원문 버전은 확보한 내용 상태다.
- 파일의 바이너리 해시와 추출 본문 해시는 별개다. 재추출과 원문 변경을 구별한다.
- 시간은 UTC로 저장하고 UI에서 한국 시간으로 표시한다.
- 공식 번역판의 대응은 확인된 근거로 연결한다. 모델 번역은 별도 번역 기록이다.

## 초기 핵심 테이블

| 테이블 | 핵심 필드·참조 | 제약·목적 |
|---|---|---|
| sources | id, kind, name, base_url | vatican/naju/user_import 구분. 직접 가져온 파일의 발행 출처는 미확인 가능 |
| documents | id, title, author, issued_on, document_type, metadata_status | 저작물의 정체성. 날짜·저자가 미확인이면 빈값과 상태로 보존 |
| editions | id, document_id, source_id, language, canonical_url, translation_kind | 언어판·발행 형태. 파일은 canonical_url이 없을 수 있음 |
| assets | id, sha256, media_type, byte_size, relative_path, original_filename | 동일 바이너리 해시는 유일. 상대 경로로 보관소 이동 가능 |
| acquisitions | id, edition_id, asset_id, origin_kind, origin_url, acquired_at, job_id | 다운로드·사용자 가져오기 이력. 같은 파일의 복수 유입 경로 보존 |
| document_versions | id, edition_id, acquisition_id, body_sha256, extracted_text, extractor_version, created_at | 본문 또는 추출 방식이 바뀌면 새 버전. 원본 파일과 추출기 식별 |
| extraction_pages | id, version_id, page_number, method, engine_revision, language, status, raw_text, corrected_text, confidence, reviewed_at | 스캔·혼합 PDF의 페이지별 추출/OCR 상태. 엔진이 제공하지 않는 confidence는 빈값 |
| passages | id, version_id, ordinal, official_number, page_start, page_end, locator, start_offset, end_offset, text | 원문 버전 내부 순서 유일. 원문과 위치 검증 |
| translations | id, passage_id, source_hash, target_language, model_profile, prompt_revision, text, status, review_status, error, created_at | 원문 ID·해시·모델·프롬프트로 번역 재사용. 실패와 미검토 생성물 구별 |
| embeddings | id, model_profile, input_hash, dimensions, vector, created_at | 모델 프로필과 입력 해시의 조합 유일. 정규화 float32 벡터 |
| passage_embeddings | passage_id, model_profile, input_hash, embedding_id | 원문 문단과 임베딩을 외래 키로 연결 |
| ingestion_jobs | id, target, job_kind, status, checkpoint, attempts, error_code, updated_at | 목록 발견·다운로드·추출·색인의 재개 상태 |
| index_generations | id, created_at, manifest_hash, pipeline_revision, status | 원문·번역·모델 변경을 포함한 색인 세대 |
| search_runs | id, query_original, query_normalized, filters, mode, cache_key, index_generation_id, pipeline_revision, status, created_at | 검색 당시의 조건과 자료 버전. 정상 검색만 재사용 |
| search_hits | run_id, rank, passage_id, translation_id, score, excerpt, highlight_ranges | 당시 순위·근거를 보존. run_id와 rank는 유일 |
| search_history | id, run_id, accessed_at, reused | 같은 결과의 재사용과 최초 검색을 구분 |

문헌판, 자산, 원문 버전, 문단 사이의 참조는 외래 키로 검증한다. SQLite 연결마다 foreign_keys를 활성화한다.
개인 파일 경로가 공식 발행 URL로 오인되지 않도록 acquisition과 edition의 출처를 분리한다.

## 파일 가져오기 흐름

1. 사용자가 파일을 선택하면 형식·크기·파일 해시를 검사한다.
2. 로컬 보관소로 원본을 복사한다. 사용자 원본 파일은 변경하지 않는다.
3. DB에 보관 파일과 가져오기 이력을 기록하고 문헌 메타데이터를 추출한다.
4. 본문·페이지·문단을 추출해 원문 버전과 근거 문단으로 저장한다.
5. 기존 공식 문헌과 일치 후보가 있으면 검토 후 연결한다. 제목 유사성만으로 병합하지 않는다.
6. 검색 색인에 추가하고 새 색인 세대를 발행한다.

파일 저장 후 DB 커밋이 실패하면 정리 대상으로 기록한다. 파일 복사·DB 기록·색인 공개 사이의 중단을 복구할 수 있어야 한다.
현재 구현은 원본을 임시 복사하고 SHA256을 확인한 뒤 보관한다. 작업에 보관 예정 경로를 먼저 기록하고, 보관 파일 등록과 문헌 저장을 분리해 추출 실패 시에도 파일을 추적한다. 문헌·가져오기·버전·페이지·문단 쓰기는 하나의 트랜잭션으로 처리한다. 중단·미등록 파일은 점검 대상으로 표시하며 자동 삭제/자동 재개는 아직 구현하지 않았다.

정상 추출의 재사용 키는 파일 ID·문헌판 ID·추출기/파서 버전·PDF OCR 언어와 모델 해시다. 각 가져오기 이력은 새 행으로 남기고 사용한 버전 ID를 참조한다. PDF 원시 추출 텍스트는 페이지에 저장하며 문단 오프셋은 버전의 정규화 추출 본문 기준이다. 원래 HTML의 바이트 오프셋이나 공식 문단 번호로 간주하지 않는다.
로컬 OCR은 1차 기능이다. 스캔 PDF는 페이지별 OCR로 처리하고 혼합 PDF는 기존 텍스트 추출과 OCR 경로를 구분한다. 페이지 상태는 pending/running/succeeded/needs_review/failed로 보존한다. 검토 상태와 처리 성공은 별개로 판별한다.

근거 문단의 locator는 PDF 페이지와 가능한 경우 원본 페이지의 영역 좌표, 추출 페이지 ID를 포함한다. OCR 원시 결과와 교정 결과를 보존하고 문단은 해당 원문 버전에 연결한다. OCR 엔진이나 교정 본문을 바꾸면 새 원문 버전으로 기록해 과거 검색 근거를 유지한다. 전체 추출 텍스트로 좌표를 계산할 때 문단 오프셋도 검증한다.

파일 처리 상태는 일부 페이지 성공과 전체 성공을 구분한다. 실패 페이지는 재시도할 수 있고 미처리 페이지를 포함한 파일을 완전 수집으로 표시하지 않는다. 엔진·언어 모델은 실제 샘플 평가 후 선택하며 OCR 원문을 외부 서비스로 전송하지 않는다.

## 검색 색인

- FTS5와 벡터 색인은 원문 DB에서 재생성 가능한 파생 데이터다.
- FTS용 정수 키는 passage UUID와 매핑한다.
- 임베딩은 문단 ID·모델 revision·차원·입력 해시로 식별한다. 번역 기반 임베딩이면 번역 ID도 연결한다.
- 토크나이저와 벡터 저장 제품은 한국어 질의·문헌량·장비 평가 후 선택한다.
- 새 색인은 준비 완료 후 원자적으로 현재 세대로 바꾼다. 검색 실행 중 다른 세대가 섞이지 않게 한다.

## 검색 결과 재사용

현재 검색 실행은 전체 트랜잭션이 성공한 뒤에만 보존한다. 실패는 기록/캐시를 남기지 않고 오류로 반환한다. 정상 빈 결과는 재사용할 수 있다. search_hits의 snapshot은 당시 문헌 제목·출처·언어·URL·발표일·점수·근거 발췌·강조 위치를 보존하며 문헌 버전과 문단은 외래 키로 보호한다.

현재 정상 추출 버전과 문헌 메타데이터를 비교해 색인 세대를 관리한다. 색인 재생성은 파생 FTS만 교체하고 과거 실행과 근거 버전을 유지한다. 키워드 검색과 세대 교체는 하나의 쓰기 트랜잭션에서 수행한다. 의미 검색은 긴 모델 호출을 쓰기 트랜잭션 밖에서 수행하고 배치별 임베딩만 커밋한다. 결과 저장 전 세대가 같은지 재검사해 변경된 원문과 결과가 섞이지 않게 한다. 대량 자료의 메타데이터 비교·직접 벡터 순회 비용은 후속 부하 평가 대상이다.

캐시 키는 정규화 질의·필터·검색 모드·색인 세대·질의 확장 및 검색 모델 revision을 안정적으로 직렬화한 해시다.
키워드 키에는 검색 알고리즘 버전을 포함한다. 결과 상한도 키에 포함하며 단어 AND 검색은 순서와 중복을 정규화하고 구절 순서는 유지한다. 결합 검색은 문장의 단어 순서를 유지하고 임베딩 모델 digest·런타임·문맥 길이·입력 지침과 결합 알고리즘 버전을 추가한다. 검색어 원문은 각 요청 이력에 남긴다.
필터 순서는 정규화하되 인용구·부정·언어 의미는 유지한다.

같은 키의 성공한 검색 결과는 재사용한다. 실패나 중단은 유효한 빈 검색 결과로 취급하지 않는다.
색인 변경 후에는 새 검색 실행을 만든다. 과거 run과 hit는 원문 버전 및 해당 번역 버전을 계속 참조한다.
현재 hit는 원문 문단을 참조하며, 번역은 원문 문단에서 별도로 조회한다. 번역 결과를 검색 근거에 붙이는 UI 단계에는 사용한 번역 ID를 명시적으로 전달한다.
캐시 만료는 과거 검색 기록 삭제와 별개다. 원문 버전이나 번역을 정리할 때 과거 근거가 끊어지지 않도록 참조 여부를 검사한다.

## 로컬 모델 파생 데이터

임베딩 입력은 제목과 원문 문단이다. 모델별 질의 지침도 입력 해시에 포함한다. 현재 자료 규모에서는 SQLite 벡터를 읽어 코사인 유사도를 직접 계산하고 키워드 순위와 RRF로 결합한다. 학습형 재정렬기와 ANN 서버는 아직 도입하지 않았다.

번역 캐시는 문단 ID·원문 해시·목표 언어(현재 한국어 고정)·모델 digest/런타임/옵션·프롬프트 버전으로 구분한다. 완료 출력과 실패 기록을 보존하며 실패는 재사용하지 않는다. 원문 버전은 수정하지 않는다. 완료는 생성 처리의 완료일 뿐 내용의 승인이나 정확도 판정이 아니다. 새 번역의 검토 상태는 항상 unreviewed다.

모델 태그가 바뀌면 새 digest 프로필로 생성한다. 호출 후 digest도 재확인한다. 모델이 꺼져 있으면 신규 번역은 오류이고 신규 결합 검색은 진단을 포함한 키워드 대체 경로다. 과거 검색/번역 ID 열기는 모델 없이 동작한다.

## GraphDB 확장 경계

구조적 연결은 초기 관계형 DB의 외래 키에서 바로 복원한다.

| 관계형 데이터 | Graph 노드·관계 매핑 |
|---|---|
| document → edition → version → passage | Document → HAS_EDITION → Edition → HAS_VERSION → Version → HAS_PASSAGE → Passage |
| acquisition·asset | Edition → Acquisition → Asset, Version → EXTRACTED_FROM → Acquisition |
| translation | Passage → HAS_TRANSLATION → Translation |
| 문단의 명시적 문헌 인용 | Passage → CITES → Document. 대상 미확정은 unresolved로 유지 |

의미 관계를 실제로 도입하는 단계에는 다음 구조를 추가한다. 초기부터 자동 지식 추출이나 Graph 서버를 요구하지 않는다.

| 테이블 | 역할 |
|---|---|
| entities / entity_aliases | 인물·기관·장소·주제의 고유 ID와 언어별 별칭 |
| entity_mentions | 근거 문단에서 개체가 언급된 정확한 위치 |
| relations | source_entity_id, relation_type, target_entity_id, status, method, model_revision, reviewed_at |
| relation_evidence | relation_id, passage_id, start_offset, end_offset, evidence_role |

- 관계 후보·검토됨·기각됨을 분리한다. confidence는 검토 상태를 대신하지 않는다.
- 주제 유사성, 원문의 명시적 인용, 공식 기관 판단은 서로 다른 관계 유형이다.
- 근거 없는 모델 추론은 검토된 관계로 승격하지 않는다.
- 내보내기는 노드 UUID·관계 ID·버전·근거 위치를 보존하고 같은 데이터를 다시 보내도 중복을 만들지 않는다.
- 초기 GraphDB 연계는 읽기 전용 투영을 제안한다. 원문과 검토 정보의 수정은 원본 DB에서 수행해 이중 쓰기 충돌을 피한다.
- Graph 동기화 중단 시 원본 DB 검색이 계속 동작해야 한다.

## 보관·삭제·복구

- 로컬 보관소에는 DB, assets, 모델, 재생성 가능한 색인을 구분한다.
- 원본 DB·보관 파일·manifest를 일관된 시점에 백업한다. 검색 색인은 복원 후 재생성할 수 있다.
- 파일은 여러 문헌판에서 참조할 수 있다. 문헌 삭제 시 실제 파일 참조를 검사한다.
- 사용자가 삭제한 문헌은 일반 검색에서 제외하고 복구 가능한 보관 상태를 둔다. 영구 삭제는 과거 검색 근거 영향과 함께 별도 처리한다.
- 공개 GitHub에는 앱 코드·설계·권리 확인된 테스트 자료만 저장한다. 수집 원문·사용자 문서·DB·검색 기록은 저장하지 않는다.

## 2차 종합 답변의 확장 지점

1차 출시 후 answer_runs와 answer_citations를 추가한다. 답변 실행은 사용한 검색 실행 ID·질의·원문/번역 버전·로컬 모델 revision·프롬프트 revision·생성 본문·완료 상태를 보존한다. 인용은 답변 내 위치와 근거 문단 ID를 연결하고 인용 구절이 보존 본문에 존재하는지 검증한다.

답변 캐시는 근거 집합과 모델·프롬프트 버전이 일치할 때만 재사용한다. 생성 실패를 유효한 답변으로 저장하지 않으며 원문과 모델 출력의 구분을 유지한다. GraphDB 연결은 이 기능의 필수 실행 조건이 아니다.

공식 참고. https://www.sqlite.org/fts5.html 및 https://www.sqlite.org/foreignkeys.html
