"""릴리스 관계와 버전 대신 커밋 기준의 소스 추적을 검증한다."""
import json
import subprocess
import unittest
from unittest.mock import patch

from app.graph import Graph
from app.indexer import Indexer
from tests import test_architecture


class SourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_architecture.ArchitectureTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        files = {
            'pyproject.toml': '[project]\nname = "linkmerce"\nversion = "1.0.22"\n\n[tool.private]\npassword = "metadata-must-not-export"\n',
            'src/linkmerce/core/ebay/esmplus/order/extract.py': 'class Order: pass\n',
            'src/linkmerce/api/ebay/esmplus.py': '''def order():
    from linkmerce.core.ebay.esmplus.order.extract import Order
    return Order()
''',
            'airflow/dags/ebay/order.py': '''"""ESM PLUS 주문. 유효한 쿠키는 재사용하고 없는 경우 로그인을 시도한다."""
from airflow.sdk import DAG
with DAG(dag_id="ebay_order"):
    PATH = "ebay.esmplus.order"
    def config():
        return read_config(PATH, tables=True)
    def main(tables):
        from linkmerce.api.ebay.esmplus import order
        from dual_load import merge_table_from_duckdb
        order()
        merge_table_from_duckdb(target_table=tables['order'])
    # dynamic_mapping_dbt_bigquery(selector="ebay_order")
    # dynamic_mapping_dbt_postgres(selector="ebay_order")
    def summary():
        return dynamic_mapping_dbt_postgres(selector="ebay_order_summary")
''',
            'dbt_postgres/models/intermediate/sales/ebay/ebay__sales_summary.sql': "select * from {{ source('ebay', 'order') }}\n",
            'dbt_postgres/models/marts/analytics__sales_summary.sql': "select * from {{ ref('ebay__sales_summary') }}\n",
        }
        # 같은 플랫폼·업무 이름의 모듈이 많아도 명시한 Dag이 검색에서 밀리지 않아야 한다.
        for index in range(12):
            files[f'src/linkmerce/core/ebay/esmplus/order/helper{index}.py'] = 'VALUE = 1\n'
        for relative, text in files.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        with (self.root / 'src/env/config.yaml').open('a') as f:
            f.write('\nebay:\n  esmplus:\n    order:\n      tables:\n        order: ebay.order\n')
        with (self.root / 'dbt_postgres/models/sources.yml').open('a') as f:
            f.write('  - name: ebay\n    schema: ebay\n    tables:\n      - name: order\n')
        with (self.root / 'dbt_postgres/selectors.yml').open('a') as f:
            f.write('  - name: ebay_order_summary\n    definition:\n      method: fqn\n      value: intermediate.sales.ebay.ebay__sales_summary\n')

    def tearDown(self):
        self.fixture.tearDown()

    def test_release_path_and_korean_aliases_preserve_postgres_only_selector(self):
        graph = Graph(Indexer(self.root).build())
        core = 'py:linkmerce.core.ebay.esmplus.order.extract'
        summary = 'model:postgres:ebay__sales_summary'
        self.assertTrue(graph.path(core, summary))
        self.assertIn('model:postgres:analytics__sales_summary', graph.down[core])
        self.assertEqual({e['target'] for e in graph.outgoing['dag:ebay_order'] if e['relation'] == 'runs_selector'},
                         {'selector:postgres:ebay_order_summary'})
        self.assertTrue(any(e['relation'] == 'configured_load' for e in graph.outgoing['dag:ebay_order']))
        for question in ('ESM PLUS 주문 Dag은 어떤 dbt 모델과 연결돼?', '이베이 주문 dbt 모델', 'ESM플러스 주문 dbt 모델'):
            context = graph.context(question)
            self.assertIn('dag:ebay_order', {n['id'] for n in context['nodes']})
            if 'Dag' in question:
                self.assertEqual(context['entities'][0]['id'], 'dag:ebay_order')
            self.assertTrue(any(e['source'] == 'selector:postgres:ebay_order_summary' and e['target'] == summary
                                for e in context['relations']))
            self.assertEqual(context['source']['package_version'], '1.0.22')
            self.assertIn(graph.data['meta']['version_evidence'], {e['id'] for e in context['evidence']})

    def test_same_version_new_commit_and_uncommitted_changes_are_distinguished(self):
        def git(*args):
            return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout.strip()
        git('init', '-q')
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Initial fixture')
        first = Indexer(self.root).build()['meta']
        self.assertEqual(first['commit'], git('rev-parse', 'HEAD'))
        self.assertFalse(first['source_dirty'])
        path = self.root / 'src/linkmerce/api/ebay/esmplus.py'
        path.write_text(path.read_text() + '\n# Same-version source change\n')
        changed = Indexer(self.root).build()['meta']
        self.assertTrue(changed['source_dirty'])
        self.assertEqual(changed['commit'], first['commit'])
        self.assertNotEqual(changed['fingerprint'], first['fingerprint'])
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Same-version update')
        second = Indexer(self.root).build()['meta']
        self.assertFalse(second['source_dirty'])
        self.assertNotEqual(first['commit'], second['commit'])
        self.assertEqual(first['package_version'], second['package_version'])

    def test_metadata_does_not_publish_unrelated_toml_settings(self):
        snapshot = Indexer(self.root).build()
        self.assertEqual(snapshot['meta']['package_version'], '1.0.22')
        self.assertNotIn('metadata-must-not-export', json.dumps(snapshot))

    def test_unavailable_git_and_missing_package_metadata_remain_unknown(self):
        (self.root / 'pyproject.toml').unlink()
        with patch('app.indexer.shutil.which', return_value=None):
            meta = Indexer(self.root).build()['meta']
        self.assertEqual(meta['commit'], '')
        self.assertIsNone(meta['source_dirty'])
        self.assertIsNone(meta['package_version'])
