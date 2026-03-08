#!/bin/bash

# RLaaS Deployment Script
# This script automates the deployment process for RLaaS

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT=${1:-development}
COMPOSE_FILE="docker-compose.yml"

if [ "$ENVIRONMENT" = "production" ]; then
    COMPOSE_FILE="docker-compose.prod.yml"
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}RLaaS Deployment Script${NC}"
echo -e "${GREEN}Environment: $ENVIRONMENT${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Function to check if Docker is installed
check_docker() {
    echo -e "${YELLOW}Checking Docker installation...${NC}"
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker is not installed${NC}"
        echo "Please install Docker from https://docs.docker.com/get-docker/"
        exit 1
    fi
    echo -e "${GREEN}✓ Docker is installed${NC}"
}

# Function to check if Docker Compose is installed
check_docker_compose() {
    echo -e "${YELLOW}Checking Docker Compose installation...${NC}"
    if ! command -v docker-compose &> /dev/null; then
        echo -e "${RED}Error: Docker Compose is not installed${NC}"
        echo "Please install Docker Compose from https://docs.docker.com/compose/install/"
        exit 1
    fi
    echo -e "${GREEN}✓ Docker Compose is installed${NC}"
}

# Function to check if ports are available
check_ports() {
    echo -e "${YELLOW}Checking if required ports are available...${NC}"
    
    if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo -e "${RED}Error: Port 8000 is already in use${NC}"
        echo "Please stop the service using port 8000 or change RLAAS_SERVER_PORT"
        exit 1
    fi
    
    if lsof -Pi :6379 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo -e "${YELLOW}Warning: Port 6379 is already in use${NC}"
        echo "If you have Redis running locally, this is expected"
    fi
    
    echo -e "${GREEN}✓ Ports are available${NC}"
}

# Function to build Docker images
build_images() {
    echo -e "${YELLOW}Building Docker images...${NC}"
    docker-compose -f $COMPOSE_FILE build
    echo -e "${GREEN}✓ Docker images built successfully${NC}"
}

# Function to start services
start_services() {
    echo -e "${YELLOW}Starting services...${NC}"
    docker-compose -f $COMPOSE_FILE up -d
    echo -e "${GREEN}✓ Services started${NC}"
}

# Function to wait for services to be healthy
wait_for_health() {
    echo -e "${YELLOW}Waiting for services to be healthy...${NC}"
    
    MAX_ATTEMPTS=30
    ATTEMPT=0
    
    while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo -e "${GREEN}✓ Services are healthy${NC}"
            return 0
        fi
        
        ATTEMPT=$((ATTEMPT + 1))
        echo -n "."
        sleep 2
    done
    
    echo -e "${RED}Error: Services did not become healthy in time${NC}"
    echo "Check logs with: docker-compose -f $COMPOSE_FILE logs"
    exit 1
}

# Function to display service information
display_info() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Deployment Successful!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Service URLs:"
    echo "  - API: http://localhost:8000"
    echo "  - Health Check: http://localhost:8000/health"
    echo "  - Metrics: http://localhost:8000/metrics"
    echo "  - API Docs: http://localhost:8000/docs"
    echo ""
    echo "Useful Commands:"
    echo "  - View logs: docker-compose -f $COMPOSE_FILE logs -f"
    echo "  - Stop services: docker-compose -f $COMPOSE_FILE down"
    echo "  - Restart: docker-compose -f $COMPOSE_FILE restart"
    echo ""
    echo "Test the service:"
    echo '  curl -X POST http://localhost:8000/v1/rate-limit/check \'
    echo '    -H "Content-Type: application/json" \'
    echo '    -d '"'"'{"client_id":"test","endpoint":"/api/test","http_method":"GET"}'"'"
    echo ""
}

# Main deployment flow
main() {
    check_docker
    check_docker_compose
    
    # Skip port check on macOS/Windows where lsof might not work
    if command -v lsof &> /dev/null; then
        check_ports
    fi
    
    build_images
    start_services
    wait_for_health
    display_info
}

# Run main function
main
