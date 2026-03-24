# Canva to WhatsApp Status Automation

Automatically publishes every page of a public Canva design as WhatsApp status images. Designed to run daily — it re-downloads the design each time, so any changes you make in Canva are reflected automatically.

## How It Works

1. **Canva Download**: Uses Playwright (headless Chromium) to open your public Canva design URL, detect all pages, and screenshot each one as a high-quality PNG.
2. **WhatsApp Posting**: Uses Playwright with a persistent browser session to open WhatsApp Web, navigate to the Status tab, and upload each image as a status update.
3. **Scheduling**: A cron job triggers the script daily at 12:00 AM Colombian time (UTC-5).

## Prerequisites

- **Python 3.11+**
- **pip** (Python package manager)
- A **public Canva design URL** (the "view" link you share with anyone)
- A **WhatsApp account** linked to WhatsApp Web
- A **Linux server or machine** that stays on (for scheduled runs)

## Project Structure

```
wap-automation/
├── main.py                # Entry point and orchestrator
├── canva_downloader.py    # Downloads Canva pages as PNG images
├── wap_status_poster.py   # Posts images to WhatsApp status via WhatsApp Web
├── setup.sh               # Installation script
├── requirements.txt       # Python dependencies
├── .env.example           # Configuration template
├── .env                   # Your configuration (not tracked in git)
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
- Python dependencies (`playwright`, `python-dotenv`, `Pillow`)
- Chromium browser for Playwright
- Creates `.env` from the template

### Step 3: Configure your Canva URL

Edit the `.env` file:

```bash
nano .env
```

Set your public Canva design URL:

```
CANVA_URL=https://www.canva.com/design/YOUR_DESIGN_ID/view
```

### Step 4: First-time WhatsApp Web login

This opens a visible browser window so you can log in to WhatsApp Web:

```bash
python main.py --setup
```

**What happens:**
1. A Chromium browser window opens with WhatsApp Web
2. Scan the QR code with your phone (WhatsApp > Linked Devices > Link a Device)
3. Wait until your chats appear
4. The session is automatically saved to `browser_data/`
5. The browser closes

**After this, all future runs are fully automatic — no QR code needed.**

### Step 5: Test the automation

Run a full cycle to verify everything works:

```bash
python main.py
```

Or test just the download step:

```bash
python main.py --download-only
```

### Step 6: Set up the daily cron job

The automation should run every day at **12:00 AM Colombian time** (Colombia is UTC-5, so this is **05:00 UTC**).

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
| `python main.py --setup` | First-time WhatsApp Web login |
| `python main.py --url <URL>` | Override the Canva URL from .env |
| `python main.py --download-only` | Only download images, skip posting |
| `python main.py --no-headless` | Run browsers visually (for debugging) |

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `CANVA_URL` | Public Canva design URL | *(required)* |
| `DELAY_BETWEEN_STATUSES` | Seconds between posting each status | `5` |
| `HEADLESS` | Run browser without UI (`true`/`false`) | `true` |

## Important Considerations

### WhatsApp Web Session

- The session is saved in `browser_data/` and persists between runs.
- If WhatsApp Web logs you out (e.g., you unlink the device from your phone), you need to run `python main.py --setup` again.
- **Do not** commit the `browser_data/` directory — it contains your session credentials.

### Canva Design Requirements

- The design URL must be **public** (anyone with the link can view it).
- The automation screenshots each page as it appears in the Canva viewer.
- Changes you make to the Canva design are picked up on the next run since images are re-downloaded every time.

### Image Quality

- Images are captured at 1920x1080 viewport resolution.
- The automation tries to screenshot just the design canvas area for the best quality.
- If the canvas element can't be detected, it falls back to a full viewport screenshot.

### Rate Limiting

- A configurable delay (`DELAY_BETWEEN_STATUSES`) is added between each status post to avoid triggering WhatsApp rate limits.
- Default is 5 seconds between posts.

### Logs

- Console output goes to stdout.
- A persistent log file is written to `automation.log` in the project directory.
- Cron output is captured in `cron.log` (if configured as shown above).

## Troubleshooting

### "WhatsApp Web did not load in time"
- Your session may have expired. Run `python main.py --setup` to log in again.

### "No images downloaded"
- Verify the Canva URL is correct and publicly accessible.
- Try opening the URL in a regular browser to confirm it loads.
- Run with `--no-headless` to see what the browser sees.

### "Could not find Status tab"
- WhatsApp Web UI may have changed. Run with `--no-headless` to debug.
- Check if your WhatsApp account has status posting enabled.

### Cron job not running
- Check `cron.log` for error messages.
- Ensure the paths in the crontab are absolute.
- Verify cron service is running: `sudo systemctl status cron`
- Make sure the Playwright browser is installed for the cron user.

### Session issues after server restart
- The browser session in `browser_data/` should survive restarts.
- If it doesn't, run `python main.py --setup` to re-authenticate.
