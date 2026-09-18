from src.llm import structured_chat

from src.prompts import (
    TIER2_SYSTEM_PROMPT,
    make_answer_prompt,
    make_chart_prompt,
    make_plan_prompt,
    make_python_prompt,
    make_sql_prompt,
    make_sql_repair_prompt,
)

from src.schemas import (
    AnalysisPlan,
    Answer,
    ChartSpec,
    Claim,
    DraftAnswer,
    PythonRequest,
    SQLRequest,
)

from src.tools import (
    extract_sql_metadata,
    make_chart,
    run_python,
    run_sql,
)

# ============================================================
# PLAN
# ============================================================

def create_plan(
    question: str,
) -> AnalysisPlan:

    return structured_chat(
        system_prompt=TIER2_SYSTEM_PROMPT,
        user_prompt=make_plan_prompt(
            question
        ),
        response_model=AnalysisPlan,
    )

# ============================================================
# FALLBACK CLAIM BUILDING
# ============================================================

MONTH_NAMES = {
    "01": "January",
    "02": "February",
    "03": "March",
    "04": "April",
    "05": "May",
    "06": "June",
    "07": "July",
    "08": "August",
    "09": "September",
    "10": "October",
    "11": "November",
    "12": "December",
}


def format_month_label(
    invoice_month: str,
) -> str:
    """
    Convert '2011-10' -> 'October 2011'
    """

    year, month = invoice_month.split("-")
    month_name = MONTH_NAMES.get(
        month,
        month,
    )

    return f"{month_name} {year}"


def has_incomplete_month(
    tool_calls,
) -> bool:
    """
    Return True if any successful SQL result explicitly
    reports an incomplete month.
    """

    for call in tool_calls:

        if (
            call.tool != "run_sql"
            or not call.ok
        ):
            continue

        for row in call.rows:

            if (
                "is_complete_month" in row
                and row["is_complete_month"] is False
            ):
                return True

    return False


def question_mentions_december_2011(
    question: str,
) -> bool:
    """
    Return True when the user explicitly references
    December 2011, the known incomplete month.
    """

    q = question.lower()

    return (
        "december 2011" in q
        or "2011-12" in q
    )


def build_fallback_claims(
    tool_calls,
) -> list[Claim]:
    """
    Build grounded Claim objects directly from successful
    tool results when the LLM omits the claims array.

    This is formatting, not Tier 3 verification.
    """

    claims = []

    # --------------------------------------------------------
    # Find the first successful SQL call with rows.
    # --------------------------------------------------------

    sql_call = next(
        (
            call
            for call in tool_calls
            if (
                call.tool == "run_sql"
                and call.ok
                and len(call.rows) > 0
            )
        ),
        None,
    )

    if sql_call is not None:

        rows = sql_call.rows

        # ====================================================
        # CASE 1 — MONTHLY REVENUE
        # ====================================================

        if all(
            (
                "invoice_month" in row
                and "net_revenue" in row
            )
            for row in rows
        ):

            for row in rows:

                month_label = format_month_label(
                    str(row["invoice_month"])
                )

                revenue = round(
                    float(row["net_revenue"]),
                    2,
                )

                claims.append(
                    Claim(
                        text=(
                            f"{month_label} revenue was "
                            f"GBP {revenue:,.2f}."
                        ),
                        value=revenue,
                        unit="GBP",
                        source_tool_call=sql_call.index,
                        derivation=None,
                        derived_from=[],
                    )
                )

                if (
                    "trading_days" in row
                    and row["trading_days"] is not None
                ):

                    trading_days = int(
                        row["trading_days"]
                    )

                    claims.append(
                        Claim(
                            text=(
                                f"{month_label} had "
                                f"{trading_days} trading days."
                            ),
                            value=trading_days,
                            unit="days",
                            source_tool_call=sql_call.index,
                            derivation=None,
                            derived_from=[],
                        )
                    )

        # ====================================================
        # CASE 2 — GENERIC RANKING
        #
        # Works for:
        # products
        # countries
        # customers
        # ====================================================

        else:

            metric_priority = [
                "total_revenue",
                "net_revenue",
                "gross_revenue",
                "revenue",
                "units_sold",
                "orders",
            ]

            label_priority = [
                "description",
                "country",
                "customer_id",
                "stock_code",
            ]

            metric_key = next(
                (
                    key
                    for key in metric_priority
                    if all(
                        (
                            key in row
                            and row[key] is not None
                        )
                        for row in rows
                    )
                ),
                None,
            )

            label_key = next(
                (
                    key
                    for key in label_priority
                    if all(
                        (
                            key in row
                            and row[key] is not None
                        )
                        for row in rows
                    )
                ),
                None,
            )

            if (
                metric_key is not None
                and label_key is not None
            ):

                for rank, row in enumerate(
                    rows,
                    start=1,
                ):

                    # ----------------------------------------
                    # Build readable label
                    # ----------------------------------------

                    raw_label = row[
                        label_key
                    ]

                    if (
                        isinstance(raw_label, float)
                        and raw_label.is_integer()
                    ):
                        raw_label = int(
                            raw_label
                        )

                    if label_key == "customer_id":

                        label = (
                            f"Customer {raw_label}"
                        )

                    elif (
                        label_key == "description"
                        and "stock_code" in row
                    ):

                        label = (
                            f"{row['stock_code']} "
                            f"({raw_label})"
                        )

                    else:

                        label = str(
                            raw_label
                        )

                    # ----------------------------------------
                    # Metric
                    # ----------------------------------------

                    metric_value = float(
                        row[metric_key]
                    )

                    metric_label = (
                        metric_key
                        .replace("_", " ")
                    )

                    # Revenue metrics
                    if "revenue" in metric_key:

                        value = round(
                            metric_value,
                            2,
                        )

                        text = (
                            f"Rank {rank}: "
                            f"{label} generated "
                            f"GBP {value:,.2f} "
                            f"in {metric_label}."
                        )

                        unit = "GBP"

                    else:

                        value = metric_value

                        text = (
                            f"Rank {rank}: "
                            f"{label} had "
                            f"{value:,.2f} "
                            f"{metric_label}."
                        )

                        unit = None

                    claims.append(
                        Claim(
                            text=text,
                            value=value,
                            unit=unit,
                            source_tool_call=sql_call.index,
                            derivation=None,
                            derived_from=[],
                        )
                    )

    # ========================================================
    # PYTHON-DERIVED CLAIMS
    # ========================================================

    python_calls = [
        call
        for call in tool_calls
        if (
            call.tool == "run_python"
            and call.ok
            and len(call.rows) > 0
        )
    ]

    for python_call in python_calls:

        row = python_call.rows[0]

        operation = row.get(
            "operation"
        )

        value = row.get(
            "value"
        )

        inputs = row.get(
            "inputs",
            [],
        )

        unit = row.get(
            "unit"
        )

        if value is None:
            continue

        if operation == "pct_change":

            claim_value = round(
                float(value),
                2,
            )

            text = (
                f"Revenue changed by "
                f"{claim_value:.2f}%."
            )

        elif operation == "difference":

            claim_value = round(
                float(value),
                2,
            )

            text = (
                f"The calculated difference was "
                f"{claim_value:,.2f}."
            )

        else:

            claim_value = round(
                float(value),
                4,
            )

            text = (
                f"The calculated {operation} "
                f"was {claim_value}."
            )

        claims.append(
            Claim(
                text=text,
                value=claim_value,
                unit=unit,
                source_tool_call=python_call.index,
                derivation=operation,
                derived_from=[
                    float(v)
                    for v in inputs
                ],
            )
        )

    return claims

def build_fallback_kpis(
    tool_calls,
) -> dict:
    """
    Build a small grounded KPI summary directly from
    successful tool results.

    Used when fallback claims are required.
    """

    sql_call = next(
        (
            call
            for call in tool_calls
            if (
                call.tool == "run_sql"
                and call.ok
                and len(call.rows) > 0
            )
        ),
        None,
    )

    if sql_call is None:
        return {}

    rows = sql_call.rows

    # --------------------------------------------------------
    # Monthly revenue
    # --------------------------------------------------------

    if all(
        (
            "invoice_month" in row
            and "net_revenue" in row
        )
        for row in rows
    ):

        kpis = {}

        for row in rows:

            month_label = format_month_label(
                str(row["invoice_month"])
            )

            kpis[
                f"{month_label} revenue"
            ] = round(
                float(row["net_revenue"]),
                2,
            )

        # Include derived Python result when present.
        python_call = next(
            (
                call
                for call in tool_calls
                if (
                    call.tool == "run_python"
                    and call.ok
                    and len(call.rows) > 0
                )
            ),
            None,
        )

        if python_call is not None:

            result = python_call.rows[0]

            if (
                result.get("operation")
                == "pct_change"
            ):

                kpis[
                    "Revenue change (%)"
                ] = round(
                    float(result["value"]),
                    2,
                )

        return kpis

    # --------------------------------------------------------
    # Ranking results
    # --------------------------------------------------------

    first = rows[0]

    metric_priority = [
        "total_revenue",
        "net_revenue",
        "gross_revenue",
        "revenue",
    ]

    metric_key = next(
        (
            key
            for key in metric_priority
            if key in first
        ),
        None,
    )

    if metric_key is None:
        return {}

    value = round(
        float(first[metric_key]),
        2,
    )

    # Customer
    if "customer_id" in first:

        customer_id = first[
            "customer_id"
        ]

        if (
            isinstance(customer_id, float)
            and customer_id.is_integer()
        ):
            customer_id = int(
                customer_id
            )

        return {
            "Top customer": str(customer_id),
            "Top customer revenue": value,
        }

    # Country
    if "country" in first:

        return {
            "Top country": str(
                first["country"]
            ),
            "Top country revenue": value,
        }

    # Product
    if "stock_code" in first:

        return {
            "Top product": str(
                first["stock_code"]
            ),
            "Top product revenue": value,
        }

    return {}

def build_fallback_findings(
    claims: list[Claim],
) -> str:
    """
    Produce conservative findings directly from grounded
    fallback claims.

    Used only when the LLM omitted structured claims.
    """

    if not claims:

        return (
            "The analysis completed successfully, "
            "but no structured numerical claims were produced."
        )

    derived_claims = [
        claim
        for claim in claims
        if claim.derivation is not None
    ]

    # Monthly calculation:
    # show all grounded facts because there are only a few.
    if derived_claims:

        selected = claims

    # Rankings:
    # summarize the first three grounded results.
    else:

        selected = claims[:3]

    return " ".join(
        claim.text
        for claim in selected
    )

def normalize_chart_source(
    chart_spec,
    tool_calls,
):
    """
    Ensure a chart references a successful SQL result.
    """

    if (
        chart_spec is None
        or chart_spec.type == "none"
    ):
        return chart_spec

    successful_sql_calls = [
        call
        for call in tool_calls
        if (
            call.tool == "run_sql"
            and call.ok
            and len(call.rows) > 0
        )
    ]

    if not successful_sql_calls:
        return chart_spec

    calls_by_index = {
        call.index: call
        for call in successful_sql_calls
    }

    current_source = (
        chart_spec.source_tool_call
    )

    if current_source not in calls_by_index:

        chart_spec.source_tool_call = (
            successful_sql_calls[-1].index
        )

    return chart_spec



# ============================================================
# RUN FULL TIER 2
# ============================================================

def run_tier2(
    question: str,
) -> tuple[Answer, AnalysisPlan]:

    # --------------------------------------------------------
    # 1. PLAN
    # --------------------------------------------------------

    plan = create_plan(
        question
    )

    # --------------------------------------------------------
    # 2. REFUSE QUESTIONS THE DATA CANNOT ANSWER
    # --------------------------------------------------------

    if not plan.sufficient_data:

        reason = (
            plan.reason
            or
            "The available dataset cannot answer this question."
        )

        answer = Answer(
            question=question,
            findings=reason,
            claims=[],
            kpis={},
            fields_used=[],
            filters_used=[],
            chart_spec=None,
            limitations=reason,
            insufficient_data=True,
            tool_calls=[],
        )

        return answer, plan
    # --------------------------------------------------------
    # PLAN SAFETY GUARD
    # --------------------------------------------------------

    if (
        plan.sufficient_data
        and len(plan.steps) == 0
    ):

        answer = Answer(
            question=question,
            findings=(
                "The analysis plan did not contain any "
                "executable data-retrieval steps, so Tier 2 "
                "cannot safely answer this question."
            ),
            claims=[],
            kpis={},
            fields_used=[],
            filters_used=[],
            chart_spec=None,
            limitations=(
                "The planner marked the question as answerable "
                "but did not generate a SQL execution step."
            ),
            insufficient_data=False,
            tool_calls=[],
        )

        return answer, plan
    # --------------------------------------------------------
    # 3. EXECUTE THE PLAN
    # --------------------------------------------------------

    tool_calls = []

    selected_chart = None

    ordered_steps = sorted(
        plan.steps,
        key=lambda step: step.step,
    )

    for step in ordered_steps:

        # ====================================================
        # SQL
        # ====================================================

        if step.tool == "run_sql":

            # =================================================
            # FIRST SQL ATTEMPT
            # =================================================

            sql_request = structured_chat(
                system_prompt=TIER2_SYSTEM_PROMPT,
                user_prompt=make_sql_prompt(
                    question=question,
                    objective=step.objective,
                ),
                response_model=SQLRequest,
            )

            call = run_sql(
                sql=sql_request.sql,
                index=len(tool_calls),
            )

            tool_calls.append(
                call
            )

            # =================================================
            # ONE-TIME SQL REPAIR
            # =================================================

            if not call.ok:

                repair_request = structured_chat(
                    system_prompt=TIER2_SYSTEM_PROMPT,
                    user_prompt=make_sql_repair_prompt(
                        question=question,
                        objective=step.objective,
                        failed_sql=call.code,
                        error=(
                            call.error
                            or
                            "Unknown SQL execution error."
                        ),
                    ),
                    response_model=SQLRequest,
                )

                repaired_call = run_sql(
                    sql=repair_request.sql,
                    index=len(tool_calls),
                )

                tool_calls.append(
                    repaired_call
                )

                # From this point onward, the repaired
                # call becomes the active result.
                call = repaired_call

            # =================================================
            # IF BOTH ATTEMPTS FAILED, STOP CLEANLY
            # =================================================

            if not call.ok:

                answer = Answer(
                    question=question,
                    findings=(
                        "The SQL analysis could not be "
                        "completed successfully after "
                        "one repair attempt."
                    ),
                    claims=[],
                    kpis={},
                    fields_used=[],
                    filters_used=[],
                    chart_spec=None,
                    limitations=call.error,
                    insufficient_data=False,
                    tool_calls=tool_calls,
                )

                return answer, plan
        # ====================================================
        # PYTHON CALCULATION
        # ====================================================

        elif step.tool == "run_python":

            # ------------------------------------------------
            # BUSINESS RULE:
            # Do not calculate month-to-month changes when
            # one of the queried months is incomplete.
            # ------------------------------------------------

            if (
                has_incomplete_month(tool_calls)
                or question_mentions_december_2011(question)
            ):
                continue

            python_request = structured_chat(
                system_prompt=TIER2_SYSTEM_PROMPT,
                user_prompt=make_python_prompt(
                    question=question,
                    objective=step.objective,
                    tool_calls=tool_calls,
                ),
                response_model=PythonRequest,
            )

            call = run_python(
                request=python_request,
                index=len(tool_calls),
            )

            tool_calls.append(
                call
            )

            if not call.ok:

                answer = Answer(
                    question=question,
                    findings=(
                        "The required calculation could "
                        "not be completed successfully."
                    ),
                    claims=[],
                    kpis={},
                    fields_used=[],
                    filters_used=[],
                    chart_spec=None,
                    limitations=call.error,
                    insufficient_data=False,
                    tool_calls=tool_calls,
                )

                return answer, plan

        # ====================================================
        # CHART
        # ====================================================

        elif step.tool == "make_chart":

            chart_spec = structured_chat(
                system_prompt=TIER2_SYSTEM_PROMPT,
                user_prompt=make_chart_prompt(
                    question=question,
                    objective=step.objective,
                    tool_calls=tool_calls,
                ),
                response_model=ChartSpec,
            )
            chart_spec = normalize_chart_source(
                chart_spec,
                tool_calls,
            )

            call = make_chart(
                chart_spec=chart_spec,
                index=len(tool_calls),
            )

            tool_calls.append(
                call
            )

            if (
                call.ok
                and chart_spec.type != "none"
            ):
                selected_chart = (
                    chart_spec.model_dump(mode="json")
                )
    # --------------------------------------------------------
    # EVIDENCE SAFETY GUARD
    # --------------------------------------------------------

    successful_data_calls = [
        call
        for call in tool_calls
        if (
            call.ok
            and call.tool in {
                "run_sql",
                "run_python",
            }
        )
    ]

    if len(successful_data_calls) == 0:

        answer = Answer(
            question=question,
            findings=(
                "No successful data tool call produced evidence "
                "for this question, so Tier 2 will not generate "
                "a numerical answer."
            ),
            claims=[],
            kpis={},
            fields_used=[],
            filters_used=[],
            chart_spec=selected_chart,
            limitations=(
                "No successful SQL or Python result was "
                "available to ground the answer."
            ),
            insufficient_data=False,
            tool_calls=tool_calls,
        )

        return answer, plan
    # --------------------------------------------------------
    # 4. GENERATE STRUCTURED DRAFT ANSWER
    # --------------------------------------------------------

    draft = structured_chat(
     system_prompt=TIER2_SYSTEM_PROMPT,
     user_prompt=make_answer_prompt(
        question=question,
        plan=plan,
        tool_calls=tool_calls,
        ),
        response_model=DraftAnswer,
    )

    # --------------------------------------------------------
    # 5. IMPORTANT:
    #    Tier 2 does NOT perform verification.
    #
    #    If the model omitted claims, build them
    #    deterministically from the real tool log.
    # --------------------------------------------------------

    used_fallback_claims = False

    final_claims = draft.claims

    if len(final_claims) == 0:

        final_claims = build_fallback_claims(
            tool_calls
        )

        used_fallback_claims = True

    for claim in final_claims:

        claim.status = None
        claim.evidence = None
        claim.failure_reason = None

    final_findings = draft.findings
    final_kpis = draft.kpis

    if (
        used_fallback_claims
        and len(final_claims) > 0
    ):

        final_findings = (build_fallback_findings(
            final_claims
            )
        )
        
        final_kpis = (build_fallback_kpis(
            tool_calls
            )
        )

    final_limitations = (
        draft.limitations
    )

    if (
        (
            has_incomplete_month(tool_calls)
            or question_mentions_december_2011(question)
        )
        and not final_limitations
    ):
        final_limitations = (
            "December 2011 is incomplete and contains only "
            "8 trading days, so it should not be treated as "
            "directly comparable with a complete month."
        )
    # --------------------------------------------------------
    # BUILD DETERMINISTIC SQL METADATA
    # --------------------------------------------------------

    actual_fields_used = []

    actual_filters_used = []

    for call in tool_calls:

        if (
            call.tool != "run_sql"
            or not call.ok
        ):
            continue

        metadata = extract_sql_metadata(
            call.code
        )

        for field in metadata[
            "fields_used"
        ]:

            if field not in actual_fields_used:
                actual_fields_used.append(
                    field
                )

        for filter_text in metadata[
            "filters_used"
        ]:

            if filter_text not in actual_filters_used:
                actual_filters_used.append(
                    filter_text
                )


    # 6. BUILD FINAL ANSWER
    #
    #    Tool calls come from OUR ACTUAL PYTHON LOG,
    #    not from the language model.
    # --------------------------------------------------------

    answer = Answer(
        question=question,
        findings=final_findings,
        claims=final_claims,
        kpis=final_kpis,
        fields_used=(
           actual_fields_used
           if actual_fields_used
           else draft.fields_used
        ),
        filters_used=(
           actual_filters_used
           if actual_filters_used
           else draft.filters_used
        ),
        chart_spec=selected_chart,
        limitations=final_limitations,
        insufficient_data=draft.insufficient_data,
        tool_calls=tool_calls,
    )

    return answer, plan


# ============================================================
# PUBLIC INTERFACE FOR TIER 3 / DASHBOARD
# ============================================================

def ask_tier2(
    question: str,
) -> Answer:

    answer, _ = run_tier2(
        question
    )

    return answer