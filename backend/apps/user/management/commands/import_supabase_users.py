import csv

from django.core.management.base import BaseCommand
from django.utils.crypto import get_random_string

from apps.user.models import User


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "t", "yes", "on")


class Command(BaseCommand):
    help = "Import users exported from Supabase (CSV) into Django User model"

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path",
            type=str,
            help="Path to the CSV file exported from Supabase",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"]

        created = 0
        skipped_existing = 0
        skipped_invalid = 0

        self.stdout.write(self.style.NOTICE(f"Reading CSV from {csv_path}"))

        with open(csv_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                # Campos esperados en el CSV:
                # email, role, email_verified, mfa_enabled, active
                raw_email = row.get("email")
                email = (raw_email or "").strip().lower()
                if not email:
                    skipped_invalid += 1
                    self.stderr.write(f"Skipping row without email: {row}")
                    continue

                # Si ya existe un usuario con ese email, no lo duplicamos
                if User.objects.filter(email=email).exists():
                    skipped_existing += 1
                    continue

                raw_role = (row.get("role") or "").strip()

                # Mapea roles del CSV a los de Django si hiciera falta
                # Ajustá este diccionario según cómo se guarden en tu modelo User
                role_map = {
                    "Administrator": "Administrator",
                    "administrator": "Administrator",
                    "Admin": "Administrator",
                    "admin": "Administrator",
                    "Manager": "manager",
                    "manager": "manager",
                    "Member": "member",
                    "member": "member",
                    "": "member",  # default
                }
                role = role_map.get(raw_role, "member")

                email_verified = parse_bool(row.get("email_verified"), default=False)
                mfa_enabled = parse_bool(row.get("mfa_enabled"), default=False)
                is_active = parse_bool(row.get("active"), default=True)

                # Creamos el usuario sin contraseña usable,
                # para forzar a que haga "forgot password" o un set password desde tu flujo.
                user = User(
                    email=email,
                    role=role,
                    is_active=is_active,
                )

                # Si tu modelo User tiene estos campos, los asignamos.
                if hasattr(user, "email_verified"):
                    user.email_verified = email_verified
                if hasattr(user, "mfa_enabled"):
                    user.mfa_enabled = mfa_enabled

                # Opcional: dar permisos extra al rol Administrator
                if hasattr(user, "is_staff") and role == "Administrator":
                    user.is_staff = True
                if hasattr(user, "is_superuser") and role == "Administrator":
                    # Opcional: si quieres que Administrator sea superusuario en Django
                    user.is_superuser = False  # pon True si realmente querés superusers
                                             # O mejor manejalo desde el admin

                # Seteamos una contraseña aleatoria y luego la marcamos como unusable
                # para evitar logins con esa password.
                random_password = get_random_string(12)
                user.set_password(random_password)
                user.set_unusable_password()

                user.save()

                self.stdout.write(f"Created user {user.pk} - {email} - role={role}")
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {created} users, "
                f"skipped existing={skipped_existing}, invalid={skipped_invalid}."
            )
        )
