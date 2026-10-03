import json

from seoforge.analysis.structured_data import analyze_page, invisible_faq_questions
from seoforge.models import PageData


def page(*blocks: object, text: str = "") -> PageData:
    p = PageData(url="https://s.test/p", final_url="https://s.test/p", status=200)
    p.json_ld = [b if isinstance(b, str) else json.dumps(b) for b in blocks]
    p.text = text
    return p


def messages(p: PageData) -> list[str]:
    return [f"{x.level}:{x.type}:{x.message}" for i in analyze_page(p).items for x in i.problems]


def test_invalid_json_reported() -> None:
    result = analyze_page(page("{ broken"))
    assert result.parse_errors and "Invalid JSON" in result.parse_errors[0]


def test_required_and_recommended() -> None:
    msgs = messages(
        page({"@context": "https://schema.org", "@type": "Product", "description": "x"})
    )
    assert "error:Product:missing required 'name'" in msgs
    assert any(m.startswith("warning:Product:missing recommended 'offers") for m in msgs)


def test_graph_nested_and_context() -> None:
    doc = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BlogPosting",
                "headline": "H",
                "datePublished": "March 3",
                "author": {"@type": "Person"},
            },
            {"@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 2}]},
        ],
    }
    msgs = messages(page(doc))
    assert any("datePublished 'March 3' is not ISO 8601" in m for m in msgs)
    assert "error:Person:missing required 'name'" in msgs  # nested author validated
    assert any("position should be 1" in m for m in msgs)
    no_ctx = messages(page({"@type": "Organization", "name": "X"}))
    assert any("@context" in m for m in no_ctx)


def test_local_business_subtype_and_alternatives() -> None:
    msgs = messages(page({"@context": "https://schema.org", "@type": "Dentist", "name": "D"}))
    assert "error:LocalBusiness:missing required 'address'" in msgs
    offer = {"@context": "https://schema.org", "@type": "Offer", "priceSpecification": {"x": 1}}
    assert not [m for m in messages(page(offer)) if m.startswith("error")]


def test_faq_visibility() -> None:
    faq = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Is it free?",
                "acceptedAnswer": {"@type": "Answer", "text": "Yes"},
            },
            {
                "@type": "Question",
                "name": "Hidden question?",
                "acceptedAnswer": {"@type": "Answer", "text": "x"},
            },
        ],
    }
    p = page(faq, text="Is it free? Yes it is.")
    assert invisible_faq_questions(p, analyze_page(p)) == ["Hidden question?"]
