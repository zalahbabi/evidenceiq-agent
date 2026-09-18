import json
from pathlib import Path

from src.tier2_agent import ask_tier2


QUESTIONS = {
    "monthly_comparison": (
        "Did November 2011 beat October 2011 "
        "on revenue, and by how much?"
    ),
    "incomplete_month": (
        "Did December 2011 revenue fall "
        "compared with November 2011?"
    ),
    "top_products": (
        "What were the top 10 products by revenue?"
    ),
    "top_customers": (
        "Who were the top five customers by revenue?"
    ),
    "top_countries_outside_uk": (
        "Which countries generated the most revenue outside the UK?"
    ),
    "profit_margin": (
        "What was our profit margin in 2011?"
    ),
}


def main():
    output_dir = Path("fixtures")
    output_dir.mkdir(exist_ok=True)

    for name, question in QUESTIONS.items():
        print(f"Generating {name}...")

        answer = ask_tier2(question)

        output_path = output_dir / f"{name}.json"

        output_path.write_text(
            json.dumps(
                answer.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
