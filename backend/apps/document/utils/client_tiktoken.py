from functools import lru_cache
from typing import List
import tiktoken

@lru_cache(maxsize=1)
def get_encoding():
    """
    Returns the tiktoken encoding for the text-embedding-3-small model.
    Cached for performance using LRU with a single slot.
    """
    return tiktoken.encoding_for_model("text-embedding-3-small")

def encode_text(text: str) -> List[int]:
    """Encodes a string into token IDs."""
    return get_encoding().encode(text)

def decode_text(tokens: List[int]) -> str:
    """Decodes token IDs back into a string."""
    return get_encoding().decode(tokens)

def token_count(text: str) -> int:
    """Returns the number of tokens in a given string."""
    return len(encode_text(text))
