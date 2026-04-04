from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0002_user_security_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="approved",
            field=models.BooleanField(default=False),
        ),
    ]
