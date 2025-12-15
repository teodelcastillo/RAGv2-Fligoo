from __future__ import annotations

from typing import Iterable

from django.db.models import Q, QuerySet

from apps.document.models import Document


def accessible_documents_for(user, slugs: Iterable[str]) -> QuerySet[Document]:
    """
    Returns the subset of documents identified by `slugs` that the user can access.
    Includes:
    - Own documents
    - Public documents
    - Documents shared directly with user
    - Documents in projects shared with user
    """
    qs = Document.objects.filter(slug__in=slugs)
    if user.is_staff:
        return qs
    
    # Documents in projects shared with user
    from apps.project.models import ProjectShare
    shared_project_ids = ProjectShare.objects.filter(
        user=user
    ).values_list('project_id', flat=True)
    
    return qs.filter(
        Q(owner=user) 
        | Q(is_public=True) 
        | Q(shares__user=user)
        | Q(projects__id__in=shared_project_ids)
    ).distinct()


def accessible_documents_queryset(user) -> QuerySet[Document]:
    """
    Returns a QuerySet of all documents accessible to the user.
    Useful for RAG global when a session has no assigned documents.
    Includes:
    - Own documents
    - Public documents
    - Documents shared directly with user
    - Documents in projects shared with user
    """
    qs = Document.objects.all()
    if user.is_staff:
        return qs
    
    # Documents in projects shared with user
    from apps.project.models import ProjectShare
    shared_project_ids = ProjectShare.objects.filter(
        user=user
    ).values_list('project_id', flat=True)
    
    return qs.filter(
        Q(owner=user) 
        | Q(is_public=True) 
        | Q(shares__user=user)
        | Q(projects__id__in=shared_project_ids)
    ).distinct()

