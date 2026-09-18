from src.tier2_agent import ask_tier2


def test_tier2_returns_claims_for_november_vs_october():

    answer = ask_tier2(
        "Did November 2011 beat October 2011 on revenue, and by how much?"
    )

    assert answer.insufficient_data is False

    assert len(answer.claims) >= 3

    claim_values = [
        claim.value
        for claim in answer.claims
    ]

    assert 1069368.23 in claim_values
    assert 1456145.8 in claim_values
    assert 36.17 in claim_values


def test_tier2_refuses_profit_margin():

    answer = ask_tier2(
        "What was our profit margin in 2011?"
    )

    assert answer.insufficient_data is True

    assert len(answer.claims) == 0

    assert len(answer.tool_calls) == 0

    assert answer.limitations is not None


def test_december_incomplete_month_blocks_calculation():

    answer = ask_tier2(
        "Did December 2011 revenue fall compared with November 2011?"
    )

    assert answer.insufficient_data is False

    # Tier 2 must surface the known incomplete-month caveat.
    assert answer.limitations is not None

    assert "incomplete" in (
        answer.limitations.lower()
    )

    # No derived month-to-month calculation should execute
    # when December 2011 is involved.
    python_calls = [
        call
        for call in answer.tool_calls
        if call.tool == "run_python"
    ]

    assert len(python_calls) == 0


def test_top_products_use_required_filters():

    answer = ask_tier2(
        "What were the top 10 products by revenue?"
    )

    assert answer.insufficient_data is False

    sql_calls = [
        call
        for call in answer.tool_calls
        if (
            call.tool == "run_sql"
            and call.ok
        )
    ]

    assert len(sql_calls) >= 1

    sql = sql_calls[0].code.lower()

    # Required EvidenceIQ product rules.
    assert "is_product" in sql
    assert "is_outlier" in sql
    assert "is_cancellation" in sql

    # Must actually return a top 10.
    assert len(
        sql_calls[0].rows
    ) == 10

    # No Python should be necessary for this ranking.
    python_calls = [
        call
        for call in answer.tool_calls
        if call.tool == "run_python"
    ]

    assert len(python_calls) == 0

    # Chart choice is evaluated more strictly in the
    # 30-question benchmark because the live LLM may vary.
    if answer.chart_spec is not None:

        assert (
            answer.chart_spec["type"]
            == "bar"
        )

    # Tier 3 needs structured numeric claims.
    assert len(answer.claims) == 10


def test_top_customers_by_revenue():

    answer = ask_tier2(
        "Who were the top five customers by revenue?"
    )

    assert answer.insufficient_data is False

    sql_calls = [
        call
        for call in answer.tool_calls
        if (
            call.tool == "run_sql"
            and call.ok
        )
    ]

    assert len(sql_calls) >= 1

    sql = sql_calls[0].code.lower()

    assert "dim_customer" in sql
    assert "net_revenue" in sql
    assert "limit 5" in sql

    assert len(
        sql_calls[0].rows
    ) == 5

    # Correct top customer from the actual database.
    first_row = sql_calls[0].rows[0]

    assert int(
        first_row["customer_id"]
    ) == 18102

    assert abs(
        float(
            first_row["net_revenue"]
        )
        - 570380.61
    ) < 0.01

    assert len(answer.claims) == 5


def test_country_revenue_excludes_uk():

    answer = ask_tier2(
        "Which countries generated the most revenue outside the UK?"
    )

    assert answer.insufficient_data is False

    sql_calls = [
        call
        for call in answer.tool_calls
        if (
            call.tool == "run_sql"
            and call.ok
        )
    ]

    assert len(sql_calls) >= 1

    sql = sql_calls[0].code.lower()

    assert "country" in sql
    assert "is_cancellation" in sql
    assert "united kingdom" in sql
    assert "group by" in sql
    assert "order by" in sql

    # UK must not appear in the result.
    countries = [
        row["country"]
        for row in sql_calls[0].rows
    ]

    assert (
        "United Kingdom"
        not in countries
    )

    # Dataset ground truth from executed SQL.
    assert countries[0] == "EIRE"

    assert abs(
        float(
            sql_calls[0].rows[0][
                "total_revenue"
            ]
        )
        - 658767.31
    ) < 0.01

    assert len(
        answer.claims
    ) == len(
        sql_calls[0].rows
    )