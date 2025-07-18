#!/bin/bash

set -e

VENV_DIR="./venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

ensure_venv() {
  if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
  fi

  echo "Installing Python dependencies..."
  $PIP install --upgrade pip
  $PIP install -r app/requirements.txt
}

case "$1" in
  video_server)
    ensure_venv
    echo "🚀 Starting video WebSocket server..."
    $PYTHON video/server.py
    ;;
  video_client)
    ensure_venv
    echo "📺 Running video stream client..."
    $PYTHON video/client.py
    ;;
  server)
    ensure_venv
    echo "Starting WebSocket server..."
    $PYTHON app/server/server.py
    ;;
  client)
    ensure_venv
    echo "Running WebSocket client..."
    $PYTHON app/client/client.py
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
    echo "  ./run.sh server         # Start backend WebSocket server"
    echo "  ./run.sh client         # Run Python WebSocket client"
    echo "  ./run.sh video_server   # Start video WebSocket server"
    echo "  ./run.sh video_client   # Run video stream client"
    echo "  ./run.sh frontend       # Start frontend with npm"
    ;;
esac
