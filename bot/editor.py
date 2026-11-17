"""The AI editor: picks the best stories and writes the post text with Claude."""
import json
import re

import anthropic

CATEGORIES = ["RACE NEWS", "RESULT", "TRANSFER", "TEAM NEWS", "RIDER NEWS", "GEAR & TECH", "UCI", "BREAKING"]


class Editor:
    def __init__(self, api_key: str, settings: dict):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.settings = settings
        self.model = settings["ai"]["model"]

    def _ask(self, system: str, prompt: str, max_tokens: int = 1500) -> dict | list:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return parse_json(text)

    def _brief(self) -> str:
        p = self.settings["page"]
        return (f"You are the editor of the Instagram page \"{p['name']}\".\n"
                f"Focus: {p['focus'].strip()}\nAvoid: {p['avoid'].strip()}\n"
                f"Language: {p['language']}.")

    def select(self, stories, recent_headlines: list[str], limit: int) -> list[dict]:
        """Score candidate stories and return the best few as [{i, score, category}]."""
        lines = []
        for i, s in enumerate(stories):
            summary = f" | {s.summary[:220]}" if s.summary else ""
            lines.append(f"[{i}] ({s.source}) {s.title}{summary}")
        recent = "\n".join(f"- {h}" for h in recent_headlines[-30:]) or "(none yet)"
        system = self._brief() + (
            "\nYour job: choose which news stories would make the most engaging, shareable "
            "Instagram posts for cycling fans today. Prefer big names, big races, official "
            "announcements, results, transfers and notable product launches. Several headlines "
            "may describe the same event: treat them as one and pick the most informative. "
            "Never pick a story the page has already covered. Reply with JSON only."
        )
        prompt = (
            f"Already posted recently (do NOT repeat these events):\n{recent}\n\n"
            f"Candidate headlines:\n" + "\n".join(lines) + "\n\n"
            "Return a JSON list of the stories worth posting, best first, at most "
            f"{limit + 3} items. Each item: {{\"i\": <index>, \"score\": <1-10 engagement score>, "
            f"\"category\": one of {CATEGORIES}, \"duplicates\": [<indexes of other headlines about the same event>]}}. "
            "Return [] if nothing is worth posting."
        )
        result = self._ask(system, prompt, max_tokens=1200)
        if not isinstance(result, list):
            return []
        min_score = self.settings["ai"].get("min_score", 6)
        picks = []
        for item in result:
            try:
                i = int(item["i"])
                if 0 <= i < len(stories) and int(item.get("score", 0)) >= min_score:
                    picks.append({"i": i, "score": int(item["score"]),
                                  "category": str(item.get("category", "RACE NEWS")).upper(),
                                  "duplicates": [int(d) for d in item.get("duplicates", []) if str(d).isdigit()]})
            except (KeyError, ValueError, TypeError):
                continue
        return picks

    def write(self, story, category: str) -> dict | None:
        """Write the graphic headline, caption, hashtags and alt text for one story."""
        p = self.settings["page"]
        facts = story.text or story.summary or "(only the headline is available)"
        system = self._brief() + (
            f"\nTone: {p['tone'].strip()}\n"
            "Rules: use ONLY facts stated in the source material below; never invent results, "
            "times, quotes, prices or dates. Write everything in your own words (no copied "
            "sentences, no quotes longer than a few words). If the material is clearly a rumour, "
            "say so or set \"confirmed\" to false. If there isn't enough information for a "
            "useful post, set \"skip\" to true. Reply with JSON only."
        )
        prompt = (
            f"Source: {story.source}\nHeadline: {story.title}\nURL: {story.url}\n"
            f"Material:\n{facts}\n\n"
            "Return a JSON object with:\n"
            "- \"headline\": punchy headline for the graphic, max 70 characters, no emoji, no hashtags\n"
            f"- \"category\": short label, one of {CATEGORIES} (suggested: {category})\n"
            "- \"caption\": Instagram caption: a strong first line, then 2-4 short sentences explaining "
            "the news and why it matters, then a question to invite comments. Max 900 characters. "
            "End with a line \"Source: <publication name>\". No hashtags in the caption\n"
            "- \"hashtags\": list of 6-10 relevant hashtags without the # sign (mix big and niche)\n"
            "- \"alt_text\": one-sentence description of the graphic for visually impaired users\n"
            "- \"confirmed\": true if the news is officially confirmed, false if rumour/report\n"
            "- \"skip\": true if this should not be posted\n"
            "- \"note\": one short line for the page owner about anything to double-check (or \"\")"
        )
        result = self._ask(system, prompt, max_tokens=1500)
        if not isinstance(result, dict) or result.get("skip"):
            return None
        if not result.get("headline") or not result.get("caption"):
            return None
        result["headline"] = result["headline"].strip()[:90]
        result["category"] = str(result.get("category") or category).upper()[:20]
        tags = [re.sub(r"[^\w]", "", t.lstrip("#")) for t in result.get("hashtags", [])]
        result["hashtags"] = [t for t in tags if t][:12]
        return result


def parse_json(text: str):
    """Pull the first JSON object/list out of the model's reply."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    pairs = [("[", "]"), ("{", "}")]
    # Try whichever bracket comes first, so an object containing a list parses as the object.
    pairs.sort(key=lambda p: text.find(p[0]) if text.find(p[0]) != -1 else len(text))
    for opener, closer in pairs:
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
