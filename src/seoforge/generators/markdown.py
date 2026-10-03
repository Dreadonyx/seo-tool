"""Convert a page's main content to clean Markdown (for mirrors and llms-full.txt)."""

from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser, LexborNode

from seoforge.crawler.parser import BOILERPLATE, NON_CONTENT, main_content_node
from seoforge.urls import normalize

SKIP = set(NON_CONTENT.replace(" ", "").split(",")) | {
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "input",
    "select",
    "dialog",
}
BLOCK = {
    "p",
    "div",
    "section",
    "article",
    "main",
    "ul",
    "ol",
    "li",
    "table",
    "pre",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "figure",
    "figcaption",
    "hr",
    "dl",
    "dt",
    "dd",
    "details",
    "summary",
}
WS = re.compile(r"[ \t\r\f\v]+")


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


class _Converter:
    def __init__(self, base: str) -> None:
        self.base = base

    def inline(self, node: LexborNode) -> str:
        out: list[str] = []
        child = node.child
        while child is not None:
            out.append(self.inline_node(child))
            child = child.next
        return WS.sub(" ", "".join(out))

    def inline_node(self, node: LexborNode) -> str:
        tag = node.tag or ""
        if tag == "-text":
            return node.text_content or ""
        if tag in SKIP or tag == "-comment":
            return ""
        if tag == "br":
            return "  \n"
        if tag in ("strong", "b"):
            inner = self.inline(node).strip()
            return f"**{inner}**" if inner else ""
        if tag in ("em", "i"):
            inner = self.inline(node).strip()
            return f"*{inner}*" if inner else ""
        if tag == "code":
            return f"`{node.text()}`"
        if tag == "a":
            text = self.inline(node).strip()
            href = normalize(node.attributes.get("href") or "", self.base)
            if not text:
                return ""
            return f"[{text}]({href})" if href else text
        if tag == "img":
            alt = (node.attributes.get("alt") or "").strip()
            src = normalize(node.attributes.get("src") or "", self.base)
            return f"![{alt}]({src})" if alt and src else ""
        if tag in BLOCK:
            return "\n\n" + self.block(node) + "\n\n"
        return self.inline(node)

    def block(self, node: LexborNode, depth: int = 0) -> str:
        tag = node.tag or ""
        if tag in SKIP:
            return ""
        if tag and tag[0] == "h" and tag[1:].isdigit():
            return "#" * int(tag[1]) + " " + self.inline(node).strip()
        if tag == "p" or tag == "summary" or tag == "figcaption" or tag == "dt":
            return self.inline(node).strip()
        if tag == "dd":
            return ": " + self.inline(node).strip()
        if tag == "hr":
            return "---"
        if tag == "pre":
            return "```\n" + (node.text() or "").strip("\n") + "\n```"
        if tag == "blockquote":
            inner = self.children(node, depth)
            return "\n".join("> " + line if line else ">" for line in inner.splitlines())
        if tag in ("ul", "ol"):
            lines = []
            n = 1
            child = node.child
            while child is not None:
                if child.tag == "li":
                    marker = f"{n}." if tag == "ol" else "-"
                    body = self.children(child, depth + 1).strip()
                    first, *rest = body.splitlines() or [""]
                    lines.append(f"{marker} {first}")
                    pad = " " * (len(marker) + 1)
                    lines.extend(pad + r for r in rest if r.strip())
                    n += 1
                child = child.next
            return "\n".join(lines)
        if tag == "table":
            rows = []
            for tr in node.css("tr"):
                cells = [_escape_cell(self.inline(c)) for c in tr.css("th, td")]
                if cells:
                    rows.append(cells)
            if not rows:
                return ""
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
            out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            return "\n".join(out)
        return self.children(node, depth)

    def children(self, node: LexborNode, depth: int = 0) -> str:
        parts: list[str] = []
        inline_buf: list[str] = []

        def flush() -> None:
            text = WS.sub(" ", "".join(inline_buf)).strip()
            if text:
                parts.append(text)
            inline_buf.clear()

        child = node.child
        while child is not None:
            tag = child.tag or ""
            if tag in BLOCK:
                flush()
                rendered = self.block(child, depth)
                if rendered.strip():
                    parts.append(rendered)
            else:
                inline_buf.append(self.inline_node(child))
            child = child.next
        flush()
        return "\n\n".join(parts)


def html_to_markdown(
    html: str, base: str, title: str | None = None, source_url: str | None = None
) -> str:
    tree = LexborHTMLParser(html)
    for node in tree.css(NON_CONTENT):
        node.decompose()
    root = main_content_node(tree)
    if root is None:
        return ""
    if root.tag == "body":
        for node in root.css(BOILERPLATE):
            node.decompose()
    body = _Converter(base).children(root)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    header = []
    if title and not body.startswith("# "):
        header.append(f"# {title}")
    if source_url:
        header.append(f"Source: {source_url}")
    return ("\n\n".join([*header, body]) if header else body) + "\n"
