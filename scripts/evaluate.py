"""명시적으로 승인된 단일 API 계정의 실제 답변 검증. API 사용료가 발생한다."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from app import auth, ai
from app.indexer import Indexer
from app.graph import Graph


async def evaluate(output):
    with sqlite3.connect(auth.DB_PATH) as db:
        rows = db.execute('SELECT payload FROM sessions WHERE expires > ?', (time.time(),)).fetchall()
    accounts = [json.loads(auth.fernet.decrypt(row[0])) for row in rows]
    accounts = [account for account in accounts if account.get('provider') == 'openai']
    if len(accounts) != 1:
        raise RuntimeError('Expected exactly one active API account; refusing to choose a user arbitrarily')
    key = accounts[0]['key']
    model = 'gpt-6-luna'
    available = await ai.models(key, 'openai')
    if model not in {m['id'] for m in available}:
        raise RuntimeError('Approved model is not listed for this account')
    graph = Graph(Indexer(Path(os.getenv('LINKMERCE_ROOT', '/source/linkmerce'))).build())
    questions = [
        'smartstore_order Dag이 사용하는 BigQuery와 Postgres의 dbt selector를 각각 설명해줘. 실행 조건을 단정하지 마.',
        'linkmerce.api.smartstore.api.order는 어떤 Core 추출 및 변환 모듈을 import하는지 알려줘.',
        'smartstore_order가 어제 운영 환경에서 성공했는지 확인할 수 있어?',
    ]
    results = []
    for question in questions:
        context = graph.context(question)
        # 3회 * 최대 15만 입력 바이트 + 4096 출력 토큰으로 승인한 테스트 범위를 제한한다.
        # 2026-10-28 공시 단가: 입력 $0.10/MTok, 출력 $0.50/MTok.
        # 토큰 수 <= UTF-8 바이트 수라는 보수적 상한으로도 총 $0.10 미만이다.
        if len(json.dumps(context, ensure_ascii=False).encode()) + len(ai.INSTRUCTIONS.encode()) > 150000:
            raise RuntimeError('Approved test payload limit exceeded')
        start = time.monotonic()
        answer = await ai.answer(context, key, model, max_output_tokens=4096, reasoning_effort='low')
        citations = set(re.findall(r'\[(E[0-9a-f]{12})\]', answer))
        known = {e['id'] for e in context['evidence']}
        result = {'question': question, 'answer': answer, 'seconds': round(time.monotonic() - start, 2),
                  'citations': sorted(citations), 'unknown_citations': sorted(citations - known),
                  'provided_evidence': len(known), 'completed': True}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    report = {'tested_at': datetime.now(timezone.utc).isoformat(), 'model': model,
              'snapshot': graph.data['meta']['fingerprint'], 'results': results}
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if any(result['unknown_citations'] or not result['citations'] for result in results):
        raise RuntimeError('Citation validation failed; inspect the report')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='/data/evaluation.json')
    parser.add_argument('--confirm-api-usage', action='store_true', required=True)
    args = parser.parse_args()
    asyncio.run(evaluate(args.output))
