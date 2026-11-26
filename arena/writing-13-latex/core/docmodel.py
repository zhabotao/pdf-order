#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docmodel: shared document model on top of pdf_parse.

Every reading task in this arena needs the same primitives: paragraphs that carry
page + bbox anchors, a section hierarchy, figure/table captions, a reference list
and equation lines. This module derives them once, deterministically, so each
task adapter only implements its own transform.

Standard library only.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pdf_parse  # noqa: E402

HEADING_WORDS = {
    "abstract", "introduction", "background", "related work", "methods",
    "method", "materials and methods", "results", "results and discussion",
    "discussion", "conclusion", "conclusions", "references", "bibliography",
    "acknowledgements", "acknowledgments", "appendix",
    "摘要", "引言", "前言", "背景", "相关工作", "方法", "材料与方法", "结果",
    "讨论", "结论", "参考文献", "致谢", "附录", "实验", "实验设置",
}

CAPTION_RE = re.compile(
    r"^\s*(图|表|Figure|Fig\.?|Table|Scheme|Algorithm|公式|式)\s*[0-9一二三四五六七八九十]",
    re.I,
)

NUMBERED_HEADING_RE = re.compile(
    r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})[\s、.．]\s*(\S.{0,60})$"
)
CHAPTER_HEADING_RE = re.compile(r"^\s*第\s*[一二三四五六七八九十百\d]+\s*[章节部分]")

REF_ENTRY_RE = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3}[.、)])\s+\S")

MATH_HINT = set("=∑∏∫√±×÷≈≠≤≥∂∇αβγδεζηθλμνξπρστφχψωΓΔΘΛΞΠΣΦΨΩ")


class Paragraph:
    __slots__ = ("id", "page", "bbox", "text", "font_size", "kind")

    def __init__(self, pid, page, bbox, text, font_size, kind="body"):
        self.id = pid
        self.page = page
        self.bbox = bbox
        self.text = text
        self.font_size = font_size
        self.kind = kind

    def as_dict(self):
        return {
            "id": self.id,
            "page": self.page,
            "bbox": self.bbox,
            "text": self.text,
            "font_size": self.font_size,
            "kind": self.kind,
        }


class Section:
    __slots__ = ("id", "level", "title", "page", "bbox", "paragraphs")

    def __init__(self, sid, level, title, page, bbox):
        self.id = sid
        self.level = level
        self.title = title
        self.page = page
        self.bbox = bbox
        self.paragraphs = []

    def as_dict(self):
        return {
            "id": self.id,
            "level": self.level,
            "title": self.title,
            "page": self.page,
            "bbox": self.bbox,
            "paragraph_ids": [p.id for p in self.paragraphs],
        }


class Document:
    def __init__(self, path, raw, max_pages=None):
        self.path = path
        self.raw = raw
        self.max_pages = max_pages
        self.paragraphs = []
        self.sections = []
        self._build()

    # ---- construction ------------------------------------------------
    def _build(self):
        sizes = []
        for page in self.raw.get("pages", []):
            for b in page.get("blocks", []):
                sizes.append(b.get("font_size") or 10.0)
        self.body_size = _median(sizes) if sizes else 10.0

        idx = 0
        for page in self.raw.get("pages", []):
            for b in page.get("blocks", []):
                text = (b.get("text") or "").strip()
                if not text:
                    continue
                idx += 1
                self.paragraphs.append(
                    Paragraph(
                        f"p{page.get('page')}-{idx}",
                        page.get("page"),
                        b.get("bbox"),
                        text,
                        b.get("font_size") or self.body_size,
                        _classify(text, b.get("font_size") or self.body_size, self.body_size),
                    )
                )
        self._split_sections()

    def _split_sections(self):
        current = Section("s0", 0, "(document)", None, None)
        self.sections = [current]
        for para in self.paragraphs:
            if para.kind == "heading":
                current = Section(
                    f"s{len(self.sections)}",
                    _heading_level(para.text),
                    para.text,
                    para.page,
                    para.bbox,
                )
                self.sections.append(current)
            current.paragraphs.append(para)
        # a document with no detected heading still exposes one flat section
        if len(self.sections) == 1:
            self.sections[0].title = "(正文)"

    # ---- accessors ---------------------------------------------------
    def body_paragraphs(self):
        return [p for p in self.paragraphs if p.kind == "body"]

    def captions(self):
        return [p for p in self.paragraphs if p.kind == "caption"]

    def references(self):
        """Reference list entries, if the document has a References section."""
        ref_sections = [
            s for s in self.sections
            if s.title.strip().lower().strip(":：") in ("references", "bibliography", "参考文献")
        ]
        entries = []
        for sec in ref_sections:
            for para in sec.paragraphs:
                if para is sec.paragraphs[0] and _is_heading_text(para.text):
                    continue
                for chunk in _split_ref_entries(para.text):
                    if not (REF_ENTRY_RE.match(chunk) or len(chunk) >= 40):
                        continue
                    entries.append(
                        {
                            "page": para.page,
                            "bbox": para.bbox,
                            "text": chunk,
                            "anchor": para.id,
                        }
                    )
        return entries

    def equations(self):
        out = []
        for para in self.paragraphs:
            t = para.text.strip()
            if len(t) > 200:
                continue
            hints = sum(1 for ch in t if ch in MATH_HINT)
            numbered = re.search(r"\(\s*\d{1,3}\s*\)\s*$", t)
            if hints >= 2 or (hints >= 1 and numbered):
                out.append({"page": para.page, "bbox": para.bbox, "text": t, "anchor": para.id})
        return out

    def full_text(self):
        return "\n".join(p.text for p in self.paragraphs)

    def summary(self):
        return {
            "paragraphs": len(self.paragraphs),
            "sections": len([s for s in self.sections if s.level > 0]),
            "captions": len(self.captions()),
            "references": len(self.references()),
            "equations": len(self.equations()),
            "body_size": round(self.body_size, 2),
        }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _median(vals):
    if not vals:
        return 10.0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _is_heading_text(text):
    t = text.strip().rstrip(":：").lower()
    return t in HEADING_WORDS


def _heading_level(text):
    m = NUMBERED_HEADING_RE.match(text)
    if m:
        return m.group(1).count(".") + 1
    if CHAPTER_HEADING_RE.match(text):
        return 1
    if _is_heading_text(text):
        return 1
    return 2


def _wordy(t):
    """True when a string carries real words, not just numbers/units."""
    letters = sum(1 for ch in t if ch.isalpha() or "\u4e00" <= ch <= "\u9fff")
    return letters >= 2


def _classify(text, size, body_size):
    t = text.strip()
    if CAPTION_RE.match(t):
        return "caption"
    if len(t) > 120:
        return "body"
    if not _wordy(t):
        return "body"
    if _is_heading_text(t):
        return "heading"
    if size >= body_size * 1.12 and len(t) <= 80 and not re.match(r"^\d+\.\d+\s", t):
        return "heading"
    m = NUMBERED_HEADING_RE.match(t)
    if (
        m
        and len(t) <= 60
        and _wordy(m.group(2))
        and not t.endswith(("\u3002", ".", "\uff1b", ";"))
        and not re.match(r"^\d+(\.\d+)?\s*[A-Za-z\u00b5\u03bc]?$", t)
    ):
        return "heading"
    if CHAPTER_HEADING_RE.match(t) and len(t) <= 60:
        return "heading"
    return "body"


def _split_ref_entries(text):
    """Split a reference block into individual entries by leading [n] / n. markers."""
    starts = [m.start() for m in REF_ENTRY_RE.finditer(text)]
    if len(starts) < 2:
        return [text] if text else []
    starts.append(len(text))
    return [text[starts[i]: starts[i + 1]].strip() for i in range(len(starts) - 1)]


def load(path, max_pages=None):
    raw = pdf_parse.extract(path, max_pages, include_text=True)
    return Document(path, raw, max_pages)
