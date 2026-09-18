from datetime import date, datetime
from decimal import Decimal

import sqlglot
from sqlglot import expressions as exp

from src.db import get_connection
from src.schemas import (
    ChartSpec,
    PythonRequest,
    ToolCall,
)


# ============================================================
# HELPERS
# ============================================================


def json_safe(value):
    """
    Convert database values into JSON-safe Python values.
    """

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value

def extract_sql_metadata(
    sql: str,
) -> dict:
    """
    Extract actual source fields and WHERE filters
    from executed SQL.

    SQL aliases such as total_revenue are excluded
    from fields_used.
    """

    try:
        tree = sqlglot.parse_one(
            sql,
            read="duckdb",
        )

        # ----------------------------------------------------
        # Collect aliases created in SELECT expressions.
        # Example:
        # SUM(revenue) AS total_revenue
        # ----------------------------------------------------

        aliases = set()

        for alias in tree.find_all(
            exp.Alias
        ):
            if alias.alias:
                aliases.add(
                    alias.alias
                )

        # ----------------------------------------------------
        # Collect actual source columns.
        # ----------------------------------------------------

        fields = []

        for column in tree.find_all(
            exp.Column
        ):
            name = column.name

            if not name:
                continue

            # Exclude references to calculated aliases.
            if name in aliases:
                continue

            if name not in fields:
                fields.append(
                    name
                )

        # ----------------------------------------------------
        # Extract WHERE clauses.
        # ----------------------------------------------------

        filters = []

        for where in tree.find_all(
            exp.Where
        ):

            filter_text = where.this.sql(
                dialect="duckdb"
            )

            if filter_text not in filters:
                filters.append(
                    filter_text
                )

        return {
            "fields_used": fields,
            "filters_used": filters,
        }

    except Exception:

        return {
            "fields_used": [],
            "filters_used": [],
        }
    
# ============================================================
# SQL SAFETY
# ============================================================

FORBIDDEN_SQL_NODES = {
    "insert",
    "update",
    "delete",
    "create",
    "drop",
    "alter",
    "copy",
    "command",
    "merge",
    "truncate",
    "attach",
    "detach",
    "install",
    "load",
    "pragma",
}


def validate_sql(sql: str):
    """
    Ensure that the model generated one read-only query.
    """

    if not sql or not sql.strip():
        raise ValueError(
            "SQL query is empty."
        )

    statements = sqlglot.parse(
        sql,
        read="duckdb",
    )

    if len(statements) != 1:
        raise ValueError(
            "Only one SQL statement is allowed."
        )

    tree = statements[0]

    # Reject dangerous SQL operations.
    for node in tree.walk():
        key = getattr(
            node,
            "key",
            "",
        ).lower()

        if key in FORBIDDEN_SQL_NODES:
            raise ValueError(
                f"Forbidden SQL operation: {key}"
            )

    # Require an actual SELECT somewhere in the tree.
    if tree.find(exp.Select) is None:
        raise ValueError(
            "Only read-only SELECT queries are allowed."
        )


# ============================================================
# TOOL 1 — RUN SQL
# ============================================================

def run_sql(
    sql: str,
    index: int,
    max_rows: int = 200,
) -> ToolCall:

    connection = None

    try:
        validate_sql(sql)

        connection = get_connection()

        cursor = connection.execute(sql)

        columns = [
            description[0]
            for description in cursor.description
        ]

        raw_rows = cursor.fetchmany(max_rows)

        rows = []

        for row in raw_rows:
            rows.append(
                {
                    column: json_safe(value)
                    for column, value
                    in zip(columns, row)
                }
            )

        return ToolCall(
            index=index,
            tool="run_sql",
            code=sql,
            ok=True,
            rows=rows,
            error=None,
        )

    except Exception as error:

        return ToolCall(
            index=index,
            tool="run_sql",
            code=sql,
            ok=False,
            rows=[],
            error=str(error),
        )

    finally:
        if connection is not None:
            connection.close()


# ============================================================
# TOOL 2 — RUN PYTHON
# ============================================================

def run_python(
    request: PythonRequest,
    index: int,
) -> ToolCall:
    """
    Perform a restricted calculation.

    IMPORTANT:
    We intentionally do NOT execute arbitrary
    Python generated by the LLM.
    """

    try:
        operation = request.operation
        values = request.values
        unit = request.unit

        if operation in {
            "pct_change",
            "share",
        } and unit is None:
            unit = "%"

        if operation == "pct_change":

            if len(values) != 2:
                raise ValueError(
                    "pct_change requires [new_value, old_value]."
                )

            new_value = values[0]
            old_value = values[1]

            if old_value == 0:
                raise ValueError(
                    "Cannot calculate percentage change "
                    "when old value is zero."
                )

            result = (
                (new_value - old_value)
                / old_value
                * 100
            )

            code = (
                f"({new_value} - {old_value}) "
                f"/ {old_value} * 100"
            )

        elif operation == "difference":

            if len(values) != 2:
                raise ValueError(
                    "difference requires [a, b]."
                )

            result = values[0] - values[1]

            code = (
                f"{values[0]} - {values[1]}"
            )

        elif operation == "ratio":

            if len(values) != 2:
                raise ValueError(
                    "ratio requires "
                    "[numerator, denominator]."
                )

            if values[1] == 0:
                raise ValueError(
                    "Cannot divide by zero."
                )

            result = values[0] / values[1]

            code = (
                f"{values[0]} / {values[1]}"
            )

        elif operation == "share":

            if len(values) != 2:
                raise ValueError(
                    "share requires [part, total]."
                )

            if values[1] == 0:
                raise ValueError(
                    "Cannot divide by zero."
                )

            result = (
                values[0]
                / values[1]
                * 100
            )

            code = (
                f"{values[0]} / {values[1]} * 100"
            )

        elif operation == "sum":

            if len(values) == 0:
                raise ValueError(
                    "sum requires at least one value."
                )

            result = sum(values)

            code = (
                " + ".join(
                    str(value)
                    for value in values
                )
            )

        elif operation == "mean":

            if len(values) == 0:
                raise ValueError(
                    "mean requires at least one value."
                )

            result = (
                sum(values)
                / len(values)
            )

            code = (
                f"mean({values})"
            )

        else:
            raise ValueError(
                f"Unsupported operation: {operation}"
            )

        return ToolCall(
            index=index,
            tool="run_python",
            code=code,
            ok=True,
            rows=[
                {
                    "result_name": request.result_name,
                    "value": result,
                    "unit": unit,
                    "operation": operation,
                    "inputs": values,
                }
            ],
            error=None,
        )

    except Exception as error:

        return ToolCall(
            index=index,
            tool="run_python",
            code=f"{request.operation}({request.values})",
            ok=False,
            rows=[],
            error=str(error),
        )


# ============================================================
# TOOL 3 — MAKE CHART
# ============================================================

def make_chart(
    chart_spec: ChartSpec,
    index: int,
) -> ToolCall:
    """
    Record the chart selected by Tier 2.

    The dashboard teammate will later render
    this specification using Plotly.
    """

    try:

        if chart_spec.type != "none":

            if chart_spec.source_tool_call is None:
                raise ValueError(
                    "Chart requires source_tool_call."
                )

            if not chart_spec.x:
                raise ValueError(
                    "Chart requires an x column."
                )

            if not chart_spec.y:
                raise ValueError(
                    "Chart requires a y column."
                )

        return ToolCall(
            index=index,
            tool="make_chart",
            code=chart_spec.model_dump_json(),
            ok=True,
            rows=[
                {
                    "chart_spec":
                        chart_spec.model_dump()
                }
            ],
            error=None,
        )

    except Exception as error:

        return ToolCall(
            index=index,
            tool="make_chart",
            code=chart_spec.model_dump_json(),
            ok=False,
            rows=[],
            error=str(error),
        )