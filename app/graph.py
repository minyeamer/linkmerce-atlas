"""Wirelog 도달 결과와 원본 edge의 출처를 함께 조회한다."""
from collections import defaultdict, deque
import re

from .engine import Wirelog

ALIASES = {"스마트스토어": "smartstore", "쿠팡": "coupang", "사방넷": "sabangnet",
           "광고": "ads", "주문": "order", "매출": "sales", "상품": "product", "재고": "stock",
           "포스트그레스": "postgres", "빅쿼리": "bigquery", "에어플로우": "airflow"}


class Graph:
    def __init__(self, snapshot):
        self.data = snapshot
        self.nodes = snapshot["nodes"]
        self.edges = snapshot["edges"]
        self.ids = {key: i + 1 for i, key in enumerate(sorted(self.nodes))}
        self.keys = {value: key for key, value in self.ids.items()}
        self.engine = Wirelog({(self.ids[e["source"]], self.ids[e["target"]]) for e in self.edges if e["dependency"]})
        self.down = defaultdict(set)
        self.up = defaultdict(set)
        for a, b in self.engine.pairs:
            if a != b:
                self.down[self.keys[a]].add(self.keys[b])
                self.up[self.keys[b]].add(self.keys[a])
        self.outgoing = defaultdict(list)
        self.incoming = defaultdict(list)
        for e in self.edges:
            self.outgoing[e["source"]].append(e)
            self.incoming[e["target"]].append(e)

    def search(self, query, limit=30, kind=None):
        query = query.lower().strip()
        for ko, en in ALIASES.items():
            query = query.replace(ko, " " + en + " ")
        tokens = re.findall(r"[a-z][a-z0-9_.]+", query)
        scored = []
        for n in self.nodes.values():
            if kind and n["kind"] != kind:
                continue
            label = n["label"].lower()
            haystack = label + " " + n["layer"]
            score = 0
            for token in tokens:
                if token == label:
                    score += 100
                elif token in haystack:
                    score += 20 + len(token)
            if not query:
                score = 1
            if score:
                scored.append((score, n))
        return [n for _, n in sorted(scored, key=lambda x: (-x[0], x[1]["id"]))[:limit]]

    def path(self, source, target):
        if target not in self.down[source]:
            return []
        queue = deque([(source, [])])
        seen = {source}
        while queue:
            current, edges = queue.popleft()
            for edge in self.outgoing[current]:
                if not edge["dependency"]:
                    continue
                nxt = edge["target"]
                if nxt == target:
                    return edges + [edge]
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, edges + [edge]))
        return []

    def neighborhood(self, key, limit=65):
        node = self.nodes[key]
        direct = self.outgoing[key] + self.incoming[key]
        chosen = {key}
        selected = []
        for edge in direct[:limit]:
            selected.append(edge)
            chosen.update([edge["source"], edge["target"]])
        return {"node": node, "nodes": [self.nodes[k] for k in sorted(chosen)], "edges": selected,
                "upstream_count": len(self.up[key]), "downstream_count": len(self.down[key]),
                "upstream": [self.nodes[k] for k in sorted(self.up[key])[:100]],
                "downstream": [self.nodes[k] for k in sorted(self.down[key])[:100]],
                "total_direct_edges": len(direct)}

    def context(self, question, focus=None):
        seeds = self.search(question, 8)
        if focus in self.nodes:
            seeds = [self.nodes[focus]] + [n for n in seeds if n["id"] != focus]
        selected, seen = [], set()
        def include(edge):
            key = (edge["source"], edge["target"], edge["relation"], edge["evidence"])
            if key not in seen and len(selected) < 100:
                seen.add(key)
                selected.append(edge)
        for node in seeds:
            for edge in self.outgoing[node["id"]] + self.incoming[node["id"]]:
                include(edge)
        # Wirelog가 확인한 도달 관계에 한해서 원본 edge 경로를 재구성한다.
        for left in seeds[:4]:
            for right in seeds[:8]:
                if left != right:
                    for edge in self.path(left["id"], right["id"]):
                        include(edge)
        for node in seeds[:3]:
            for related in sorted(self.down[node["id"]], key=lambda k: (self.nodes[k]["kind"] != "model", k))[:5]:
                for edge in self.path(node["id"], related):
                    include(edge)
        ev_ids = list(dict.fromkeys([e["evidence"] for e in selected] + [e for n in seeds for e in n["evidence"]]))
        if len(seeds) < 2 or any(word in question for word in ["전체", "구조", "처음", "역할", "architecture"]):
            ev_ids += self.data["overview"]
        evidence, budget = [], 32000
        for eid in dict.fromkeys(ev_ids):
            e = self.data["evidence"][eid]
            size = len(e["snippet"])
            if size <= budget:
                evidence.append(e)
                budget -= size
        allowed = {e["id"] for e in evidence}
        selected = [e for e in selected if e["evidence"] in allowed]
        keys = {k for e in selected for k in (e["source"], e["target"])} | {n["id"] for n in seeds}
        return {"question": question, "entities": seeds, "nodes": [self.nodes[k] for k in sorted(keys)],
                "relations": selected, "evidence": evidence,
                "scope": "코드의 정적 선언. 운영 실행 성공/실제 데이터/동적 조건 충족 여부는 알 수 없음.",
                "retrieval": "이름·별칭 검색과 Wirelog 도달 관계. 전체 관계의 완전한 검색을 보장하지 않음."}

    def evidence_answer(self, context):
        if not context["entities"]:
            return "일치하는 구성요소를 찾지 못했습니다. Dag ID, 모델명 또는 코드 경로를 지정해 주세요. 전체 구조는 README 근거에서 확인할 수 있습니다."
        lines = ["질문과 연결되는 정적 선언을 찾았습니다. 아래 화살표는 선행 요소에서 후행 요소를 가리킵니다."]
        for edge in context["relations"][:16]:
            a, b = self.nodes[edge["source"]], self.nodes[edge["target"]]
            condition = " · 조건부 실행" if edge["certainty"] == "conditional" else ""
            lines.append(f"• {a['label']} → {b['label']} ({edge['relation']}{condition}) [{edge['evidence']}]")
        lines.append("운영 실행 여부와 동적 설정은 이 결과로 확정할 수 없습니다. AI를 연결하면 이 근거를 문장으로 설명합니다.")
        return "\n\n".join(lines)
