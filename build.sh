#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

APP_DIR="$ROOT_DIR/backend/CircleUp"

if [ ! -f "$APP_DIR/requirements.txt" ]; then
	echo "requirements.txt not found at $APP_DIR"
	exit 1
fi

echo "Installing Python dependencies..."
python -m pip install --upgrade pip
python -m pip install -r "$APP_DIR/requirements.txt"

cd "$APP_DIR"

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Django build completed successfully."
