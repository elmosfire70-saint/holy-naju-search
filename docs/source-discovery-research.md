# 공식 공개 목록 발견 조사

확인일은 2026-10-31이다. 공식 페이지와 목록에 표시된 직접 링크를 웹 도구로 확인했다. 전체 사이트 크롤링이나 원문 일괄 보관은 하지 않았다. 아래의 경로 규칙은 관찰에서 도출한 구현 제안이며 기관이 제공한 API 명세가 아니다. 공개 목록의 링크 존재, 실제 본문 접근, 로컬 수집 완료는 서로 다른 상태다.

## 확인된 시작점

| 문헌군 | 확인한 URL | 확인 범위 |
| --- | --- | --- |
| 공의회 상위 목록 | [공의회 목록](https://www.vatican.va/archive/hist_councils/index.htm) | 현재 표시된 하위 링크는 제1차·제2차 바티칸 공의회다. 역사상 모든 공의회의 목록이라는 뜻은 아니다. |
| 제2차 바티칸 공의회 | [공식 목록](https://www.vatican.va/archive/hist_councils/ii_vatican_council/index.htm) | 16문헌 및 문헌별 다국어 링크. |
| 제1차 바티칸 공의회 | [공식 목록](https://www.vatican.va/archive/hist_councils/i-vatican-council/index.htm) | 두 헌장의 이탈리아어·라틴어 링크. |
| 교리서 언어 선택 | [교리서 목록](https://www.vatican.va/archive/ccc/index.htm) | 교리서와 요약편이 별도 항목이다. |
| 영어 교리서 본문 차례 | [IntraText 차례](https://www.vatican.va/archive/ENG0015/_INDEX.HTM) | 교리서 장절 본문으로 연결한다. 단어 목록·용어 색인·도움말도 함께 있으므로 구분한다. |

## 제2차 바티칸 공의회

공식 목록의 문헌은 헌장 4개, 선언 3개, 교령 9개다. 헌장은 Dei Verbum, Lumen Gentium, Sacrosanctum Concilium, Gaudium et Spes이며 선언은 Gravissimum Educationis, Nostra Aetate, Dignitatis Humanae다. 교령은 Ad Gentes, Presbyterorum Ordinis, Apostolicam Actuositatem, Optatam Totius, Perfectae Caritatis, Christus Dominus, Unitatis Redintegratio, Orientalium Ecclesiarum, Inter Mirifica다. 이는 이 목록의 문헌 구분이며 모든 역사 문헌의 분모가 아니다. [공식 목록](https://www.vatican.va/archive/hist_councils/ii_vatican_council/index.htm).

목록에 나타나는 언어의 합집합은 Arabic, Byelorussian, Chinese, Croatian, Czech, English, French, German, Hebrew, Hungarian, Italian, Latin, Latvian, Portuguese, Spanish, Swahili다. 문헌마다 제공 언어가 다르며 한국어 링크는 이 목록에서 확인되지 않는다. 언어 코드를 조합해 가상의 URL을 만들지 말고 실제 href와 언어 라벨을 보존한다. [공식 목록](https://www.vatican.va/archive/hist_councils/ii_vatican_council/index.htm).

대표 직접 링크를 열어 확인한 경로와 예외는 다음과 같다.

| 관찰 | 실제 URL |
| --- | --- |
| 헌장 HTML | [Dei Verbum 영어](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_const_19651118_dei-verbum_en.html) |
| 선언 HTML | [Nostra Aetate 영어](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_decl_19651028_nostra-aetate_en.html) |
| 교령 HTML | [Ad Gentes 영어](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_decree_19651207_ad-gentes_en.html) |
| 라틴어 파일명은 `_lt`이나 화면 라벨은 Latin/LA | [Dei Verbum 라틴어](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_const_19651118_dei-verbum_lt.html) |
| 중국어 PDF는 archive 경로 밖이다 | [Dei Verbum 중국어](https://www.vatican.va/chinese/concilio/vat-ii_dei-verbum_zh-t.pdf) |
| 히브리어는 PDF도 있다 | [Dei Verbum 히브리어](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_const_19651118_dei-verbum_he.pdf) |
| 기타 확인한 언어 접미사 | [체코어 `_cs`](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_const_19651118_dei-verbum_cs.html), [벨라루스어 `_be`](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_const_19651118_dei-verbum_be.html), [스와힐리어 `_sw`](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_const_19651118_dei-verbum_sw.html), [크로아티아어 `_hr`](https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_decl_19651028_nostra-aetate_hr.html) |

발견 규칙 제안은 해당 공식 목록의 직계 href 중 같은 호스트의 `/archive/hist_councils/ii_vatican_council/documents/` 아래 `.html`·`.pdf` 및 `/chinese/concilio/` 아래 `vat-ii_*.pdf`만 받는 것이다. HTML만 허용하거나 archive prefix만 허용하면 실제 공식 언어판을 누락한다. 문헌 본문의 주석·관련 문헌 링크로 재귀 확장하지 않는다. 제목과 언어 라벨이 없는 링크는 추정하지 말고 검토 대상으로 둔다.

## 제1차 바티칸 공의회

공식 목록에서 확인한 두 문헌의 직접 URL은 아래 네 개다. 이 목록에는 영어·한국어 링크가 없으나 다른 공식 경로에도 없다는 뜻은 아니다. [공식 목록](https://www.vatican.va/archive/hist_councils/i-vatican-council/index.htm).

- Dei Filius, 1870-04-24. [이탈리아어](https://www.vatican.va/archive/hist_councils/i-vatican-council/documents/vat-i_const_18700424_dei-filius_it.html), [라틴어](https://www.vatican.va/archive/hist_councils/i-vatican-council/documents/vat-i_const_18700424_dei-filius_la.html).
- Pastor Aeternus, 1870-07-18. [이탈리아어](https://www.vatican.va/archive/hist_councils/i-vatican-council/documents/vat-i_const_18700718_pastor-aeternus_it.html), [라틴어](https://www.vatican.va/archive/hist_councils/i-vatican-council/documents/vat-i_const_18700718_pastor-aeternus_la.html).

제안한 허용 경로는 같은 호스트의 `/archive/hist_councils/i-vatican-council/documents/vat-i_const_*.html` 중 공식 목록에서 실제 발견한 href다. 제2차의 라틴어 `_lt`와 달리 제1차 샘플은 `_la`이므로 접미사만으로 언어를 통일 추론하지 않는다.

## 영어 교리서와 한국어 공식 자료

[영어 IntraText 차례](https://www.vatican.va/archive/ENG0015/_INDEX.HTM)는 [서문 `__P1.HTM`](https://www.vatican.va/archive/ENG0015/__P1.HTM), [계시 항목 `__PF.HTM`](https://www.vatican.va/archive/ENG0015/__PF.HTM) 같은 본문으로 연결한다. 제안한 본문 허용 정규식은 대소문자를 보존한 `^/archive/ENG0015/__P[0-9A-Z]+\.HTM$`이며 차례의 직접 링크만 대상으로 한다. `_INDEX.HTM`은 발견용으로만 사용하고 단어 빈도·용어 색인·concordance·도움말 링크를 본문으로 수집하지 않는다.

교황청 [교리서 언어 선택 목록](https://www.vatican.va/archive/ccc/index.htm)에는 한국어 링크가 보이지 않는다. 다만 한국천주교주교회의의 [한국어 교리서 진입점](https://www.cbck.or.kr/Documents/Catechism)과 [제11항 한국어·라틴어 본문](https://www.cbck.or.kr/documents/catechism/read/11)은 직접 확인됐다. 진입점은 개정 제2판 18쇄, 2023-05-01 및 정정 사항을 표시하므로 영어 IntraText와 동일한 판·수정 상태라고 간주하면 안 된다. 낮은 경로 `/documents/catechism`은 도구 오류였고 실제 내비게이션 링크는 `/Documents/Catechism`이었다.

CBCK [제2차 바티칸 공의회 문헌 진입점](https://www.cbck.or.kr/Documents/Council)도 확인했으나 하위 문헌 전체·첨부·페이지 이동을 조사한 것은 아니다. CBCK robots는 `https://www.cbck.or.kr/robots.txt` 접근에서 도구 오류가 발생해 확인하지 못했다. 한국어 자료의 존재는 확인하되 이번 Vatican/najumary 수집 허용 범위에 자동 추가하지 않고 별도 정책·목록 조사 대상으로 남긴다.

## 트리엔트 및 더 이전 공의회

교황청 기본 [공의회 목록](https://www.vatican.va/archive/hist_councils/index.htm)에 이 공의회들의 직접 링크가 없다는 사실만 확인했다. Vatican 공식 도메인에서 트리엔트·피렌체·라테라노 관련 목록을 제한적으로 검색했으나 이번 조사에서는 수집 가능한 전체 문헌 목록 진입점을 확정하지 못했다. 따라서 상태는 `entry_not_yet_verified`이며 `문헌 없음` 또는 `온라인 공개 없음`이 아니다.

[교황청 사도문서고 보유 자료 설명](https://www.archivioapostolicovaticano.va/content/aav/en/patrimonio.html)은 제1차·제2차 바티칸 공의회 기록 전체와 트리엔트 공의회에서 생산된 기록 상당 부분을 소장한다고 설명한다. **소장·목록·인쇄 출판·공개 전문 제공은 서로 다르다.** 이 설명 페이지를 공의회 전문 파일로 가져오거나, 소장 사실을 온라인 전문 접근 성공으로 기록하지 않는다. 문서고는 기존 허용 호스트와도 다르므로 자동 수집을 확장하지 않는다.

이후 조사 시 공식 편집판·권별 식별자·파일 공개 여부·본문 추출 가능성을 각각 확인한다. 다른 문헌의 주석에 나타난 공의회 인용은 해당 공의회의 전체 원문을 확보한 것으로 계산하지 않는다.

## robots와 운영 경계

[교황청 robots](https://www.vatican.va/robots.txt)는 확인 시 `User-agent: *`, `Allow: *`, `Crawl-delay: 2`였다. 자동 클라이언트는 호스트 요청 사이 최소 2초를 지키고 실행 시 다시 확인한다. robots 확인 실패는 허용으로 간주하지 않는다.

[교황청 이용 조건](https://www.vatican.va/content/vatican/en/legal-notes.html)은 개인·비영리 이용과 그 밖의 복제·수집·배포를 구분한다. robots 허용은 재배포 허가가 아니다. 원문은 개인 PC의 Git 제외 데이터에 보관하며 공개 서비스·전문 재배포·외부 모델 전송으로 확장하지 않는다.

구현 검증 제안은 고정 호스트·프로토콜·포트·경로 검사, fragments 제거와 query 거부, 리디렉션 최종 URL 재검사, 목록/본문 URL 구분, 발견 한도·요청/바이트 한도 및 중단 상태 저장이다. 발견 건수는 확인한 목록·시각·언어 필터·상한과 함께 제시한다. `발견 N건`을 전체 교회 문헌의 확보율로 표시하지 않는다.

기존 우선 회칙 세 개는 사용자 후보 목록 그대로 유지한다. 이번 조사는 그 세 개가 모든 주요 회칙의 확정 목록이라는 판단이나 새 우선순위 결정을 하지 않았다.

## 수행한 확인과 미확인

- 공식 목록 4개와 영어 교리서 차례, 대표 HTML/PDF 및 robots·이용 조건을 웹 도구로 열어 확인했다. 문서에 연결한 URL은 도구에서 실제 관찰한 주소다.
- 모든 언어판 본문·PDF 품질·최신 개정 일치·CBCK robots·역사 공의회 전체 공개 목록은 확인하지 않았다.
- 이 문서는 연구 결과만 기록한다. 수집 코드·DB·기존 설정·Git 이력은 변경하지 않았다.
