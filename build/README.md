# AtlasClaw Deployment Guide

This guide describes how to deploy AtlasClaw in your own environment using pre-built Docker images.

## Prerequisites

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 20 GB SSD | 100+ GB SSD |
| OS | Linux (CentOS 7+, Ubuntu 18.04+, or equivalent) | Latest LTS |

### Required Software

- **Docker** 20.10 or higher
- **Docker Compose** 2.0 or higher

### Install Docker

**CentOS/RHEL:**
```bash
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl start docker
sudo systemctl enable docker
```

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

**Verify Installation:**
```bash
docker --version
docker compose version
```

---

## Quick Start

### 1. Create Deployment Directory

```bash
mkdir -p /opt/atlasclaw/{config,data,logs}
cd /opt/atlasclaw
```

**Directory Structure:**

```
/opt/atlasclaw/
├── docker-compose.yml      # Docker Compose orchestration file
├── config/
│   └── atlasclaw.json      # Configuration file (mounted to /app/atlasclaw.json in container)
├── data/                   # Database and runtime data (persisted volume)
└── logs/                   # Application logs (persisted volume)
```

The `config/atlasclaw.json` is mounted to `/app/atlasclaw.json` inside the container where the application reads its configuration.

### 2. Download Compose File

Download the appropriate `docker-compose.yml` for your edition:

**OpenSource Edition:**
```bash
curl -o docker-compose.yml https://your-registry.com/atlasclaw/docker-compose-opensource.yml
```

**Enterprise Edition:**
```bash
curl -o docker-compose.yml https://your-registry.com/atlasclaw/docker-compose-enterprise.yml
```

### 3. Create Configuration

Create `/opt/atlasclaw/config/atlasclaw.json`:

**OpenSource:**
```json
{
  "workspace": {
    "path": "./data"
  },
  "database": {
    "type": "sqlite",
    "sqlite": {
      "path": "./data/atlasclaw.db"
    }
  },
  "model": {
    "primary": "deepseek-main",
    "fallbacks": [],
    "temperature": 0.2,
    "tokens": [
      {
        "id": "deepseek-main",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "YOUR_API_KEY_HERE",
        "api_type": "openai"
      }
    ]
  },
  "auth": {
    "provider": "api_key",
    "api_key": {
      "keys": {
        "sk-your-secret-key": {
          "user_id": "admin",
          "roles": ["admin"]
        }
      }
    }
  }
}
```

**Enterprise:**
```json
{
  "workspace": {
    "path": "./data"
  },
  "database": {
    "type": "mysql",
    "mysql": {
      "host": "mysql",
      "port": 3306,
      "database": "atlasclaw",
      "user": "atlasclaw",
      "password": "your-mysql-password",
      "charset": "utf8mb4"
    }
  },
  "model": {
    "primary": "deepseek-main",
    "fallbacks": [],
    "temperature": 0.2,
    "tokens": [
      {
        "id": "deepseek-main",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "YOUR_API_KEY_HERE",
        "api_type": "openai"
      }
    ]
  },
  "auth": {
    "provider": "oidc",
    "oidc": {
      "issuer": "https://auth.your-company.com",
      "client_id": "atlasclaw-client",
      "client_secret": "your-client-secret",
      "redirect_uri": "https://atlasclaw.your-company.com/api/auth/callback"
    }
  }
}
```

Set proper permissions:
```bash
chmod 600 /opt/atlasclaw/config/atlasclaw.json
```

### 4. Start AtlasClaw

```bash
cd /opt/atlasclaw
docker compose up -d
```

### 5. Run Database Migrations (Enterprise Only)

```bash
docker compose exec atlasclaw alembic upgrade head
```

### 6. Verify Deployment

```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{"status": "healthy", "timestamp": "2026-03-23T10:00:00+00:00"}
```

Access the web UI at: `http://your-server-ip:8000`

---

## Available Images

### OpenSource Edition

- **Image**: `your-registry.com/atlasclaw:latest`
- **Features**: SQLite database, single container
- **Best for**: Small teams, evaluation, development

### Enterprise Edition

- **Image**: `your-registry.com/atlasclaw-official:latest`
- **Features**: MySQL support, multi-container, high availability
- **Best for**: Production, large organizations

### Pull Images Manually

```bash
# OpenSource
docker pull your-registry.com/atlasclaw:latest

# Enterprise
docker pull your-registry.com/atlasclaw-official:latest
```

---

## Custom Providers, Skills & Channels

AtlasClaw supports loading custom providers, skills, and channels from external directories. This allows you to extend AtlasClaw functionality without modifying the core image.

### Directory Structure

Create the following directory structure on your host:

```bash
mkdir -p /opt/atlasclaw/extensions/{providers,skills,channels}
```

**Directory Layout:**
```
/opt/atlasclaw/
├── workspace/              # Configuration, logs, user data
├── data/                   # Database files
└── extensions/
    ├── providers/          # Custom providers (e.g., cloud, monitoring)
    ├── skills/             # Custom skills (e.g., deployment, automation)
    └── channels/           # Custom channels (e.g., wecom, feishu)
```

### Loading Custom Providers

Providers extend AtlasClaw with new capabilities for cloud services, monitoring systems, etc.

#### 1. Download Providers

Download providers from the official repository:

```bash
cd /opt/atlasclaw/extensions

# Clone the providers repository
git clone https://github.com/CloudChef/atlasclaw-providers.git providers-src

# Copy specific provider to extensions directory
cp -r providers-src/providers/aws ./providers/
cp -r providers-src/providers/kubernetes ./providers/

# Or copy all providers
cp -r providers-src/providers/* ./providers/

# Remove source directory (optional)
rm -rf providers-src
```

#### 2. Provider Structure

Each provider should follow this structure:
```
/opt/atlasclaw/extensions/providers/
└── aws/
    ├── __init__.py
    ├── provider.py          # Main provider implementation
    ├── requirements.txt     # Dependencies
    ├── config/
    │   └── config.json      # Provider configuration
    └── README.md
```

#### 3. Install Dependencies

Install provider dependencies (optional):

```bash
docker compose exec atlasclaw pip install -r /app/extensions/providers/aws/requirements.txt
```

#### 4. Configure Provider

Add provider configuration to `/opt/atlasclaw/workspace/atlasclaw.json`:

```json
{
  "service_providers": {
    "aws-prod": {
      "type": "aws",
      "config": {
        "region": "cn-north-1",
        "access_key": "YOUR_ACCESS_KEY",
        "secret_key": "YOUR_SECRET_KEY"
      }
    }
  }
}
```

### Loading Custom Skills

Skills enable AtlasClaw to perform specific tasks and workflows.

#### 1. Download Skills

Download skills from the official repository:

```bash
cd /opt/atlasclaw/extensions

# Clone the skills repository
git clone https://github.com/CloudChef/atlasclaw-providers.git skills-src

# Copy specific skill to extensions directory
cp -r skills-src/skills/deployment ./skills/
cp -r skills-src/skills/monitoring ./skills/

# Or copy all skills
cp -r skills-src/skills/* ./skills/

# Remove source directory (optional)
rm -rf skills-src
```

#### 2. Skill Structure

Each skill should follow one of these structures:

**Markdown Skill:**
```
/opt/atlasclaw/extensions/skills/
└── deployment/
    ├── SKILL.md             # Skill definition (name, description, tools)
    ├── requirements.txt     # Dependencies (optional)
    └── scripts/
        └── deploy.sh        # Helper scripts (optional)
```

**Executable Skill:**
```
/opt/atlasclaw/extensions/skills/
└── monitoring/
    ├── __init__.py
    ├── skill.py             # Python skill implementation
    ├── requirements.txt     # Dependencies
    └── config.json          # Default configuration
```

**Example SKILL.md:**
```yaml
---
name: deployment
version: "1.0.0"
description: Deploy applications to various platforms
tools:
  - name: deploy_k8s
    description: Deploy to Kubernetes cluster
    parameters:
      namespace: Target namespace
      image: Container image
---

# Deployment Skill

This skill enables AtlasClaw to deploy applications...

## Usage

```
@atlasclaw deploy to kubernetes namespace:default image:myapp:v1.0
```
```

#### 3. Install Skill Dependencies

```bash
# For Python-based skills
docker compose exec atlasclaw pip install -r /app/extensions/skills/monitoring/requirements.txt

# Or install all skill dependencies at once
for req in /app/extensions/skills/*/requirements.txt; do
  docker compose exec atlasclaw pip install -r "$req"
done
```

#### 4. Enable Skills in Configuration

Skills in `/opt/atlasclaw/extensions/skills/` are automatically discovered. No additional configuration needed.

To restrict available skills, edit `/opt/atlasclaw/workspace/atlasclaw.json`:

```json
{
  "security": {
    "allowed_tools": ["deployment.deploy_k8s", "monitoring.check_health"]
  }
}
```

### Loading Custom Channels

Channels enable AtlasClaw to communicate through different messaging platforms.

#### 1. Download Channels

```bash
cd /opt/atlasclaw/extensions

git clone https://github.com/CloudChef/atlasclaw-providers.git channels-src

# Copy specific channel
cp -r channels-src/channels/slack ./channels/

# Or copy all channels
cp -r channels-src/channels/* ./channels/

rm -rf channels-src
```

#### 2. Channel Structure

```
/opt/atlasclaw/extensions/channels/
└── slack/
    ├── __init__.py
    ├── channel.py           # Channel implementation
    ├── requirements.txt     # Dependencies
    └── config/
        └── config.json      # Channel configuration
```

#### 3. Configure Channel

Add channel to `/opt/atlasclaw/workspace/atlasclaw.json`:

```json
{
  "channels": {
    "slack-bot": {
      "type": "slack",
      "config": {
        "token": "xoxb-your-bot-token",
        "signing_secret": "your-signing-secret"
      }
    }
  }
}
```

### Reload Extensions Without Restart

After adding or modifying extensions, you can reload them:

```bash
# Reload providers
docker compose exec atlasclaw atlasclaw reload providers

# Reload skills
docker compose exec atlasclaw atlasclaw reload skills

# Reload all extensions
docker compose exec atlasclaw atlasclaw reload all
```

Or simply restart the container:

```bash
docker compose restart atlasclaw
```

### Verifying Extensions

Check loaded extensions:

```bash
# List providers
curl http://localhost:8000/api/providers

# List skills
curl http://localhost:8000/api/skills

# List channels
curl http://localhost:8000/api/channels
```

---

## Operations

### View Logs

```bash
docker compose logs -f atlasclaw
```

### Stop Services

```bash
docker compose down
```

### Update to Latest Version

```bash
# Pull latest images
docker compose pull

# Restart services
docker compose up -d

# Enterprise only: run migrations
docker compose exec atlasclaw alembic upgrade head
```

### Backup

**OpenSource:**
```bash
# Backup data directory
tar -czf atlasclaw-backup-$(date +%Y%m%d).tar.gz /opt/atlasclaw/data /opt/atlasclaw/config
```

**Enterprise:**
```bash
# Backup database
docker exec atlasclaw-mysql mysqldump -u root -p atlasclaw > atlasclaw-db-$(date +%Y%m%d).sql

# Backup files
tar -czf atlasclaw-backup-$(date +%Y%m%d).tar.gz /opt/atlasclaw/data /opt/atlasclaw/config
```

---

## Configuration Reference

### LLM Provider

Configure in `atlasclaw.json`:

```json
{
  "model": {
    "primary": "deepseek-main",
    "tokens": [
      {
        "id": "deepseek-main",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "your-api-key"
      }
    ]
  }
}
```

### Authentication

**API Key (OpenSource):**
```json
{
  "auth": {
    "provider": "api_key",
    "api_key": {
      "keys": {
        "sk-your-key": {
          "user_id": "admin",
          "roles": ["admin"]
        }
      }
    }
  }
}
```

**OIDC/OAuth2 (Enterprise):**
```json
{
  "auth": {
    "provider": "oidc",
    "oidc": {
      "issuer": "https://auth.company.com",
      "client_id": "your-client-id",
      "client_secret": "your-client-secret"
    }
  }
}
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose logs atlasclaw

# Verify config syntax
docker run --rm -v /opt/atlasclaw/config/atlasclaw.json:/app/atlasclaw.json:ro your-registry.com/atlasclaw:latest python -c "import json; json.load(open('/app/atlasclaw.json'))"
```

### Database Connection Failed (Enterprise)

```bash
# Check MySQL container
docker compose ps mysql
docker compose logs mysql

# Test MySQL connection
docker compose exec mysql mysql -u atlasclaw -p -e "SELECT 1"
```

### Port Already in Use

Edit `docker-compose.yml` to change the port mapping:

```yaml
ports:
  - "8080:8000"  # Change 8080 to your preferred port
```

### Permission Denied

Ensure proper file permissions:

```bash
chmod 600 /opt/atlasclaw/config/atlasclaw.json
chown -R $(id -u):$(id -g) /opt/atlasclaw/data
```

---

## Support

For technical support, contact your AtlasClaw representative or refer to the full documentation at [docs link].
