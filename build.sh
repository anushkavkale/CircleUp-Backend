#!/bin/sh
set -eu

APP_DIR="$(dirname "$0")/backend/CircleUp"

python -m pip install --upgrade pip
python -m pip install -r "$APP_DIR/requirements.txt"

cd "$APP_DIR"
python manage.py migrate --noinput
python manage.py collectstatic --noinput
