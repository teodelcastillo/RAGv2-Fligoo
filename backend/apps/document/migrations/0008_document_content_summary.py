# Generated manually for content_summary field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("document", "0007_document_category_ref"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="content_summary",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Resumen automático del contenido, generado al procesar el archivo. "
                    "Mejora búsqueda semántica y recomendaciones de documentos relacionados."
                ),
            ),
        ),
    ]
