"""Publishes posts through Meta's official Instagram Graph API (Facebook Login / system user)."""
import time

import requests

TIMEOUT = 60


class InstagramError(RuntimeError):
    pass


class Instagram:
    def __init__(self, ig_user_id: str, token: str, api_version: str = "v25.0"):
        self.ig = ig_user_id
        self.token = token
        self.base = f"https://graph.facebook.com/{api_version}"

    def _req(self, method: str, path: str, **params):
        params["access_token"] = self.token
        url = f"{self.base}/{path}"
        r = (requests.get(url, params=params, timeout=TIMEOUT) if method == "GET"
             else requests.post(url, data=params, timeout=TIMEOUT))
        data = r.json()
        if "error" in data:
            e = data["error"]
            raise InstagramError(f"{e.get('message')} (code {e.get('code')}, subcode {e.get('error_subcode')})")
        return data

    def account(self) -> dict:
        return self._req("GET", self.ig, fields="username,name,followers_count")

    def quota(self) -> dict:
        data = self._req("GET", f"{self.ig}/content_publishing_limit", fields="quota_usage,config")
        return (data.get("data") or [{}])[0]

    def publish_image(self, image_url: str, caption: str, alt_text: str = "") -> str:
        params = {"image_url": image_url, "caption": caption[:2200]}
        if alt_text:
            params["alt_text"] = alt_text[:1000]
        try:
            container = self._req("POST", f"{self.ig}/media", **params)
        except InstagramError as ex:
            if alt_text and "alt_text" in str(ex):
                params.pop("alt_text")
                container = self._req("POST", f"{self.ig}/media", **params)
            else:
                raise
        cid = container["id"]

        # Wait until Instagram has fetched and processed the image.
        for _ in range(20):
            status = self._req("GET", cid, fields="status_code").get("status_code")
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Media container {status}")
            time.sleep(3)

        result = self._req("POST", f"{self.ig}/media_publish", creation_id=cid)
        return result["id"]

    def permalink(self, media_id: str) -> str:
        try:
            return self._req("GET", media_id, fields="permalink").get("permalink", "")
        except InstagramError:
            return ""
