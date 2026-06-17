#!/bin/bash

# reMarkableSync Launch Script for macOS
# Automatically removes Gatekeeper quarantine flag and launches the application

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Remove quarantine flag from the executable (handles Gatekeeper)
echo "Preparing reMarkableSync..."
xattr -cr "$SCRIPT_DIR/reMarkableSync" 2>/dev/null

# Make sure the executable has execute permissions
chmod +x "$SCRIPT_DIR/reMarkableSync" 2>/dev/null

# Launch the application with any arguments passed to this script
"$SCRIPT_DIR/reMarkableSync" "$@"
