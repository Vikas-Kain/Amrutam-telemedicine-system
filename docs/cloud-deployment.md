# Cloud Hosting & Live Instance Guide

This guide explains how to host a live, publicly accessible instance of the Amrutam Telemedicine Backend on free or low-cost cloud platforms so hiring managers and recruiters can test endpoints and review interactive documentation at any time.

---

## Recommended Cloud Hosting Platforms

| Platform | Free Tier / Cost | Setup Time | Cold Starts | Recommended For |
|---|---|---|---|---|
| **[Railway.app](https://railway.app)** | $5 free trial credit / ~$5/mo | **5 minutes** | **None (always warm)** | **Top Pick for Resumes** |
| **[Render.com](https://render.com)** | 100% Free tier (Web + Postgres) | **5 minutes** (via `render.yaml`) | ~30s on first request | 100% Free long-term hosting |
| **[Fly.io](https://fly.io)** | Free allowances | 10 minutes | Minimal | Global edge deployments |

---

## Method 1: Deploy on Railway.app (Recommended — Fastest & No Cold Starts)

Railway is the best platform for resumes because containers remain warm and do not suffer from free-tier sleep latency.

### Step-by-Step Deployment

1. **Push your repository to GitHub:**
   Ensure your latest code is pushed to your GitHub account (e.g., `https://github.com/<your-username>/Amrutam-telemedicine-system`).

2. **Log into Railway:**
   - Go to [railway.app](https://railway.app) and sign in with your GitHub account.

3. **Create a New Project:**
   - Click **"New Project"** -> **"Deploy from GitHub repo"**.
   - Select your `Amrutam-telemedicine-system` repository.

4. **Add PostgreSQL Database:**
   - On your project canvas, click **"New"** -> **"Database"** -> **"Add PostgreSQL"**.
   - Railway will provision a dedicated PostgreSQL 16 database.

5. **Configure Environment Variables:**
   - Click on your application service card -> navigate to **"Variables"** tab -> click **"New Variable"** -> **"Add Reference"**:
     - `DATABASE_URL` -> Select `Postgres.DATABASE_URL` (our codebase automatically normalizes `postgresql://` to `postgresql+asyncpg://`).
   - Add the following additional variables:
     - `APP_ENV`: `production`
     - `DEBUG`: `false`
     - `SECRET_KEY`: Generate a random 32+ character string (e.g. `railway-prod-secret-key-32-chars-long!`)
     - `MFA_ENCRYPTION_KEY`: `MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI=`
     - `RATE_LIMIT_BACKEND`: `memory`
     - `LOG_FORMAT`: `json`
     - `LOG_LEVEL`: `INFO`
     - `METRICS_ENABLED`: `true`

6. **Configure Startup & Migration Command:**
   - In the application service settings, navigate to **"Deploy"** tab.
   - Set **"Custom Start Command"** to:
     ```bash
     alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
     ```
   - *Why:* This guarantees that Alembic applies all schema migrations before starting the Uvicorn web server.

7. **Generate Public Domain:**
   - In service settings, navigate to **"Networking"** -> **"Public Networking"** -> Click **"Generate Domain"**.
   - Railway will assign a public HTTPS URL like:
     `https://amrutam-telemedicine-production.up.railway.app`

---

## Method 2: Deploy on Render.com (100% Free with 1-Click Blueprint)

Render provides free Web Services and free PostgreSQL instances. We have included a pre-configured [`render.yaml`](../render.yaml) blueprint in the repository.

### Step-by-Step Deployment

1. **Log into Render:**
   - Go to [render.com](https://render.com) and sign in with GitHub.

2. **Deploy via Blueprint:**
   - Click **"New +"** in the top navigation -> select **"Blueprint"**.
   - Connect your GitHub repository.
   - Render automatically reads [`render.yaml`](../render.yaml) and provisions:
     1. `amrutam-db`: Free PostgreSQL database.
     2. `amrutam-telemedicine-api`: Docker web service with automatic database wiring.

3. **Apply Database Migrations:**
   - Once deployed, go to the Web Service in Render Dashboard -> click **"Shell"** (or use SSH) and run:
     ```bash
     alembic upgrade head
     ```

4. **Access Your Live URL:**
   - Render assigns a public URL: `https://amrutam-telemedicine-api.onrender.com`.

> **Note on Free Tier Sleep:** Render's free tier spins down after 15 minutes of inactivity. The first request takes ~30-45 seconds to wake up. You can mention this in your README or keep it awake with a free cron monitor like [UptimeRobot](https://uptimerobot.com).

---

## How to Verify Your Live Public Deployment

Once your app is live, test these public endpoints:

1. **Interactive Swagger Documentation:**
   ```
   https://<your-app-domain>/docs
   ```
   *Recruiters can inspect and execute live API calls right in their browser.*

2. **Process Liveness Probe:**
   ```
   https://<your-app-domain>/health/live
   ```
   *Expected Response:* `{"status":"ok"}` (HTTP 200)

3. **Database Readiness Probe:**
   ```
   https://<your-app-domain>/health/ready
   ```
   *Expected Response:* `{"status":"ready","database":"connected"}` (HTTP 200)

4. **Prometheus Metrics Exposition:**
   ```
   https://<your-app-domain>/metrics
   ```
   *Expected Response:* Prometheus text metrics with request counters and duration histograms.

---

## How to Showcase on Your Resume & GitHub

### 1. In Your Resume Header / Project Section
```markdown
Amrutam Telemedicine Backend (Python, FastAPI, PostgreSQL, Docker)
Live Demo: https://amrutam-telemedicine.up.railway.app/docs
GitHub: https://github.com/<your-username>/Amrutam-telemedicine-system
```

### 2. At the Top of Your GitHub `README.md`
Add a live badge and demo link:
```markdown
[![Live Demo](https://img.shields.io/badge/Live%20Demo-Swagger%20UI-success?style=for-the-badge&logo=fastapi)](https://<your-app-domain>/docs)
[![API Status](https://img.shields.io/badge/Health%20Check-Ready-brightgreen?style=for-the-badge)](https://<your-app-domain>/health/ready)
```
