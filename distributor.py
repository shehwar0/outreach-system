from __future__ import annotations

import random
from typing import Dict, List, Optional

from config import SenderConfig


class SenderDistributor:
    def __init__(self, senders: List[SenderConfig], sender_type_priority: List[str]) -> None:
        self._senders = senders
        self._random = random.Random()
        self._type_weights = self._build_priority_weights(sender_type_priority)

    @staticmethod
    def _build_priority_weights(priority_order: List[str]) -> Dict[str, int]:
        if not priority_order:
            return {}

        max_weight = len(priority_order)
        weights: Dict[str, int] = {}
        for index, sender_type in enumerate(priority_order):
            normalized = sender_type.lower().strip()
            weights[normalized] = max(1, max_weight - index)
        return weights

    def apply_existing_counts(self, sender_attempt_counts: Dict[str, int]) -> None:
        for sender in self._senders:
            sender.sent_count = int(sender_attempt_counts.get(sender.email.lower(), 0))

    def has_capacity(self) -> bool:
        return any(self._is_sender_available(sender) for sender in self._senders)

    def pick_sender(self) -> Optional[SenderConfig]:
        available_senders = [sender for sender in self._senders if self._is_sender_available(sender)]
        if not available_senders:
            return None

        weights = []
        for sender in available_senders:
            remaining = sender.daily_limit - sender.sent_count
            remaining_weight = max(1, remaining)
            priority_weight = self._type_weights.get(sender.type.lower(), 1)
            jitter = self._random.uniform(0.85, 1.15)
            weights.append(remaining_weight * priority_weight * jitter)

        selected = self._random.choices(available_senders, weights=weights, k=1)[0]
        selected.sent_count += 1
        return selected

    @staticmethod
    def _is_sender_available(sender: SenderConfig) -> bool:
        return sender.enabled and sender.sent_count < sender.daily_limit
