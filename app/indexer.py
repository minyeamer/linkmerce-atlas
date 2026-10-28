"""코드를 실행하지 않고 Linkmerce의 선언 관계와 근거를 추출한다."""
import ast
from collections import defaultdict
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import re
from pathlib import Path
import subprocess
import shutil
import tomllib

import yaml


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def name_of(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return name_of(node.value) + "." + node.attr
    return ""


def active_sql(text):
    """주석을 공백으로 바꿔 원래 행 번호를 유지한다."""
    return re.sub(r"\{#.*?#\}|/\*.*?\*/|--[^\n]*", lambda m: re.sub(r"[^\n]", " ", m[0]), text, flags=re.S)


class Indexer:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.nodes = {}
        self.edges = []
        self.evidence = {}
        self.files = {}
        self.warnings = []
        self._edge_keys = set()
        self.trees = {}
        self.modules = {}
        self.symbols = {}
        self.model_paths = {}
        self.configs = {}

    def read(self, relative):
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise ValueError("Source path escapes repository")
        text = path.read_text(encoding="utf-8")
        self.files[relative] = hashlib.sha256(text.encode()).hexdigest()
        return text

    def ev(self, relative, line, end=None, snippet=None):
        normalized = snippet is not None
        if snippet is None:
            text = self.read(relative)
            lines = text.splitlines()
            end = min(end or line + 5, line + 30, len(lines))
            snippet = "\n".join(lines[max(line - 1, 0):end])
        snippet = re.sub(r"(?:sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]+)", "[REDACTED]", snippet)
        key = "E" + hashlib.sha256(f"{relative}:{line}:{snippet}".encode()).hexdigest()[:12]
        self.evidence[key] = {"id": key, "path": relative, "line": line, "end": end or line, "snippet": snippet, "format": "normalized" if normalized else "excerpt"}
        return key

    def node(self, key, label, kind, layer, evidence=None, **extra):
        if key not in self.nodes:
            self.nodes[key] = {"id": key, "label": label, "kind": kind, "layer": layer, "evidence": [], **extra}
        if evidence and evidence not in self.nodes[key]["evidence"]:
            self.nodes[key]["evidence"].append(evidence)
        return key

    def edge(self, source, target, relation, evidence, dependency=True, certainty="declared", support=None):
        if source == target or source not in self.nodes or target not in self.nodes:
            return
        key = (source, target, relation, evidence)
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            self.edges.append({"source": source, "target": target, "relation": relation,
                               "evidence": evidence, "dependency": dependency, "certainty": certainty, "support": support or []})

    def paths(self, pattern):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.glob(pattern)
                      if not any(x in p.parts for x in ("_private", "_deprecated", "__pycache__")) and not p.is_symlink())

    def python_nodes(self):
        paths = self.paths("src/linkmerce/**/*.py") + self.paths("airflow/plugins/*.py") + self.paths("airflow/dags/**/*.py")
        for path in paths:
            try:
                tree = ast.parse(self.read(path))
            except (SyntaxError, UnicodeError) as exc:
                self.warnings.append({"path": path, "reason": type(exc).__name__})
                continue
            self.trees[path] = tree
            if path.startswith("src/"):
                module = path[4:-3].replace("/", ".").removesuffix(".__init__")
                layer = "core" if "/core/" in path else "api" if "/api/" in path else "extensions" if "/extensions/" in path else "common"
                key = self.node("py:" + module, module, "module", layer, self.ev(path, 1))
                self.modules[module] = key
                if layer == "api":
                    for item in tree.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_"):
                            symbol = module + "." + item.name
                            eid = self.ev(path, item.lineno, min(item.end_lineno, item.lineno + 7))
                            self.symbols[symbol] = self.node("fn:" + symbol, symbol, "function", layer, eid,
                                                            description=(ast.get_docstring(item) or "").split("\n\n")[0][:600])
            elif "/plugins/" in path:
                module = Path(path).stem
                key = self.node("plugin:" + module, module, "plugin", "airflow", self.ev(path, 1))
                self.modules[module] = key
            else:
                dags = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and name_of(n.func).split(".")[-1] == "DAG"]
                if not dags:
                    continue
                call = dags[0]
                kwargs = {kw.arg: kw.value for kw in call.keywords}
                dag_id = literal(kwargs.get("dag_id"))
                if not isinstance(dag_id, str):
                    self.warnings.append({"path": path, "reason": "Dynamic dag_id is not resolved"})
                    continue
                schedule = kwargs.get("schedule")
                key = self.node("dag:" + dag_id, dag_id, "dag", "airflow", self.ev(path, call.lineno, call.end_lineno),
                                description=(ast.get_docstring(tree) or "")[:2600],
                                schedule=ast.get_source_segment(self.read(path), schedule) if schedule else None)
                self.modules[path] = key
            # 설명에 쓰는 문서 문자열도 독립적인 출처로 인용할 수 있게 한다.
            description = ast.get_docstring(tree)
            if description and key in self.nodes:
                self.node(key, "", "", "", self.ev(path, tree.body[0].lineno,
                          snippet=description[:4000]))
            if "/plugins/" in path:
                public = [item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and not item.name.startswith("_")]
                for item in public[:6]:
                    self.node(key, "", "", "", self.ev(path, item.lineno, min(item.end_lineno, item.lineno + 30)))

    def config_tables(self):
        path = "src/env/config.yaml"
        if not (self.root / path).is_file():
            self.warnings.append({"path": path, "reason": "Optional config not found; table links unavailable"})
            return
        # 행 번호가 있는 YAML 트리에서 tables 값만 근거로 저장한다.
        tree = yaml.compose(self.read(path))
        def walk(node, names):
            if not isinstance(node, yaml.MappingNode):
                return
            for key, value in node.value:
                if key.value == "tables" and isinstance(value, yaml.MappingNode):
                    values = {}
                    for table_key, table_value in value.value:
                        if isinstance(table_value, yaml.ScalarNode) and re.fullmatch(r"[A-Za-z_][\w]*\.[A-Za-z_][\w]*", table_value.value):
                            ev = self.ev(path, table_value.start_mark.line + 1, snippet=f"{'.'.join(names)}.tables.{table_key.value}: {table_value.value}")
                            values[table_key.value] = (table_value.value, ev)
                    self.configs[".".join(names)] = values
                elif isinstance(value, yaml.MappingNode):
                    walk(value, names + [key.value])
        walk(tree, [])

    def resolve_import(self, imported):
        if imported in self.symbols:
            return self.symbols[imported]
        while imported:
            if imported in self.modules:
                return self.modules[imported]
            imported = imported.rpartition(".")[0]
        return None

    def python_edges(self):
        for path, tree in self.trees.items():
            module_name = path[4:-3].replace("/", ".").removesuffix(".__init__") if path.startswith("src/") else Path(path).stem
            owner = self.modules.get(module_name) or self.modules.get(path)
            if not owner:
                continue
            scope_owners = {}
            for item in ast.walk(tree):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope = self.symbols.get(module_name + "." + item.name, owner)
                    for child in ast.walk(item):
                        scope_owners.setdefault(id(child), scope)
            for item in ast.walk(tree):
                consumer = scope_owners.get(id(item), owner)
                if isinstance(item, ast.ImportFrom) and item.module:
                    for alias in item.names:
                        provider = self.resolve_import(item.module + "." + alias.name)
                        if provider:
                            self.edge(provider, consumer, "imported_by", self.ev(path, item.lineno, item.end_lineno))
                elif isinstance(item, ast.Import):
                    for alias in item.names:
                        provider = self.resolve_import(alias.name)
                        if provider:
                            self.edge(provider, consumer, "imported_by", self.ev(path, item.lineno, item.end_lineno))
            if not owner.startswith("dag:"):
                continue
            constants = {}
            for item in ast.walk(tree):
                if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                    value = literal(item.value)
                    if isinstance(value, str):
                        constants[item.targets[0].id] = value
            config_keys = set()
            load_calls = []
            dual_load_bindings = {alias.asname or alias.name for item in ast.walk(tree)
                                  if isinstance(item, ast.ImportFrom) and item.module == "dual_load"
                                  for alias in item.names}
            for item in ast.walk(tree):
                if not isinstance(item, ast.Call):
                    continue
                func = name_of(item.func).split(".")[-1]
                kwargs = {kw.arg: kw.value for kw in item.keywords}
                if func == "read_config" and item.args:
                    key = literal(item.args[0]) or constants.get(name_of(item.args[0]))
                    if isinstance(key, str) and literal(kwargs.get("tables")) is True:
                        config_keys.add(key)
                if isinstance(item.func, ast.Name) and item.func.id in dual_load_bindings and func in {"load_table_from_duckdb", "overwrite_table_from_duckdb", "merge_table_from_duckdb"}:
                    load_calls.append(item)
                if func in {"dynamic_mapping_dbt_bigquery", "dynamic_mapping_dbt_postgres"}:
                    selector = literal(kwargs.get("selector"))
                    platform = "bigquery" if "bigquery" in func else "postgres"
                    if isinstance(selector, str):
                        target = "selector:" + platform + ":" + selector
                        eid = self.ev(path, item.lineno, item.end_lineno)
                        self.node(target, f"{platform} / {selector}", "selector", "dbt_" + platform, eid)
                        self.edge(owner, target, "runs_selector", eid, certainty="conditional")
                    else:
                        self.warnings.append({"path": path, "line": item.lineno, "reason": "Dynamic dbt selector is not resolved"})
                if func in {"trigger_child_dag", "TriggerDagRunOperator"}:
                    value = literal(item.args[0]) if item.args else literal(kwargs.get("trigger_dag_id"))
                    if isinstance(value, str) and "dag:" + value in self.nodes:
                        self.edge(owner, "dag:" + value, "may_trigger", self.ev(path, item.lineno, item.end_lineno), certainty="conditional")
            for key in sorted(config_keys):
                for alias, (table, eid) in self.configs.get(key, {}).items():
                    for call in load_calls:
                        target = next((kw.value for kw in call.keywords if kw.arg == "target_table"), None)
                        if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == "tables" and literal(target.slice) == alias:
                            for platform in ("postgres", "bigquery"):
                                tid = self.node(f"table:{platform}:{table}", table, "table", platform, eid)
                                self.edge(owner, tid, "configured_load", self.ev(path, call.lineno, call.end_lineno), certainty="conditional", support=[eid])
                                self.nodes[tid]["evidence"] = list(dict.fromkeys(self.nodes[tid]["evidence"] + [eid]))
            if load_calls and not config_keys:
                self.warnings.append({"path": path, "reason": "Load calls found but static tables config could not be resolved"})

    def dbt_nodes(self):
        for platform in ("bigquery", "postgres"):
            folder = "dbt_" + platform
            for path in self.paths(folder + "/models/**/*.sql"):
                label = Path(path).stem
                key = self.node(f"model:{platform}:{label}", label, "model", folder, self.ev(path, 1), path=path)
                self.model_paths[(platform, label)] = (key, path)
            for path in self.paths(folder + "/macros/**/*.sql"):
                text = active_sql(self.read(path))
                for match in re.finditer(r"\{%[-+]?\s*macro\s+(\w+)\s*\(", text):
                    line = text.count("\n", 0, match.start()) + 1
                    end = re.search(r"\{%[-+]?\s*endmacro\b", text[match.end():])
                    end_line = text.count("\n", 0, match.end() + end.end()) + 1 if end else len(text.splitlines())
                    self.node(f"macro:{platform}:{match[1]}", match[1], "macro", folder, self.ev(path, line), path=path,
                              start_line=line, end_line=end_line)
            for path in self.paths(folder + "/models/**/*.yml") + self.paths(folder + "/models/**/*.yaml"):
                text = self.read(path)
                document = yaml.compose(text)
                if not isinstance(document, yaml.MappingNode):
                    continue
                mapping = dict((k.value, v) for k, v in document.value)
                sources = mapping.get("sources")
                if not isinstance(sources, yaml.SequenceNode):
                    continue
                for source_node in sources.value:
                    source = dict((k.value, v) for k, v in source_node.value)
                    source_name = source["name"].value
                    schema = source.get("schema", source["name"]).value
                    for table_node in source["tables"].value:
                        table = dict((k.value, v) for k, v in table_node.value)
                        table_name = table["name"].value
                        logical = source_name + "." + table_name
                        physical = schema + "." + table.get("identifier", table["name"]).value
                        eid = self.ev(path, table["name"].start_mark.line + 1,
                                      snippet=f"source {logical} -> {platform}:{physical} (normalized YAML declaration)")
                        self.node(f"source:{platform}:{logical}", logical, "source", folder, eid)
                        tid = self.node(f"table:{platform}:{physical}", physical, "table", platform, eid)
                        self.edge(tid, f"source:{platform}:{logical}", "declared_source", eid)

    def dbt_edges(self):
        for node in list(self.nodes.values()):
            if node["kind"] not in {"model", "macro"}:
                continue
            platform = node["layer"].removeprefix("dbt_")
            path = node["path"]
            text = active_sql(self.read(path))
            if node["kind"] == "macro":
                lines = text.splitlines(keepends=True)
                text = "\n" * (node["start_line"] - 1) + "".join(lines[node["start_line"] - 1:node["end_line"]])
            # 리터럴 ref/source와 알려진 macro 호출을 정적으로 해석한다.
            for match in re.finditer(r"\b(ref|source)\s*\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*['\"]([^'\"]+)['\"]\s*)?\)", text):
                if match[1] == "ref":
                    target = f"model:{platform}:{match[3] or match[2]}"
                else:
                    target = f"source:{platform}:{match[2]}.{match[3]}"
                line = text.count("\n", 0, match.start()) + 1
                if target in self.nodes:
                    self.edge(target, node["id"], "dbt_" + match[1], self.ev(path, line, line))
                else:
                    self.warnings.append({"path": path, "line": line, "reason": "Unresolved " + match[0]})
            for match in re.finditer(r"\b(\w+)\s*\(", text):
                target = f"macro:{platform}:{match[1]}"
                if target in self.nodes:
                    line = text.count("\n", 0, match.start()) + 1
                    self.edge(target, node["id"], "macro_used_by", self.ev(path, line, line))

    def selectors(self):
        for platform in ("bigquery", "postgres"):
            path = f"dbt_{platform}/selectors.yml"
            if not (self.root / path).is_file():
                continue
            text = self.read(path)
            specs = (yaml.safe_load(text) or {}).get("selectors", [])
            def expand(definition):
                if not isinstance(definition, dict):
                    raise ValueError("String selector definition is not supported")
                if "union" in definition or "intersection" in definition:
                    op = "union" if "union" in definition else "intersection"
                    included = [expand(d) for d in definition[op] if "exclude" not in d]
                    chosen = set.union(*included) if op == "union" and included else set.intersection(*included) if included else set()
                    for item in definition[op]:
                        for excluded in item.get("exclude", []):
                            chosen -= expand(excluded)
                    return chosen
                method, value = definition.get("method"), definition.get("value", "")
                if method not in {"fqn", "path"}:
                    raise ValueError(f"Unsupported selector method: {method}")
                chosen = set()
                for (p, label), (mid, model_path) in self.model_paths.items():
                    if p != platform:
                        continue
                    relative = model_path.split("/models/", 1)[1]
                    fqn = relative[:-4].replace("/", ".")
                    if (method == "path" and fnmatch.fnmatch("models/" + relative, value.rstrip("/") + "*")) or (method == "fqn" and (fnmatch.fnmatch(fqn, value) or fnmatch.fnmatch(label, value) or fqn.startswith(value + "."))):
                        chosen.add(mid)
                for flag, reverse in (("parents", True), ("children", False)):
                    if definition.get(flag):
                        pending = list(chosen)
                        adjacency = defaultdict(set)
                        for edge in self.edges:
                            if edge["relation"] == "dbt_ref":
                                adjacency[edge["target"] if reverse else edge["source"]].add(edge["source"] if reverse else edge["target"])
                        while pending:
                            for neighbor in adjacency[pending.pop()]:
                                if neighbor not in chosen:
                                    chosen.add(neighbor)
                                    pending.append(neighbor)
                return chosen
            for spec in specs:
                sid = f"selector:{platform}:{spec['name']}"
                # 해당 selector 선언 블록의 실제 행 번호를 보존한다.
                match = re.search(r"^\s*-\s*name:\s*['\"]?" + re.escape(spec["name"]) + r"['\"]?\s*$", text, re.M)
                line = text.count("\n", 0, match.start()) + 1 if match else 1
                eid = self.ev(path, line, snippet=yaml.safe_dump(spec, allow_unicode=True, sort_keys=False).strip())
                self.node(sid, f"{platform} / {spec['name']}", "selector", "dbt_" + platform, eid)
                try:
                    for mid in sorted(expand(spec["definition"])):
                        self.edge(sid, mid, "selects_model", eid)
                except ValueError as exc:
                    self.warnings.append({"path": path, "selector": spec["name"], "reason": str(exc)})

    def source_metadata(self):
        """패키지 버전과 실제 색인한 Git 리비전을 기록한다."""
        version, version_evidence = None, None
        path = "pyproject.toml"
        if (self.root / path).is_file():
            try:
                text = self.read(path)
                project = tomllib.loads(text).get("project", {})
                if project.get("name") == "linkmerce" and isinstance(project.get("version"), str):
                    version = project["version"]
                    section = re.search(r"^\[project\]\s*$", text, re.M)
                    line = text.count("\n", 0, section.start()) + 1 if section else 1
                    version_evidence = self.ev(path, line, snippet="[project]\nname = \"linkmerce\"\nversion = " + json.dumps(version))
            except (tomllib.TOMLDecodeError, UnicodeError):
                self.warnings.append({"path": path, "reason": "Package metadata could not be parsed"})
        commit, dirty = "", None
        if shutil.which("git"):
            command = ["git", "--no-optional-locks", "-c", f"safe.directory={self.root}", "-c", "core.fsmonitor=false", "-C", str(self.root)]
            try:
                revision = subprocess.run(command + ["rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
                if revision.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", revision.stdout.strip()):
                    commit = revision.stdout.strip()
                    status = subprocess.run(command + ["status", "--porcelain", "--untracked-files=normal"],
                                            capture_output=True, text=True, timeout=10)
                    if status.returncode == 0:
                        dirty = bool(status.stdout.strip())
            except (OSError, subprocess.TimeoutExpired):
                pass
        return version, version_evidence, commit, dirty

    def build(self):
        if not (self.root / "src/linkmerce").is_dir():
            raise ValueError("Linkmerce source directory not found")
        self.python_nodes()
        self.config_tables()
        self.dbt_nodes()
        self.python_edges()
        self.dbt_edges()
        self.selectors()
        overview = []
        if (self.root / "README.md").is_file():
            lines = self.read("README.md").splitlines()
            for start in range(0, min(len(lines), 270), 22):
                overview.append(self.ev("README.md", start + 1, start + 22))
        package_version, version_evidence, commit, source_dirty = self.source_metadata()
        if version_evidence:
            overview.insert(0, version_evidence)
        extractor_version = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        rules = Path(__file__).parents[1] / "ontology/linkmerce.dl"
        ontology_version = hashlib.sha256(rules.read_bytes()).hexdigest()
        fingerprint = hashlib.sha256((str(sorted(self.files.items())) + extractor_version + ontology_version).encode()).hexdigest()
        return {"nodes": self.nodes, "edges": self.edges, "evidence": self.evidence, "overview": overview,
                "warnings": self.warnings, "meta": {"indexed_at": datetime.now(timezone.utc).isoformat(),
                "commit": commit, "source_dirty": source_dirty, "package_version": package_version,
                "version_evidence": version_evidence, "fingerprint": fingerprint, "extractor_version": extractor_version, "ontology_version": ontology_version, "files": len(self.files), "analysis": "static"}}
