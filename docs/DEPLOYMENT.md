# AtlasClaw-Core Deployment Guide

> **DEPRECATED**: This document has been merged into [Development Specification](./development-spec.md) §11 (Deployment & Operations).
> Please refer to the canonical development spec for up-to-date deployment instructions.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the Application](#running-the-application)
5. [Docker Deployment](#docker-deployment)
6. [Production Deployment](#production-deployment)
7. [Environment Variables](#environment-variables)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 10 GB | 50+ GB SSD |
| Python | 3.10+ | 3.11+ |

### Required Software

- Python 3.10 or higher
- pip or uv (Python package manager)
- Git

### Optional Software

- Docker and Docker Compose
- Nginx or Apache (for reverse proxy)
- Redis (for caching)

---

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd AtlasClaw-Core
```

### 2. Create Virtual Environment

```bash
# Using venv
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on Linux/macOS
source venv/bin/activate
```

### 3. Install Dependencies

```bash
# Using pip
pip install -r requirements.txt

# Using uv (faster)
uv pip install -r requirements.txt
```

### 4. Verify Installation

```bash
python -c "import app.atlasclaw; print('Installation successful')"
```

---

## Configuration

### 1. Create Configuration File

Copy the example configuration:

```bash
cp atlasclaw.json.example atlasclaw.json
```

### 2. Configure LLM Provider

Edit `atlasclaw.json`:

```json
{
  "model": {
    "primary": "deepseek/deepseek-chat",
    "fallbacks": [],
    "temperature": 0.7,
    "providers": {
      "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key": "${DEEPSEEK_API_KEY}",
        "api_type": "openai"
      }
    }
  }
}
```

### 3. Configure Service Providers (Optional)

Add Jira, ServiceNow, or other providers:

```json
{
  "service_providers": {
    "jira": {
      "dev": {
        "base_url": "https://jira.company.com",
        "username": "${JIRA_USERNAME}",
        "password": "${JIRA_PASSWORD}",
        "api_version": "2",
        "default_project": "PROJ"
      }
    }
  }
}
```

### 4. Environment Variables

Create `.env` file:

```bash
# LLM API Keys
DEEPSEEK_API_KEY=your-api-key-here

# Jira Credentials
JIRA_USERNAME=your-username
JIRA_PASSWORD=your-password

# Optional: Custom config path
ATLASCLAW_CONFIG=/path/to/atlasclaw.json
```

---

## Running the Application

### Development Mode

```bash
# Set environment variables (Windows PowerShell)
$env:NO_PROXY="*"
$env:ATLASCLAW_CONFIG="atlasclaw.json"

# Run development server
uvicorn app.atlasclaw.main:app --host 0.0.0.0 --port 8000 --reload
```

### Production Mode

```bash
# Set environment variables
export NO_PROXY="*"
export ATLASCLAW_CONFIG="atlasclaw.json"

# Run with multiple workers
uvicorn app.atlasclaw.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Using Gunicorn

```bash
gunicorn app.atlasclaw.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Verify Deployment

```bash
# Health check
curl http://localhost:8000/api/health

# Expected response:
# {"status": "healthy"}
```

---

## Docker Deployment

### 1. Build Docker Image

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "app.atlasclaw.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build:

```bash
docker build -t atlasclaw-core .
```

### 2. Run Container

```bash
docker run -d \
  --name atlasclaw \
  -p 8000:8000 \
  -v $(pwd)/atlasclaw.json:/app/atlasclaw.json \
  -e DEEPSEEK_API_KEY=your-api-key \
  atlasclaw-core
```

### 3. Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  atlasclaw:
    build: .
    container_name: atlasclaw-core
    ports:
      - "8000:8000"
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - JIRA_USERNAME=${JIRA_USERNAME}
      - JIRA_PASSWORD=${JIRA_PASSWORD}
    volumes:
      - ./atlasclaw.json:/app/atlasclaw.json
      - ./data:/app/data
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - atlasclaw
    restart: unless-stopped
```

Run:

```bash
docker-compose up -d
```

---

## Production Deployment

### 1. Nginx Reverse Proxy

```nginx
# nginx.conf
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    location /api/agent/runs/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
    }
}
```

### 2. SSL/TLS with Let's Encrypt

```bash
# Install certbot
sudo apt-get install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com
```

### 3. Systemd Service

```ini
# /etc/systemd/system/atlasclaw.service
[Unit]
Description=AtlasClaw Core Service
After=network.target

[Service]
Type=simple
User=atlasclaw
Group=atlasclaw
WorkingDirectory=/opt/atlasclaw/AtlasClaw-Core
Environment="PATH=/opt/atlasclaw/venv/bin"
Environment="NO_PROXY=*"
Environment="ATLASCLAW_CONFIG=/opt/atlasclaw/AtlasClaw-Core/atlasclaw.json"
ExecStart=/opt/atlasclaw/venv/bin/uvicorn app.atlasclaw.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable atlasclaw
sudo systemctl start atlasclaw
sudo systemctl status atlasclaw
```

### 4. Log Rotation

```bash
# /etc/logrotate.d/atlasclaw
/opt/atlasclaw/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 atlasclaw atlasclaw
    sharedscripts
    postrotate
        systemctl reload atlasclaw
    endscript
}
```

---

## Environment Variables

### Core Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ATLASCLAW_CONFIG` | Path to configuration file | `atlasclaw.json` |
| `NO_PROXY` | Proxy bypass | `*` |
| `LOG_LEVEL` | Logging level | `INFO` |

### LLM Provider Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPSEEK_API_KEY` | DeepSeek API key | Yes |
| `ANTHROPIC_API_KEY` | Anthropic API key | Optional |
| `OPENAI_API_KEY` | OpenAI API key | Optional |

### Service Provider Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `JIRA_USERNAME` | Jira username | Optional |
| `JIRA_PASSWORD` | Jira password | Optional |
| `SERVICENOW_INSTANCE` | ServiceNow instance | Optional |
| `SERVICENOW_USERNAME` | ServiceNow username | Optional |
| `SERVICENOW_PASSWORD` | ServiceNow password | Optional |

### Security Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Application secret key | Random |
| `ALLOWED_HOSTS` | Allowed hostnames | `*` |
| `CORS_ORIGINS` | CORS allowed origins | `*` |

---

## Troubleshooting

### Common Issues

#### 1. Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill process
kill -9 <PID>

# Or use different port
uvicorn app.atlasclaw.main:app --host 0.0.0.0 --port 8080
```

#### 2. Permission Denied

```bash
# Fix permissions
sudo chown -R $USER:$USER /opt/atlasclaw
chmod -R 755 /opt/atlasclaw
```

#### 3. Module Not Found

```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

#### 4. Configuration Not Loading

```bash
# Verify config path
echo $ATLASCLAW_CONFIG

# Check config syntax
python -c "import json; json.load(open('atlasclaw.json'))"
```

#### 5. LLM API Errors

```bash
# Test API connectivity
curl -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  https://api.deepseek.com/v1/models
```

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
uvicorn app.atlasclaw.main:app --host 0.0.0.0 --port 8000 --reload
```

### Health Check Script

```bash
#!/bin/bash
# health-check.sh

HEALTH_URL="http://localhost:8000/api/health"
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL)

if [ $RESPONSE -eq 200 ]; then
    echo "✓ AtlasClaw is healthy"
    exit 0
else
    echo "✗ AtlasClaw is unhealthy (HTTP $RESPONSE)"
    exit 1
fi
```

### Backup and Restore

```bash
# Backup data
tar -czf atlasclaw-backup-$(date +%Y%m%d).tar.gz \
  ~/.atlasclaw \
  atlasclaw.json

# Restore data
tar -xzf atlasclaw-backup-20240310.tar.gz -C /
```

---

## Monitoring

### Prometheus Metrics (Optional)

Add to `atlasclaw.json`:

```json
{
  "monitoring": {
    "enabled": true,
    "metrics_port": 9090
  }
}
```

### Health Check Endpoint

```bash
# Basic health check
curl http://localhost:8000/api/health

# Detailed health check
curl http://localhost:8000/api/health?detailed=true
```

---

## Security Best Practices

1. **Never commit secrets** to version control
2. **Use environment variables** for sensitive data
3. **Enable HTTPS** in production
4. **Set up firewall rules** to restrict access
5. **Regularly update dependencies**
6. **Use strong authentication** for admin access
7. **Monitor logs** for suspicious activity

---

## Next Steps

- [Configure Skills](../README.md#skills)
- [Set up Authentication](../README.md#authentication)
- [Customize UI](../app/frontend/README.md)
- [Add Providers](../openspec/AGENTS.md)
