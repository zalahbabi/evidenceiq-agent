from src.tier2_agent import ask_tier2


def main():
    question = "Who were the top five customers by revenue?"

    answer = ask_tier2(question)

    print("\nFINDINGS")
    print(answer.findings)

    print("\nCLAIMS")
    for claim in answer.claims:
        print(
            {
                "text": claim.text,
                "value": claim.value,
                "unit": claim.unit,
                "source_tool_call": claim.source_tool_call,
            }
        )

    print("\nKPIS")
    print(answer.kpis)

    print("\nCHART SPEC")
    print(answer.chart_spec)

    print("\nLIMITATIONS")
    print(answer.limitations)

    print("\nINSUFFICIENT DATA")
    print(answer.insufficient_data)

    print("\nTOOL CALLS")
    for call in answer.tool_calls:
        print(
            {
                "index": call.index,
                "tool": call.tool,
                "ok": call.ok,
                "code": call.code,
                "error": call.error,
            }
        )


if __name__ == "__main__":
    main()
