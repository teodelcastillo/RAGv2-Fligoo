from django.db import migrations
import pgvector.django

class Migration(migrations.Migration):

    dependencies = []

    operations = [
        pgvector.django.VectorExtension(),
    ]