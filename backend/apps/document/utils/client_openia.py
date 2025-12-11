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
    Wrapper for the Chat Completions API that returns text + token usage.
    """
    # Format messages for OpenAI Chat Completions API
    formatted_messages = [
        {
            "role": message["role"],
            "content": message["content"],
        }
        for message in messages
    ]

    response = client.chat.completions.create(
        model=model or MODEL_COMPLETION,
        temperature=temperature,
        messages=formatted_messages,
    )

    # Extract the completion text from the response
    if not response.choices or not response.choices[0].message.content:
        raise ValueError("OpenAI API returned an empty response")
    
    completion_text = response.choices[0].message.content.strip()
    
    # Extract usage information
    usage = {
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens,
    }
    return completion_text, usage