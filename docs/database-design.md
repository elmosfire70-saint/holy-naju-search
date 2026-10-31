# 문헌·파일·검색 기록 DB 설계

논리 설계이며 실행 가능한 SQL 마이그레이션은 구현 단계에서 작성한다.
개인 PC용 초기 원본 DB는 SQLite를 제안한다. GraphDB는 같은 ID와 근거를 사용하는 후속 검색·탐색 저장소로 확장한다.

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
| translations | id, passage_id, language, text, provider, model_revision, prompt_revision, status, reviewed_at | 원문 ID와 생성 버전으로 번역 재사용. 실패 상태도 구별 |
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

캐시 키는 정규화 질의·필터·검색 모드·색인 세대·질의 확장 및 검색 모델 revision을 안정적으로 직렬화한 해시다.
필터 순서는 정규화하되 인용구·부정·언어 의미는 유지한다.

같은 키의 성공한 검색 결과는 재사용한다. 실패나 중단은 유효한 빈 검색 결과로 취급하지 않는다.
색인 변경 후에는 새 검색 실행을 만든다. 과거 run과 hit는 원문 버전 및 해당 번역 버전을 계속 참조한다.
캐시 만료는 과거 검색 기록 삭제와 별개다. 원문 버전이나 번역을 정리할 때 과거 근거가 끊어지지 않도록 참조 여부를 검사한다.

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
