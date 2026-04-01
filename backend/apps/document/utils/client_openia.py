"""
OpenAI Client Service

Centralized service for OpenAI API interactions across the application.
Uses a shared client instance for efficiency while allowing per-call configuration.

Architecture Decision:
- Single shared client: All apps (documents, chat, evaluations) use the same
  client instance to reuse HTTP connections and reduce overhead.
- Configuration flexibility: Model, temperature, and other parameters are
  passed per-call, allowing each app to customize behavior as needed.
- Lazy initialization: Client is created only when needed, ensuring environment
  variables are loaded.

Usage by App:
- Documents: Uses embed_text() for document chunk embeddings
- Chat: Uses generate_chat_completion() for conversational responses
- Evaluations: Uses generate_chat_completion() for structured evaluations
"""
import os
from typing import List, Tuple, Optional

from openai import OpenAI


# Model defaults from environment
MODEL_EMBEDDING = os.environ.get("MODEL_EMBEDDING", "text-embedding-3-small")
MODEL_COMPLETION = os.environ.get("MODEL_COMPLETION", "gpt-4o-mini")

# Lazy initialization of OpenAI client to avoid issues with env vars not being loaded
_client: Optional[OpenAI] = None


def get_openai_client() -> OpenAI:
    """
    Get or create the shared OpenAI client instance.
    
    Uses singleton pattern with lazy initialization to:
    - Ensure environment variables are loaded before client creation
    - Reuse HTTP connections across all apps (documents, chat, evaluations)
    - Reduce memory footprint and connection overhead
    
    Returns:
        OpenAI: Shared client instance
        
    Raises:
        ValueError: If OPENAI_API_KEY is not configured
    """
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is not set. "
                "Please ensure it's configured in your .env file or environment."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def embed_text(text: str, model: str | None = None) -> List[float]:
    """
    Generate embeddings for text using OpenAI's embedding model.
    
    Primarily used by the Documents app for creating vector embeddings
    of document chunks for RAG (Retrieval Augmented Generation).
    
    Args:
        text: Text to generate embedding for
        model: Embedding model to use (defaults to MODEL_EMBEDDING)
        
    Returns:
        List[float]: Embedding vector (1536 dimensions for text-embedding-3-small)
    """
    client = get_openai_client()
    embedding_model = model or MODEL_EMBEDDING
    response = client.embeddings.create(input=text, model=embedding_model)
    return response.data[0].embedding


def generate_chat_completion(
    messages: List[dict],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> Tuple[str, dict]:
    """
    Generate chat completion using OpenAI's chat models.
    
    Used by:
    - Chat app: Conversational responses with RAG context
    - Evaluations app: Structured metric/pillar evaluations
    
    The shared client allows each app to customize behavior via parameters:
    - Chat: Uses session-specific model and temperature
    - Evaluations: Uses run-specific model and temperature
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys
        model: Model to use (defaults to MODEL_COMPLETION)
        temperature: Sampling temperature (0.0-2.0, default 0.1)
        max_tokens: Maximum tokens in response (optional)
        timeout: Request timeout in seconds (optional)
        
    Returns:
        Tuple[str, dict]: (completion_text, usage_info)
            - completion_text: Generated response text
            - usage_info: Dict with 'input_tokens', 'output_tokens', 'total_tokens'
            
    Raises:
        ValueError: If API returns empty response
    """
    # Format messages for OpenAI Chat Completions API
    formatted_messages = [
        {
            "role": message["role"],
            "content": message["content"],
        }
        for message in messages
    ]

    client = get_openai_client()
    
    # Build request parameters
    request_params = {
        "model": model or MODEL_COMPLETION,
        "temperature": temperature,
        "messages": formatted_messages,
    }
    
    # Add optional parameters if provided
    if max_tokens is not None:
        request_params["max_tokens"] = max_tokens
    
    # Make API call with optional timeout
    if timeout is not None:
        response = client.chat.completions.create(
            **request_params,
            timeout=timeout,
        )
    else:
        response = client.chat.completions.create(**request_params)

    # Extract the completion text from the response
    if not response.choices:
        raise ValueError("OpenAI API returned an empty response")

    raw_content = response.choices[0].message.content
    completion_text = (raw_content or "").strip()
    if not completion_text:
        raise ValueError("OpenAI API returned an empty response")

    usage_obj = getattr(response, "usage", None)
    if usage_obj is not None:
        usage = {
            "input_tokens": usage_obj.prompt_tokens or 0,
            "output_tokens": usage_obj.completion_tokens or 0,
            "total_tokens": usage_obj.total_tokens or 0,
        }
    else:
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return completion_text, usage