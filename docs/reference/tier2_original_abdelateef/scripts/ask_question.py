import json
import sys

from src.tier2_agent import run_tier2


def main():

    if len(sys.argv) < 2:
        print(
            "Usage: python -m scripts.ask_question "
            "\"Your business question\""
        )
        return

    question = " ".join(
        sys.argv[1:]
    )

    answer, plan = run_tier2(
        question
    )

    print("\n")
    print("=" * 70)
    print("QUESTION")
    print("=" * 70)
    print(question)

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


if __name__ == "__main__":
    main()