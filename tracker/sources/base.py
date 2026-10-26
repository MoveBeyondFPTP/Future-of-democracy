"""Shared context handed to every state source."""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass, field

from ..classify import classify_text, election_related, merge
from ..http import Client


class SessionNotAvailable(Exception):
    """The session doesn't exist on the state's site yet (e.g. before
    prefiling opens). Not an error: the session is skipped quietly."""


@dataclass
class Context:
    state: str
    categories: list
    cache: dict
    client: Client = field(default_factory=Client)
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("tracker"))
    started: float = field(default_factory=time.time)
    # Soft time budget per state so one slow site can't stall the whole run.
    budget_seconds: int = 50 * 60
    warnings: list = field(default_factory=list)

    def classify(self, text: str, lead: str = "") -> dict:
        return classify_text(text, self.categories, lead)

    def classify_body(self, text: str) -> dict:
        """Classify full bill text: only strong terms count, because long texts
        mention weak terms (at-large, demographic data...) in passing."""
        return classify_text(text, self.categories, "", allow_weak=False)

    def screen(self, text: str) -> bool:
        """True if a bill looks election-related enough to be worth a
        closer (more expensive) look: detail page, full text."""
        return bool(self.classify(text)) or election_related(text)

    def merge(self, a: dict, b: dict) -> dict:
        return merge(a, b)

    def out_of_time(self) -> bool:
        return time.time() - self.started > self.budget_seconds

    def warn(self, msg: str):
        self.log.warning("[%s] %s", self.state, msg)
        if len(self.warnings) < 50:
            self.warnings.append(msg)


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()
