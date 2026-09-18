from ollama import chat
from pydantic import ValidationError

from src.config import MODEL_NAME


def structured_chat(
    system_prompt,
    user_prompt,
    response_model,
):

    last_error = None

    for attempt in range(2):

        if attempt == 0:

            prompt = user_prompt

        else:

            prompt = (
                user_prompt
                + "\n\n"
                + "IMPORTANT RETRY INSTRUCTION:\n"
                + "Your previous structured response was "
                + "invalid or incomplete JSON. "
                + "Return one COMPLETE JSON object that "
                + "strictly matches the requested schema. "
                + "Keep all explanatory text concise. "
                + "Do not include text outside the JSON object."
            )

        response = chat(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            format=response_model.model_json_schema(),
            options={
                "temperature": 0,
                "num_predict": 2048,
            },
        )

        try:

            return response_model.model_validate_json(
                response.message.content
            )

        except ValidationError as exc:

            last_error = exc

    raise last_error