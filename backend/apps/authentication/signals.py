import logging

from django.contrib.auth import get_user_model
from django.db import OperationalError, ProgrammingError
from django.db.models.signals import pre_save
from django.dispatch import receiver
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

logger = logging.getLogger(__name__)
User = get_user_model()


def _blacklist_user_tokens(user):
    try:
        tokens = OutstandingToken.objects.filter(user=user)
        for token in tokens:
            BlacklistedToken.objects.get_or_create(token=token)
    except (OperationalError, ProgrammingError) as exc:
        logger.debug("Token blacklist tables not ready: %s", exc)


@receiver(pre_save, sender=User)
def invalidate_tokens_on_sensitive_change(sender, instance, **kwargs):
    if not instance.pk:
        return

    try:
        previous = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    should_blacklist = False
    if (
        previous.last_password_change != instance.last_password_change
        and instance.last_password_change
    ):
        should_blacklist = True
    if previous.is_active and not instance.is_active:
        should_blacklist = True

    if should_blacklist:
        _blacklist_user_tokens(instance)

