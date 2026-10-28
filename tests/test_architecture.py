import json
from pathlib import Path
import tempfile
import unittest

from app.engine import Wirelog
from app.graph import Graph
from app.indexer import Indexer


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        files = {
            'src/linkmerce/core/store/api/order/extract.py': 'class Order: pass\n',
            'src/linkmerce/api/store.py': 'def order():\n    from linkmerce.core.store.api.order.extract import Order\n    return Order()\n',
            'airflow/plugins/dual_load.py': 'def load_table_from_duckdb(**kwargs): pass\n',
            'airflow/dags/order.py': '''from airflow import DAG
with DAG(dag_id='store_order', schedule='@daily'):
    PATH = 'store.api.order'
    def configs():
        return read_config(PATH, tables=True)
    def main(tables):
        from linkmerce.api.store import order
        from dual_load import load_table_from_duckdb
        order()
        load_table_from_duckdb(target_table=tables['order'])
    def dbt():
        return dynamic_mapping_dbt_postgres(selector='sales')
''',
            'src/env/config.yaml': '''store:
  api:
    order:
      credentials: never_export_this
      customer_id: sensitive_identifier
      tables:
        order: store.order
''',
            'src/env/credentials.yaml': 'SECRET_SHOULD_NEVER_BE_READ',
            'dbt_postgres/models/sources.yml': "sources:\n  - name: store\n    schema: store\n    tables:\n      - name: order\n",
            'dbt_postgres/models/staging/order_base.sql': "select * from {{ source('store', 'order') }}\n",
            'dbt_postgres/models/marts/sales.sql': "-- {{ ref('comment_only') }}\nselect * from {{ ref('order_base') }}\n",
            'dbt_postgres/models/marts/unrelated.sql': 'select 1\n',
            'dbt_postgres/selectors.yml': '''selectors:
  - name: sales
    definition:
      union:
        - method: fqn
          value: marts.sales
          parents: true
''',
            'dbt_bigquery/models/marts/sales.sql': 'select 1\n',
            'dbt_postgres/macros/combined.sql': "{% macro first() %}{{ ref('order_base') }}{% endmacro %}\n{% macro second() %}select 1{% endmacro %}\n",
            'README.md': 'Store architecture fixture\n',
        }
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def tearDown(self):
        self.temp.cleanup()

    def test_native_recursive_closure_and_cycles(self):
        pairs = Wirelog({(1, 2), (2, 3), (3, 2), (4, 5)}).pairs
        self.assertIn((1, 3), pairs)
        self.assertIn((2, 2), pairs)
        self.assertNotIn((1, 5), pairs)

    def test_real_engine_connects_core_api_dag_table_dbt(self):
        graph = Graph(Indexer(self.root).build())
        source = 'py:linkmerce.core.store.api.order.extract'
        target = 'model:postgres:sales'
        path = graph.path(source, target)
        self.assertTrue(path)
        self.assertEqual(path[0]['source'], source)
        self.assertEqual(path[-1]['target'], target)
        self.assertTrue(all(e['evidence'] in graph.data['evidence'] for e in path))
        self.assertNotIn('model:bigquery:sales', graph.down['dag:store_order'])
        self.assertNotIn('model:postgres:unrelated', graph.down['dag:store_order'])
        self.assertTrue(any(e['relation'] == 'configured_load' for e in graph.edges))
        selector_models = {e['target'] for e in graph.edges if e['source'] == 'selector:postgres:sales'}
        self.assertEqual(selector_models, {'model:postgres:sales', 'model:postgres:order_base'})

    def test_credentials_and_non_table_config_are_not_exported(self):
        indexer = Indexer(self.root)
        snapshot = indexer.build()
        serialized = json.dumps(snapshot)
        for secret in ('never_export_this', 'sensitive_identifier', 'SECRET_SHOULD_NEVER_BE_READ'):
            self.assertNotIn(secret, serialized)
        self.assertNotIn('src/env/credentials.yaml', indexer.files)

    def test_comments_and_other_macro_bodies_are_not_dependencies(self):
        snapshot = Indexer(self.root).build()
        self.assertFalse(any('comment_only' in w['reason'] for w in snapshot['warnings']))
        self.assertFalse(any(e['source'] == 'model:postgres:order_base' and e['target'] == 'macro:postgres:second' for e in snapshot['edges']))
        self.assertTrue(any(e['source'] == 'model:postgres:order_base' and e['target'] == 'macro:postgres:first' for e in snapshot['edges']))

    def test_explicit_dag_query_excludes_unrelated_generic_layer_matches(self):
        graph = Graph(Indexer(self.root).build())
        context = graph.context('store_order Dag은 어떤 dbt 모델과 연결돼?')
        self.assertTrue(any(e['relation'] == 'selects_model' for e in context['relations']))
        self.assertFalse(any(n['id'] == 'model:bigquery:sales' for n in context['entities']))
        for edge in context['relations']:
            if edge['relation'] == 'configured_load':
                self.assertTrue(edge['support'])
                self.assertTrue(all(eid in {e['id'] for e in context['evidence']} for eid in edge['support']))
        self.assertIn('dbt_postgres', graph.evidence_answer(context))

    def test_documentation_and_plugin_implementation_have_evidence(self):
        dag_path = self.root / 'airflow/dags/order.py'
        dag_path.write_text('"""Store order runs conditionally."""\n' + dag_path.read_text())
        snapshot = Indexer(self.root).build()
        dag_evidence = [snapshot['evidence'][eid]['snippet'] for eid in snapshot['nodes']['dag:store_order']['evidence']]
        self.assertIn('Store order runs conditionally.', dag_evidence)
        plugin_evidence = [snapshot['evidence'][eid]['snippet'] for eid in snapshot['nodes']['plugin:dual_load']['evidence']]
        self.assertTrue(any('def load_table_from_duckdb' in text for text in plugin_evidence))
        self.assertIn('extractor_version', snapshot['meta'])
        self.assertIn('ontology_version', snapshot['meta'])

    def test_symlink_cannot_read_outside_repository(self):
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / 'secret.py'
            secret.write_text('LEAK = 123')
            link = self.root / 'src/linkmerce/outside.py'
            link.symlink_to(secret)
            indexer = Indexer(self.root)
            with self.assertRaises(ValueError):
                indexer.read('src/linkmerce/outside.py')
            self.assertNotIn('src/linkmerce/outside.py', indexer.paths('src/linkmerce/**/*.py'))


if __name__ == '__main__':
    unittest.main()
