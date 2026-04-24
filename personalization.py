from __future__ import annotations

import json
import random
import re
from collections import deque
from typing import Deque, Optional
from urllib import error as url_error
from urllib import request as url_request

from config import AIConfig


class PersonalizationEngine:
    def __init__(self, ai_config: AIConfig) -> None:
        self._ai_config = ai_config
        self._random = random.Random()
        self._recent_lines: Deque[str] = deque(maxlen=120)

    def generate_context_line(self, name: str, business: str, city: str) -> str:
        line = ""

        if self._ai_config.enabled and self._ai_config.provider == "openai_compatible":
            line = self._generate_with_openai_compatible(name=name, business=business, city=city) or ""

        if not line:
            line = self._fallback_line(name=name, business=business, city=city)

        cleaned = self._sanitize_line(line)
        if cleaned in self._recent_lines:
            cleaned = self._sanitize_line(self._fallback_line(name=name, business=business, city=city, force_variant=True))

        self._recent_lines.append(cleaned)
        return cleaned

    def _generate_with_openai_compatible(self, name: str, business: str, city: str) -> Optional[str]:
        api_key = self._ai_config.resolved_api_key()
        if not api_key:
            return None

        prompt = (
            "Write exactly one natural sentence with at most 15 words. "
            "No emojis, no sales language, no hype, no exclamation marks. "
            "Use this lead info only if available: "
            f"name={name}, business={business}, city={city or 'N/A'}."
        )

        payload = {
            "model": self._ai_config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You produce one short human sentence for email context. No marketing tone.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self._ai_config.temperature,
            "max_tokens": 60,
        }

        data = json.dumps(payload).encode("utf-8")
        req = url_request.Request(
            self._ai_config.endpoint,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

        try:
            with url_request.urlopen(req, timeout=self._ai_config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except (url_error.URLError, TimeoutError, OSError):
            return None

        try:
            parsed = json.loads(body)
            return str(parsed["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def _fallback_line(self, name: str, business: str, city: str, force_variant: bool = False) -> str:
        city_part = f" in {city}" if city else ""
        variants = [
            f"I came across your {business}{city_part} and appreciated the way it is presented.",
            f"I noticed your {business}{city_part} and thought your public presence felt thoughtful.",
            f"I saw your {business}{city_part} and liked how clearly your work is described.",
            f"I found your {business}{city_part} and it gave a strong first impression.",
            f"I read about your {business}{city_part} and found it genuinely interesting.",
        ]

        if force_variant:
            self._random.shuffle(variants)

        return self._random.choice(variants)

    def _sanitize_line(self, text: str) -> str:
        text = text.replace("\n", " ").replace("\r", " ").strip()
        text = text.strip('"\'')
        text = re.sub(r"\s+", " ", text)
        text = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()

        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ,.'-!?")
        text = "".join(ch for ch in text if ch in allowed_chars)
        text = re.sub(r"\s+", " ", text).strip()

        words = text.split()
        if len(words) > 15:
            text = " ".join(words[:15]).rstrip(".,;:!?") + "."

        if not text:
            text = "I came across your business and found it interesting."

        return text
