"""Deterministic source architecture, health, impact, and evolution analysis."""

from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
from pathlib import PurePosixPath
import re
from typing import Iterable

from app.schemas.architecture import (
    AnalysisCoverage,
    ApiRoute,
    ArchitectureAnalysis,
    ArchitectureDependency,
    ArchitectureDiff,
    ArchitectureHealth,
    ArchitectureHealthIssue,
    CodeRelation,
    CodeSymbol,
    ImpactAnalysis,
    ImpactEdge,
    ImpactNode,
    ImpactAnalysisRequest,
    TestMapping,
)
from app.schemas.project_analysis import ProjectAnalysis
from app.schemas.repository import FileCategory, RepositoryFileContent, RepositorySnapshot
from app.services.project_analysis import ProjectAnalysisService


PARSER_VERSION = "1.2"
PYTHON_SUFFIXES = {".py"}
WEB_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "websocket"}
MAX_SYMBOLS = 2500
MAX_RELATIONS = 5000
MAX_GRAPH_NODES = 120


@dataclass(slots=True)
class _PendingRelation:
    source: str
    target_name: str
    relation: str
    path: str
    line: int | None
    language: str
    import_level: int = 0


class ArchitectureAnalysisService:
    """Build architecture evidence without requiring an LLM."""

    parser_version = PARSER_VERSION

    def analyze(
        self,
        snapshot: RepositorySnapshot,
        project: ProjectAnalysis | None = None,
    ) -> ArchitectureAnalysis:
        project = project or ProjectAnalysisService().analyze(snapshot)
        revision = self.revision_for(snapshot)
        generated_at = datetime.now(timezone.utc)
        symbols: dict[str, CodeSymbol] = {}
        relations: list[CodeRelation] = []
        routes: list[ApiRoute] = []
        pending: list[_PendingRelation] = []
        parse_warnings: list[str] = []
        parsed_source_paths: set[str] = set()

        contents = [
            content
            for content in snapshot.source_contents
            if PurePosixPath(content.path).suffix.lower() in PYTHON_SUFFIXES | WEB_SUFFIXES
            and content.category in {FileCategory.SOURCE, FileCategory.TEST}
        ]
        module_keys = {content.path: self._module_key(content.path) for content in contents}
        aliases = self._module_aliases(module_keys)

        for content in contents:
            language = self._language(content.path)
            module_key = module_keys[content.path]
            symbols[module_key] = CodeSymbol(
                key=module_key,
                name=PurePosixPath(content.path).stem,
                qualified_name=self._module_name(content.path),
                kind="module",
                path=content.path,
                language=language,
                line_start=1,
                line_end=max(1, len(content.content.splitlines())),
                fingerprint=self._fingerprint(content.content),
                metadata={
                    "category": content.category.value,
                    "line_count": len(content.content.splitlines()),
                    "truncated": content.truncated,
                },
            )

            try:
                if language == "Python":
                    new_symbols, new_relations, new_routes = self._parse_python(content, module_key)
                else:
                    new_symbols, new_relations, new_routes = self._parse_web(content, module_key)
            except (SyntaxError, ValueError) as exc:
                parse_warnings.append(f"{content.path}: {type(exc).__name__}")
                continue

            parsed_source_paths.add(content.path)
            for symbol in new_symbols:
                if len(symbols) >= MAX_SYMBOLS:
                    break
                symbols.setdefault(symbol.key, symbol)
            pending.extend(new_relations)
            routes.extend(new_routes)

        local_symbols = self._local_symbol_index(symbols.values())
        for item in pending:
            target = self._resolve_relation_target(item, aliases, module_keys, local_symbols, symbols)
            if target is None:
                continue
            relations.append(CodeRelation(
                source=item.source,
                target=target,
                relation=item.relation,  # type: ignore[arg-type]
                evidence_path=item.path,
                evidence_line=item.line,
                confidence=1.0 if item.relation == "contains" else 0.9,
            ))

        relations = self._deduplicate_relations(relations)[:MAX_RELATIONS]
        test_mappings = self._build_test_mappings(contents, symbols, relations)
        for mapping in test_mappings:
            test_module = module_keys.get(mapping.test_path)
            if not test_module:
                continue
            for source_path in mapping.source_paths:
                source_module = module_keys.get(source_path)
                if source_module:
                    relations.append(CodeRelation(
                        source=test_module,
                        target=source_module,
                        relation="tests",
                        evidence_path=mapping.test_path,
                        confidence=mapping.confidence,
                    ))

        dependencies = [
            ArchitectureDependency(
                name=item.name,
                version=item.version,
                ecosystem=item.ecosystem,
                group=item.group,
                source_file=item.source_file,
            )
            for item in project.dependency_packages
        ]
        coverage = self._coverage(snapshot, project, parsed_source_paths, parse_warnings)
        health = self._health(project, symbols, relations, routes, test_mappings, dependencies, coverage)
        return ArchitectureAnalysis(
            repository=snapshot.identity.full_name,
            revision=revision,
            generated_at=generated_at,
            parser_version=PARSER_VERSION,
            coverage=coverage,
            symbols=list(symbols.values()),
            relations=self._deduplicate_relations(relations)[:MAX_RELATIONS],
            routes=self._deduplicate_routes(routes),
            test_mappings=test_mappings,
            dependencies=dependencies,
            health=health,
        )

    def impact(
        self,
        analysis: ArchitectureAnalysis,
        request: ImpactAnalysisRequest,
    ) -> ImpactAnalysis:
        symbols_by_key = {symbol.key: symbol for symbol in analysis.symbols}
        seed_paths = self._impact_seed_paths(analysis, request)
        module_by_path = {
            symbol.path: symbol
            for symbol in analysis.symbols
            if symbol.kind == "module" and symbol.path
        }
        seed_keys = {
            module_by_path[path].key
            for path in seed_paths
            if path in module_by_path
        }

        # Impact propagates from a changed module to its dependants. Keeping the
        # graph at file level avoids exploding through every ``contains`` edge.
        adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
        seen_adjacency: set[tuple[str, str, str]] = set()
        for relation in analysis.relations:
            if relation.relation == "contains":
                continue
            source_symbol = symbols_by_key.get(relation.source)
            target_symbol = symbols_by_key.get(relation.target)
            source_module = module_by_path.get(source_symbol.path) if source_symbol and source_symbol.path else None
            target_module = module_by_path.get(target_symbol.path) if target_symbol and target_symbol.path else None
            if source_module is None or target_module is None or source_module.key == target_module.key:
                continue

            # ``source imports/calls target`` means a target change can affect
            # source. Test relations already point from test to source.
            edge = (target_module.key, source_module.key, relation.relation)
            if edge not in seen_adjacency:
                adjacency[edge[0]].append((edge[1], edge[2]))
                seen_adjacency.add(edge)

        depth_by_key = {key: 0 for key in seed_keys}
        parent_edges: list[ImpactEdge] = []
        queue = deque(seed_keys)
        while queue and len(depth_by_key) < MAX_GRAPH_NODES:
            current = queue.popleft()
            current_depth = depth_by_key[current]
            if current_depth >= request.max_depth:
                continue
            for target, relation in adjacency.get(current, []):
                if target not in symbols_by_key or target in depth_by_key:
                    continue
                depth_by_key[target] = current_depth + 1
                parent_edges.append(ImpactEdge(source=current, target=target, relation=relation))
                queue.append(target)

        affected_modules = [symbols_by_key[key] for key in depth_by_key if key in symbols_by_key]
        affected_files = sorted({symbol.path for symbol in affected_modules if symbol.path})
        affected_symbols = [
            symbol
            for symbol in analysis.symbols
            if symbol.path in affected_files and symbol.kind != "dependency"
        ]
        recommended_tests = [
            mapping
            for mapping in analysis.test_mappings
            if set(mapping.source_paths) & set(affected_files) or mapping.test_path in affected_files
        ]
        affected_routes = [route for route in analysis.routes if route.path in affected_files]

        risk_score = 0
        if seed_paths:
            production_files = [path for path in affected_files if not self._is_test_path(path)]
            first_hop_dependants = sum(1 for depth in depth_by_key.values() if depth == 1)
            breadth_score = min(24, round(math.log2(len(production_files) + 1) * 6))
            coupling_score = min(18, first_hop_dependants * 3)
            route_score = min(18, len(affected_routes) * 3)
            critical_terms = {"auth", "security", "database", "storage", "config", "settings", "webhook", "main"}
            critical_score = 8 if any(
                any(term in path.lower() for term in critical_terms)
                for path in seed_paths
            ) else 0
            test_gap_score = 12 if production_files and not recommended_tests else 0
            depth_score = max(depth_by_key.values(), default=0) * 3
            risk_score = min(
                95,
                8 + breadth_score + coupling_score + route_score
                + critical_score + test_gap_score + depth_score,
            )
        if risk_score >= 70:
            risk_level = "high"
        elif risk_score >= 40:
            risk_level = "medium"
        else:
            risk_level = "low"
        reasons = (
            [
                f"以 {len(seed_paths)} 个文件作为分析起点，沿调用方、导入方和测试关系展开 {request.max_depth} 层。",
                f"共定位 {len(affected_files)} 个影响文件，其中 {sum(1 for depth in depth_by_key.values() if depth == 1)} 个为直接关联。",
            ]
            if seed_paths
            else ["未从当前已索引源码中定位到可靠起点，请补充文件路径或更具体的符号名。"]
        )
        if affected_routes:
            reasons.append(f"涉及 {len(affected_routes)} 个 API 路由，需要验证接口兼容性。")
        if recommended_tests:
            reasons.append(f"找到 {len(recommended_tests)} 个相关测试文件。")
        elif affected_files:
            reasons.append("未找到明确关联测试，建议补充回归测试。")

        nodes = [
            ImpactNode(
                key=symbol.key,
                label=symbol.name,
                kind=symbol.kind,
                path=symbol.path,
                depth=depth_by_key[symbol.key],
                reason="分析起点" if depth_by_key[symbol.key] == 0 else "由调用方、导入方或测试关系关联",
            )
            for symbol in affected_modules[:MAX_GRAPH_NODES]
        ]
        return ImpactAnalysis(
            repository=analysis.repository,
            revision=analysis.revision,
            seed_paths=seed_paths,
            affected_files=affected_files,
            affected_symbols=affected_symbols[:200],
            recommended_tests=recommended_tests[:30],
            affected_routes=affected_routes[:50],
            risk_score=risk_score,
            risk_level=risk_level,
            reasons=reasons,
            nodes=nodes,
            edges=parent_edges[:240],
        )

    def diff(self, base: ArchitectureAnalysis, target: ArchitectureAnalysis) -> ArchitectureDiff:
        base_symbols = {self._symbol_identity(item): item for item in base.symbols}
        target_symbols = {self._symbol_identity(item): item for item in target.symbols}
        shared_symbols = set(base_symbols) & set(target_symbols)
        changed_symbols = [
            target_symbols[key]
            for key in shared_symbols
            if base_symbols[key].fingerprint != target_symbols[key].fingerprint
        ]

        base_routes = {(item.method, item.route, item.path): item for item in base.routes}
        target_routes = {(item.method, item.route, item.path): item for item in target.routes}
        base_dependencies = {self._dependency_identity(item): item for item in base.dependencies}
        target_dependencies = {self._dependency_identity(item): item for item in target.dependencies}
        return ArchitectureDiff(
            repository=target.repository,
            base_revision=base.revision,
            target_revision=target.revision,
            added_symbols=[target_symbols[key] for key in sorted(set(target_symbols) - set(base_symbols))][:300],
            removed_symbols=[base_symbols[key] for key in sorted(set(base_symbols) - set(target_symbols))][:300],
            changed_symbols=changed_symbols[:300],
            added_routes=[target_routes[key] for key in sorted(set(target_routes) - set(base_routes))],
            removed_routes=[base_routes[key] for key in sorted(set(base_routes) - set(target_routes))],
            added_dependencies=[target_dependencies[key] for key in sorted(set(target_dependencies) - set(base_dependencies))],
            removed_dependencies=[base_dependencies[key] for key in sorted(set(base_dependencies) - set(target_dependencies))],
            health_score_delta=target.health.score - base.health.score,
        )

    @staticmethod
    def revision_for(snapshot: RepositorySnapshot) -> str:
        if snapshot.source_revision:
            return snapshot.source_revision
        if snapshot.recent_commits:
            return snapshot.recent_commits[0].sha
        return f"sync-{snapshot.synced_at.strftime('%Y%m%d%H%M%S')}"

    def _parse_python(
        self,
        content: RepositoryFileContent,
        module_key: str,
    ) -> tuple[list[CodeSymbol], list[_PendingRelation], list[ApiRoute]]:
        tree = ast.parse(content.content, filename=content.path)
        lines = content.content.splitlines()
        symbols: list[CodeSymbol] = []
        pending: list[_PendingRelation] = []
        routes: list[ApiRoute] = []
        stack: list[CodeSymbol] = []

        service = self

        class Visitor(ast.NodeVisitor):
            def visit_Import(self, node: ast.Import) -> None:
                source = stack[-1].key if stack else module_key
                for alias in node.names:
                    pending.append(_PendingRelation(source, alias.name, "imports", content.path, node.lineno, "Python"))

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                source = stack[-1].key if stack else module_key
                module = node.module or ""
                pending.append(_PendingRelation(source, module, "imports", content.path, node.lineno, "Python", node.level))

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                symbol = service._python_symbol(content.path, lines, node, stack, module_key, "class")
                symbols.append(symbol)
                pending.append(_PendingRelation(symbol.parent_key or module_key, symbol.key, "contains", content.path, node.lineno, "Python"))
                stack.append(symbol)
                self.generic_visit(node)
                stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._visit_function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._visit_function(node)

            def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                kind = "method" if stack and stack[-1].kind == "class" else "function"
                symbol = service._python_symbol(content.path, lines, node, stack, module_key, kind)
                symbols.append(symbol)
                pending.append(_PendingRelation(symbol.parent_key or module_key, symbol.key, "contains", content.path, node.lineno, "Python"))
                for decorator in node.decorator_list:
                    route = service._python_route(decorator, symbol, content.path, node.lineno)
                    if route:
                        routes.append(route)
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        called_name = service._python_call_name(child.func)
                        if called_name:
                            pending.append(_PendingRelation(symbol.key, called_name, "calls", content.path, getattr(child, "lineno", node.lineno), "Python"))
                stack.append(symbol)
                for statement in node.body:
                    self.visit(statement)
                stack.pop()

        Visitor().visit(tree)
        return symbols, pending, routes

    def _parse_web(
        self,
        content: RepositoryFileContent,
        module_key: str,
    ) -> tuple[list[CodeSymbol], list[_PendingRelation], list[ApiRoute]]:
        symbols: list[CodeSymbol] = []
        pending: list[_PendingRelation] = []
        routes: list[ApiRoute] = []
        lines = content.content.splitlines()
        import_re = re.compile(r"(?:from\s+|require\s*\(\s*)['\"]([^'\"]+)['\"]")
        function_re = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")
        class_re = re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")
        component_re = re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+([A-Z][\w$]*)\s*=\s*(?:\([^)]*\)|[\w$]+)\s*=>")
        route_re = re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete|options|head)\s*\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*([A-Za-z_$][\w$]*))?")

        by_name: dict[str, CodeSymbol] = {}
        for line_number, line in enumerate(lines, start=1):
            for match in import_re.finditer(line):
                pending.append(_PendingRelation(module_key, match.group(1), "imports", content.path, line_number, "TypeScript"))

            match = function_re.search(line)
            kind = "function"
            if not match:
                match = class_re.search(line)
                kind = "class"
            if not match:
                match = component_re.search(line)
                kind = "component"
            if match:
                name = match.group(1)
                key = f"symbol:{content.path}:{name}:{line_number}"
                symbol = CodeSymbol(
                    key=key,
                    name=name,
                    qualified_name=f"{self._module_name(content.path)}.{name}",
                    kind=kind,  # type: ignore[arg-type]
                    path=content.path,
                    language="TypeScript" if content.path.endswith((".ts", ".tsx")) else "JavaScript",
                    line_start=line_number,
                    line_end=line_number,
                    parent_key=module_key,
                    fingerprint=self._fingerprint(line.strip()),
                )
                symbols.append(symbol)
                by_name[name] = symbol
                pending.append(_PendingRelation(module_key, key, "contains", content.path, line_number, "TypeScript"))

            route_match = route_re.search(line)
            if route_match:
                handler_name = route_match.group(3) or "inline_handler"
                handler = by_name.get(handler_name)
                routes.append(ApiRoute(
                    method=route_match.group(1).upper(),
                    route=route_match.group(2),
                    handler_key=handler.key if handler else module_key,
                    handler_name=handler_name,
                    path=content.path,
                    line=line_number,
                ))
        return symbols, pending, routes

    def _python_symbol(self, path, lines, node, stack, module_key, kind) -> CodeSymbol:
        parent_key = stack[-1].key if stack else module_key
        parent_name = stack[-1].qualified_name if stack else self._module_name(path)
        end_line = getattr(node, "end_lineno", node.lineno)
        snippet = "\n".join(lines[node.lineno - 1:end_line])
        return CodeSymbol(
            key=f"symbol:{path}:{parent_name}.{node.name}:{node.lineno}",
            name=node.name,
            qualified_name=f"{parent_name}.{node.name}",
            kind=kind,
            path=path,
            language="Python",
            line_start=node.lineno,
            line_end=end_line,
            parent_key=parent_key,
            fingerprint=self._fingerprint(snippet),
        )

    def _python_route(self, decorator, symbol, path, line) -> ApiRoute | None:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            return None
        method = decorator.func.attr.lower()
        if method not in ROUTE_METHODS or not decorator.args:
            return None
        route_value = decorator.args[0]
        if not isinstance(route_value, ast.Constant) or not isinstance(route_value.value, str):
            return None
        return ApiRoute(
            method=method.upper(),
            route=route_value.value,
            handler_key=symbol.key,
            handler_name=symbol.qualified_name,
            path=path,
            line=line,
        )

    @staticmethod
    def _python_call_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _resolve_relation_target(self, item, aliases, module_keys, local_symbols, symbols) -> str | None:
        if item.relation == "contains" and item.target_name in symbols:
            return item.target_name
        if item.relation == "calls":
            candidates = local_symbols.get((item.path, item.target_name), [])
            return candidates[0] if len(candidates) == 1 else None

        if item.language == "Python":
            target_name = self._python_absolute_import(item.path, item.target_name, item.import_level)
            candidates = aliases.get(target_name, [])
        elif item.target_name.startswith("."):
            resolved_path = self._resolve_web_path(item.path, item.target_name, module_keys)
            return module_keys.get(resolved_path) if resolved_path else None
        else:
            candidates = []

        closest = self._closest_module_candidate(item.path, candidates, module_keys)
        if closest is not None:
            return closest
        package = item.target_name.lstrip(".").split(".", 1)[0].split("/", 1)[0]
        if not package:
            return None
        key = f"dependency:{package}"
        symbols.setdefault(key, CodeSymbol(
            key=key,
            name=package,
            qualified_name=package,
            kind="dependency",
            language="external",
        ))
        return key

    @staticmethod
    def _closest_module_candidate(
        source_path: str,
        candidates: list[str],
        module_keys: dict[str, str],
    ) -> str | None:
        """Resolve duplicate module aliases within the caller's source root."""
        if len(candidates) == 1:
            return candidates[0]
        path_by_key = {key: path for path, key in module_keys.items()}
        source_parts = PurePosixPath(source_path).parts
        scored: list[tuple[int, str]] = []
        for candidate in candidates:
            candidate_path = path_by_key.get(candidate)
            if not candidate_path:
                continue
            common_prefix = 0
            for source_part, candidate_part in zip(source_parts, PurePosixPath(candidate_path).parts, strict=False):
                if source_part != candidate_part:
                    break
                common_prefix += 1
            scored.append((common_prefix, candidate))
        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score = scored[0][0]
        best = [candidate for score, candidate in scored if score == best_score]
        return best[0] if best_score > 0 and len(best) == 1 else None

    def _build_test_mappings(self, contents, symbols, relations) -> list[TestMapping]:
        module_path = {symbol.key: symbol.path for symbol in symbols.values() if symbol.kind == "module"}
        imported_sources: dict[str, set[str]] = defaultdict(set)
        for relation in relations:
            if relation.relation != "imports":
                continue
            source_path = module_path.get(relation.source)
            target_path = module_path.get(relation.target)
            if source_path and target_path and self._is_test_path(source_path) and not self._is_test_path(target_path):
                imported_sources[source_path].add(target_path)

        source_paths = [content.path for content in contents if content.category == FileCategory.SOURCE]
        mappings: list[TestMapping] = []
        for content in contents:
            if content.category != FileCategory.TEST and not self._is_test_path(content.path):
                continue
            if not self._is_test_case_path(content.path):
                continue
            linked = set(imported_sources.get(content.path, set()))
            if not linked:
                stem = PurePosixPath(content.path).stem.lower()
                normalized = re.sub(r"^(test_|spec_)", "", stem)
                normalized = re.sub(r"(_test|\.test|\.spec)$", "", normalized)
                linked.update(path for path in source_paths if PurePosixPath(path).stem.lower() == normalized)
            mappings.append(TestMapping(
                test_path=content.path,
                source_paths=sorted(linked),
                confidence=0.95 if imported_sources.get(content.path) else (0.65 if linked else 0.25),
                reason="测试文件直接导入源码模块" if imported_sources.get(content.path) else (
                    "测试与源码文件名匹配" if linked else "仅识别到测试文件，未找到明确源码关联"
                ),
            ))
        return mappings

    def _coverage(self, snapshot, project, parsed_source_paths, parse_warnings) -> AnalysisCoverage:
        indexed_files = len(snapshot.source_contents)
        discovered = max(project.analyzed_file_count, indexed_files)
        discovered_source = max(project.source_count, len([
            item for item in snapshot.source_contents if item.category == FileCategory.SOURCE
        ]))
        indexed_source = len([
            item for item in snapshot.source_contents if item.category == FileCategory.SOURCE
        ])
        parsed_source = len([
            path for path in parsed_source_paths
            if next((item for item in snapshot.source_contents if item.path == path), None)
            and next(item for item in snapshot.source_contents if item.path == path).category == FileCategory.SOURCE
        ])
        warnings = list(parse_warnings[:12])
        if indexed_files < discovered:
            warnings.append(f"仅保存了 {indexed_files}/{discovered} 个已发现文件的内容。")
        truncated = sum(item.truncated for item in snapshot.source_contents)
        if truncated:
            warnings.append(f"{truncated} 个文件内容被截断，符号和关系可能不完整。")
        unsupported = indexed_source - parsed_source
        if unsupported:
            warnings.append(f"{unsupported} 个源码文件不是当前语义解析器支持的 Python/JS/TS 类型或解析失败。")
        return AnalysisCoverage(
            discovered_files=discovered,
            indexed_files=indexed_files,
            discovered_source_files=discovered_source,
            parsed_source_files=parsed_source,
            truncated_files=truncated,
            file_coverage_percent=round(min(100.0, indexed_files * 100 / discovered), 1) if discovered else 100.0,
            parser_coverage_percent=round(min(100.0, parsed_source * 100 / discovered_source), 1) if discovered_source else 100.0,
            warnings=warnings,
        )

    def _health(self, project, symbols, relations, routes, test_mappings, dependencies, coverage) -> ArchitectureHealth:
        module_symbols = {key: value for key, value in symbols.items() if value.kind == "module" and value.path}
        import_relations = [
            relation for relation in relations
            if relation.relation == "imports" and relation.source in module_symbols and relation.target in module_symbols
        ]
        adjacency: dict[str, set[str]] = defaultdict(set)
        incoming: Counter[str] = Counter()
        outgoing: Counter[str] = Counter()
        for relation in import_relations:
            adjacency[relation.source].add(relation.target)
            outgoing[relation.source] += 1
            incoming[relation.target] += 1

        cycles = self._strongly_connected_cycles(module_symbols, adjacency)
        oversized = [
            symbol.path for symbol in module_symbols.values()
            if int(symbol.metadata.get("line_count", 0)) >= 800 and symbol.path
        ]
        high_coupling = [
            module_symbols[key].path for key in module_symbols
            if incoming[key] + outgoing[key] >= 10 and module_symbols[key].path
        ]
        source_modules = {
            symbol.path for symbol in module_symbols.values()
            if symbol.metadata.get("category") == FileCategory.SOURCE.value and symbol.path
        }
        tested_sources = {path for mapping in test_mappings for path in mapping.source_paths}
        untested = sorted(source_modules - tested_sources)
        orphaned = [
            symbol.path for key, symbol in module_symbols.items()
            if len(module_symbols) > 1 and incoming[key] == 0 and outgoing[key] == 0
            and symbol.metadata.get("category") == FileCategory.SOURCE.value and symbol.path
        ]
        version_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
        for item in dependencies:
            if item.version:
                version_groups[(item.ecosystem, item.name.lower())].add(item.version)
        conflicts = [f"{ecosystem}:{name}" for (ecosystem, name), versions in version_groups.items() if len(versions) > 1]

        issues: list[ArchitectureHealthIssue] = []
        if cycles:
            cycle_paths = sorted({module_symbols[key].path for cycle in cycles for key in cycle if module_symbols[key].path})
            issues.append(ArchitectureHealthIssue(
                code="circular_import",
                severity="critical",
                title="检测到模块循环依赖",
                description=f"发现 {len(cycles)} 组循环导入，可能增加初始化和修改风险。",
                evidence_paths=cycle_paths[:12],
                suggestion="提取公共接口或下沉共享模型，打破双向依赖。",
            ))
        if high_coupling:
            issues.append(ArchitectureHealthIssue(
                code="high_coupling",
                severity="warning",
                title="部分模块耦合度较高",
                description=f"{len(high_coupling)} 个模块的导入入度与出度之和达到 10。",
                evidence_paths=sorted(high_coupling)[:12],
                suggestion="检查模块职责，并通过服务接口隔离跨层调用。",
            ))
        if oversized:
            issues.append(ArchitectureHealthIssue(
                code="oversized_module",
                severity="warning",
                title="存在超大源码文件",
                description="文件超过 800 行，可能承担了过多职责。",
                evidence_paths=sorted(oversized)[:12],
                suggestion="按业务职责拆分类、路由或服务。",
            ))
        if untested:
            issues.append(ArchitectureHealthIssue(
                code="missing_test_link",
                severity="warning",
                title="部分源码没有明确测试映射",
                description=f"{len(untested)} 个源码模块未通过导入或命名规则关联到测试。",
                evidence_paths=untested[:12],
                suggestion="补充对应测试，或在测试中直接导入被测模块以形成可追踪关系。",
            ))
        if orphaned:
            issues.append(ArchitectureHealthIssue(
                code="orphan_module",
                severity="info",
                title="发现孤立源码模块",
                description=f"{len(orphaned)} 个模块没有检测到内部导入关系。",
                evidence_paths=sorted(orphaned)[:12],
                suggestion="确认它们是否为独立入口、脚本或未使用代码。",
            ))
        if conflicts:
            issues.append(ArchitectureHealthIssue(
                code="dependency_version_conflict",
                severity="warning",
                title="依赖版本声明不一致",
                description=f"{len(conflicts)} 个依赖在不同清单中使用了不同版本范围。",
                evidence_paths=sorted({item.source_file for item in dependencies if f"{item.ecosystem}:{item.name.lower()}" in conflicts}),
                suggestion="统一依赖版本范围并重新生成锁文件。",
            ))
        if coverage.file_coverage_percent < 80 or coverage.parser_coverage_percent < 70:
            issues.append(ArchitectureHealthIssue(
                code="partial_analysis",
                severity="warning",
                title="架构分析覆盖率有限",
                description=f"文件内容覆盖率 {coverage.file_coverage_percent}%，解析器覆盖率 {coverage.parser_coverage_percent}%。",
                evidence_paths=[],
                suggestion="扩大同步文件上限，或为主要语言增加解析器。",
            ))

        deduction = sum(18 if item.severity == "critical" else 8 if item.severity == "warning" else 3 for item in issues)
        score = max(0, 100 - deduction)
        grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "E"
        return ArchitectureHealth(
            score=score,
            grade=grade,
            metrics={
                "module_count": len(module_symbols),
                "internal_import_count": len(import_relations),
                "cycle_count": len(cycles),
                "route_count": len(routes),
                "test_mapping_count": len(test_mappings),
                "untested_module_count": len(untested),
                "high_coupling_module_count": len(high_coupling),
                "dependency_conflict_count": len(conflicts),
            },
            issues=issues,
        )

    def _impact_seed_paths(self, analysis, request) -> list[str]:
        available_paths = sorted({symbol.path for symbol in analysis.symbols if symbol.path})
        requested = {path.replace("\\", "/").lstrip("./") for path in request.paths}
        matched = {
            path
            for path in available_paths
            if path in requested or any(path.endswith(candidate) for candidate in requested)
        }
        if matched:
            return sorted(matched)

        issue_text = (request.issue_text or "").lower()
        terms = {
            term.lower() for term in re.findall(r"[A-Za-z0-9_./-]{3,}", issue_text)
            if term.lower() not in {
                "issue", "error", "bug", "feature", "request", "fix", "change",
                "this", "that", "with", "from", "when", "after", "before",
            }
        }
        domain_aliases = {
            "认证": {"auth", "login", "token", "security"},
            "登录": {"auth", "login", "token", "user"},
            "权限": {"auth", "permission", "role", "security"},
            "路由": {"route", "router", "api", "endpoint"},
            "接口": {"api", "route", "endpoint", "client"},
            "数据库": {"database", "storage", "store", "repository", "db"},
            "存储": {"storage", "store", "repository", "database"},
            "配置": {"config", "settings", "environment", "env"},
            "测试": {"test", "tests", "spec", "pytest"},
            "前端": {"frontend", "component", "page", "view", "ui"},
            "后端": {"backend", "service", "api", "route"},
            "依赖": {"dependency", "package", "requirements", "pyproject"},
            "webhook": {"webhook", "event", "handler"},
            "issue": {"issue", "classifier", "webhook"},
        }
        for label, aliases in domain_aliases.items():
            if label in issue_text:
                terms.update(aliases)

        evidence_by_path: dict[str, set[str]] = defaultdict(set)
        for symbol in analysis.symbols:
            if symbol.path:
                evidence_by_path[symbol.path].update({symbol.name.lower(), symbol.qualified_name.lower()})
        for route in analysis.routes:
            evidence_by_path[route.path].update({route.route.lower(), route.handler_name.lower()})

        scored = []
        for path in available_paths:
            lowered = path.lower()
            evidence = " ".join(evidence_by_path.get(path, set()))
            score = sum(
                4 if term in PurePosixPath(lowered).name
                else 3 if term in evidence
                else 1
                for term in terms
                if term in lowered or term in evidence
            )
            if score:
                scored.append((score, path))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [path for _, path in scored[:5]]

    @staticmethod
    def _module_key(path: str) -> str:
        return f"module:{path}"

    @staticmethod
    def _module_name(path: str) -> str:
        value = str(PurePosixPath(path).with_suffix("")).replace("/", ".")
        return value.removesuffix(".__init__")

    def _module_aliases(self, module_keys: dict[str, str]) -> dict[str, list[str]]:
        aliases: dict[str, list[str]] = defaultdict(list)
        for path, key in module_keys.items():
            parts = self._module_name(path).split(".")
            for index in range(len(parts)):
                alias = ".".join(parts[index:])
                if key not in aliases[alias]:
                    aliases[alias].append(key)
        return aliases

    @staticmethod
    def _local_symbol_index(symbols: Iterable[CodeSymbol]) -> dict[tuple[str, str], list[str]]:
        index: dict[tuple[str, str], list[str]] = defaultdict(list)
        for symbol in symbols:
            if symbol.path and symbol.kind in {"function", "method", "component"}:
                index[(symbol.path, symbol.name)].append(symbol.key)
        return index

    def _python_absolute_import(self, path: str, module: str, level: int) -> str:
        if level <= 0:
            return module
        package = self._module_name(path).split(".")[:-1]
        keep = max(0, len(package) - level + 1)
        prefix = package[:keep]
        if module:
            prefix.extend(module.split("."))
        return ".".join(prefix)

    @staticmethod
    def _resolve_web_path(current_path: str, target: str, module_keys: dict[str, str]) -> str | None:
        base = PurePosixPath(current_path).parent
        candidate = base.joinpath(target)
        normalized_parts: list[str] = []
        for part in candidate.parts:
            if part == "..":
                if normalized_parts:
                    normalized_parts.pop()
            elif part != ".":
                normalized_parts.append(part)
        normalized = "/".join(normalized_parts)
        candidates = [normalized, *(f"{normalized}{suffix}" for suffix in WEB_SUFFIXES)]
        candidates.extend(f"{normalized}/index{suffix}" for suffix in WEB_SUFFIXES)
        return next((item for item in candidates if item in module_keys), None)

    @staticmethod
    def _language(path: str) -> str:
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".py":
            return "Python"
        if suffix in {".ts", ".tsx"}:
            return "TypeScript"
        return "JavaScript"

    @staticmethod
    def _is_test_path(path: str) -> bool:
        lowered = path.lower()
        name = PurePosixPath(lowered).name
        return any(part in {"test", "tests", "__tests__"} for part in PurePosixPath(lowered).parts) or bool(
            re.search(r"(^test_|_test\.|\.test\.|\.spec\.)", name)
        )

    @staticmethod
    def _is_test_case_path(path: str) -> bool:
        name = PurePosixPath(path.lower()).name
        return bool(re.search(
            r"(^test_.*\.py$|_test\.py$|(^|\.)test\.(js|jsx|ts|tsx)$|\.spec\.(js|jsx|ts|tsx)$)",
            name,
        ))

    @staticmethod
    def _fingerprint(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _deduplicate_relations(relations: list[CodeRelation]) -> list[CodeRelation]:
        unique: dict[tuple[str, str, str], CodeRelation] = {}
        for relation in relations:
            unique.setdefault((relation.source, relation.target, relation.relation), relation)
        return list(unique.values())

    @staticmethod
    def _deduplicate_routes(routes: list[ApiRoute]) -> list[ApiRoute]:
        unique: dict[tuple[str, str, str], ApiRoute] = {}
        for route in routes:
            unique.setdefault((route.method, route.route, route.path), route)
        return list(unique.values())

    @staticmethod
    def _strongly_connected_cycles(modules, adjacency) -> list[list[str]]:
        index = 0
        stack: list[str] = []
        on_stack: set[str] = set()
        indices: dict[str, int] = {}
        low_links: dict[str, int] = {}
        components: list[list[str]] = []

        def visit(node: str) -> None:
            nonlocal index
            indices[node] = index
            low_links[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)
            for target in adjacency.get(node, set()):
                if target not in indices:
                    visit(target)
                    low_links[node] = min(low_links[node], low_links[target])
                elif target in on_stack:
                    low_links[node] = min(low_links[node], indices[target])
            if low_links[node] == indices[node]:
                component: list[str] = []
                while stack:
                    item = stack.pop()
                    on_stack.remove(item)
                    component.append(item)
                    if item == node:
                        break
                if len(component) > 1 or node in adjacency.get(node, set()):
                    components.append(component)

        for key in modules:
            if key not in indices:
                visit(key)
        return components

    @staticmethod
    def _symbol_identity(symbol: CodeSymbol) -> tuple[str, str, str | None]:
        return symbol.kind, symbol.qualified_name, symbol.path

    @staticmethod
    def _dependency_identity(item: ArchitectureDependency) -> tuple[str, str, str | None, str]:
        return item.ecosystem, item.name.lower(), item.version, item.source_file
