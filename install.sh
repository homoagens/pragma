#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing dependencies..."
./venv/bin/pip install -r requirements.txt

echo ""
echo "Done. Run ./start.sh to launch Pragma."
