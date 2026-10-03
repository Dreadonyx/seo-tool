"""Answer Engine Optimization: question coverage, concise answer blocks, FAQ sections, snippet
formatting and E-E-A-T signals. Everything is derived from the page's own text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from seoforge.analysis import pagetype as pt
from seoforge.analysis.keywords import KeywordReport
from seoforge.models import PageData

QUESTION_START = re.compile(
    r"^(what|how|why|when|where|who|whom|which|can|could|does|do|did|is|are|was|should|will|"
    r"would|has|have)\b",
    re.I,
)
FAQ_HEADING = re.compile(
    r"\b(faq|faqs|frequently asked|common questions|questions and answers)\b", re.I
)
DEFINITION = re.compile(r"\b(is|are|refers to|means)\s+(a|an|the)\b", re.I)
IDEAL = (40, 60)

TEMPLATES = {
    "informational": ["What is {kw}?", "How does {kw} work?", "Why is {kw} important?"],
    "commercial": [
        "What is the best {kw}?",
        "How do I choose a {kw}?",
        "{Kw} vs alternatives: which is better?",
    ],
    "transactional": ["How much does {kw} cost?", "Where can I get {kw}?", "Is {kw} worth it?"],
}


def is_question(text: str) -> bool:
    text = text.strip()
    return text.endswith("?") or bool(QUESTION_START.match(text))


@dataclass(slots=True)
class QA:
    question: str
    answer: str
    words: int
    list_items: int = 0  # answered with a list (snippet-friendly for steps / rankings)

    @property
    def ideal(self) -> bool:
        return IDEAL[0] <= self.words <= IDEAL[1] or self.list_items >= 3


@dataclass(slots=True)
class PageAEO:
    url: str
    questions: list[str] = field(default_factory=list)  # existing question headings
    suggested_questions: list[str] = field(default_factory=list)  # template-based
    qa: list[QA] = field(default_factory=list)
    drafts: dict[str, str] = field(default_factory=dict)  # question -> trimmed draft from page text
    has_faq: bool = False
    has_definition: bool = False
    has_steps: bool = False
    has_table: bool = False
    is_article: bool = False
    eeat: dict[str, bool] = field(default_factory=dict)
    author: str | None = None
    published: str | None = None
    modified: str | None = None
    citations: int = 0

    @property
    def answer_blocks(self) -> int:
        return sum(1 for q in self.qa if q.ideal)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "questions": self.questions + [f"(suggested) {q}" for q in self.suggested_questions],
            "question_headings": len(self.questions),
            "answer_blocks": self.answer_blocks,
            "answers": [
                {
                    "question": q.question,
                    "words": q.words,
                    "list_items": q.list_items,
                    "ideal": q.ideal,
                }
                for q in self.qa
            ],
            "drafts": self.drafts,
            "has_faq": self.has_faq,
            "has_definition": self.has_definition,
            "has_steps": self.has_steps,
            "has_table": self.has_table,
            "is_article": self.is_article,
            "eeat": self.eeat,
            "author": self.author,
            "published": self.published,
            "modified": self.modified,
            "citations": self.citations,
        }


@dataclass(slots=True)
class SiteEEAT:
    about: str | None = None
    contact: str | None = None
    privacy: str | None = None
    terms: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "about": self.about,
            "contact": self.contact,
            "privacy": self.privacy,
            "terms": self.terms,
        }


@dataclass(slots=True)
class AEOReport:
    pages: list[PageAEO] = field(default_factory=list)
    site: SiteEEAT = field(default_factory=SiteEEAT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": [p.to_dict() for p in self.pages],
            "site": self.site.to_dict(),
            "note": "Suggested questions are templates built from extracted keywords; answer "
            "drafts are trimmed from your own page text. Edit both before publishing.",
        }


def _sections(page: PageData) -> list[tuple[str, list[tuple[str, str]]]]:
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for tag, text in page.outline:
        if tag == "h1":  # the H1 is the page topic; its 'answer' is the whole page
            sections.append(("", []))
        elif tag in ("h2", "h3", "h4", "h5", "h6", "summary", "dt"):
            sections.append((text, []))
        elif sections:
            sections[-1][1].append((tag, text))
    return sections


def draft_answer(text: str, max_words: int = IDEAL[1]) -> str:
    """Take whole sentences from the page text up to ~60 words. Never invents content."""
    out: list[str] = []
    count = 0
    for sentence in pt.sentences(text):
        n = len(sentence.split())
        if out and count + n > max_words:
            break
        out.append(sentence)
        count += n
    draft = " ".join(out)
    words = draft.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def analyze_page(page: PageData, primary: str | None, intent: str) -> PageAEO:
    result = PageAEO(url=page.url, is_article=pt.is_article(page))
    for heading, body in _sections(page):
        if not heading:
            continue
        if not is_question(heading):
            if FAQ_HEADING.search(heading):
                result.has_faq = True
            continue
        result.questions.append(heading)
        paragraphs = [text for tag, text in body if tag in ("p", "dd")]
        items = [text for tag, text in body if tag == "li"]
        if not paragraphs and not items:
            continue
        if not paragraphs or (body and body[0][0] == "li"):
            qa = QA(heading, " / ".join(items), sum(len(i.split()) for i in items), len(items))
        else:
            qa = QA(heading, paragraphs[0], len(paragraphs[0].split()), len(items))
        result.qa.append(qa)
        if not qa.ideal and paragraphs:
            draft = draft_answer(" ".join(paragraphs))
            if len(draft.split()) >= 15 and draft != qa.answer:
                result.drafts[heading] = draft
        if heading.lower().startswith("how") and any(tag == "li" for tag, _ in body):
            result.has_steps = True
    types = pt.schema_types(page)
    result.has_faq = result.has_faq or "FAQPage" in types or page.has_details
    result.has_table = page.tables_count > 0
    intro = " ".join(text for tag, text in page.outline[:6] if tag == "p")
    result.has_definition = bool(DEFINITION.search(intro))
    if primary and intent in ("informational", "commercial", "transactional"):
        existing = " ".join(result.questions).lower()
        for template in TEMPLATES[intent]:
            q = template.format(kw=primary, Kw=primary[:1].upper() + primary[1:])
            if primary.lower() not in existing or q.lower().split()[0] not in existing:
                result.suggested_questions.append(q)
    result.author = pt.author_name(page)
    result.published = pt.published_date(page)
    result.modified = pt.modified_date(page)
    result.citations = len(pt.citations(page))
    result.eeat = {
        "author": bool(result.author),
        "author_page": bool(pt.author_url(page)),
        "date": bool(result.published or result.modified),
        "citations": result.citations > 0,
    }
    return result


SITE_PAGES = {
    "about": re.compile(r"/(about|about-us|company|who-we-are|team)(/|$|\.html)", re.I),
    "contact": re.compile(r"/(contact|contact-us|support|get-in-touch)(/|$|\.html)", re.I),
    "privacy": re.compile(r"/(privacy|privacy-policy|datenschutz)(/|$|\.html)", re.I),
    "terms": re.compile(r"/(terms|terms-of-service|tos|legal|imprint|impressum)(/|$|\.html)", re.I),
}


def site_eeat(pages: list[PageData]) -> SiteEEAT:
    site = SiteEEAT()
    known = {link.url for p in pages for link in p.internal_links} | {p.url for p in pages}
    for key, pattern in SITE_PAGES.items():
        match = next((u for u in sorted(known) if pattern.search(urlsplit(u).path)), None)
        setattr(site, key, match)
    return site


def analyze(pages: list[PageData], keywords: KeywordReport | None) -> AEOReport:
    kw = {p.url: p for p in keywords.pages} if keywords else {}
    report = AEOReport(site=site_eeat(pages))
    for page in pages:
        if not page.is_indexable:
            continue
        info = kw.get(page.url)
        report.pages.append(
            analyze_page(page, info.primary if info else None, info.intent if info else "unknown")
        )
    return report
