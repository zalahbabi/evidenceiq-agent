import json

from src.tier2_agent import run_tier2


QUESTION = (
    "Did November 2011 beat October 2011 "
    "on revenue, and by how much?"
)


answer, plan = run_tier2(
    QUESTION
)


print("\n")
print("=" * 70)
print("QUESTION")
print("=" * 70)
print(QUESTION)


print("\n")
print("=" * 70)
print("PLAN")
print("=" * 70)

print(
    json.dumps(
        plan.model_dump(
            mode="json"
        ),
        indent=2,
    )
)


print("\n")
print("=" * 70)
print("TOOL CALLS")
print("=" * 70)

for call in answer.tool_calls:

    print(
        json.dumps(
            call.model_dump(
                mode="json"
            ),
            indent=2,
        )
    )


print("\n")
print("=" * 70)
print("FINAL ANSWER")
print("=" * 70)

print(
    json.dumps(
        answer.model_dump(
            mode="json"
        ),
        indent=2,
    )
)