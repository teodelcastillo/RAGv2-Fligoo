import os
from typing import List, Tuple

from openai import OpenAI


MODEL_EMBEDDING = os.environ.get("MODEL_EMBEDDING", "text-embedding-3-small")
MODEL_COMPLETION = os.environ.get("MODEL_COMPLETION", "gpt-4o-mini")

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def embed_text(text: str) -> List[float]:
    response = client.embeddings.create(input=text, model=MODEL_EMBEDDING)
    return response.data[0].embedding


def generate_chat_completion(
    messages: List[dict],
    *,
    model: str | None = None,
    temperature: float = 0.1,
) -> Tuple[str, dict]:
    """
    Wrapper for the Responses API that returns text + token usage.
    """
    formatted_input = [
        {
            "role": message["role"],
            "content": [{"type": "text", "text": message["content"]}],
        }
        for message in messages
    ]

    response = client.responses.create(
        model=model or MODEL_COMPLETION,
        temperature=temperature,
        input=formatted_input,
    )

    text_fragments = []
    if getattr(response, "output_text", None):
        text_fragments.extend(response.output_text)
    else:
        for block in getattr(response, "output", []) or []:
            content_items = getattr(block, "content", None)
            # Some SDK versions nest content under block.message.content
            if not content_items and hasattr(block, "message"):
                content_items = getattr(block.message, "content", None)
            if not content_items:
                continue
            for item in content_items:
                if getattr(item, "type", None) in ("output_text", "text"):
                    text_fragments.append(getattr(item, "text", ""))

    completion_text = "\n".join(fragment for fragment in text_fragments if fragment).strip()
    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
        "total_tokens": getattr(response.usage, "total_tokens", 0),
    }
    return completion_text, usage