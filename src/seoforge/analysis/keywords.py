"""Keyword extraction (TF-IDF, YAKE, n-grams), intent classification, clustering and
keyword-to-page mapping with cannibalization detection. All local; no paid APIs."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

from seoforge.models import PageData

Intent = Literal["informational", "commercial", "transactional", "navigational", "unknown"]

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "aren't",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "can't",
        "cannot",
        "could",
        "couldn't",
        "did",
        "didn't",
        "do",
        "does",
        "doesn't",
        "doing",
        "don't",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "hadn't",
        "has",
        "hasn't",
        "have",
        "haven't",
        "having",
        "he",
        "he'd",
        "he'll",
        "he's",
        "her",
        "here",
        "here's",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "how's",
        "i",
        "i'd",
        "i'll",
        "i'm",
        "i've",
        "if",
        "in",
        "into",
        "is",
        "isn't",
        "it",
        "it's",
        "its",
        "itself",
        "let's",
        "me",
        "more",
        "most",
        "mustn't",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "ought",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "shan't",
        "she",
        "she'd",
        "she'll",
        "she's",
        "should",
        "shouldn't",
        "so",
        "some",
        "such",
        "than",
        "that",
        "that's",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "there's",
        "these",
        "they",
        "they'd",
        "they'll",
        "they're",
        "they've",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "wasn't",
        "we",
        "we'd",
        "we'll",
        "we're",
        "we've",
        "were",
        "weren't",
        "what",
        "what's",
        "when",
        "when's",
        "where",
        "where's",
        "which",
        "while",
        "who",
        "who's",
        "whom",
        "why",
        "why's",
        "will",
        "with",
        "won't",
        "would",
        "wouldn't",
        "you",
        "you'd",
        "you'll",
        "you're",
        "you've",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "also",
        "may",
        "might",
        "must",
        "shall",
        "us",
        "via",
        "per",
        "etc",
        "just",
        "get",
        "got",
        "use",
        "used",
        "using",
        "one",
        "two",
        "new",
        "like",
        "within",
        "without",
        "across",
        "s",
        "t",
        "re",
        "ve",
        "ll",
        "d",
        "m",
    ]
)

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'’+#.-]*[a-z0-9+#]|[a-z0-9]", re.I)

INTENT_PATTERNS: list[tuple[Intent, re.Pattern[str]]] = [
    (
        "transactional",
        re.compile(
            r"\b(buy|price|pricing|prices|cost|cheap|discount|coupon|deal|order|purchase|subscribe|"
            r"download|free trial|sign ?up|quote|hire|book|shop|for sale|checkout|plans?)\b",
            re.I,
        ),
    ),
    (
        "commercial",
        re.compile(
            r"\b(best|top \d*|vs\.?|versus|review|reviews|compare|comparison|alternatives?|"
            r"ranking|rated|recommended|pros and cons)\b",
            re.I,
        ),
    ),
    (
        "navigational",
        re.compile(
            r"\b(login|log in|sign in|contact|about us|careers|support|dashboard|account|"
            r"official site|homepage)\b",
            re.I,
        ),
    ),
    (
        "informational",
        re.compile(
            r"\b(how|what|why|when|where|who|which|guide|tutorial|tips|learn|examples?|ideas|"
            r"definition|meaning|explained|introduction|vs what|faq|steps?|checklist)\b",
            re.I,
        ),
    ),
]


SEGMENT_RE = re.compile(r"[!?;:,()\[\]{}|\n\"“”•·–—/]+\s*|\.(?:\s+|$)|\s-\s")


def tokenize(text: str) -> list[str]:
    return [t.lower().strip(".'’") for t in TOKEN_RE.findall(text)]


def segments(text: str) -> list[list[str]]:
    """Token lists per phrase segment; n-grams never cross punctuation or block boundaries."""
    return [toks for part in SEGMENT_RE.split(text) if (toks := tokenize(part))]


def content_blocks(page: PageData) -> list[str]:
    return page.blocks or [page.text]


def ngrams(tokens: list[str], n: int) -> list[str]:
    out = []
    for i in range(len(tokens) - n + 1):
        gram = tokens[i : i + n]
        if gram[0] in STOPWORDS or gram[-1] in STOPWORDS:
            continue
        if any(t.isdigit() and len(t) < 3 for t in gram) or any(len(t) < 2 for t in gram):
            continue
        out.append(" ".join(gram))
    return out


def page_terms(page: PageData, max_n: int = 3) -> Counter[str]:
    """Weighted n-gram counts: body x1, H2/H3 x2, H1 x3, title x3, meta description x2."""
    counts: Counter[str] = Counter()
    heading_texts = {h.text for h in page.headings}
    weighted = [(b, 1) for b in content_blocks(page) if b not in heading_texts]
    weighted += [(page.title or "", 3), (page.meta_description or "", 2)]
    weighted += [(h.text, 3 if h.level == 1 else 2) for h in page.headings if h.level <= 3]
    for text, weight in weighted:
        for tokens in segments(text):
            for n in range(1, max_n + 1):
                for gram in ngrams(tokens, n):
                    counts[gram] += weight
    return counts


def tfidf(pages: list[PageData], top: int = 15) -> dict[str, list[tuple[str, float]]]:
    docs = {p.url: page_terms(p) for p in pages}
    n_docs = len(docs)
    df: Counter[str] = Counter()
    for counts in docs.values():
        df.update(counts.keys())
    out: dict[str, list[tuple[str, float]]] = {}
    for url, counts in docs.items():
        total = sum(counts.values()) or 1
        scores = {}
        for term, c in counts.items():
            if c < 2 and " " not in term:
                continue
            idf = math.log((n_docs + 1) / (df[term] + 1)) + 1
            # Favour multi-word phrases slightly: they are closer to real search queries.
            scores[term] = (c / total) * idf * (1 + 0.3 * term.count(" "))
        out[url] = sorted(scores.items(), key=lambda kv: -kv[1])[:top]
    return out


def yake_keywords(text: str, top: int = 10, lang: str = "en") -> list[tuple[str, float]]:
    """YAKE (unsupervised, single-document). Lower score = more relevant."""
    if len(text.split()) < 20:
        return []
    try:
        import yake

        extractor = yake.KeywordExtractor(lan=lang[:2] or "en", n=3, top=top, dedupLim=0.8)
        return [(kw.lower(), float(score)) for kw, score in extractor.extract_keywords(text)]
    except Exception:  # pragma: no cover - YAKE is optional at runtime
        return []


def classify_intent(phrase: str, page: PageData | None = None, brand: str | None = None) -> Intent:
    """Rule-based intent estimate from query modifiers, then page signals."""
    for intent, pattern in INTENT_PATTERNS:
        if pattern.search(phrase):
            return intent
    if brand and brand.lower() in phrase.lower():
        return "navigational"
    if page is not None:
        blob = " ".join(page.json_ld).lower()
        if '"product"' in blob or '"offer"' in blob:
            return "transactional"
        if any(t in blob for t in ('"article"', '"blogposting"', '"newsarticle"', '"howto"')):
            return "informational"
        path = urlsplit(page.url).path.strip("/")
        if path in ("", "about", "about-us", "contact", "contact-us", "login", "careers"):
            return "navigational"
        signals = " ".join([page.title or ""] + [h.text for h in page.headings[:5]])
        for intent, pattern in INTENT_PATTERNS:
            if pattern.search(signals):
                return intent
    return "unknown"


def _stem_word(w: str) -> str:
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _stem(phrase: str) -> str:
    """Light normalization so 'tools'/'tool' and 'testing'/'tests' collide; not a real stemmer."""
    return " ".join(_stem_word(w) for w in phrase.split())


@dataclass(slots=True)
class PageKeywords:
    url: str
    primary: str | None
    secondary: list[str] = field(default_factory=list)
    intent: Intent = "unknown"
    tfidf: list[tuple[str, float]] = field(default_factory=list)
    yake: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "primary": self.primary,
            "secondary": self.secondary,
            "intent": self.intent,
            "tfidf": [[t, round(s, 5)] for t, s in self.tfidf],
            "yake": [[t, round(s, 5)] for t, s in self.yake],
        }


@dataclass(slots=True)
class KeywordReport:
    pages: list[PageKeywords] = field(default_factory=list)
    cannibalization: dict[str, list[str]] = field(default_factory=dict)
    clusters: list[dict[str, Any]] = field(default_factory=list)
    clustering_method: str = "tfidf"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": [p.to_dict() for p in self.pages],
            "cannibalization": self.cannibalization,
            "clusters": self.clusters,
            "clustering_method": self.clustering_method,
            "note": "Keywords are extracted from your own content. Search volumes are not "
            "included because no free, reliable source exists.",
        }


def analyze(pages: list[PageData], cluster: bool = True, brand: str | None = None) -> KeywordReport:
    pages = [p for p in pages if p.is_indexable and p.word_count > 0]
    report = KeywordReport()
    if not pages:
        return report
    tf = tfidf(pages)
    for p in pages:
        blob = ".\n".join(filter(None, [p.title, *p.h1s, *content_blocks(p)]))
        yk = yake_keywords(blob[:20000], lang=p.lang or "en")
        title_blob = " ".join([p.title or "", *p.h1s]).lower()
        candidates: dict[str, float] = defaultdict(float)
        for rank, (term, _) in enumerate(tf[p.url][:10]):
            candidates[term] += 10 - rank
        for rank, (term, _) in enumerate(yk[:10]):
            candidates[term] += 10 - rank
        for term in list(candidates):
            if term in title_blob:
                candidates[term] *= 1.5 + 0.5 * term.count(" ")
        ranked = sorted(candidates, key=lambda t: -candidates[t])
        primary = ranked[0] if ranked else None
        report.pages.append(
            PageKeywords(
                url=p.url,
                primary=primary,
                secondary=ranked[1:6],
                intent=classify_intent(primary or "", p, brand),
                tfidf=tf[p.url],
                yake=yk,
            )
        )
    report.cannibalization = find_cannibalization(report.pages, {p.url: p for p in pages})
    if cluster:
        phrases = sorted({k for pk in report.pages for k in [pk.primary, *pk.secondary] if k})
        report.clusters, report.clustering_method = cluster_phrases(phrases)
    return report


def find_cannibalization(
    keywords: list[PageKeywords], pages: dict[str, PageData]
) -> dict[str, list[str]]:
    """Pages whose primary keyword (and title focus) collide."""
    groups: dict[str, list[str]] = defaultdict(list)
    labels: dict[str, str] = {}
    for pk in keywords:
        if pk.primary and " " in pk.primary:  # single words are too broad to call cannibalization
            key = _stem(pk.primary)
            labels.setdefault(key, pk.primary)
            groups[key].append(pk.url)
    out = {labels[k]: sorted(v) for k, v in groups.items() if len(v) > 1}
    # Title overlap check: near-identical title word sets also compete.
    titles = {u: set(tokenize(p.title or "")) - STOPWORDS for u, p in pages.items()}
    urls = sorted(titles)
    for i, a in enumerate(urls):
        for b in urls[i + 1 :]:
            ta, tb = titles[a], titles[b]
            if len(ta) >= 3 and len(tb) >= 3 and len(ta & tb) / len(ta | tb) >= 0.8:
                key = "title: " + " ".join(sorted(ta & tb))
                out.setdefault(key, [])
                for u in (a, b):
                    if u not in out[key]:
                        out[key].append(u)
    return out


def _tfidf_vectors(phrases: list[str]) -> list[dict[str, float]]:
    """Character trigram vectors - robust for short phrases without a model."""
    vecs = []
    for ph in phrases:
        padded = f"  {ph} "
        grams = Counter(padded[i : i + 3] for i in range(len(padded) - 2))
        words = Counter(ph.split())
        grams.update({f"w:{w}": 3 * c for w, c in words.items() if w not in STOPWORDS})
        norm = math.sqrt(sum(v * v for v in grams.values())) or 1.0
        vecs.append({k: v / norm for k, v in grams.items()})
    return vecs


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def cluster_phrases(
    phrases: list[str], threshold: float | None = None
) -> tuple[list[dict[str, Any]], str]:
    """Greedy centroid clustering. Uses local sentence-transformers if installed."""
    if not phrases:
        return [], "none"
    method = "char-trigram-tfidf"
    vectors: list[dict[str, float]]
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        emb = model.encode(phrases, normalize_embeddings=True)
        vectors = [{str(i): float(x) for i, x in enumerate(row)} for row in emb]
        method = "sentence-transformers/all-MiniLM-L6-v2"
        threshold = threshold or 0.6
    except Exception:
        vectors = _tfidf_vectors(phrases)
        threshold = threshold or 0.45
    clusters: list[tuple[dict[str, float], list[int]]] = []
    for i, vec in enumerate(vectors):
        best, best_sim = None, threshold
        for c_idx, (centroid, _members) in enumerate(clusters):
            sim = _cos(vec, centroid) / max(1e-9, math.sqrt(_cos(centroid, centroid)))
            if sim >= best_sim:
                best, best_sim = c_idx, sim
        if best is None:
            clusters.append((dict(vec), [i]))
        else:
            centroid, members = clusters[best]
            for k, v in vec.items():
                centroid[k] = centroid.get(k, 0.0) + v
            members.append(i)
    out: list[dict[str, Any]] = []
    for _, members in clusters:
        terms = [phrases[i] for i in members]
        label = min(terms, key=lambda t: (len(t.split()) != 2, len(t)))
        out.append({"label": label, "keywords": terms, "size": len(terms)})
    out.sort(key=lambda c: -c["size"])
    return out, method
