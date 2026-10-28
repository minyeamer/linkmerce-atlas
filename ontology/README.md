# Linkmerce Atlas 온톨로지 명세

Linkmerce의 코드와 설정을 어떤 개념·관계로 표현하고, Wirelog가 무엇을 계산하는지 정의한다.
프로젝트 구조를 처음 이해하려는 사람과 정적 추출기를 수정하는 개발자가 함께 보는 문서다.

## 1. 모델의 목적과 범위

다음 질문에 코드 근거를 연결하는 것이 목적이다.

- 이 API 함수는 어떤 Core 모듈을 가져오는가?
- 이 Dag은 어느 플랫폼의 dbt selector를 사용하는가?
- selector가 선택하는 모델과 그 후속 모델은 무엇인가?
- 두 구성요소가 어떤 관계를 거쳐 연결되며 각 연결의 원문은 어디인가?

모델의 대상은 **코드·설정에 선언된 구성요소와 의존 관계**다.
DB 행 데이터, 실제 실행 이력, 로그인 성공 상태, 매출 지표의 업무 정의는 포함하지 않는다.
Python의 Core 모듈과 DB의 `core` 스키마를 구분하며, Python API 함수가 HTTP 서버라는 전제도 두지 않는다.

이 구현은 프로젝트에 필요한 경량 도메인 온톨로지다.
개념과 관계는 Python/JSON 그래프로 표현하고, 도달 계산만 Datalog 관계로 투영한다.
OWL/RDF 스키마, 클래스의 상속·동치·배타성 공리, 그 공리를 검사하는 일반 온톨로지 추론기는 구현하지 않았다.
아래 종류·관계 표는 현재 구현의 의미 명세이며, 이를 별도의 기계 판독 스키마로 강제하는 검증기는 아직 없다.

## 2. 명세·사실·규칙·설명의 위치

| 구분 | 위치 | 역할 |
| --- | --- | --- |
| 온톨로지 명세 | 이 문서 | 개념, 식별자, 관계의 의미·방향·해석 한계를 정의 |
| 사실 추출 | [app/indexer.py](../app/indexer.py) | 소스를 실행하지 않고 구성요소·직접 관계·근거를 추출 |
| 실행 규칙 | [linkmerce.dl](linkmerce.dl) | `dependency`에서 전이적 도달 관계 `reaches`를 계산 |
| 엔진 연결 | [app/engine.py](../app/engine.py) | 공개 C API로 실제 Wirelog 라이브러리에 사실을 입력 |
| 탐색·설명 경로 | [app/graph.py](../app/graph.py) | 검색, 도달 결과 조회, 원본 edge를 통한 근거 경로 재구성 |
| 자연어 설명 | [app/ai.py](../app/ai.py) | 선택된 사실과 근거를 LLM으로 설명 |
| 추출 결과 | Docker 데이터 볼륨의 `/data/snapshot.json` | 해당 색인의 개별 대상·관계·근거·메타데이터. Git 공개 대상에서 제외 |

`linkmerce.dl`만 읽으면 개념의 종류나 `imported_by`의 뜻을 알 수 없다.
그 파일은 온톨로지 전체를 정의한 파일이 아니라 **현재 온톨로지를 대상으로 실행하는 도달 규칙 파일**이다.
LLM이 온톨로지를 만들거나 사실을 승인하는 구조도 아니다. 종류와 관계는 앱에서 정하고 정적 추출기가 입력을 만든다.

## 3. 개념과 식별자

`kind`는 개념의 종류이고, `layer`는 소속 계층이다.
`id`는 개별 대상의 식별자이며 `label`은 표시 이름이다. 표시 이름만으로 두 대상을 합치지 않는다.
아래 `{...}`는 식별자 형식을 설명하는 자리표시자다.

| kind | 의미 | 식별자 형식 | layer |
| --- | --- | --- | --- |
| `module` | Python 모듈. Core 클래스 각각은 독립 노드로 추출하지 않음 | `py:{module}` | `core`, `api`, `extensions`, `common` |
| `function` | API 모듈의 최상위 공개 함수 | `fn:{module}.{function}` | `api` |
| `dag` | 정적 문자열 `dag_id`로 확인한 Airflow Dag | `dag:{dag_id}` | `airflow` |
| `plugin` | Airflow 플러그인 모듈 | `plugin:{module}` | `airflow` |
| `table` | 설정 또는 dbt source 선언에서 확인한 테이블 식별자 | `table:{platform}:{schema}.{table}` | `postgres`, `bigquery` |
| `source` | dbt의 논리적 source와 table 조합 | `source:{platform}:{source}.{table}` | `dbt_postgres`, `dbt_bigquery` |
| `model` | dbt SQL 모델 | `model:{platform}:{file_stem}` | `dbt_postgres`, `dbt_bigquery` |
| `macro` | SQL 파일에 선언된 dbt macro | `macro:{platform}:{name}` | `dbt_postgres`, `dbt_bigquery` |
| `selector` | Dag 또는 selectors.yml에서 확인한 dbt selector | `selector:{platform}:{name}` | `dbt_postgres`, `dbt_bigquery` |

### 식별 범위의 주의점

- `platform`은 `postgres` 또는 `bigquery`다. 두 플랫폼의 동명 모델·테이블·selector는 다른 대상이다.
- dbt `source`는 논리적 선언이고 `table`은 정적으로 해석한 스키마·테이블명이다. 둘을 같은 종류로 합치지 않는다.
- 실제 DB의 존재 여부나 profile에 따른 database/schema는 조회하지 않는다.
- 현재 모델·macro 식별자는 플랫폼과 이름을 사용한다. 같은 플랫폼에서 동명 모델·macro가 충돌하는 상황이나 외부 패키지 namespace를 일반적으로 해결하는 설계는 아니다.
- 이 표는 추출한 대상의 범위다. 코드에 존재하는 모든 함수·클래스·태스크를 개별 대상으로 모델링하지 않는다.

## 4. 관계의 의미와 방향

모든 화살표는 **공급자·선행 요소 → 소비자·후행 요소** 방향이다.
예를 들어 `A imported_by B`는 **B가 A를 import한다**는 뜻이다.
소비자에서 공급자로 향하는 일반적인 “depends on” 그림과 반대일 수 있으므로 방향을 확인해야 한다.

| relation | source → target | 의미 | certainty |
| --- | --- | --- | --- |
| `imported_by` | module/function/plugin → module/function/plugin/dag | target에서 source에 해당하는 정적 import를 발견 | `declared` |
| `configured_load` | dag → table | `tables` 설정과 지원하는 `dual_load` 호출의 적재 대상을 연결 | `conditional` |
| `runs_selector` | dag → selector | 지원하는 dbt 작업 구성 함수에 문자열 selector가 전달됨 | `conditional` |
| `selects_model` | selector → model | 지원하는 정적 selector 정의가 모델을 선택 | `declared` |
| `declared_source` | table → source | dbt source 선언의 논리적 이름과 정적 테이블명을 연결 | `declared` |
| `dbt_source` | source → model/macro | target의 SQL에서 리터럴 `source()` 참조를 발견 | `declared` |
| `dbt_ref` | model → model/macro | target의 SQL에서 리터럴 `ref()` 참조를 발견 | `declared` |
| `macro_used_by` | macro → model/macro | target에서 알려진 macro 이름의 사용을 발견 | `declared` |
| `may_trigger` | dag → dag | 지원하는 트리거 호출에 다른 Dag의 정적 ID가 전달됨 | `conditional` |

### 선언과 실행은 다릅니다

`declared`는 선언을 정적으로 발견했다는 뜻이며, 운영 환경에서 실행되었거나 검증되었다는 뜻이 아니다.
`conditional`은 실행 조건이 있는 구성임을 나타낸다. 현재 모든 분기 조건을 논리식으로 저장·평가하지는 않는다.

- import는 실제 함수 호출이나 데이터 흐름을 보장하지 않는다.
- 적재 대상 선언은 실제 적재·테이블 존재·성공 건수를 보장하지 않는다.
- selector 연결은 실제 Dag 실행에서 그 selector가 수행됐다는 뜻이 아니다.
- 트리거 선언은 후속 Dag이 실제로 실행됐다는 뜻이 아니다.
- 주석 처리된 Python 호출은 AST의 실행 구문이 아니므로 활성 관계로 추출하지 않는다.
- Python·Jinja의 모든 동적 구문이나 dbt CLI의 전체 선택 의미를 해석하지 않는다.

## 5. 직접 사실과 원문 근거

스냅샷의 `nodes`는 ID를 키로 한 구성요소 사전이고, `edges`는 직접 관계 목록이다.
다음은 구조를 보여주는 **합성 예제**다. 실제 운영 설정이나 저장된 스냅샷을 옮긴 것이 아니다.

```json
{
  "source": "py:linkmerce.core.store.api.order.extract",
  "target": "fn:linkmerce.api.store.order",
  "relation": "imported_by",
  "evidence": "E000000000001",
  "dependency": true,
  "certainty": "declared",
  "support": []
}
```

- `source`, `target`: 연결 양끝의 구성요소 ID
- `relation`: 위 표의 직접 관계 종류
- `evidence`: 스냅샷의 `evidence` 사전에 존재하는 주 근거 ID
- `support`: 연결 해석에 함께 필요한 추가 근거 ID. 적재 호출과 테이블명 매핑을 함께 제시하는 경우 등이 있음
- `dependency`: Wirelog 도달 계산에 넣을 연결인지 표시
- `certainty`: 정적 선언의 성격. 확률이나 사람의 승인 상태가 아님

근거는 `id`, `path`, `line`, `end`, `snippet`, `format`을 가진다.
ID는 상대 경로·행·발췌 내용으로 만든 해시이며 발췌가 달라지면 바뀔 수 있다.
`format: excerpt`는 색인 시점의 코드 발췌이고 `normalized`는 YAML 선언·버전 정보 등을 정규화한 표현이다.
정규화된 표현을 원문의 완전한 복사본으로 해석하지 않는다.

설정에서는 필요한 테이블명 매핑만 근거로 내보낸다.
자격 증명·쿠키·서비스 계정·dbt profile·환경변수 파일과 DB 행 데이터는 사실의 출처로 사용하지 않는다.
코드 발췌 자체에도 공개 제한이 있을 수 있으므로, AI 전송·공개 범위는 적용하는 저장소에 맞춰 확인해야 한다.

## 6. Wirelog로 투영하는 사실과 추론 규칙

Python의 종류 있는 관계 중 `dependency: true`인 연결을 숫자 쌍으로 변환한다.
문자열 ID와 정수의 대응은 해당 그래프에서 만들며, 이 정수는 색인 간에 고정된 도메인 식별자가 아니다.
원래 관계 종류와 근거는 Python 그래프에 남겨 둔다.

```datalog
.decl dependency(upstream: int64, downstream: int64)
.decl reaches(upstream: int64, downstream: int64)
reaches(X, Y) :- dependency(X, Y).
reaches(X, Z) :- reaches(X, Y), dependency(Y, Z).
```

- `dependency`: 직접 입력한 의존 관계
- `reaches`: 직접 연결 또는 여러 연결을 이어서 도달할 수 있는 쌍
- 첫 규칙: 직접 연결도 도달 관계다.
- 둘째 규칙: X에서 Y에 도달하고 Y에서 Z로 직접 연결되면 X에서 Z에 도달한다.

예를 들어 `dependency(1, 2)`와 `dependency(2, 3)`을 넣으면 `reaches(1, 3)`을 도출한다.
순환이 있으면 엔진 결과에 자기 자신으로의 도달도 생길 수 있으며, 앱의 상위·하위 목록에서는 이를 제외한다.
모든 원본 관계는 같은 `dependency`로 투영되므로 `reaches`만으로 어떤 종류의 관계를 거쳤는지는 알 수 없다.

### 도달 결과의 해석

도달 결과는 **정적으로 추출한 관계들을 통한 구성상 연결 가능성**이다.
코드 import, 실행 제어, 데이터 참조가 섞여 있으므로 이를 일괄적으로 실제 데이터 계보나 장애 전파 경로로 단정하지 않는다.
현재 플랫폼별 추론 규칙이나 관계 종류별 허용 경로 규칙을 별도로 실행하지는 않는다.

Wirelog가 도달 여부를 계산하면 Python이 원본 edge를 따라 최단 경로 하나와 단계별 근거를 재구성한다.
이는 Wirelog의 내장 증명 트리나 모든 가능한 경로의 목록이 아니다.
시작·수동 갱신 때 전체 스냅샷과 새 Wirelog 세션을 만든다. 엔진의 증분 기능을 사용하는 영구 세션 동기화는 아직 없다.

## 7. 현재 소스에 적용한 예

Linkmerce 1.0.22의 검토 기준은 [소스 업데이트 기록](../docs/linkmerce-source.json)에 있다.
ESM PLUS 주문의 대표 연결은 다음과 같다.

```text
Core order.extract / order.transform
    └─ imported_by → API esmplus.order
                        └─ imported_by → ebay_order Dag
                                            └─ runs_selector → postgres / ebay_order_summary
                                                                  └─ selects_model → ebay__sales_summary

postgres의 ebay.order 테이블
    └─ declared_source → dbt source ebay.order
                             └─ dbt_source → ebay__sales_summary
                                                  └─ dbt_ref → analytics__sales_summary
```

이 그림은 연결의 일부다. Dag에서 테이블로 향하는 `configured_load` 등은 별도로 존재한다.
Postgres 전용 요약 모델이 있다는 이유로 BigQuery에도 같은 모델이 있다고 만들지 않는다.
Dag에 주석 처리된 dbt 작업도 활성 `runs_selector` 사실로 만들지 않는다.
쿠키 재사용·유효성 검사는 문서와 코드에서 설명할 수 있는 흐름이며, 실제 쿠키 유효성을 Atlas가 판정하는 것은 아니다.

## 8. 답변의 경계와 출처 리비전

관계가 발견되지 않았다고 곧바로 존재하지 않는다고 답하지 않는다.
정적 추출의 지원 범위 밖일 수 있기 때문이다. 이것은 답변 정책이며, OWL의 열린 세계 추론기를 사용한다는 뜻은 아니다.
운영 성공·현재 DB 상태·장애 발생 여부는 별도의 관측 자료가 필요하다.

색인 메타데이터는 패키지 버전, 실제 Git 커밋, 미커밋 변경 여부, 파일 해시 기반 fingerprint와 추출기·규칙 해시를 기록한다.
마지막 검토 커밋과 현재 색인한 Git HEAD는 다를 수 있다. 버전 번호가 같다는 이유만으로 같은 소스라고 판단하지 않는다.
자세한 갱신 절차는 [소스 업데이트 기준](../docs/linkmerce-source.md)을 따른다.

LLM은 검색된 관계와 원문을 설명하며 새로운 사실이나 규칙을 자동으로 추가하지 않는다.
존재하는 근거 ID를 인용했는지 검사하지만, 모든 설명 문장의 의미가 논리적으로 증명되는 것은 아니다.

## 9. 모델을 바꿀 때

1. 답할 질문과 필요한 개념·관계의 의미, 방향, 범위를 이 문서에 먼저 명시한다.
2. [Indexer](../app/indexer.py)의 추출과 [Graph](../app/graph.py)의 탐색에 반영한다.
3. 새로운 도출 의미가 필요하면 [Datalog 규칙](linkmerce.dl)을 수정한다. 종류를 추가했다는 이유만으로 규칙을 반드시 바꿀 필요는 없다.
4. [관계 테스트](../tests/test_architecture.py)와 [소스 업데이트 회귀 테스트](../tests/test_source_sync.py)에 올바른 연결과 오연결 방지를 검증한다.
5. 실제 Wirelog로 검증하고, 원본 변경에 대응한 경우 마지막 검토 커밋도 함께 갱신한다.

현재 구현의 개념·관계가 이 명세와 달라진다면 둘을 함께 수정해야 한다.
