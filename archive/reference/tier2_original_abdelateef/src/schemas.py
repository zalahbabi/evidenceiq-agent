from typing import Any, Literal

from pydantic import BaseModel, Field


# ============================================================
# 1. TOOL LOG
# ============================================================

class ToolCall(BaseModel):
    index: int

    tool: Literal[
        "run_sql",
        "run_python",
        "make_chart",
    ]

    code: str

    ok: bool

    rows: list[dict[str, Any]] = Field(
        default_factory=list
    )

    error: str | None = None


# ============================================================
# 2. CLAIM
# ============================================================

class Claim(BaseModel):
    text: str

    value: float | int | None = None

    unit: str | None = None

    source_tool_call: int | None = None

    derivation: str | None = None

    derived_from: list[float] = Field(
        default_factory=list
    )

    # Tier 3 will populate these later.
    status: Literal[
        "supported",
        "flagged",
        "unsupported",
    ] | None = None

    evidence: str | None = None

    failure_reason: str | None = None


# ============================================================
# 3. FINAL ANSWER OBJECT
# ============================================================

class Answer(BaseModel):
    question: str

    findings: str

    claims: list[Claim] = Field(
        default_factory=list
    )

    kpis: dict[str, float | int | str] = Field(
    default_factory=dict
    )

    fields_used: list[str] = Field(
        default_factory=list
    )

    filters_used: list[str] = Field(
        default_factory=list
    )

    chart_spec: dict[str, Any] | None = None

    limitations: str | None = None

    insufficient_data: bool = False

    tool_calls: list[ToolCall] = Field(
        default_factory=list
    )


# ============================================================
# 4. PLANNER OUTPUT
# ============================================================

class PlanStep(BaseModel):
    step: int

    tool: Literal[
        "run_sql",
        "run_python",
        "make_chart",
    ]

    objective: str

    depends_on: list[int] = Field(
        default_factory=list
    )


class AnalysisPlan(BaseModel):
    sufficient_data: bool = True

    reason: str | None = None

    steps: list[PlanStep] = Field(
        default_factory=list
    )


# ============================================================
# 5. SQL GENERATION OUTPUT
# ============================================================

class SQLRequest(BaseModel):
    sql: str


# ============================================================
# 6. PYTHON CALCULATION REQUEST
# ============================================================

class PythonRequest(BaseModel):
    operation: Literal[
        "pct_change",
        "difference",
        "ratio",
        "share",
        "sum",
        "mean",
    ]

    values: list[float]

    result_name: str

    unit: str | None = None

    explanation: str | None = None


# ============================================================
# 7. CHART SPECIFICATION
# ============================================================

class ChartSpec(BaseModel):
    type: Literal[
        "bar",
        "line",
        "scatter",
        "table",
        "none",
    ]

    source_tool_call: int | None = None

    x: str | None = None

    y: str | None = None

    title: str | None = None

    x_label: str | None = None

    y_label: str | None = None


# ============================================================
# 8. MODEL-GENERATED DRAFT ANSWER
# ============================================================

class DraftAnswer(BaseModel):
    findings: str

    claims: list[Claim] = Field(
        default_factory=list
    )

    kpis: dict[str, float | int | str] = Field(
    default_factory=dict
    )

    fields_used: list[str] = Field(
        default_factory=list
    )

    filters_used: list[str] = Field(
        default_factory=list
    )

    limitations: str | None = None

    insufficient_data: bool = False