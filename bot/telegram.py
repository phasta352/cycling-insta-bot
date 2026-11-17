"""Minimal Telegram Bot API client: sends drafts with buttons and reads your answers."""
import requests

TIMEOUT = 30


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)

    def _call(self, method: str, **params):
        r = requests.post(f"{self.base}/{method}", json=params, timeout=TIMEOUT)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
        return data["result"]

    def get_me(self):
        return self._call("getMe")

    def send(self, text: str, buttons=None, html: bool = True):
        params = {"chat_id": self.chat_id, "text": text[:4096], "disable_web_page_preview": True}
        if html:
            params["parse_mode"] = "HTML"
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self._call("sendMessage", **params)

    def send_photo(self, photo_url: str, caption: str = ""):
        return self._call("sendPhoto", chat_id=self.chat_id, photo=photo_url,
                          caption=caption[:1024], parse_mode="HTML")

    def edit_text(self, message_id: int, text: str):
        try:
            self._call("editMessageText", chat_id=self.chat_id, message_id=message_id,
                       text=text[:4096], parse_mode="HTML", disable_web_page_preview=True)
        except RuntimeError:
            pass  # message too old / unchanged: not important

    def answer_callback(self, callback_id: str, text: str = ""):
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])
        except RuntimeError:
            pass  # button presses older than a few minutes can't be answered; harmless

    def updates(self, offset: int):
        return self._call("getUpdates", offset=offset, timeout=0,
                          allowed_updates=["message", "callback_query"])


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
