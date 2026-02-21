#!/bin/bash
# Convenience script to run the trade copier

set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
    echo "Loading environment from .env..."
    export $(cat .env | grep -v '^#' | xargs)
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Run the copier
echo "Starting IBKR Trade Copier..."
python -m copier.main
