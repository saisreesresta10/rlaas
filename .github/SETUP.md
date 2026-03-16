# GitHub Actions Setup Guide

This explains how to configure the CI/CD pipeline for RLaaS.

## How the Pipeline Works

```
Push to any branch
    └─> CI runs (tests + lint)

Push to main branch
    └─> CI runs
    └─> CD builds Docker image → pushes to GitHub Container Registry
    └─> Auto-deploys to Staging
    └─> Manual trigger → deploys to Production
```

## Step 1: Create GitHub Environments

Go to your repo → Settings → Environments → New environment

Create two environments:
- `staging`
- `production` (add "Required reviewers" for safety)

## Step 2: Add GitHub Secrets

Go to Settings → Secrets and variables → Actions

### For Staging

| Secret Name | Value |
|-------------|-------|
| `STAGING_HOST` | IP address of your staging server |
| `STAGING_USER` | SSH username (e.g. `ubuntu`) |
| `STAGING_SSH_KEY` | Private SSH key content (the full `-----BEGIN...` block) |

### For Production

| Secret Name | Value |
|-------------|-------|
| `PROD_HOST` | IP address of your production server |
| `PROD_USER` | SSH username |
| `PROD_SSH_KEY` | Private SSH key content |

## Step 3: Prepare Your Servers

Run the setup script on each server:

```bash
# SSH into your server
ssh ubuntu@your-server-ip

# Download and run setup script
curl -sSL https://raw.githubusercontent.com/YOUR_ORG/rlaas/main/scripts/server-setup.sh | bash

# Copy your production config
scp docker-compose.prod.yml ubuntu@your-server-ip:/opt/rlaas/
scp .env.production ubuntu@your-server-ip:/opt/rlaas/.env
```

## Step 4: Push to Main

```bash
git add .
git commit -m "feat: add CI/CD pipeline"
git push origin main
```

This triggers the full pipeline automatically.

## Triggering a Production Deploy

1. Go to your repo on GitHub
2. Click Actions tab
3. Select "CD - Build & Deploy"
4. Click "Run workflow"
5. Select `production` from the dropdown
6. Click "Run workflow"

A reviewer must approve before it deploys (if you set required reviewers).

## Monitoring Pipeline Runs

- Go to Actions tab in your GitHub repo
- Green checkmark = passed
- Red X = failed, click to see logs

## What Each Workflow Does

### `ci.yml` — Runs on every push
- Spins up a real Redis container
- Runs all unit and integration tests
- Checks code formatting

### `cd.yml` — Runs on push to main
- Builds Docker image
- Pushes to GitHub Container Registry (free)
- SSH into server and pulls + restarts the container
- Verifies health check passes

### `load-test.yml` — Runs weekly or manually
- Starts the full service
- Runs 100 concurrent users for 60 seconds
- Validates p99 < 10ms SLA
- Uploads results as downloadable artifact
