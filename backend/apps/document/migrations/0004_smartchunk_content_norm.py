from django.db import migrations, models
from django.db.models import Func
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ("document", "0003_search_indexes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="smartchunk",
                    name="content_norm",
                    field=models.GeneratedField(
                        db_persist=True,
                        expression=Func(
                            Lower("content"),
                            function="immutable_unaccent",
                        ),
                        output_field=models.TextField(),
                        editable=False,
                    ),
                ),
            ],
        ),
    ]
