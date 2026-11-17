# Cycling News Today: Instagram bot

Finds fresh pro-cycling and gear news, has Claude pick the best stories and write the posts,
designs a branded graphic, sends it to you on Telegram for approval, then posts it to Instagram.
It runs for free on GitHub Actions every 30 minutes.

## 1. Upload the code

1. Unzip `cycling-insta-bot.zip` on your computer.
2. Open your repository on github.com and click **Add file → Upload files**.
3. Drag **everything inside** the unzipped folder (including the hidden `.github` folder) into the page.
   - Mac: in Finder press `Cmd + Shift + .` to show hidden folders.
   - If `.github` won't upload by dragging, create it by hand: **Add file → Create new file**, name it
     `.github/workflows/bot.yml`, and paste in the contents of that file.
4. Click **Commit changes**.

The repository should look like this:

```
.github/workflows/bot.yml   ← the schedule
bot/                        ← the code
assets/fonts/               ← fonts for the graphics
state/                      ← the bot's memory (filled in automatically)
config.yaml                 ← your settings
requirements.txt
```

## 2. Test the connections

1. In your repo, open the **Actions** tab. If asked, click **I understand… enable them**.
2. Click **Cycling news bot** on the left, then **Run workflow**, choose **check**, and run it.
3. After about a minute, Telegram shows a report with ✅ or ❌ for Instagram, Claude, Cloudinary,
   Telegram and the news sources. Fix any ❌ before continuing (see Troubleshooting).

## 3. Try a first scout

Run the workflow again with **scout**. You'll get up to 2 drafts in Telegram, each with a graphic and caption:

- **✅ Approve**: queued and posted at the next free slot (at least 2 h apart, 08:00–22:00)
- **⚡ Post now**: posted on the next run, ignoring the spacing
- **❌ Skip**: dropped

From now on it runs by itself. Button presses are picked up within about 30 minutes, because the bot only wakes up every 30 minutes.

## Telegram commands

| Command | What it does |
| --- | --- |
| `/status` | Posts today, queue, waiting drafts, broken sources |
| `/scout` | Look for news on the next run |
| `/pause` | Stop scouting and posting |
| `/resume` | Start again |

## Changing settings

Edit `config.yaml` directly on GitHub (click it, then the pencil icon). You can change:

- page name, tone, focus and topics to avoid
- posting hours, posts per day, spacing, drafts per scout
- colors, and a logo (upload a square PNG as `assets/logo.png`)
- news sources (RSS feeds and Google News searches)
- `approval: required: false` to go fully automatic later

## Costs

- **GitHub Actions**: about 1,000–1,400 of the 2,000 free monthly minutes on a private repo.
  Check usage under *Settings → Billing and plans*. To use fewer, change the cron line in
  `.github/workflows/bot.yml` to `"0 6-21 * * *"` (hourly).
- **Claude API**: roughly €2–5/month at this volume. Set a spend limit in the Anthropic Console.
- **Cloudinary, Telegram, Instagram API**: free.

## Troubleshooting

- **Instagram ❌ "permissions" or code 10/200**: the system-user token is missing
  `instagram_content_publish` or isn't assigned to the Instagram account. Regenerate it in
  Business Settings → System users, with the Instagram account and Facebook Page assigned as assets.
- **Instagram ❌ "Unsupported get request" / code 100**: `INSTAGRAM_APP_ID` isn't the Instagram
  *business account* ID (usually starts with 1784…).
- **No drafts arriving**: send `/status`. The bot only drafts stories the AI scores 6/10 or higher;
  quiet news days produce fewer drafts. Lower `ai: min_score` to get more.
- **Workflow didn't run on schedule**: GitHub's scheduled runs can be delayed by 5–20 minutes at busy times.
- **Any error**: the bot messages you on Telegram. Full logs are in the Actions tab, under the failed run.

## How it works

`bot/sources.py` reads the feeds → `bot/editor.py` asks Claude to score stories and write the
post → `bot/design.py` draws the graphic → `bot/storage.py` uploads it to Cloudinary →
`bot/telegram.py` sends you the draft → `bot/instagram.py` publishes it. `bot/main.py` ties it
together, and `state/state.json` remembers what's been seen, approved and posted.

The bot writes every post in its own words and makes its own graphics. It never reposts
photos or text from news sites, which keeps the page safe under Instagram's originality rules.
