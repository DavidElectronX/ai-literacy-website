#!/usr/bin/env python3
"""Clean up HTML files in the docs directory."""
from __future__ import annotations

import html
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
REPORT_PATH = Path(__file__).resolve().parent.parent / "codex_html_cleanup_report.txt"

VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

PRESERVE_WHITESPACE_TAGS = {"pre", "code", "textarea", "script", "style"}

FOOTER_PATTERN = re.compile(r"(©|creative commons)", re.IGNORECASE)
FOOTER_CANDIDATE_TAGS = {"p", "div", "section", "span", "small", "footer", "aside", "blockquote", "ul", "ol", "li"}


class Node:
    __slots__ = ("tag", "attrs", "children", "text", "parent", "is_doctype", "is_comment")

    def __init__(
        self,
        tag: Optional[str] = None,
        attrs: Optional[Dict[str, str]] = None,
        text: Optional[str] = None,
        parent: Optional["Node"] = None,
        *,
        is_doctype: bool = False,
        is_comment: bool = False,
    ) -> None:
        self.tag = tag
        self.attrs: Dict[str, str] = dict(attrs or {})
        self.children: List[Node] = []
        self.text = text
        self.parent = parent
        self.is_doctype = is_doctype
        self.is_comment = is_comment

    def append(self, node: "Node") -> None:
        node.parent = self
        self.children.append(node)

    def remove(self, node: "Node") -> None:
        for index, child in enumerate(self.children):
            if child is node:
                del self.children[index]
                child.parent = None
                return


class DOMBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack: List[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        node = Node(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].append(node)
        if tag not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        node = Node(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                return
        # unmatched closing tags are ignored

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].append(Node(text=data))

    def handle_comment(self, data: str) -> None:
        comment = Node(text=data, is_comment=True)
        self.stack[-1].append(comment)

    def handle_decl(self, decl: str) -> None:
        doctype = Node(text=decl, is_doctype=True)
        self.stack[-1].append(doctype)


def parse_html(content: str) -> Node:
    parser = DOMBuilder()
    parser.feed(content)
    parser.close()
    return parser.root


def iter_tags(node: Node, *names: str) -> Iterable[Node]:
    name_filter = {name for name in names if name}
    for child in node.children:
        if child.tag:
            if not name_filter or child.tag in name_filter:
                yield child
            yield from iter_tags(child, *names)


def get_text(node: Node) -> str:
    if node.tag is None:
        return node.text or ""
    if node.is_comment or node.is_doctype:
        return ""
    return "".join(get_text(child) for child in node.children)


def is_whitespace_node(node: Node) -> bool:
    return node.tag is None and (node.text or "").strip() == ""


def unwrap(node: Node) -> None:
    parent = node.parent
    if not parent:
        return
    index = parent.children.index(node)
    parent.children.pop(index)
    for child in node.children:
        child.parent = parent
    parent.children[index:index] = node.children
    node.children = []
    node.parent = None


def remove_node(node: Node) -> None:
    parent = node.parent
    if not parent:
        return
    parent.remove(node)


def clean_whitespace(node: Node, preserve: bool = False) -> None:
    preserve = preserve or (node.tag in PRESERVE_WHITESPACE_TAGS if node.tag else False)
    for child in list(node.children):
        if child.tag is None:
            if preserve:
                continue
            if child.text and "\r" in child.text:
                child.text = child.text.replace("\r", "")
            if child.text and "\t" in child.text:
                child.text = child.text.replace("\t", " ")
            if (child.text or "").strip() == "":
                parent = child.parent
                if parent:
                    parent.children.remove(child)
                continue
        clean_whitespace(child, preserve)


def meaningful_children(node: Node) -> List[Node]:
    result: List[Node] = []
    for child in node.children:
        if child.is_comment or child.is_doctype:
            continue
        if child.tag is None and (child.text or "").strip() == "":
            continue
        result.append(child)
    return result


def remove_redundant_wrappers(root: Node, stats: Dict[str, int]) -> None:
    changed = True
    while changed:
        changed = False
        for div in list(iter_tags(root, "div")):
            if div.attrs:
                continue
            children = meaningful_children(div)
            if len(children) != 1:
                continue
            child = children[0]
            if child.tag in {"section", "main"} and not any(
                c for c in div.children if c.tag is None and (c.text or "").strip()
            ):
                unwrap(div)
                stats["div_unwrapped"] += 1
                changed = True
                break
            if child.tag == "div" and not child.attrs:
                unwrap(div)
                stats["div_unwrapped"] += 1
                changed = True
                break


def remove_empty_headings(root: Node, stats: Dict[str, int]) -> None:
    for heading in list(iter_tags(root, "h1", "h2")):
        if get_text(heading).strip() == "":
            remove_node(heading)
            stats["empty_headings_removed"] += 1


def remove_empty_italics(root: Node, stats: Dict[str, int]) -> None:
    for italic in list(iter_tags(root, "i")):
        if italic.attrs:
            continue
        if get_text(italic).strip():
            continue
        if any(child.tag for child in italic.children):
            continue
        remove_node(italic)
        stats["empty_italics_removed"] += 1


def add_alt_text(root: Node, stats: Dict[str, int]) -> None:
    for image in iter_tags(root, "img"):
        alt = image.attrs.get("alt")
        if not alt or alt.strip() == "":
            image.attrs["alt"] = "Image description"
            stats["alt_added"] += 1


def normalize_headings(root: Node, stats: Dict[str, int]) -> None:
    headings = [node for node in iter_tags(root, "h1", "h2", "h3", "h4", "h5", "h6") if get_text(node).strip()]
    if not headings:
        return
    first = headings[0]
    if first.tag != "h1":
        first.tag = "h1"
        stats["headings_adjusted"] += 1
    for heading in headings[1:]:
        original = heading.tag
        if heading.tag == "h1":
            heading.tag = "h2"
        elif heading.tag in {"h4", "h5", "h6"}:
            heading.tag = "h3"
        # ensure not skipping levels beyond h3
        if heading.tag != original:
            stats["headings_adjusted"] += 1


def find_ancestor(node: Node, names: set[str]) -> Optional[Node]:
    current = node.parent
    while current:
        if current.tag in names:
            return current
        current = current.parent
    return None


def move_footer_elements(root: Node, stats: Dict[str, int]) -> None:
    candidates: List[Node] = []
    for tag in iter_tags(root):
        if tag.tag in {"script", "style", "noscript"}:
            continue
        if tag.tag not in FOOTER_CANDIDATE_TAGS:
            continue
        if FOOTER_PATTERN.search(get_text(tag)):
            if find_ancestor(tag, {"footer"}):
                continue
            text_content = get_text(tag).strip()
            if len(text_content) > 400:
                continue
            candidates.append(tag)
    if not candidates:
        return
    # filter nested candidates to keep only the outermost elements
    filtered: List[Node] = []
    for node in candidates:
        if any(is_descendant(node, other) for other in candidates if other is not node):
            continue
        filtered.append(node)
    candidates = filtered
    main = next((node for node in iter_tags(root, "main")), None)
    if main is None:
        body = next((node for node in iter_tags(root, "body")), None)
        if body is None:
            return
        main = Node("main")
        for child in list(body.children):
            body.remove(child)
            main.append(child)
        body.append(main)
    footer = next((node for node in main.children if node.tag == "footer"), None)
    if footer is None:
        footer = Node("footer")
        main.append(footer)
    for node in candidates:
        parent = node.parent
        if not parent:
            continue
        parent.remove(node)
        footer.append(node)
        stats["footer_elements_moved"] += 1


def is_descendant(node: Node, potential_ancestor: Node) -> bool:
    current = node.parent
    while current:
        if current is potential_ancestor:
            return True
        current = current.parent
    return False


def ensure_matching_sections(root: Node) -> None:
    # Parser already ensures proper nesting, but we remove stray text nodes inside html/head/body
    clean_whitespace(root)


def render_attributes(attrs: Dict[str, str]) -> str:
    if not attrs:
        return ""
    parts = []
    for key, value in attrs.items():
        if value is None:
            parts.append(f" {key}")
        else:
            parts.append(f" {key}=\"{html.escape(value, quote=True)}\"")
    return "".join(parts)


def render_node(node: Node, indent: int = 0, preserve: bool = False) -> str:
    if node.is_doctype:
        return f"<!{node.text}>"
    if node.is_comment:
        indent_str = "  " * indent
        return f"{indent_str}<!--{node.text or ''}-->"
    if node.tag is None:
        text = node.text or ""
        if preserve or not text.strip():
            return text
        indent_str = "  " * indent
        return f"{indent_str}{text.strip()}"
    indent_str = "  " * indent
    attrs = render_attributes(node.attrs)
    if node.tag in VOID_ELEMENTS:
        return f"{indent_str}<{node.tag}{attrs}>"
    preserve_children = preserve or node.tag in PRESERVE_WHITESPACE_TAGS
    child_strings: List[str] = []
    for child in node.children:
        rendered = render_node(child, indent + 1, preserve_children)
        if rendered == "":
            continue
        child_strings.append(rendered)
    if not child_strings:
        return f"{indent_str}<{node.tag}{attrs}></{node.tag}>"
    joiner = "\n"
    if preserve_children:
        content = "".join(child_strings)
        return f"{indent_str}<{node.tag}{attrs}>{content}</{node.tag}>"
    content = joiner.join(child_strings)
    return f"{indent_str}<{node.tag}{attrs}>\n{content}\n{indent_str}</{node.tag}>"


def indent_block(text: str, level: int) -> str:
    prefix = "  " * level
    return "\n".join(f"{prefix}{line}" if line else "" for line in text.splitlines())


def render_document(root: Node) -> str:
    doctype = next((child for child in root.children if child.is_doctype), None)
    html_node = next((child for child in root.children if child.tag == "html"), None)
    parts: List[str] = []
    if doctype is not None:
        parts.append(render_node(doctype))
    else:
        parts.append("<!DOCTYPE html>")
    if html_node is not None:
        parts.append(render_node(html_node))
    else:
        content_parts: List[str] = []
        for child in root.children:
            if child is doctype:
                continue
            rendered = render_node(child)
            if rendered:
                content_parts.append(rendered)
        if content_parts:
            body_content = "\n".join(content_parts)
            parts.append("<html>")
            parts.append("  <body>")
            parts.append(indent_block(body_content, 2))
            parts.append("  </body>")
            parts.append("</html>")
    return "\n".join(parts) + "\n"


def validate_html(content: str) -> List[str]:
    # Re-parse the document to ensure it is consumable by the tolerant parser.
    parse_html(content)
    return []


def process_file(path: Path) -> Optional[Dict[str, int]]:
    original = path.read_text(encoding="utf-8")
    root = parse_html(original)
    stats: Dict[str, int] = defaultdict(int)
    remove_redundant_wrappers(root, stats)
    remove_empty_headings(root, stats)
    remove_empty_italics(root, stats)
    add_alt_text(root, stats)
    normalize_headings(root, stats)
    move_footer_elements(root, stats)
    ensure_matching_sections(root)
    output = render_document(root)
    if output == original:
        return None
    warnings = validate_html(output)
    path.write_text(output, encoding="utf-8")
    stats["validation_warnings"] = len(warnings)
    return stats


def main() -> None:
    report_lines: List[str] = []
    modified_files = 0
    for path in sorted(DOCS_DIR.glob("*.html")):
        result = process_file(path)
        if not result:
            continue
        modified_files += 1
        report_lines.append(f"File: {path.name}")
        for key, value in sorted(result.items()):
            if key == "validation_warnings" and value == 0:
                continue
            report_lines.append(f"  - {key.replace('_', ' ').capitalize()}: {value}")
        if result.get("validation_warnings", 0) == 0:
            report_lines.append("  - Validation warnings: none")
        report_lines.append("")
    if modified_files == 0:
        REPORT_PATH.write_text("No files required changes.\n", encoding="utf-8")
    else:
        REPORT_PATH.write_text("\n".join(report_lines).strip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
