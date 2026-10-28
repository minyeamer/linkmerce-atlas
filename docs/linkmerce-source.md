# Linkmerce 소스 업데이트 기준

마지막으로 검토한 원본은 [linkmerce-source.json](linkmerce-source.json)에 기록한다.
패키지 버전이 같아도 이후 커밋이 있을 수 있으므로 **`reviewed_commit`부터 현재 HEAD까지의 전체 차이**를 검토한다.
이 파일은 Atlas의 검토 기준이며, 실행 중인 소스의 리비전을 고정하거나 자동으로 동기화하지 않는다.

## 마지막 검토 범위

- 패키지 버전: `1.0.22`
- 마지막 검토 커밋: `0dc7b0d41b70b3d73fd10598224f6d9869dc0b2e`
- 검토일: 2026-10-28
- `cc40ff14c06059a0b7f40d88d9b4f19e1650dc23`의 ESM PLUS 주문 ETL 추가와 이후 `0dc7b0d`의 쿠키 재사용 변경까지 포함한다.
- 이전 검토 커밋은 기록되어 있지 않다. 이번 기록을 다음 업데이트의 기준점으로 사용한다.

## 1.0.22에서 확인한 맥락

- ESM PLUS 주문 Core의 Extractor·Transformer와 공개 API `linkmerce.api.ebay.esmplus.order`가 추가됐다.
- `ebay_order` Dag은 API와 `dual_load.merge_table_from_duckdb`를 사용한다. 구성상 주문 및 주문 상품 적재 연결이며 성공 이력은 아니다.
- 활성 dbt 작업 선언은 **Postgres의 `ebay_order_summary` selector**이며 `ebay__sales_summary`를 선택한다.
- 이 모델은 `source('ebay', 'order')`를 참조하고, 후속 `analytics__sales_summary` 모델이 이 모델을 참조한다.
- Dag의 BigQuery/Postgres `ebay_order` 작업은 주석 처리되어 있다. 이 주석을 활성 작업으로 연결하거나 BigQuery에도 같은 매출 요약 모델이 있다고 추정하지 않는다.
- 후속 커밋은 `login_ebay_bulk`에서 기존 쿠키의 유효성을 먼저 확인하고, 필요할 때 로그인하는 흐름을 추가했다. 실제 인증정보나 쿠키 파일은 Atlas에서 읽거나 검증하지 않는다.
- 인증 검증 함수의 일부는 `import_module`과 문자열 보간으로 선택된다. Atlas의 정적 import 분석은 그 런타임 호출 관계를 완전히 복원하지 않는다. Dag 문서와 플러그인 코드 근거로 확인 가능한 범위만 설명한다.

기존 정적 추출기로 새 Core→API→Dag→selector→모델 관계를 추출할 수 있었다. ESM PLUS/이베이의 자연어 검색을 보완하고, 주석 처리된 작업과 Postgres 전용 selector를 구분하는 회귀 테스트를 추가했다.
새로운 Datalog 규칙은 필요하지 않아 도달 관계 규칙은 유지했다.

## 다음 업데이트 절차

Atlas 루트에서 원본 경로에 맞춰 실행한다. 경로가 다르면 `../linkmerce`를 변경한다.

```bash
BASE=$(python3 -c 'import json; print(json.load(open("docs/linkmerce-source.json"))["reviewed_commit"])')
git -C ../linkmerce status --short
git -C ../linkmerce merge-base --is-ancestor "$BASE" HEAD
git -C ../linkmerce log --oneline "$BASE"..HEAD
git -C ../linkmerce diff --stat "$BASE" HEAD
git -C ../linkmerce diff "$BASE" HEAD -- src/linkmerce airflow dbt_bigquery dbt_postgres README.md pyproject.toml
git -C ../linkmerce diff HEAD -- src/linkmerce airflow dbt_bigquery dbt_postgres README.md pyproject.toml
```

기준 커밋이 원본 이력의 조상이 아니거나 찾을 수 없다면 이력 변경·다른 체크아웃 여부부터 확인한다.
버전 태그 간 차이만으로 검토를 대체하지 않는다. 마지막 `diff HEAD`로 추적 중인 파일의 미커밋 변경을 별도로 확인하고, 새 파일은 `status`에서 확인한다. 이를 기준 커밋의 내용과 구분한다.

관계 추출·검색·설명 근거에 필요한 변경을 반영하고 실제 Wirelog 기반 테스트를 실행한다.
확인한 뒤에만 `reviewed_commit`, `package_version`, `reviewed_on`을 갱신하고, Atlas 변경과 함께 커밋한다.
원본 스냅샷, 인증정보, 실계정 AI 응답은 이 기록에 포함하지 않는다.

## 실행 중인 색인의 리비전

`/api/stats`와 UI 하단은 실제로 읽은 패키지 버전과 Git HEAD를 표시한다.
답변의 `source`에도 `package_version`, `commit`, `source_dirty`, `fingerprint`를 포함하며, AI 설명에 같은 정보를 전달한다.

- `source_dirty: false`: 색인 시 확인한 작업 트리에 변경이 없다.
- `source_dirty: true`: HEAD 이외의 로컬 변경도 있다. 커밋만으로 입력 전체를 재현할 수 없다.
- `source_dirty: null`: Git 상태를 확인하지 못했다. 소스 아카이브나 `.git`이 마운트되지 않은 경우에도 이를 깨끗한 작업 트리로 간주하지 않는다.

실행 이미지에는 Git을 포함한다. 표준 `.git` 디렉터리가 소스와 함께 마운트된 경우 HEAD와 작업 트리 상태를 조회하며, Git worktree 등 외부 메타데이터가 필요한 체크아웃에서는 해당 메타데이터에 접근할 수 없으면 미확인으로 남는다.
소스가 색인 도중 바뀌지 않는 상태에서 갱신해야 한다. 파일별 해시의 스냅샷 식별자도 함께 보관하지만, 이 기록이 원본 전체를 복제하는 것은 아니다.
