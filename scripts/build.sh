#!/bin/bash

# Build and run RLaaS with Docker Compose

set -e

echo "Building RLaaS Docker containers..."

# Build the application
docker-compose build

echo "Starting RLaaS services..."

# Start services
docker-compose up -d

echo "Waiting for services to be healthy..."

# Wait for services to be ready
sleep 10

# Check health
echo "Checking service health..."
curl -f http://localhost:8000/health || {
    echo "Health check failed. Checking logs..."
    docker-compose logs rlaas
    exit 1
}

echo "RLaaS is running successfully!"
echo "API available at: http://localhost:8000"
echo "Health check: http://localhost:8000/health"
echo "Metrics: http://localhost:8000/metrics"

echo ""
echo "To stop services: docker-compose down"
echo "To view logs: docker-compose logs -f"