from django.db import migrations


def add_postgres_trigram_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        cursor.execute('CREATE INDEX IF NOT EXISTS users_first_name_trgm ON users USING gin (first_name gin_trgm_ops)')
        cursor.execute('CREATE INDEX IF NOT EXISTS users_last_name_trgm ON users USING gin (last_name gin_trgm_ops)')
        cursor.execute('CREATE INDEX IF NOT EXISTS courses_title_trgm ON courses_course USING gin (title gin_trgm_ops)')
        cursor.execute('CREATE INDEX IF NOT EXISTS courses_subtitle_trgm ON courses_course USING gin (subtitle gin_trgm_ops)')
        cursor.execute('CREATE INDEX IF NOT EXISTS courses_description_trgm ON courses_course USING gin (description gin_trgm_ops)')
        cursor.execute('CREATE INDEX IF NOT EXISTS lessons_title_trgm ON courses_lesson USING gin (title gin_trgm_ops)')
        cursor.execute('CREATE INDEX IF NOT EXISTS users_date_joined_desc ON users (date_joined DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS courses_status_published_idx ON courses_course (status, published_at DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS courses_created_desc_idx ON courses_course (created_at DESC)')


def remove_postgres_trigram_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for name in ('users_first_name_trgm', 'users_last_name_trgm', 'courses_title_trgm', 'courses_subtitle_trgm', 'courses_description_trgm', 'lessons_title_trgm', 'users_date_joined_desc', 'courses_status_published_idx', 'courses_created_desc_idx'):
            cursor.execute(f'DROP INDEX IF EXISTS {name}')


class Migration(migrations.Migration):
    initial = True
    dependencies = [('users', '0001_initial'), ('courses', '0002_initial')]
    operations = [migrations.RunPython(add_postgres_trigram_indexes, remove_postgres_trigram_indexes)]
