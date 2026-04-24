from __future__ import annotations

import random
import re
from typing import Dict, List


class TemplateManager:
    DEFAULT_BODY_TEMPLATES = [
        "Hi {name},\n\n{context_line}\n\nI noticed {business} does not have a website yet. Most customers {city} search online before choosing a service, and a simple homepage could help you get more calls.\n\nWould it be worth a quick look at how that could work for you?\n\nBest regards,",
        "Hello {name},\n\n{context_line}\n\nI work with small businesses {city} on getting their first website up. A basic homepage for {business} could help new customers find and trust you more easily.\n\nHappy to share a quick example if you are curious.\n\nBest,",
        "Hi {name},\n\n{context_line}\n\nI noticed {business} {city} does not seem to have a website yet. In my experience, even a simple one-page site can bring in a few extra calls each week.\n\nWould you be open to seeing how that might look for your business?\n\nRegards,",
        "Hello {name},\n\n{context_line}\n\nQuick question — have you thought about having a website for {business} {city}? A lot of your competitors already have one, and customers tend to pick businesses they can look up online.\n\nI can show you a short example if you are interested.\n\nThanks,",
        "Hi {name},\n\n{context_line}\n\nI put together a quick demo homepage for {business} to show what a website could look like for you: {demo_link}\n\nIt is just an example, but it gives you an idea of how customers {city} would find you online.\n\nWorth a look?\n\nBest regards,",
        "Hello {name},\n\n{context_line}\n\nYour reviews for {business} {city} are impressive. A website would make it even easier for new customers to find you and get in touch directly.\n\nI can share a quick example if you want to see how it would look.\n\nRegards,",
        "Hi {name},\n\n{context_line}\n\nI came across {business} {city} and noticed you do not have a website yet. I help local businesses get a simple, professional homepage that brings in more calls and bookings.\n\nInterested in seeing a quick example?\n\nThank you,",
    ]

    def __init__(self, subject_templates: List[str], body_templates: List[str] | None = None) -> None:
        self._random = random.Random()
        self._body_templates = body_templates or self.DEFAULT_BODY_TEMPLATES
        self._subject_templates = subject_templates
        self._last_body_index: int | None = None
        self._last_subject_index: int | None = None

    def pick_body_template(self) -> str:
        return self._pick_non_consecutive(self._body_templates, "_last_body_index")

    def pick_subject_template(self) -> str:
        return self._pick_non_consecutive(self._subject_templates, "_last_subject_index")

    def render(self, template: str, placeholders: Dict[str, str]) -> str:
        text = template.format_map(_SafeFormatDict(placeholders))
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        text = re.sub(r"\n\s+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _pick_non_consecutive(self, templates: List[str], last_attr: str) -> str:
        if not templates:
            raise ValueError("Template list cannot be empty.")

        if len(templates) == 1:
            return templates[0]

        available_indices = list(range(len(templates)))
        last_index = getattr(self, last_attr)
        if last_index in available_indices:
            available_indices.remove(last_index)

        chosen_index = self._random.choice(available_indices)
        setattr(self, last_attr, chosen_index)
        return templates[chosen_index]


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return ""
