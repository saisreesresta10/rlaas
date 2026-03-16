#!/bin/bash
# RLaaS Server Setup Script
# Run this ONCE on a fresh Ubuntu 22.04 server to prepare it for deployment.
#
# Usage:
#   ssh user@your-server
#   curl -sSL https://raw.githubusercontent.com/YOUR_ORG/rlaas/main/scripts/server-setup.sh | bash

set -e

echo "========================================"
echo "  RLaaS Server Setup"
echo "========================================"

# Update system
apt-get update -y
apt-get upgrade -y

# Install Docker
echo "Installing Docker..."
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER

# Install Docker Compose
echo "Installing Docker Compose..."
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create app directory
mkdir -p /opt/rlaas
cd /opt/rlaas

# Create systemd service so RLaaS auto-starts on reboot
cat > /etc/systemd/system/rlaas.service << 'EOF'
[Unit]
Description=RLaaS Rate Limiter Service
Requires=docker.service
After=docker.service

[Service]
WorkingDirectory=/opt/rlaas
ExecStart=/usr/local/bin/docker-compose -f docker-compose.prod.yml up
ExecStop=/usr/local/bin/docker-compose -f docker-compose.prod.yml down
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable rlaas

# Basic firewall rules
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw allow 8000/tcp  # RLaaS API
ufw --force enable

echo ""
echo "========================================"
echo "  Server setup complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Copy your docker-compose.prod.yml to /opt/rlaas/"
echo "  2. Copy your .env file to /opt/rlaas/"
echo "  3. Run: systemctl start rlaas"
echo "  4. Check: curl http://localhost:8000/health"
echo ""
