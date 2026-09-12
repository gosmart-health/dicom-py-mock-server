#!/bin/bash
set -e

# Default settings
REPO="${1:-imanabu/dicom-py-mock-server}"
VERSION="${2:-0.3.3}"

echo "=================================================="
echo "Pushing DICOM Mock Server to Docker Registry"
echo "Target Repository: ${REPO}"
echo "Version Tag:       ${VERSION}"
echo "Latest Tag:        latest"
echo "=================================================="

# Ensure local image exists or build it
if ! docker image inspect dicom-py-mock-server:latest >/dev/null 2>&1; then
    echo "Local image dicom-py-mock-server:latest not found. Building..."
    docker build -t dicom-py-mock-server:latest .
fi

# Tag version and latest
docker tag dicom-py-mock-server:latest "${REPO}:${VERSION}"
docker tag dicom-py-mock-server:latest "${REPO}:latest"

# Push to registry
echo "Pushing ${REPO}:${VERSION}..."
docker push "${REPO}:${VERSION}"

echo "Pushing ${REPO}:latest..."
docker push "${REPO}:latest"

echo "=================================================="
echo "Successfully pushed ${REPO}:${VERSION} and ${REPO}:latest!"
echo "=================================================="

