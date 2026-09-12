#!/bin/bash
# Create or edit .env file
set -e

# Clean up temporary received directory on startup
# rm -rf received
uv run dicom-py-mock-server

# Start the mock server
exec uv run dicom-py-mock-server "$@"

