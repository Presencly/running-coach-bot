# Deployment Guide

Deploy your Running Coach Bot to the cloud for always-on operation.

## Option 1: Railway (Recommended for Beginners)

Railway is the simplest option with automatic deploys from GitHub.

### Prerequisites
- GitHub account with this repo pushed
- Railway account (railway.app)

### Steps

1. **Sign in to Railway**
   - Go to https://railway.app
   - Click "Start a Project"
   - Select "Deploy from GitHub repo"

2. **Connect GitHub**
   - Authorize Railway to access your repos
   - Select the `running-coach-bot` repo

3. **Configure Environment**
   - Railway will auto-detect Python and run `pip install -r requirements.txt`
   - Click "Add Variables" and set:
     - `TELEGRAM_BOT_TOKEN`
     - `TELEGRAM_USER_ID`
     - `STRAVA_CLIENT_ID`
     - `STRAVA_CLIENT_SECRET`
     - `ANTHROPIC_API_KEY`
     - `DATABASE_PATH=/app/coach.db`

4. **Add Persistent Storage**
   - In Railway dashboard, go to your service
   - Click "Add Plugin"
   - Select "Disk"
   - Mount at path: `/app`
   - This persists your SQLite database

5. **Deploy**
   - Railway will trigger a build automatically
   - Watch the logs: you should see `🚀 Bot is running`
   - Your bot is now live!

### Managing Your Deployment
- **View logs**: Dashboard → Deployments → select deployment → View Logs
- **Update code**: Push to GitHub → Railway auto-redeploys
- **Restart**: Go to Deployments → click current → Restart

## Option 2: Fly.io (Better for Customization)

Fly.io offers more control, still simple for Python apps.

### Prerequisites
- flyctl CLI installed: `brew install flyctl` (macOS) or `curl https://fly.io/install.sh | sh`
- Fly.io account
- This repo cloned locally

### Steps

1. **Initialize Fly App**
   ```bash
   flyctl launch --name my-running-coach
   ```
   
   It will:
   - Detect Python/Docker
   - Ask a few questions
   - Generate `fly.toml` configuration
   
   Answer as follows:
   - "Tweak these settings?" → No
   - "Create Postgres?" → No (we're using SQLite)

2. **Add Persistent Storage**
   
   Edit `fly.toml` and add:
   ```toml
   [env]
   DATABASE_PATH = "/mnt/data/coach.db"

   [[mounts]]
   source = "data"
   destination = "/mnt/data"
   ```

3. **Create Volume**
   ```bash
   flyctl volumes create data --size 1
   ```

4. **Set Secrets**
   ```bash
   flyctl secrets set TELEGRAM_BOT_TOKEN=xxx
   flyctl secrets set TELEGRAM_USER_ID=xxx
   flyctl secrets set STRAVA_CLIENT_ID=xxx
   flyctl secrets set STRAVA_CLIENT_SECRET=xxx
   flyctl secrets set ANTHROPIC_API_KEY=xxx
   ```

5. **Deploy**
   ```bash
   flyctl deploy
   ```
   
   Watch the logs:
   ```bash
   flyctl logs
   ```

6. **Verify**
   ```bash
   flyctl status
   ```

### Managing Your Deployment
```bash
# View logs
flyctl logs

# Restart app
flyctl restart

# Redeploy after code changes
flyctl deploy

# View secrets
flyctl secrets list

# Update a secret
flyctl secrets set TELEGRAM_BOT_TOKEN=new_value
```

## Option 3: Docker Compose (Local/VPS)

For running on your own server or NAS.

### Prerequisites
- Docker and Docker Compose installed

### Steps

1. **Create docker-compose.yml**
   ```yaml
   version: '3.8'
   
   services:
     running-coach:
       build: .
       restart: unless-stopped
       environment:
         TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
         TELEGRAM_USER_ID: ${TELEGRAM_USER_ID}
         STRAVA_CLIENT_ID: ${STRAVA_CLIENT_ID}
         STRAVA_CLIENT_SECRET: ${STRAVA_CLIENT_SECRET}
         ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
         DATABASE_PATH: /app/data/coach.db
       volumes:
         - ./data:/app/data
       networks:
         - running-coach
   
   networks:
     running-coach:
   ```

2. **Set up .env file**
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

3. **Run**
   ```bash
   docker-compose up -d
   ```

4. **Monitor**
   ```bash
   docker-compose logs -f running-coach
   ```

## Strava OAuth Setup After Deployment

After deploying, you need to complete Strava OAuth **once**:

1. SSH into your deployment (or access via Railway/Fly.io console)
2. Run:
   ```bash
   python strava_auth.py
   ```
3. Follow the prompts (open browser URL, authorize, paste code)
4. Tokens are saved to database

## Database Backups

### Railway
- Your data is on a persistent disk connected to your deployment
- To backup: download the `.db` file from your project artifact storage

### Fly.io
```bash
# Download backup
flyctl ssh console -s
# Inside: cp /mnt/data/coach.db ~/backup.db
# Exit, then download from your local machine
```

### Docker Compose
```bash
# Backup
cp data/coach.db data/coach.db.backup

# Or automated daily backup
# Add to crontab: 0 2 * * * cp /path/to/data/coach.db /path/to/backups/coach.db.$(date +\%Y\%m\%d)
```

## Monitoring & Alerting

### Check Bot is Healthy
Periodically send a test message to verify the bot is responsive.

### View Logs
- **Railway**: Dashboard → Logs
- **Fly.io**: `flyctl logs`
- **Docker**: `docker-compose logs`

### Common Issues

| Issue | Solution |
|-------|----------|
| Bot not responding | Check logs, verify TELEGRAM_BOT_TOKEN is valid |
| "No Strava tokens" | Run strava_auth.py (see above) |
| Out of memory | Reduce conversation history limit in config |
| API rate limited | Wait 15 minutes, bot caches aggressively |

## Cost Estimate (Monthly)

| Service | Tier | Cost |
|---------|------|------|
| Railway | Free → Hobby | $5-20 |
| Fly.io | Free tier | Free (3 shared VMs) |
| Anthropic | Pay-as-you-go | ~$1-5 (daily coaching queries) |
| Telegram | Free | $0 |
| Strava | Free | $0 |
| **Total** | | ~$1-25/month |

Using Fly.io free tier + Anthropic API = ~$1-5/month total.

---

Choose Railway for simplicity, or Fly.io if you want more control. Both work great!
