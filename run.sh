#!/bin/bash

set -e

VENV_DIR="./venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

if [ "$1" = "server" ] || [ "$1" = "client" ] || [ "$1" = "wifi" ]; then
  if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
  fi

  echo "Installing Python dependencies..."
  $PIP install --upgrade pip 
  $PIP install -r app/requirements.txt
fi

case "$1" in
  server)
    echo "Starting WebSocket server..."
    $PYTHON app/server/server.py
    ;;
  client)
    echo "Running WebSocket client..."
    $PYTHON app/client/client.py
    ;;
  wifi)
    echo "Starting WiFi/ESP32 comms (MQTT bridge)..."
    $PYTHON app/server/comms.py
    ;;
  frontend)
    echo "Starting frontend..."
    cd app/frontend
    npm install
    npm start
    ;;
  *)
    echo "✅ Project environment ready."
    echo "Usage:"
    echo "  ./run.sh server     # Start backend WebSocket server"
    echo "  ./run.sh client     # Run Python WebSocket client"
    echo "  ./run.sh wifi       # Test ESP32 ↔ Pi MQTT comms (comms.py)"
    echo "  ./run.sh frontend   # Start frontend with npm"
    ;;
esac
