#!/usr/bin/env python3
"""Generate static HTML pages from the LibGuide export."""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

# ---------------------------------------------------------------------------
# Site structure definition
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.replace("&", " and ")
    ascii_text = ascii_text.replace("'", "")
    ascii_text = ascii_text.replace("\u2019", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug.lower()

@dataclass(frozen=True)
class Page:
    title: str
    slug: str
    children: Tuple["Page", ...] = ()

    @classmethod
    def build(cls, title: str, children: Sequence["Page"] | None = None) -> "Page":
        return cls(title=title, slug=slugify(title), children=tuple(children or ()))

SITE_PAGES: Tuple[Page, ...] = (
    Page(
        title="Pillars of AI Literacy",
        slug="index",
    ),
    Page.build(
        "Authentic Learning and AI Use",
        (
            Page.build("Learning is Hard - and it's supposed to be"),
        ),
    ),
    Page.build(
        "Understand and Explore Generative AI",
        (
            Page.build("Gen AI Fundamentals"),
            Page.build("Gen AI - Behind the Curtain"),
            Page.build("Gen AI Tools, Platforms, and Interfaces"),
            Page.build("Potential and Limitations of Gen AI"),
        ),
    ),
    Page.build(
        "Analyze and Apply Gen AI",
        (
            Page.build("Essentials for Smart Engagement"),
            Page.build("AI Quick Queries & Idea Sparker"),
            Page.build("AI Study Buddy & Skill Builder"),
            Page.build("AI-Generated Writing: Effective and Ethical Use"),
            Page.build("AI Research Assistants"),
            Page.build("AI Risks & Ethical Considerations"),
            Page.build("AI's Jagged Frontier"),
        ),
    ),
    Page.build("AI Contribution Statement"),
)

PAGE_BY_TITLE: Dict[str, Page] = {}

def register_pages(pages: Iterable[Page]) -> None:
    for page in pages:
        PAGE_BY_TITLE[page.title] = page
        register_pages(page.children)

register_pages(SITE_PAGES)

PAGE_IDS: Dict[str, str] = {}

# ---------------------------------------------------------------------------
# HTML parsing utilities
# ---------------------------------------------------------------------------

SELF_CLOSING_TAGS = {
    "br",
    "img",
    "hr",
    "meta",
    "link",
    "input",
    "source",
    "track",
    "col",
    "area",
    "base",
}

SKIP_TAGS = {"script", "style", "noscript", "button"}

ATTRIBUTE_BLOCKLIST_PREFIXES = ("data-", "on")
ATTRIBUTE_BLOCKLIST = {
    "class",
    "style",
    "role",
    "tabindex",
    "aria-hidden",
    "aria-expanded",
}


class Node:
    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag: str | None = None, attrs: Dict[str, str] | None = None, text: str | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: List[Node] = []
        self.text = text

    def append(self, node: "Node") -> None:
        self.children.append(node)


class DOMBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str | None]]) -> None:
        node = Node(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].append(node)
        if tag not in SELF_CLOSING_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, str | None]]) -> None:
        node = Node(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[: index]
                break

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self.stack[-1].append(Node(text=data))

    def handle_comment(self, data: str) -> None:
        # Ignore comments entirely
        return


def parse_fragment(fragment: str) -> Node:
    parser = DOMBuilder()
    parser.feed(fragment)
    return parser.root


def iter_nodes(node: Node) -> Iterable[Node]:
    for child in node.children:
        yield child
        if child.tag is not None:
            yield from iter_nodes(child)


def find_content_nodes(root: Node) -> List[Node]:
    nodes: List[Node] = []
    for node in iter_nodes(root):
        if node.tag == "div" and node.attrs.get("id", "").startswith("s-lg-content-"):
            nodes.append(node)
    return nodes


def sanitize_attributes(attrs: Dict[str, str]) -> Dict[str, str]:
    cleaned: Dict[str, str] = {}
    for key, value in attrs.items():
        if key in ATTRIBUTE_BLOCKLIST:
            continue
        if any(key.startswith(prefix) for prefix in ATTRIBUTE_BLOCKLIST_PREFIXES):
            continue
        if value is None:
            continue
        if key == "id" and (
            value.startswith("s-lg-") or value.startswith("s-lib-") or value.startswith("genai-")
        ):
            continue
        cleaned[key] = value
    return cleaned


def node_to_html(node: Node) -> str:
    if node.tag is None:
        return html.escape(node.text or "")
    if node.tag in SKIP_TAGS:
        return ""
    attrs = sanitize_attributes(node.attrs)
    attributes = "".join(
        f' {name}="{html.escape(value, quote=True)}"'
        for name, value in attrs.items()
    )
    children_html = "".join(node_to_html(child) for child in node.children)
    if node.tag in SELF_CLOSING_TAGS:
        return f"<{node.tag}{attributes}>"
    return f"<{node.tag}{attributes}>{children_html}</{node.tag}>"


# ---------------------------------------------------------------------------
# Link normalisation
# ---------------------------------------------------------------------------

INTERNAL_GUIDE_PATTERN = re.compile(r"https://libguides\.okanagan\.bc\.ca/c\.php\?g=743006(?:&amp;|&)p=(\d+)(#[^\"']*)?")
LIBGUIDE_HOME_PATTERN = re.compile(r"https://libguides\.okanagan\.bc\.ca/ai-literacy(#[^\"']*)?")
LIBGUIDE_PAGE_PATTERN = re.compile(r"https://libguides\.okanagan\.bc\.ca/c\.php\?g=743006(#[^\"']*)?")
HASHED_INTERNAL_PATTERN = re.compile(r"#https://libguides\.okanagan\.bc\.ca/c\.php\?g=743006(?:&amp;|&)p=(\d+)(#[^\"']*)?")

ID_ALIASES = {
    "5369872": "Gen AI - Behind the Curtain",
}


def update_internal_links(content: str, id_to_slug: Dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        page_id, anchor = match.groups()
        slug = id_to_slug.get(page_id)
        if not slug:
            return match.group(0)
        suffix = anchor or ""
        return f"{slug}.html{suffix}"

    content = INTERNAL_GUIDE_PATTERN.sub(lambda m: replace(m), content)
    content = LIBGUIDE_HOME_PATTERN.sub(lambda m: f"index.html{m.group(1) or ''}", content)
    content = LIBGUIDE_PAGE_PATTERN.sub(lambda m: f"index.html{m.group(1) or ''}", content)

    def replace_hash(match: re.Match[str]) -> str:
        page_id, anchor = match.groups()
        slug = id_to_slug.get(page_id)
        if not slug:
            return match.group(0)
        suffix = anchor or ""
        return f"{slug}.html{suffix}"

    content = HASHED_INTERNAL_PATTERN.sub(lambda m: replace_hash(m), content)
    content = re.sub(r'href="#([^"#]+\.html)"', r'href="\1"', content)
    return content


# ---------------------------------------------------------------------------
# Navigation rendering
# ---------------------------------------------------------------------------

def build_nav_list(pages: Sequence[Page], current_slug: str) -> Tuple[str, bool]:
    items: List[str] = []
    contains_current = False
    for page in pages:
        child_html, child_active = build_nav_list(page.children, current_slug)
        is_current = page.slug == current_slug
        active = is_current or child_active
        classes = []
        if active:
            classes.append("active")
        if page.children:
            classes.append("has-children")
        class_attr = f' class="{" ".join(classes)}"' if classes else ""
        items.append(
            f"<li{class_attr}><a href='{page.slug}.html'>{html.escape(page.title)}</a>{child_html}</li>"
        )
        contains_current = contains_current or active
    if not items:
        return "", contains_current
    return f"<ul class='nav-list'>{''.join(items)}</ul>", contains_current


def render_navigation(current_slug: str) -> str:
    nav_html, _ = build_nav_list(SITE_PAGES, current_slug)
    return nav_html


# ---------------------------------------------------------------------------
# Page template
# ---------------------------------------------------------------------------

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{title} - AI Literacy for Students</title>
    <link rel=\"stylesheet\" href=\"styles.css\" />
</head>
<body>
    <header>
        <div class=\"site-title\">
            <h1><a href=\"index.html\">AI Literacy for Students</a></h1>
            <p class=\"tagline\">Understand, explore, and apply generative AI responsibly.</p>
        </div>
    </header>
    <nav>
        {navigation}
    </nav>
    <main>
        <h2>{title}</h2>
        {content}
    </main>
    <footer>
        <p>&copy; {year} AI Literacy for Students.</p>
    </footer>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Main routine
# ---------------------------------------------------------------------------

PAGE_SECTION_PATTERN = re.compile(
    r'<div id="s-lg-page-section-(\d+)" class="s-lg-page-section clearfix"><h4 class="pull-left">([^<]+)</h4></div>'
)


def extract_page_fragments(html_source: str) -> Dict[str, str]:
    fragments: Dict[str, str] = {}
    matches = list(PAGE_SECTION_PATTERN.finditer(html_source))
    for index, match in enumerate(matches):
        page_id, title = match.groups()
        PAGE_IDS[title] = page_id
        if title not in PAGE_BY_TITLE:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html_source)
        fragments[title] = html_source[start:end]
    return fragments


def sanitize_fragment(fragment: str) -> str:
    root = parse_fragment(fragment)
    content_nodes = find_content_nodes(root)
    if not content_nodes:
        return ""
    return "".join(node_to_html(node) for node in content_nodes)


def build_pages() -> None:
    source_html = Path("originals/ai-literacy-libguide-full.html").read_text(encoding="utf-8")
    fragments = extract_page_fragments(source_html)

    id_to_slug = {PAGE_IDS[title]: PAGE_BY_TITLE[title].slug for title in fragments}
    for alias_id, alias_title in ID_ALIASES.items():
        if alias_title in PAGE_BY_TITLE:
            id_to_slug[alias_id] = PAGE_BY_TITLE[alias_title].slug
    site_dir = Path("site")
    site_dir.mkdir(parents=True, exist_ok=True)

    for title, fragment in fragments.items():
        page = PAGE_BY_TITLE[title]
        clean_html = sanitize_fragment(fragment)
        clean_html = update_internal_links(clean_html, id_to_slug)
        navigation = render_navigation(page.slug)
        page_html = PAGE_TEMPLATE.format(
            title=html.escape(title),
            navigation=navigation,
            content=clean_html,
            year="2024",
        )
        Path(site_dir, f"{page.slug}.html").write_text(page_html, encoding="utf-8")


def main() -> None:
    build_pages()


if __name__ == "__main__":
    main()
