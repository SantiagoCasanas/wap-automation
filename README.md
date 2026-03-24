# Canva to WhatsApp Status Automation

Automatically downloads every page of a Canva design as JPG images via the **Canva Connect API** and publishes each one as a WhatsApp status. Designed to run daily at **12:00 AM Colombian time** — it re-downloads the design each run, so any changes you make in Canva are reflected automatically.

## How It Works

1. **Canva Download**: Uses the [Canva Connect API](https://www.canva.dev) to export all pages of a design as JPG. No browser automation needed — the API handles the export directly.
2. **WhatsApp Posting**: Opens WhatsApp Web via Playwright with a persistent session, navigates to the Status tab, and uploads each image as a status update.
3. **Scheduling**: A cron job runs the script daily at 12:00 AM Colombian time (05:00 UTC).

## Prerequisites

- **Python 3.11+**
- **pip** (Python package manager)
- A **Canva account** with a [Canva Developer](https://www.canva.dev) integration
- A **WhatsApp account** linked to WhatsApp Web
- A **Linux server or machine** that stays on (for scheduled runs)

## Project Structure

```
wap-automation/
├── main.py                # Entry point and orchestrator
├── canva_downloader.py    # Downloads Canva design pages via the Connect API
├── wap_status_poster.py   # Posts images to WhatsApp status via WhatsApp Web
├── setup.sh               # Installation script
├── requirements.txt       # Python dependencies
├── .env.example           # Configuration template
├── .env                   # Your configuration (not tracked in git)
├── canva_tokens.json      # Canva API tokens (not tracked in git)
├── browser_data/          # WhatsApp Web session (not tracked in git)
└── downloads/             # Temporary image storage (not tracked in git)
```

## Setup Instructions

### Step 1: Clone the repository

```bash
git clone <repository-url>
cd wap-automation
```

### Step 2: Run the setup script

```bash
chmod +x setup.sh
./setup.sh
```

This installs:
- Python dependencies (`requests`, `playwright`, `python-dotenv`, `Pillow`)
- Chromium browser for Playwright (used for WhatsApp Web)
- Creates `.env` from the template

### Step 3: Create a Canva API integration

1. Go to **https://www.canva.dev** and sign in with your Canva account
2. Click **"Create an integration"**
3. Set the **redirect URL** to: `http://127.0.0.1:8420/oauth/callback`
4. Enable the following scopes:
   - `design:content:read`
   - `design:meta:read`
5. Copy your **Client ID** and **Client Secret**

### Step 4: Configure your `.env` file

Edit the `.env` file:

```bash
nano .env
```

Set your values:

```
CANVA_URL=https://www.canva.com/design/YOUR_DESIGN_ID/view
CANVA_CLIENT_ID=your_client_id_here
CANVA_CLIENT_SECRET=your_client_secret_here
DELAY_BETWEEN_STATUSES=5
HEADLESS=true
```

### Step 5: Authorize the Canva API (one-time)

```bash
python main.py --setup-canva
```

**What happens:**
1. A URL is printed in the terminal (and opens in your browser automatically if possible)
2. Sign in to Canva and authorize the integration
3. You're redirected back to `localhost` where the script captures the authorization code
4. Tokens are saved to `canva_tokens.json` — they refresh automatically on future runs

### Step 6: First-time WhatsApp Web login

```bash
python main.py --setup-wap
```

**What happens:**
1. A Chromium browser window opens with WhatsApp Web
2. Link your device (WhatsApp > Linked Devices > Link a Device > scan the QR code)
3. Wait until your chats appear
4. The session is saved to `browser_data/`
5. The browser closes automatically

**After this, all future runs are fully automatic — no QR code needed.**

### Step 7: Test the automation

Test just the Canva download:

```bash
python main.py --download-only
```

This exports all pages via the API and saves them to `downloads/extracted/`.

Run a full cycle (download + post to WhatsApp):

```bash
python main.py
```

### Step 8: Set up the daily cron job

The automation runs every day at **12:00 AM Colombian time** (UTC-5 = 05:00 UTC).

Open the crontab editor:

```bash
crontab -e
```

Add this line (adjust the path to your installation):

```cron
0 5 * * * cd /path/to/wap-automation && /usr/bin/python3 main.py >> /path/to/wap-automation/cron.log 2>&1
```

**Explanation:**
- `0 5 * * *` = Every day at 05:00 UTC = 12:00 AM Colombia (UTC-5)
- `cd /path/to/wap-automation` = Change to project directory
- `/usr/bin/python3 main.py` = Run the automation
- `>> cron.log 2>&1` = Append output to log file

Verify the cron job is saved:

```bash
crontab -l
```

## Usage

| Command | Description |
|---|---|
| `python main.py` | Run full automation (download + post) |
| `python main.py --setup-canva` | Authorize Canva API (one-time OAuth flow) |
| `python main.py --setup-wap` | First-time WhatsApp Web login |
| `python main.py --url <URL>` | Override the Canva URL from .env |
| `python main.py --download-only` | Only download images, skip posting |
| `python main.py --no-headless` | Run WhatsApp browser visually (for debugging) |

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `CANVA_URL` | Canva design URL (view or edit link) | *(required)* |
| `CANVA_CLIENT_ID` | Client ID from your Canva integration | *(required)* |
| `CANVA_CLIENT_SECRET` | Client Secret from your Canva integration | *(required)* |
| `DELAY_BETWEEN_STATUSES` | Seconds between posting each status | `5` |
| `HEADLESS` | Run WhatsApp browser without UI (`true`/`false`) | `true` |

## Important Considerations

### Canva API Tokens

- Tokens are saved in `canva_tokens.json` and refresh automatically (access tokens last 4 hours).
- If tokens become invalid, run `python main.py --setup-canva` to re-authorize.
- **Do not** commit `canva_tokens.json` — it contains your API credentials.

### WhatsApp Web Session

- The session is saved in `browser_data/` and persists between runs.
- If WhatsApp Web logs you out (e.g., you unlink the device from your phone), run `python main.py --setup-wap` again.
- **Do not** commit `browser_data/` — it contains your session credentials.

### How the Canva Download Works

The automation uses the Canva Connect API:
1. Extracts the design ID from your URL
2. Creates an export job via `POST /v1/exports` (format: JPG)
3. Polls the job status until complete
4. Downloads the exported file(s) — ZIP for multi-page designs, single JPG otherwise
5. Extracts images to `downloads/extracted/`

### Rate Limiting

- **Canva API**: 20 export requests per minute, 75 per 5 minutes per user. More than enough for daily runs.
- **WhatsApp**: A configurable delay (`DELAY_BETWEEN_STATUSES`) is added between each status post. Default is 5 seconds.

### Logs

- Console output goes to stdout.
- A persistent log file is written to `automation.log` in the project directory.
- Cron output is captured in `cron.log` (if configured as shown above).

## Troubleshooting

### "No Canva tokens found"
- Run `python main.py --setup-canva` to authorize the Canva API.

### "Canva API returned 401 Unauthorized"
- Your tokens may have expired. Run `python main.py --setup-canva` to re-authorize.

### "Could not extract design ID from URL"
- Make sure the URL follows the pattern: `https://www.canva.com/design/XXXXXXXXX/view`

### "Export job failed"
- Verify the design exists and your Canva account has access to it.
- Check that your integration has the required scopes (`design:content:read`, `design:meta:read`).

### "WhatsApp Web did not load in time"
- Your WhatsApp session may have expired. Run `python main.py --setup-wap` to log in again.

### "No images downloaded"
- Check `automation.log` for detailed error messages.
- Verify the Canva URL is correct and accessible from your account.

### Cron job not running
- Check `cron.log` for error messages.
- Ensure the paths in the crontab are absolute.
- Verify cron service is running: `sudo systemctl status cron`

### Session issues after server restart
- `canva_tokens.json` and `browser_data/` should survive restarts.
- If they don't, run `--setup-canva` and `--setup-wap` to re-authenticate.
