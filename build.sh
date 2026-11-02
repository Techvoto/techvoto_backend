#!/usr/bin/env bash
# Render / generic PaaS build step
set -o errexit
pip install -r requirements.txt

# Migrations MUST be committed. If a model changed without a migration (or none exist yet), fail the build loudly
# instead of deploying a database that is missing tables. Fix locally with:
#   python manage.py makemigrations users courses assessments liveclasses payments engagement support
if ! python manage.py makemigrations --check --dry-run >/dev/null 2>&1; then
  echo "ERROR: model changes are not covered by committed migrations. Run makemigrations locally and commit the files." >&2
  exit 1
fi

python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py check --deploy --fail-level ERROR
