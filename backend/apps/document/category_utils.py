"""Helpers for document Category tree (subtree ids, path)."""
from __future__ import annotations

from typing import List, Optional, Set, Tuple

from apps.document.models import Category


def category_descendant_ids(root_id: int) -> Set[int]:
    """All category PKs in the subtree rooted at root_id, including root_id."""
    out: Set[int] = {root_id}
    frontier: List[int] = [root_id]
    while frontier:
        children = list(
            Category.objects.filter(parent_id__in=frontier).values_list("id", flat=True)
        )
        new = [c for c in children if c not in out]
        for c in new:
            out.add(c)
        frontier = new
    return out


def category_ancestor_path(category: Optional[Category]) -> List[Tuple[str, str]]:
    """
    From root to category: list of (name, slug) excluding empty.
    """
    if not category:
        return []
    chain: List[Category] = []
    node: Optional[Category] = category
    seen: Set[int] = set()
    while node and node.id not in seen:
        seen.add(node.id)
        chain.append(node)
        node = node.parent
    chain.reverse()
    return [(c.name, c.slug) for c in chain]


def resolve_write_category(
    user,
    *,
    category_slug: Optional[str] = None,
    category_name: Optional[str] = None,
    is_staff: bool = False,
) -> Tuple[Optional[Category], Optional[str]]:
    """
    Resolves (Category, legacy `category` string) for a document.
    - If `category_slug` is non-empty, use that row (owner must be user, unless staff).
    - Else if `category_name` (legacy) is non-empty, find-or-create a root Category for `user`.
    - Else: uncategorized -> (None, None).
    Raises ValueError with code 'category_not_found' or 'category_permission'.
    """
    slug = (category_slug or "").strip() if category_slug is not None else ""
    if slug:
        try:
            cat = Category.objects.get(slug=slug)
        except Category.DoesNotExist as exc:
            raise ValueError("category_not_found") from exc
        if not is_staff and cat.owner_id != user.id:
            raise ValueError("category_permission")
        return cat, cat.name

    name = (category_name or "").strip() if category_name is not None else ""
    if name:
        existing = Category.objects.filter(owner_id=user.id, name__iexact=name).first()
        if existing:
            return existing, existing.name
        cat = Category(owner=user, name=name, parent=None)
        cat.save()
        return cat, cat.name

    return None, None
