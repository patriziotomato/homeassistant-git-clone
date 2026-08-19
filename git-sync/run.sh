#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Git Sync..."

export CONFIG_DIR="${CONFIG_DIR:-/homeassistant}"

cd /app || bashio::exit.nok "App directory missing"
exec python3 -m uvicorn server:app --host 0.0.0.0 --port 8099
