"""Regex-based SQL DDL analysis: tables, keys, constraints, views, routines.

Works on the common CREATE/ALTER dialect subset (Oracle, Postgres, MySQL).
Everything reported is grounded in matched statements — nothing inferred.
"""

import re
from dataclasses import dataclass, field

IDENT = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$#.]*)'


def _clean(name: str) -> str:
    return name.strip().strip('"`[]')


def strip_sql_comments(text: str) -> str:
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


@dataclass
class ForeignKey:
    name: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


@dataclass
class CheckConstraint:
    name: str
    expression: str


@dataclass
class SqlTable:
    name: str
    file: str
    columns: list[dict] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    checks: list[CheckConstraint] = field(default_factory=list)
    uniques: list[str] = field(default_factory=list)


@dataclass
class SqlSchema:
    tables: list[SqlTable] = field(default_factory=list)
    views: list[dict] = field(default_factory=list)        # {name, file}
    procedures: list[dict] = field(default_factory=list)
    functions: list[dict] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)
    indexes: list[dict] = field(default_factory=list)      # {name, table, file}
    dropped_views_not_created: list[str] = field(default_factory=list)

    def table(self, name: str) -> SqlTable | None:
        lowered = _clean(name).lower()
        return next((t for t in self.tables if t.name.lower() == lowered), None)


def _split_columns(body: str) -> list[dict]:
    """Column definitions from a CREATE TABLE body (depth-0 comma split)."""
    parts, depth, current = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))

    columns = []
    for part in parts:
        part = part.strip()
        if not part or re.match(
            r"(?i)^(CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|KEY|INDEX)\b",
            part,
        ):
            continue
        match = re.match(rf"({IDENT})\s+(\S+)", part)
        if match:
            columns.append({"name": _clean(match.group(1)), "type": match.group(2)})
    return columns


def analyze_sql(files: dict[str, str]) -> SqlSchema | None:
    """files: {relative_path: content} for .sql files. None if no SQL given."""
    if not files:
        return None
    schema = SqlSchema()
    dropped_views: set[str] = set()

    for path, raw in files.items():
        text = strip_sql_comments(raw)

        for m in re.finditer(
            rf"(?is)\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({IDENT})\s*\((.*?)\)\s*(?:;|$)",
            text,
        ):
            table = SqlTable(name=_clean(m.group(1)), file=path)
            body = m.group(2)
            table.columns = _split_columns(body)
            inline_pk = re.search(rf"(?is)\bPRIMARY\s+KEY\s*\(([^)]+)\)", body)
            if inline_pk:
                table.primary_key = [_clean(c) for c in inline_pk.group(1).split(",")]
            for fk in re.finditer(
                rf"(?is)FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+({IDENT})\s*\(([^)]+)\)",
                body,
            ):
                table.foreign_keys.append(
                    ForeignKey(
                        name="(inline)",
                        columns=[_clean(c) for c in fk.group(1).split(",")],
                        ref_table=_clean(fk.group(2)),
                        ref_columns=[_clean(c) for c in fk.group(3).split(",")],
                    )
                )
            for ck in re.finditer(
                rf"(?is)CONSTRAINT\s+({IDENT})\s+CHECK\s*\((.+?)\)(?:,|$)", body
            ):
                table.checks.append(
                    CheckConstraint(name=_clean(ck.group(1)), expression=ck.group(2).strip())
                )
            schema.tables.append(table)

        for m in re.finditer(
            rf"(?is)\bALTER\s+TABLE\s+({IDENT})\s+ADD\s+CONSTRAINT\s+({IDENT})\s+"
            rf"(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\s*\((.*?)\)"
            rf"(?:\s*REFERENCES\s+({IDENT})\s*\(([^)]+)\))?",
            text,
        ):
            table = schema.table(m.group(1))
            if table is None:
                continue
            kind = re.sub(r"\s+", " ", m.group(3)).upper()
            name = _clean(m.group(2))
            inner = m.group(4).strip()
            if kind == "PRIMARY KEY":
                table.primary_key = [_clean(c) for c in inner.split(",")]
            elif kind == "FOREIGN KEY" and m.group(5):
                table.foreign_keys.append(
                    ForeignKey(
                        name=name,
                        columns=[_clean(c) for c in inner.split(",")],
                        ref_table=_clean(m.group(5)),
                        ref_columns=[_clean(c) for c in (m.group(6) or "").split(",")],
                    )
                )
            elif kind == "CHECK":
                table.checks.append(CheckConstraint(name=name, expression=inner))
            elif kind == "UNIQUE":
                table.uniques.append(name)

        for m in re.finditer(
            rf"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:UNIQUE\s+)?INDEX\s+({IDENT})\s+ON\s+({IDENT})",
            text,
        ):
            schema.indexes.append(
                {"name": _clean(m.group(1)), "table": _clean(m.group(2)), "file": path}
            )
        for m in re.finditer(
            rf"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:FORCE\s+)?VIEW\s+({IDENT})", text
        ):
            schema.views.append({"name": _clean(m.group(1)), "file": path})
        for m in re.finditer(
            rf"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+({IDENT})", text
        ):
            schema.procedures.append({"name": _clean(m.group(1)), "file": path})
        for m in re.finditer(
            rf"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+({IDENT})", text
        ):
            schema.functions.append({"name": _clean(m.group(1)), "file": path})
        for m in re.finditer(
            rf"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+({IDENT})", text
        ):
            schema.triggers.append({"name": _clean(m.group(1)), "file": path})
        for m in re.finditer(rf"(?is)\bDROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?({IDENT})", text):
            dropped_views.add(_clean(m.group(1)))

    if not any(
        [schema.tables, schema.views, schema.procedures, schema.functions,
         schema.triggers, schema.indexes]
    ):
        return None

    created_views = {v["name"].lower() for v in schema.views}
    schema.dropped_views_not_created = sorted(
        v for v in dropped_views if v.lower() not in created_views
    )
    return schema


def schema_to_json(schema: SqlSchema) -> dict:
    return {
        "tables": [
            {
                "name": t.name,
                "file": t.file,
                "columns": t.columns,
                "primary_key": t.primary_key,
                "foreign_keys": [
                    {
                        "name": fk.name,
                        "columns": fk.columns,
                        "ref_table": fk.ref_table,
                        "ref_columns": fk.ref_columns,
                    }
                    for fk in t.foreign_keys
                ],
                "checks": [{"name": c.name, "expression": c.expression} for c in t.checks],
                "uniques": t.uniques,
            }
            for t in schema.tables
        ],
        "views": schema.views,
        "procedures": schema.procedures,
        "functions": schema.functions,
        "triggers": schema.triggers,
        "indexes": schema.indexes,
        "dropped_views_not_created": schema.dropped_views_not_created,
    }


def schema_summary(schema: SqlSchema) -> str:
    lines = [
        f"{len(schema.tables)} tables, {len(schema.views)} views, "
        f"{len(schema.procedures)} procedures, {len(schema.functions)} functions, "
        f"{len(schema.triggers)} triggers, {len(schema.indexes)} indexes."
    ]
    for t in schema.tables:
        pk = ", ".join(t.primary_key) if t.primary_key else "NO PRIMARY KEY"
        lines.append(
            f"- {t.name} ({len(t.columns)} columns; PK: {pk}; "
            f"{len(t.foreign_keys)} FKs; {len(t.checks)} CHECKs) [{t.file}]"
        )
        for fk in t.foreign_keys:
            lines.append(
                f"    FK {fk.name}: ({', '.join(fk.columns)}) -> "
                f"{fk.ref_table}({', '.join(fk.ref_columns)})"
            )
        for ck in t.checks:
            lines.append(f"    CHECK {ck.name}: {ck.expression}")
    if schema.views:
        lines.append("Views: " + ", ".join(v["name"] for v in schema.views))
    if schema.dropped_views_not_created:
        lines.append(
            "Views dropped but never created in these files: "
            + ", ".join(schema.dropped_views_not_created)
        )
    return "\n".join(lines)


def deterministic_findings(schema: SqlSchema) -> list[dict]:
    """Grounded, no-LLM findings. Each references the actual defining file."""
    findings = []
    for t in schema.tables:
        if not t.primary_key:
            findings.append(
                {
                    "title": f"Table {t.name} has no primary key",
                    "description": (
                        f"CREATE TABLE {t.name} in {t.file} defines no PRIMARY KEY "
                        "inline or via ALTER TABLE."
                    ),
                    "category": "quality",
                    "priority": "high",
                    "confidence": "high",
                    "effort": "small",
                    "reasoning": "Parsed all CREATE TABLE and ALTER TABLE ... ADD CONSTRAINT statements; none declares a primary key for this table.",
                    "related_files": [t.file],
                }
            )
        fk_cols = {c.lower() for fk in t.foreign_keys for c in fk.columns}
        pk_cols = {c.lower() for c in t.primary_key}
        for col in t.columns:
            cname = col["name"].lower()
            if (
                cname.endswith("id")
                and cname not in pk_cols
                and cname not in fk_cols
                and len(cname) > 2
            ):
                findings.append(
                    {
                        "title": f"Column {t.name}.{col['name']} looks like a foreign key but has no FK constraint",
                        "description": (
                            f"{col['name']} in table {t.name} ({t.file}) follows the "
                            "*id naming convention but no FOREIGN KEY constraint references another table."
                        ),
                        "category": "quality",
                        "priority": "medium",
                        "confidence": "medium",
                        "effort": "small",
                        "reasoning": "Column name ends in 'id', is not part of the primary key, and no parsed FK constraint covers it. Naming is a heuristic, so confidence is medium.",
                        "related_files": [t.file],
                    }
                )
    for view in schema.dropped_views_not_created:
        files = sorted({t.file for t in schema.tables}) or []
        findings.append(
            {
                "title": f"View {view} is dropped but never created",
                "description": (
                    f"A DROP VIEW {view} statement exists, but no CREATE VIEW {view} "
                    "appears in any analyzed SQL file."
                ),
                "category": "quality",
                "priority": "medium",
                "confidence": "high",
                "effort": "medium",
                "reasoning": "DROP VIEW parsed without a matching CREATE VIEW in the repository's SQL files — the view definition is missing or was never committed.",
                "related_files": files,
            }
        )
    return findings
