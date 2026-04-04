from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0002_user_security_fields"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE user_user ADD COLUMN IF NOT EXISTS approved boolean NOT NULL DEFAULT false;",
            reverse_sql="ALTER TABLE user_user DROP COLUMN IF EXISTS approved;",
            state_operations=[
                migrations.AddField(
                    model_name="user",
                    name="approved",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]
