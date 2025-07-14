#!/bin/bash

set -e

VENV_DIR="./venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

echo "Installing dependencies..."
$PIP install --upgrade pip 
$PIP install -r app/requirements.txt

if [ "$1" = "server" ]; then
  echo "Starting WebSocket server..."
  $PYTHON app/server/server.py
else
  echo "✅ Environment set up. To start the server, run:"
  echo "./run.sh server"
fi
