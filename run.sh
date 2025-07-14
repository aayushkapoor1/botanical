#!/bin/bash

# Exit on any error
set -e

# Define virtual environment directory relative to project root
VENV_DIR="./venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

# Install dependencies using venv
echo "Installing dependencies..."
$PIP install --upgrade pip  # optional
$PIP install -r app/requirements.txt

# Run the backend server
echo "Starting server..."
$PYTHON app/server/server.py
