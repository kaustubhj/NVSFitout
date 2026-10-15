#!/usr/bin/env bash
# Build step for hosted deployments (Render, Railway, any Linux host)
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py setup_erp ${ERP_LOAD_DEMO:+--demo} --password "${ERP_ADMIN_PASSWORD:-Fitout@123}"
