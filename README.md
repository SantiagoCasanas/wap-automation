# Canva to WhatsApp Status Automation

Automatically downloads every page of a Canva design as high-quality JPG images and publishes each one as a WhatsApp status. Designed to run daily at **12:00 AM Colombian time** — it re-downloads the design each run, so any changes you make in Canva are reflected automatically.

## How It Works

1. **Canva Download**: Logs into your Canva account via Playwright (headless browser), opens the design in edit mode, and uses the native **Share > Download** feature to export all pages as **JPG, size x2, quality 100** — exactly as you would do manually. Downloads the ZIP file and extracts the images.
2. **WhatsApp Posting**: Opens WhatsApp Web via Playwright with a persistent session, navigates to the Status tab, and uploads each image as a status update.
3. **Scheduling**: A cron job runs the script daily at 12:00 AM Colombian time (05:00 UTC).

## Prerequisites

- **Python 3.11+**
- **pip** (Python package manager)
- A **Canva account** (free tier works)
- A **WhatsApp account** linked to WhatsApp Web
- A **Linux server or machine** that stays on (for scheduled runs)

## Project Structure

```
wap-automation/
├── main.py                # Entry point and orchestrator
├── canva_downloader.py    # Logs into Canva, downloads pages as JPG via native export
├── wap_status_poster.py   # Posts images to WhatsApp status via WhatsApp Web
├── setup.sh               # Installation script
├── requirements.txt       # Python dependencies
├── .env.example           # Configuration template
├── .env                   # Your configuration (not tracked in git)
├── canva_browser_data/    # Canva login session (not tracked in git)
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

Set your Canva design URL:

```
CANVA_URL=https://www.canva.com/design/YOUR_DESIGN_ID/view
```

### Step 4: First-time Canva login

This opens a visible browser so you can log in to your Canva account:

```bash
python main.py --setup-canva
```

**What happens:**
1. A Chromium browser window opens with Canva's login page
2. Log in with your Canva account (email, Google, etc.)
3. Once logged in, the session is saved to `canva_browser_data/`
4. The browser closes automatically

**After this, all future runs use the saved session — no manual login needed.**

### Step 5: First-time WhatsApp Web login

This opens a visible browser so you can link your WhatsApp:

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

### Step 6: Test the automation

Test just the Canva download:

```bash
python main.py --download-only
```

This will log into Canva, open your design, and download all pages as JPG. Check the `downloads/extracted/` folder for the images.

Run a full cycle (download + post to WhatsApp):

```bash
python main.py
```

### Step 7: Set up the daily cron job

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
| `python main.py --setup-canva` | First-time Canva login |
| `python main.py --setup-wap` | First-time WhatsApp Web login |
| `python main.py --url <URL>` | Override the Canva URL from .env |
| `python main.py --download-only` | Only download images, skip posting |
| `python main.py --no-headless` | Run browsers visually (for debugging) |

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `CANVA_URL` | Canva design URL (view or edit link) | *(required)* |
| `DELAY_BETWEEN_STATUSES` | Seconds between posting each status | `5` |
| `HEADLESS` | Run browser without UI (`true`/`false`) | `true` |

## Important Considerations

### Canva Session

- The Canva login session is saved in `canva_browser_data/` and persists between runs.
- If Canva logs you out (session expires, password change, etc.), run `python main.py --setup-canva` again.
- **Do not** commit `canva_browser_data/` — it contains your login credentials.
- The automation uses Canva's native download (JPG, x2, quality 100), producing clean images without any Canva UI elements.

### WhatsApp Web Session

- The session is saved in `browser_data/` and persists between runs.
- If WhatsApp Web logs you out (e.g., you unlink the device from your phone), run `python main.py --setup-wap` again.
- **Do not** commit `browser_data/` — it contains your session credentials.

### How the Canva Download Works

The automation replicates exactly what you do manually:
1. Opens the design in Canva's editor (converts `/view` URL to `/edit`)
2. Clicks **Share > Download**
3. Selects **JPG** file type
4. Sets size to **x2**
5. Sets quality to **100**
6. Selects **All pages**
7. Clicks **Download** → receives a ZIP file
8. Extracts the ZIP to get individual JPG images

### Image Quality

- Images are exported as **JPG at 2x size with 100% quality** — the same as downloading manually.
- No screenshots are taken — the images come directly from Canva's export engine.
- This produces clean, high-resolution images without any Canva UI (no arrows, page numbers, logos, etc.).

### Rate Limiting

- A configurable delay (`DELAY_BETWEEN_STATUSES`) is added between each status post to avoid triggering WhatsApp rate limits.
- Default is 5 seconds between posts.

### Logs

- Console output goes to stdout.
- A persistent log file is written to `automation.log` in the project directory.
- Cron output is captured in `cron.log` (if configured as shown above).

## Troubleshooting

### "Canva editor did not load in time"
- Your Canva session may have expired. Run `python main.py --setup-canva` to log in again.
- Verify the design URL is correct and you have access to it.

### "Could not find Share button" / "Could not find Download option"
- Canva's UI may have changed. Run with `--no-headless` to see what the browser sees.
- Make sure the design is accessible from your Canva account.

### "WhatsApp Web did not load in time"
- Your WhatsApp session may have expired. Run `python main.py --setup-wap` to log in again.

### "No images downloaded"
- Run with `--no-headless --download-only` to watch the browser and see where it fails.
- Verify you can manually download the design from the same Canva account.

### Cron job not running
- Check `cron.log` for error messages.
- Ensure the paths in the crontab are absolute.
- Verify cron service is running: `sudo systemctl status cron`
- Make sure the Playwright browser is installed for the cron user.

### Session issues after server restart
- Both `canva_browser_data/` and `browser_data/` should survive restarts.
- If they don't, run `--setup-canva` and `--setup-wap` to re-authenticate.
