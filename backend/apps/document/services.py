from __future__ import annotations

from typing import Iterable

from django.db.models import Q, QuerySet

from apps.document.models import Document


def accessible_documents_for(user, slugs: Iterable[str]) -> QuerySet[Document]:
    """
    Returns the subset of documents identified by `slugs` that the user can access.
    """
    qs = Document.objects.filter(slug__in=slugs)
    if user.is_staff:
        return qs
    return qs.filter(Q(owner=user) | Q(is_public=True))

