"""Entry point. GitHub Actions runs `python -m bot.main run` every 30 minutes.

Each run:
  1. reads your Telegram button presses and commands,
  2. publishes the next approved post if a posting slot is free,
  3. every few hours, looks for new stories and sends you drafts.
"""
import datetime as dt
import sys
import time
import traceback
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from . import design, sources, state as state_mod, storage
from .config import ROOT, load_secrets, load_settings
from .instagram import Instagram
from .telegram import Telegram, esc

OUT = ROOT / "out"

HELP = (
    "<b>Commands</b>\n"
    "/status: queue, drafts and today's numbers\n"
    "/scout: look for news on the next run\n"
    "/pause: stop scouting and posting\n"
    "/resume: start again\n\n"
    "Button presses are picked up on the next run (within about 30 minutes)."
)


class Bot:
    def __init__(self):
        self.settings = load_settings()
        self.secrets = load_secrets()
        self.state = state_mod.load()
        self.tz = ZoneInfo(self.settings["schedule"]["timezone"])
        self.tg = Telegram(self.secrets.telegram_token, self.secrets.telegram_chat_id)
        self.ig = Instagram(self.secrets.ig_user_id, self.secrets.ig_token,
                            self.settings["instagram"].get("api_version", "v25.0"))
        storage.configure(self.secrets)

    # ---------- helpers ----------
    def now_local(self):
        return dt.datetime.now(self.tz)

    def in_posting_hours(self) -> bool:
        start, end = self.settings["schedule"]["posting_hours"]
        return start <= self.now_local().hour <= end

    def posts_today(self) -> int:
        today = self.now_local().date()
        return sum(1 for p in self.state["published"]
                   if dt.datetime.fromtimestamp(p["at"], self.tz).date() == today)

    def handle(self) -> str:
        h = self.settings["page"].get("handle") or self.state.get("ig_handle")
        if not h:
            try:
                h = "@" + self.ig.account()["username"]
                self.state["ig_handle"] = h
            except Exception:
                h = ""
        return h

    # ---------- 1. Telegram ----------
    def process_telegram(self):
        updates = self.tg.updates(self.state["telegram_offset"])
        for u in updates:
            self.state["telegram_offset"] = u["update_id"] + 1
            if "callback_query" in u:
                self.on_button(u["callback_query"])
            elif "message" in u:
                msg = u["message"]
                if str(msg.get("chat", {}).get("id")) != self.tg.chat_id:
                    continue  # ignore strangers
                self.on_command((msg.get("text") or "").strip().split()[0:1])

    def on_button(self, cb):
        if str(cb.get("message", {}).get("chat", {}).get("id")) != self.tg.chat_id:
            return
        action, _, draft_id = (cb.get("data") or "").partition(":")
        draft = self.state["drafts"].pop(draft_id, None)
        if not draft:
            self.tg.answer_callback(cb["id"], "This draft is no longer available.")
            return
        mid = draft.get("text_message_id")
        if action == "s":
            self.tg.answer_callback(cb["id"], "Skipped")
            if mid:
                self.tg.edit_text(mid, f"❌ <b>Skipped</b>: {esc(draft['headline'])}")
        elif action in ("a", "n"):
            draft["post_now"] = action == "n"
            draft["approved_at"] = time.time()
            if draft["post_now"]:
                self.state["queue"].insert(0, draft)
            else:
                self.state["queue"].append(draft)
            label = "Posting now" if draft["post_now"] else "Approved, queued for the next slot"
            self.tg.answer_callback(cb["id"], label)
            if mid:
                self.tg.edit_text(mid, f"✅ <b>{label}</b>: {esc(draft['headline'])}")

    def on_command(self, parts):
        cmd = parts[0].lower().split("@")[0] if parts else ""
        if cmd == "/pause":
            self.state["paused"] = True
            self.tg.send("⏸ Paused. Send /resume to start again.")
        elif cmd == "/resume":
            self.state["paused"] = False
            self.tg.send("▶️ Resumed.")
        elif cmd == "/scout":
            self.state["force_scout"] = True
            self.tg.send("🔎 I'll look for news on this run.")
        elif cmd == "/status":
            self.send_status()
        elif cmd in ("/start", "/help"):
            self.tg.send(HELP)

    def send_status(self):
        s = self.state
        lines = [
            f"<b>Status</b> ({'paused' if s['paused'] else 'running'})",
            f"Posts today: {self.posts_today()} / {self.settings['schedule']['max_posts_per_day']}",
            f"Approved & queued: {len(s['queue'])}",
            f"Drafts waiting for you: {len(s['drafts'])}",
        ]
        if s["last_scout"]:
            last = dt.datetime.fromtimestamp(s["last_scout"], self.tz).strftime("%H:%M")
            lines.append(f"Last news check: {last}")
        if s["feed_errors"]:
            lines.append("\n⚠️ Sources that failed last time:")
            lines += [f"• {esc(k)}: {esc(v[:80])}" for k, v in s["feed_errors"].items()]
        self.tg.send("\n".join(lines))

    # ---------- 2. Publishing ----------
    def expire_drafts(self):
        limit = self.settings["schedule"]["draft_expiry_hours"] * 3600
        for did, d in list(self.state["drafts"].items()):
            if time.time() - d["created"] > limit:
                self.state["drafts"].pop(did)
                if d.get("text_message_id"):
                    self.tg.edit_text(d["text_message_id"], f"⌛ <b>Expired</b>: {esc(d['headline'])}")

    def publish_next(self):
        q = self.state["queue"]
        if not q or self.state["paused"]:
            return
        sch = self.settings["schedule"]
        draft = q[0]
        if not draft.get("post_now"):
            if not self.in_posting_hours() or self.posts_today() >= sch["max_posts_per_day"]:
                return
            last = max((p["at"] for p in self.state["published"]), default=0)
            if time.time() - last < sch["min_hours_between_posts"] * 3600:
                return
        try:
            media_id = self.ig.publish_image(draft["image_url"], draft["full_caption"], draft.get("alt_text", ""))
        except Exception as ex:
            draft["attempts"] = draft.get("attempts", 0) + 1
            if draft["attempts"] >= 3:
                q.pop(0)
                self.tg.send(f"🚫 Gave up posting after 3 tries: {esc(draft['headline'])}\n<code>{esc(str(ex))}</code>")
            else:
                self.tg.send(f"⚠️ Posting failed (try {draft['attempts']}/3), will retry next run:\n<code>{esc(str(ex))}</code>")
            return
        q.pop(0)
        self.state["published"].append({"id": draft["id"], "headline": draft["headline"],
                                        "url": draft["url"], "at": time.time(), "media_id": media_id})
        link = self.ig.permalink(media_id)
        self.tg.send(f"📣 <b>Posted</b>: {esc(draft['headline'])}" + (f"\n{link}" if link else ""))

    # ---------- 3. Scouting ----------
    def should_scout(self) -> bool:
        if self.state["paused"]:
            return False
        if self.state.get("force_scout"):
            return True
        sch = self.settings["schedule"]
        start, end = sch["posting_hours"]
        if not (start - 1 <= self.now_local().hour <= end - 1):
            return False
        if time.time() - self.state["last_scout"] < sch["scout_every_hours"] * 3600 - 300:
            return False
        sent_24h = sum(1 for t in self.state["drafts_sent"] if time.time() - t < 86400)
        return sent_24h < sch["max_drafts_per_day"]

    def scout(self):
        from .editor import Editor  # imported here so status-only runs stay fast

        self.state["force_scout"] = False
        self.state["last_scout"] = time.time()
        sch = self.settings["schedule"]
        candidates = sources.collect(self.settings, self.state)
        if not candidates:
            return
        editor = Editor(self.secrets.anthropic_key, self.settings)
        recent = [p["headline"] for p in self.state["published"]]
        recent += [d["headline"] for d in self.state["drafts"].values()]
        recent += [d["headline"] for d in self.state["queue"]]
        sent_24h = sum(1 for t in self.state["drafts_sent"] if time.time() - t < 86400)
        room = min(sch["drafts_per_scout"], sch["max_drafts_per_day"] - sent_24h)
        picks = editor.select(candidates, recent, room)

        # Everything that was evaluated counts as seen, so it isn't scored again.
        now = time.time()
        for c in candidates:
            self.state["seen"][c.key] = now

        made = 0
        for pick in picks:
            if made >= room:
                break
            story = candidates[pick["i"]]
            if not story.via_google:
                story.text = sources.fetch_article_text(story)
            post = editor.write(story, pick["category"])
            if not post:
                continue
            self.make_draft(story, post, pick["score"])
            made += 1

    def make_draft(self, story, post, score):
        did = uuid.uuid4().hex[:10]
        img = design.render(post["headline"], post["category"], story.source, self.settings,
                            self.handle(), OUT / f"{did}.jpg")
        image_url = storage.upload(img, did)
        tags = " ".join("#" + t for t in post["hashtags"])
        full_caption = f"{post['caption'].strip()}\n\n{tags}".strip()
        draft = {
            "id": did, "created": time.time(), "headline": post["headline"], "url": story.url,
            "source": story.source, "image_url": image_url, "full_caption": full_caption,
            "alt_text": post.get("alt_text", ""), "score": score,
        }
        self.state["drafts_sent"].append(time.time())

        rumour = "" if post.get("confirmed", True) else "\n⚠️ <b>Not officially confirmed</b>"
        note = f"\n📝 {esc(post['note'])}" if post.get("note") else ""
        self.tg.send_photo(image_url, f"<b>{esc(post['category'])}</b> · score {score}/10\n"
                                      f"<a href=\"{esc(story.url)}\">{esc(story.source)}: read the source</a>")

        if not self.settings["approval"]["required"]:
            draft["post_now"] = False
            self.state["queue"].append(draft)
            self.tg.send(f"🤖 Queued automatically:\n\n{esc(full_caption)}{rumour}{note}")
            return

        buttons = [[{"text": "✅ Approve", "callback_data": f"a:{did}"},
                    {"text": "⚡ Post now", "callback_data": f"n:{did}"}],
                   [{"text": "❌ Skip", "callback_data": f"s:{did}"}]]
        msg = self.tg.send(f"{esc(full_caption)}{rumour}{note}", buttons=buttons)
        draft["text_message_id"] = msg["message_id"]
        self.state["drafts"][did] = draft

    # ---------- main ----------
    def run(self):
        try:
            self.process_telegram()
            self.expire_drafts()
            self.publish_next()
            if self.should_scout():
                self.scout()
                self.publish_next()   # a "post now" approval might be waiting
        except Exception as ex:
            traceback.print_exc()
            try:
                self.tg.send(f"💥 The bot hit an error:\n<code>{esc(str(ex))[:1500]}</code>")
            except Exception:
                pass
            raise
        finally:
            state_mod.save(self.state)


def check():
    """Test every connection and report the results to Telegram."""
    settings = load_settings()
    secrets = load_secrets(required=False)
    report = ["<b>🔧 Connection check</b>"]

    def line(ok, name, detail=""):
        report.append(f"{'✅' if ok else '❌'} {name}" + (f": {esc(detail)}" if detail else ""))

    tg = None
    try:
        tg = Telegram(secrets.telegram_token, secrets.telegram_chat_id)
        me = tg.get_me()
        line(True, "Telegram bot", "@" + me["username"])
    except Exception as ex:
        line(False, "Telegram bot", str(ex))

    try:
        ig = Instagram(secrets.ig_user_id, secrets.ig_token, settings["instagram"].get("api_version", "v25.0"))
        acc = ig.account()
        line(True, "Instagram account", f"@{acc.get('username')} ({acc.get('followers_count', '?')} followers)")
        q = ig.quota()
        line(True, "Instagram publishing", f"{q.get('quota_usage', 0)} posts used in the last 24h")
    except Exception as ex:
        line(False, "Instagram", str(ex))

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.anthropic_key)
        client.messages.create(model=settings["ai"]["model"], max_tokens=5,
                               messages=[{"role": "user", "content": "Say ok"}])
        line(True, "Claude API", settings["ai"]["model"])
    except Exception as ex:
        line(False, "Claude API", str(ex)[:200])

    try:
        storage.configure(secrets)
        storage.ping()
        line(True, "Cloudinary", secrets.cloudinary_name)
    except Exception as ex:
        line(False, "Cloudinary", str(ex)[:200])

    tmp = {**state_mod.load(), "seen": {}}
    try:
        stories = sources.collect(settings, tmp)
        line(bool(stories), "News sources", f"{len(stories)} fresh stories found")
        for name, err in tmp["feed_errors"].items():
            report.append(f"   ⚠️ {esc(name)}: {esc(err[:80])}")
    except Exception as ex:
        line(False, "News sources", str(ex))

    text = "\n".join(report)
    print(text.replace("<b>", "").replace("</b>", ""))
    if tg:
        try:
            tg.send(text)
        except Exception as ex:
            print("Could not send report to Telegram:", ex)
    if "❌" in text:
        sys.exit(1)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "check":
        check()
    elif mode == "scout":
        b = Bot()
        b.state["force_scout"] = True
        b.run()
    else:
        Bot().run()
