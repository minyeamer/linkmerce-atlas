# Linkmerce Atlas

Linkmerce를 처음 접하는 사람이 **Core · API · Airflow · dbt · BigQuery/Postgres 사이의 코드 관계를 근거와 함께 탐색하는 웹 앱**이다. 데이터베이스에 접속하거나 데이터를 수집하지 않는다. 로컬 Linkmerce 소스를 읽기 전용으로 마운트하고, 코드를 실행하지 않고 분석한다.

실제 Wirelog C11 공유 라이브러리를 Docker 안에서 빌드해 도달 관계를 계산한다. Python으로 흉내 낸 Datalog 엔진으로 대체하지 않는다. AI 연결 없이도 구성요소·관계·경로·근거를 확인할 수 있고, AI를 연결하면 찾은 근거를 한국어로 설명한다.

## 실행

```bash
cd path/to/linkmerce-atlas
cp .env.example .env
docker compose up -d --build
```

브라우저에서 <http://localhost:8088>을 연다. 기본 소스 경로는 형제 디렉터리 `../linkmerce`다. 다른 환경에서는 `.env`의 `LINKMERCE_PATH`를 바꾼다. 호스트에 Python, Node.js, Codex CLI를 설치할 필요가 없다.

```bash
docker compose logs -f web
docker compose down
```

`docker compose down`은 계정과 색인 볼륨을 보존한다. `down -v`는 저장된 사용자 연결 정보까지 삭제하므로 주의한다.

## 사용

1. 왼쪽에서 Dag ID, 모델명 또는 모듈명을 검색한다.
2. 구성요소를 선택해 직접 연결과 Wirelog가 계산한 상위·하위 구성요소를 본다.
3. 상위·하위 목록의 항목을 누르면 두 구성요소 사이의 근거 경로를 확인한다.
4. 질문을 입력하고 `근거 탐색` 또는 `AI 설명`을 선택한다.
5. 출처 버튼을 누르면 파일 경로, 행 번호, 색인 시점의 코드가 표시된다.

예시 질문:

- `smartstore_order Dag은 BigQuery와 Postgres에서 어떤 dbt selector를 사용해?`
- `linkmerce.api.smartstore.api.order는 어떤 Core 모듈을 가져와?`
- `smartstore.order와 smartstore__sales_daily 모델은 어떻게 연결돼?`
- `dual_load가 Linkmerce의 다른 구성요소와 어떤 관계인지 설명해줘`

질문마다 독립적으로 검색한다. 이전 질문의 대화 이력을 모델에 전달하지 않으므로, 후속 질문에도 대상 이름을 적는다. 선택한 구성요소는 질문 범위에 포함된다.

## 답변 마크다운

AI 답변의 제목, 강조, 목록, 인라인 코드, 코드 블록, 인용문과 표를 렌더링한다. 출처 ID는 문장·목록·표 안에서도 클릭할 수 있는 버튼으로 유지하며, 코드 예제 안의 출처 문법은 원문 그대로 표시한다. 사용자 질문은 일반 텍스트로 표시한다.

렌더러는 로컬에 묶은 markdown-it와 DOMPurify를 사용한다. 원시 HTML과 실행 가능한 링크는 허용하지 않고, 외부 이미지는 자동으로 불러오지 않는다. 브라우저에서 CDN에 접속하지 않으며 Docker 실행에도 Node.js가 필요 없다.

## AI 계정

### 사용자별 OpenAI API 키

우측 상단 `AI 계정 연결`에서 API 키를 연결한다. 계정별로 모델 목록을 조회하고 선택한 모델로 Responses API를 호출한다. 서버 공용 API 키나 호스트 Codex 인증을 사용하지 않는다.

API 키와 OAuth 토큰은 서버 SQLite에 Fernet으로 암호화해 저장한다. 암호화 키와 세션 서명 키는 Docker의 `index-data` 볼륨에 저장한다. 브라우저 쿠키에는 임의 세션 식별자만 넣는다. 자격 증명을 localStorage, Git 또는 응답 본문에 넣지 않는다. 계정 연결은 최대 12시간 유효하며 연결 해제 시 삭제한다. 서버 관리자와 볼륨 접근 권한자는 서버의 자격 증명을 복호화할 수 있다.

기본 추천 모델은 목록에 있을 경우 `gpt-6-luna`이며, 설정한 `OPENAI_MODEL`과 사용자별 선택을 우선한다. 여러 경로를 비교하는 설명 품질은 `gpt-6.1-sol`과 비교할 수 있다. 실제 Luna 3회 검증 결과는 `docs/validation.md`에 기록했다.

API 키 검증과 모델 목록 조회가 성공해도 유료 추론 가능 여부까지 확인된 것은 아니다. 실제 AI 응답이 `response.completed`에 도달해야 호출 성공으로 처리한다. 사용 한도·권한·중단 오류를 성공한 답변으로 표시하지 않고, 다른 계정이나 과금 방식으로 자동 전환하지 않는다.

API 사용료는 사용자가 연결한 OpenAI Platform 계정에 청구된다. AI 설명 시 질문과 선택한 코드 근거가 OpenAI로 전송된다.

### ChatGPT 로그인과 구독 사용

**원격 웹 앱용 Sign in with ChatGPT는 OpenAI의 승인된 OAuth 클라이언트가 필요하다.** 현재 프로젝트는 클라이언트 등록 정보가 없으면 로그인 버튼을 비활성화한다. 다른 앱이나 Codex의 클라이언트 ID를 재사용하지 않는다.

승인된 웹 앱에서 ChatGPT 구독 사용 권한까지 부여받았다면 다음을 설정한다.

```dotenv
PUBLIC_URL=https://atlas.example.com
CHATGPT_CLIENT_ID=발급받은_웹앱_클라이언트_ID
CHATGPT_CLIENT_SECRET=발급받은_클라이언트_시크릿
```

등록할 콜백 URL은 `https://atlas.example.com/api/auth/callback`이다. OpenID Connect discovery, Authorization Code + PKCE, state/nonce 검증을 사용하는 경로를 구현했다. 로그인 권한과 `chatgpt.tokens.use.direct` 구독 사용 권한을 구분한다. 계정별 토큰 갱신과 연결 해제 시 refresh token 폐기 경로도 포함한다.

OAuth 연동 코드는 등록 정보를 전제로 하며, 실제 승인 클라이언트를 통한 통합 검증은 아직 필요하다. 공개된 로컬 앱용 자동 등록은 원격 다중 사용자 웹 서비스에 그대로 적용하지 않는다. 이 프로젝트는 Codex CLI 호출, 브라우저 로그인 쿠키 재사용 또는 비공식 ChatGPT API를 사용하지 않는다.

공식 문서(2026-10-28 확인):

- [Sign in with ChatGPT 개요](https://developers.openai.com/siwc/token-sharing-open-source)
- [웹 앱 연동과 등록 조건](https://developers.openai.com/siwc/website)
- [자체 호스팅 VM의 제한](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [모델 조회와 추론](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview 제약](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)

## 무엇을 온톨로지로 정의했는가

`module`, `function`, `dag`, `plugin`, `table`, `source`, `model`, `macro`, `selector`를 구성요소로 정의하고 아래 관계를 추출한다. 관계의 방향은 **선행 요소 → 후행 요소**다.

| 관계 | 의미 | 해석의 한계 |
| --- | --- | --- |
| imported_by | Core·API·플러그인을 다른 모듈이나 Dag이 import | 실제 호출·운영 실행을 보장하지 않음 |
| configured_load | Dag이 tables 설정을 dual_load에 전달 | 조건부 선언, 실제 적재 성공을 보장하지 않음 |
| runs_selector | Dag이 dbt selector를 사용 | 동적 실행 조건 충족 여부는 알 수 없음 |
| selects_model | 정적으로 해석한 selector가 모델을 선택 | 지원하는 fqn/path 정의에 한함 |
| declared_source | 설정상 테이블과 dbt source 연결 | 실제 DB 존재·운영 profile은 확인하지 않음 |
| dbt_source | source를 모델이나 macro가 참조 | 리터럴 source만 해석 |
| dbt_ref | 모델을 다른 모델이나 macro가 참조 | 리터럴 ref만 해석 |
| macro_used_by | 알려진 macro를 모델·macro가 사용 | 정적으로 확인된 호출 이름에 한함 |
| may_trigger | Dag이 다른 Dag을 트리거할 수 있음 | 조건부 호출 선언 |

`ontology/linkmerce.dl`은 이 관계의 전이적 도달 규칙을 정의한다. 코드 import·실행 제어·데이터 의존 관계를 함께 연결하므로, 결과는 **구성상 연결 가능성**이다. 데이터 계보나 장애 전파가 반드시 일어난다는 뜻으로 해석하지 않는다. 화면과 AI 프롬프트에서도 관계 종류와 조건부 여부를 전달한다.

Wirelog는 도달 여부를 계산한다. Python은 원본 edge를 따라 가장 짧은 경로와 각 연결의 근거를 재구성한다. Wirelog 자체의 내장 증명 기능을 사용한다고 주장하지 않는다. 현재 버전은 시작 또는 수동 갱신 때 전체 스냅샷을 다시 추출하고 Wirelog 세션을 재생성한다. 파일 감시와 변경분만 갱신하는 영구 세션은 아직 구현하지 않았다.

## 분석 범위와 정확성

- `src/linkmerce/**/*.py`, `airflow/dags/**/*.py`, `airflow/plugins/*.py`, 두 dbt 프로젝트의 models/macros/selector와 README를 분석한다.
- `src/env/config.yaml`은 `tables` 아래의 스키마·테이블명만 근거로 내보낸다. 다른 설정값은 내보내지 않는다.
- credentials, cookies, service account, dbt profiles, `.env`, DB의 행 데이터는 읽지 않는다.
- 소스를 import하거나 ETL·Dag·dbt 명령을 실행하지 않는다.
- 파일 해시로 스냅샷 식별자를 만들고, 답변을 생성한 스냅샷 ID를 응답에 포함한다. 코드 발췌는 색인 당시의 내용이다.
- 동적 Dag/selector, 외부 dbt 패키지, 전체 Python 호출 그래프, dbt 실행 profile에 따른 실제 schema/database, Jinja 분기로 생성되는 모든 SQL을 완전히 해석하지 않는다.
- 정적으로 발견한 양쪽 분기의 관계가 함께 들어갈 수 있다. `parents`/`children`은 정적 ref 그래프를 기준으로 확장한다. dbt CLI의 완전한 selector 실행과 동등하다고 보장하지 않는다.
- 지원하지 않거나 해결하지 못한 항목은 UI 하단의 분석 진단에 표시한다. 진단이 0개라도 전체 코드가 완전히 분석됐다는 뜻은 아니다.
- 검색은 이름·한국어 별칭·Wirelog 경로에 기반한다. 임베딩 검색이나 LLM 질의 계획은 아직 없다. 코드 관련 주장에는 출처를 요구하고 누락·알 수 없는 출처를 점검하지만, AI가 쓴 모든 문장의 사실 여부를 기계적으로 보증하지는 않는다.

## 개발과 검증

```bash
docker compose run --rm web python -m unittest discover -s tests -v
git diff --check
```

프런트엔드 렌더링 검증은 Node.js 개발 환경에서 실행한다. 저장된 답변을 사용하므로 AI API 비용이 발생하지 않는다.

```bash
npm ci --ignore-scripts
npm test
# 의존성을 업데이트한 경우에만 브라우저용 파일 갱신
npm run vendor:markdown
```

테스트는 실제 Wirelog 라이브러리를 사용해 재귀·순환·비연결 관계, Core→API→Dag→dbt 경로, Postgres/BigQuery 분리, 검색 관련성, 주석 및 macro 범위, 설정 비밀정보 제외, 경로 이탈 차단, 암호화된 사용자 세션 분리, API 보호를 검증한다.

폴더 구조:

```text
app/indexer.py       정적 코드·설정 추출
app/engine.py        Wirelog 공개 C API 바인딩
app/graph.py         검색·경로·근거 조회
app/auth.py          사용자별 API/OIDC 연결
app/ai.py            근거 기반 Responses API 호출
app/main.py          FastAPI 라우트
app/static/          HTML/CSS/JavaScript UI
ontology/            Datalog 규칙
scripts/             실제 계정 검증 도구
tests/               자동 검증
docs/                설계와 검증 기록
```

Wirelog 소스는 `63f75a25139795b79f0ca75783c9d771c8fc892f`에 고정한다. 엔진을 업데이트할 때 ABI·규칙·실제 경로 테스트를 함께 확인한다. Wirelog는 LGPL-3.0-or-later이며 공유 라이브러리로 연결한다. 이미지 `/opt/wirelog-src`에 해당 소스·라이선스·빌드 파일을 포함한다. 원격 배포 절차는 `docs/deployment.md`를 참고한다.
