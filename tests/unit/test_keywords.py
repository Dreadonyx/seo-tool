from seoforge.analysis.keywords import (
    PageKeywords,
    classify_intent,
    cluster_phrases,
    find_cannibalization,
    ngrams,
    segments,
    tokenize,
)
from seoforge.models import PageData


def test_ngrams_skip_stopword_edges() -> None:
    tokens = tokenize("The best widget testing tools for teams")
    grams = ngrams(tokens, 2)
    assert "widget testing" in grams
    assert "the best" not in grams and "tools for" not in grams


def test_segments_do_not_cross_punctuation() -> None:
    segs = segments("Widget testing. Node.js tools, fast")
    assert ["widget", "testing"] in segs
    assert ["node.js", "tools"] in segs


def test_intent_rules() -> None:
    assert classify_intent("buy widget tester") == "transactional"
    assert classify_intent("best widget tools 2026") == "commercial"
    assert classify_intent("how to test widgets") == "informational"
    assert classify_intent("acme login") == "navigational"
    assert classify_intent("acme widgets", brand="Acme") == "navigational"
    assert classify_intent("widget") == "unknown"


def test_cannibalization_by_primary_and_title() -> None:
    pages = {
        u: PageData(url=u, final_url=u, status=200, title=t)
        for u, t in [
            ("a", "Widget Testing Guide For Teams"),
            ("b", "Widget Testing Guide For Teams"),
            ("c", "Pricing"),
        ]
    }
    kws = [
        PageKeywords("a", "widget testing"),
        PageKeywords("b", "widget tests"),
        PageKeywords("c", "pricing"),
    ]
    found = find_cannibalization(kws, pages)
    assert found["widget testing"] == ["a", "b"]
    assert any(k.startswith("title:") for k in found)


def test_clustering_groups_similar_phrases() -> None:
    clusters, method = cluster_phrases(
        ["widget testing", "widget testing tools", "test widgets", "pricing plans", "plan pricing"]
    )
    groups = [set(c["keywords"]) for c in clusters]
    assert any({"widget testing", "widget testing tools"} <= g for g in groups)
    assert any({"pricing plans", "plan pricing"} <= g for g in groups)
    assert method
