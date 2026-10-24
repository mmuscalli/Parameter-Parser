"""
arXiv's HTML full text (rendered from the LaTeX source by LaTeXML) -> plain text for the model.

Tables come out as one row per line, cells separated by ' | ' -- both real <table>s and LaTeXML's
span-based tables (class ltx_tr / ltx_td), which is how the sideways tables of teng2023 are drawn.
Math becomes its LaTeX (the `alttext` attribute): values keep their exact uncertainties, e.g.
'0.10_{-0.05}^{+0.08}', with nothing to misread. The bibliography, scripts and navigation are
dropped (references cost tokens and no step uses them). Standard library only.
"""
from __future__ import annotations
import re
from html.parser import HTMLParser

_SKIP = {"script", "style", "nav", "header", "footer", "button", "annotation", "annotation-xml", "svg"}
_VOID = {"br", "img", "meta", "link", "hr", "input", "col", "source", "wbr"}
_BLOCK = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "li", "figcaption",
          "caption", "table", "blockquote", "dt", "dd"}
_SKIP_CLASSES = {"ltx_bibliography", "ltx_page_header", "ltx_page_footer", "ltx_dates", "ltx_role_footnotetext"}


class _Converter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip, self.math = [], [], 0, 0
        self.cells, self.cell = None, None

    def _emit(self, s: str) -> None:
        (self.cell if self.cell is not None else self.out).append(s)

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            if tag == "br":
                self._emit(" " if self.cell is not None else "\n")
            return
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        if self.skip or tag in _SKIP or cls & _SKIP_CLASSES:
            role = "skip"
        elif tag == "math":
            role = "math"
        elif tag == "tr" or "ltx_tr" in cls:
            role = "tr"
        elif tag in ("td", "th") or "ltx_td" in cls:
            role = "td"
        elif tag in _BLOCK:
            role = "block"
        else:
            role = ""
        self.stack.append((tag, role))
        if role == "skip":
            self.skip += 1
        elif role == "math":
            if not self.math:
                tex = (a.get("alttext") or "").strip()
                self._emit(f" ${tex}$ " if tex else " ")
            self.math += 1
        elif role == "tr":
            self.cells = []
        elif role == "td":
            self.cell = []
        elif role == "block" and self.cell is None:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        while self.stack:                         # close anything left open inside this element
            t, role = self.stack.pop()
            if role == "skip":
                self.skip -= 1
            elif role == "math":
                self.math -= 1
            elif role == "td" and self.cell is not None:
                if self.cells is None:
                    self.cells = []
                self.cells.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
                self.cell = None
            elif role == "tr" and self.cells is not None:
                if any(self.cells):
                    self.out.append("\n" + " | ".join(self.cells))
                self.cells = None
            elif role == "block" and self.cell is None:
                self.out.append("\n")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip and not self.math:
            self._emit(data)


def html_to_text(html: str) -> str:
    c = _Converter()
    c.feed(html)
    c.close()
    text = "".join(c.out)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def looks_like_paper(html: str) -> bool:
    """arXiv answers some /html/ requests with a 'no HTML for this paper' page: a real rendering
    is a LaTeXML document."""
    return "ltx_document" in html or "ltx_page_main" in html
