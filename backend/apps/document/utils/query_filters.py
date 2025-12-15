import re
from django.db.models import Q

def filter_by_numbers(qs, s: str, field: str = "content"):
    """
    Filter a queryset by checking if its `field` contains
    any of the numbers found in the input string.
    
    Args:
        qs: Django queryset
        s (str): input string with possible numbers
        field (str): field name to search on (default: "content")
    
    Returns:
        Filtered queryset
    """
    # extract numbers (int + float)
    numbers = [num for num in re.findall(r"\d+\.?\d*", s)]
    if not numbers:
        return qs

    query = Q()
    for num in numbers:
        print(f"Filtering for number: {num}")
        # Regex: ensure number is not part of a bigger number
        regex = rf"(?<!\d){num}(?!\d)"
        query &= Q(**{f"{field}__regex": regex})
    
    return qs.filter(query)
