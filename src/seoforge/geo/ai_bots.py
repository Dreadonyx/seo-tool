"""Registry of AI crawlers / user agents and their documented purpose.

Purposes:
  training - collects content to train AI models
  search   - indexes content so an AI search/answer product can cite and link it
  user     - fetches a page because a user asked the assistant to (not bulk crawling)

Documentation links are the operators' own pages. Where an operator publishes no
documentation, `docs` is None and the entry says so - treat those claims as unverified.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from seoforge.robots import RobotsTxt

Purpose = Literal["training", "search", "user"]


@dataclass(frozen=True, slots=True)
class AIBot:
    token: str
    operator: str
    purpose: Purpose
    docs: str | None
    note: str = ""


OPENAI = "https://platform.openai.com/docs/bots"
ANTHROPIC = (
    "https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-"
    "and-how-can-site-owners-block-the-crawler"
)
PERPLEXITY = "https://docs.perplexity.ai/guides/bots"

AI_BOTS: tuple[AIBot, ...] = (
    AIBot(
        "GPTBot",
        "OpenAI",
        "training",
        OPENAI,
        "Crawls content that may be used to train OpenAI models.",
    ),
    AIBot(
        "OAI-SearchBot",
        "OpenAI",
        "search",
        OPENAI,
        "Indexes pages for ChatGPT search results; blocking it removes you from those answers.",
    ),
    AIBot(
        "ChatGPT-User",
        "OpenAI",
        "user",
        OPENAI,
        "Fetches pages when a ChatGPT user or GPT action requests them.",
    ),
    AIBot(
        "ClaudeBot",
        "Anthropic",
        "training",
        ANTHROPIC,
        "Collects public web content for model training.",
    ),
    AIBot(
        "Claude-SearchBot",
        "Anthropic",
        "search",
        ANTHROPIC,
        "Indexes content to improve Claude's search results.",
    ),
    AIBot(
        "Claude-User",
        "Anthropic",
        "user",
        ANTHROPIC,
        "Fetches pages when a Claude user asks a question.",
    ),
    AIBot(
        "PerplexityBot",
        "Perplexity",
        "search",
        PERPLEXITY,
        "Indexes pages to surface and link them in Perplexity answers.",
    ),
    AIBot(
        "Perplexity-User",
        "Perplexity",
        "user",
        PERPLEXITY,
        "User-initiated fetches. Perplexity's docs say it generally ignores robots.txt.",
    ),
    AIBot(
        "Google-Extended",
        "Google",
        "training",
        "https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers#google-extended",
        "A robots.txt token, not a separate crawler. Controls use of content for Gemini model "
        "training and grounding. Does not affect Google Search ranking or inclusion; AI "
        "Overviews are part of Search and use Googlebot.",
    ),
    AIBot(
        "Applebot-Extended",
        "Apple",
        "training",
        "https://support.apple.com/en-us/119829",
        "A token, not a crawler: controls whether Applebot-crawled content trains Apple's "
        "foundation models. Applebot itself (Siri/Spotlight search) is unaffected.",
    ),
    AIBot(
        "CCBot",
        "Common Crawl",
        "training",
        "https://commoncrawl.org/ccbot",
        "Builds the open Common Crawl dataset, widely used to train LLMs (and for research).",
    ),
    AIBot(
        "Bytespider",
        "ByteDance",
        "training",
        None,
        "No official documentation found. If it ignores robots.txt, block it at the server/CDN.",
    ),
    AIBot(
        "Meta-ExternalAgent",
        "Meta",
        "training",
        "https://developers.facebook.com/docs/sharing/webmasters/web-crawlers",
        "Used for purposes such as training AI models or improving products.",
    ),
    AIBot(
        "Amazonbot",
        "Amazon",
        "training",
        "https://developer.amazon.com/amazonbot",
        "Amazon says data may be used to improve products and services, including training AI "
        "models; it also supports Alexa answers.",
    ),
    AIBot(
        "cohere-ai",
        "Cohere",
        "training",
        None,
        "Commonly listed token; Cohere publishes no crawler documentation (unverified).",
    ),
)

BY_TOKEN = {b.token.lower(): b for b in AI_BOTS}


def resolve_policy(preset: str, overrides: Mapping[str, str]) -> dict[str, str]:
    """Map every bot token to 'allow' or 'deny' from a preset plus per-bot overrides."""
    policy: dict[str, str] = {}
    for bot in AI_BOTS:
        if preset == "allow-all" or preset == "custom":
            decision = "allow"
        elif preset == "deny-all":
            decision = "deny"
        else:  # search-only: be cited and linked, but opt out of training
            decision = "deny" if bot.purpose == "training" else "allow"
        policy[bot.token] = decision
    for token, decision in overrides.items():
        match = BY_TOKEN.get(token.lower())
        policy[match.token if match else token] = decision
    return policy


@dataclass(frozen=True, slots=True)
class BotAccess:
    token: str
    operator: str
    purpose: str
    allowed: bool  # can fetch the homepage under the live robots.txt
    explicit: bool  # robots.txt has a group naming this bot
    docs: str | None
    note: str


def current_access(
    robots: RobotsTxt, site: str, extra_tokens: list[str] | None = None
) -> list[BotAccess]:
    home = site.rstrip("/") + "/"
    bots = list(AI_BOTS) + [
        AIBot(t, "custom", "training", None)
        for t in (extra_tokens or [])
        if t.lower() not in BY_TOKEN
    ]
    return [
        BotAccess(
            token=b.token,
            operator=b.operator,
            purpose=b.purpose,
            allowed=robots.can_fetch(b.token, home),
            explicit=robots.has_group_for(b.token),
            docs=b.docs,
            note=b.note,
        )
        for b in bots
    ]
