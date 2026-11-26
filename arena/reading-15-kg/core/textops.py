#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""textops: deterministic text utilities shared by the reading/writing tasks.

Nothing here calls a model. These are the mechanical guarantees a contestant can
actually verify: consistent glossary enforcement, paragraph alignment, number and
citation preservation checks, issue detection for prose, reference reconciliation
and static LaTeX checks.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- glossary


CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
CITE = re.compile(r"\[([0-9,\s\-–]+)\]|（\s*([0-9,\s\-–]+)\s*）")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
UNIT = re.compile(
    r"(?:%|‰|ms|s|min|h|Hz|kHz|MHz|GB|MB|KB|nm|µm|um|mm|cm|km|kg|mg|g|mL|L|"
    r"mol|nM|µM|mM|K|°C|Pa|kPa|MPa|bar|eV|keV|MeV|GeV|dB)"
)
SENT_END = re.compile(r"(?<=[。！？；.!?;])\s*")


def normalize_space(text: str) -> str:
    return re.sub(r"[ \t\u3000]{2,}", " ", text.replace("\r", "")).strip()


def split_sentences(text: str):
    parts = [p for p in SENT_END.split(text) if p and p.strip()]
    return parts or ([text] if text.strip() else [])


def term_candidates(text: str, min_len=5, limit=200):
    """Latin acronyms/terms and short CJK noun-ish chunks, frequency ranked."""
    counts = {}
    for word in LATIN_WORD.findall(text):
        low = word.lower()
        counts[low] = counts.get(low, 0) + 1
    stop = set("""
    the and for with that this from are was were which have has not but can our its their
    than into such these those when where while also been being does did then there here
    would could should must may might will shall each other some most more less very
    first last left right above below under over between within without across during
    page pages line lines text block blocks column columns figure table section paper
    using used uses make makes made take takes given give gives show shows shown found
    results result method methods study data value values number numbers type types
    """.split())
    ranked = [(w, c) for w, c in counts.items() if len(w) >= min_len and w not in stop]
    ranked.sort(key=lambda kv: (-kv[1], kv[0]))
    return ranked[:limit]


def extract_glossary(source_text: str, provided=None):
    """Build a glossary: provided entries win, then high-frequency candidates."""
    glossary = {}
    for k, v in (provided or {}).items():
        glossary[k.strip()] = v
    for term, freq in term_candidates(source_text):
        if term in glossary:
            continue
        if freq < 2:
            continue
        glossary[term] = None  # unmapped: needs an explicit translation
    return glossary


def apply_glossary(text: str, glossary: dict):
    """Enforce one translation per term, case-insensitively; report drift."""
    violations = []
    fixed = text
    for src, dst in glossary.items():
        if not dst:
            continue
        pattern = re.compile(r"(?<![A-Za-z])" + re.escape(src) + r"(?![A-Za-z])", re.I)
        for m in pattern.finditer(text):
            pass
        fixed = pattern.sub(dst, fixed)
    return fixed, violations


def glossary_consistency(pairs, glossary):
    """pairs: [(source_para, translated_para)] — check each term maps to one form."""
    issues = []
    for src, dst in glossary.items():
        if not dst:
            continue
        forms = set()
        for _, translated in pairs:
            if dst in translated:
                forms.add(dst)
        if len(forms) > 1:
            issues.append({"term": src, "forms": sorted(forms)})
    return issues


# ---------------------------------------------------------- preservation


def protected_tokens(text: str):
    """Numbers, units, citation markers and equation numbers that must survive."""
    return {
        "numbers": NUMBER.findall(text),
        "units": UNIT.findall(text),
        "citations": [m.group(0) for m in CITE.finditer(text)],
        "eqnums": re.findall(r"\(\s*\d{1,3}\s*\)", text),
        "symbols": [ch for ch in text if ch in "∑∏∫√±×÷≈≠≤≥∂∇"],
    }


def preservation_report(source: str, target: str):
    """Which protected items from the source are missing in the target."""
    a = protected_tokens(source)
    b = protected_tokens(target)
    missing = {}
    for key, vals in a.items():
        if key == "symbols":
            lost = [v for v in vals if v not in b[key]]
        else:
            lost = [v for v in vals if v not in b[key]]
        if lost:
            missing[key] = sorted(set(lost))
    return missing


# ---------------------------------------------------------------- alignment


def align_paragraphs(source_paras, translated_paras):
    """Paragraph-level pairing with explicit status instead of silent drift."""
    rows = []
    n = max(len(source_paras), len(translated_paras))
    for i in range(n):
        src = source_paras[i] if i < len(source_paras) else None
        dst = translated_paras[i] if i < len(translated_paras) else None
        status = "ok"
        if src is None:
            status = "extra_translation"
        elif dst is None:
            status = "untranslated"
        elif not dst.strip():
            status = "empty_translation"
        rows.append({"index": i, "status": status, "source": src, "translation": dst})
    return rows


# ------------------------------------------------------------- prose checks


ZH_EN_MIX = re.compile(r"[\u4e00-\u9fff][A-Za-z]{2,}|[A-Za-z]{2,}[\u4e00-\u9fff]")
HEDGE = re.compile(r"\b(?:may|might|could|seems?|appears?|possibly|likely)\b", re.I)
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b", re.I)


def prose_issues(text: str, max_sentence=45, max_paragraph=180):
    """Mechanical, checkable issues — not style opinions."""
    issues = []

    for m in ZH_EN_MIX.finditer(text):
        issues.append({"type": "mixed_script", "span": m.group(0), "hint": "中英混排缺空格或术语未译"})

    for sentence in split_sentences(text):
        words = len(sentence.split())
        if words > max_sentence:
            issues.append({"type": "long_sentence", "words": words, "span": sentence[:60] + "…"})

    for para in text.split("\n\n"):
        words = len(para.split())
        if words > max_paragraph:
            issues.append({"type": "long_paragraph", "words": words})

    for m in PASSIVE.finditer(text):
        issues.append({"type": "passive_voice", "span": m.group(0)})

    return issues


def tense_profile(text: str):
    present = len(re.findall(r"\b(?:is|are|show|shows|demonstrate|demonstrates|we observe)\b", text, re.I))
    past = len(re.findall(r"\b(?:was|were|showed|demonstrated|observed|trained|evaluated)\b", text, re.I))
    return {"present": present, "past": past,
            "dominant": "past" if past > present else "present"}


# ------------------------------------------------------------- references


BIB_FIELDS = ("author", "title", "journal", "year", "volume", "pages", "doi")


def parse_reference(text: str):
    """Very small structural guess: year, doi, volume, and a title-ish chunk."""
    ref = {"raw": text.strip()}
    year = re.findall(r"\b(19|20)\d{2}\b", text)
    ref["year"] = re.findall(r"\b(?:19|20)\d{2}\b", text)[-1] if year else None
    doi = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text)
    ref["doi"] = doi.group(0) if doi else None
    ref["has_author_block"] = bool(re.match(r"^\s*(\[\d+\]|\d+[.)])?\s*[A-Z][A-Za-z\-]+,\s", text))
    ref["key"] = (ref["doi"] or re.sub(r"\W+", "", text.lower())[:60])
    return ref


def reconcile_citations(body_text: str, references):
    """Which numbers are cited in text but absent from the list, and vice versa."""
    cited = set()
    for m in CITE.finditer(body_text):
        blob = m.group(1) or m.group(2) or ""
        for part in re.split(r"[,\s]+", blob):
            if "-" in part or "–" in part:
                a, _, b = re.split(r"[-–]", part, maxsplit=2)
                if a.isdigit() and b.isdigit():
                    cited.update(range(int(a), int(b) + 1))
            elif part.isdigit():
                cited.add(int(part))
    listed = set()
    for r in references:
        m = re.match(r"^\s*\[?(\d{1,3})[\].)]", r["raw"])
        if m:
            listed.add(int(m.group(1)))
        else:
            listed.add(len(listed) + 1)
    return {
        "cited_count": len(cited),
        "listed_count": len(listed),
        "cited_not_listed": sorted(cited - listed),
        "listed_not_cited": sorted(listed - cited),
    }


def format_style_profile(references):
    """Detect inconsistent bracket/period styles across the list."""
    bracketed = sum(1 for r in references if re.match(r"^\s*\[\d+\]", r["raw"]))
    dotted = sum(1 for r in references if re.match(r"^\s*\d+[.)]\s", r["raw"]))
    return {
        "bracketed": bracketed,
        "dotted": dotted,
        "mixed": bracketed > 0 and dotted > 0,
        "total": len(references),
    }


# ------------------------------------------------------------------ latex


def latex_checks(source: str):
    """Static checks that need no compiler: balance, undefined refs, bib sync."""
    issues = []

    depth = 0
    for i, ch in enumerate(source):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                issues.append({"type": "unbalanced_brace", "offset": i, "hint": "多余的 }"})
                depth = 0

    labels = set(re.findall(r"\\label\{([^}]+)\}", source))
    refs = set(re.findall(r"\\(?:ref|eqref|autoref|cref)\{([^}]+)\}", source))
    issues.append({"type": "undefined_refs", "items": sorted(refs - labels)})
    issues.append({"type": "unused_labels", "items": sorted(labels - refs)})

    cites = set()
    for m in re.finditer(r"\\cite[a-z]*\{([^}]+)\}", source):
        cites.update(k.strip() for k in m.group(1).split(","))
    bibitems = set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", source))
    if bibitems:
        issues.append({"type": "cites_missing_in_bib", "items": sorted(cites - bibitems)})
        issues.append({"type": "bib_uncited", "items": sorted(bibitems - cites)})

    envs = re.findall(r"\\begin\{(\w+\*?)\}", source)
    ends = re.findall(r"\\end\{(\w+\*?)\}", source)
    if sorted(envs) != sorted(ends):
        missing = [e for e in envs if envs.count(e) > ends.count(e)]
        issues.append({"type": "unbalanced_environment", "items": sorted(set(missing))})

    issues.append({"type": "double_space", "count": len(re.findall(r"[^\n] {2,}", source))})
    return [i for i in issues if i.get("items") or i.get("count") or i["type"] == "unbalanced_brace"]


# ------------------------------------------------------------------ misc


def wc(text: str):
    return {
        "chars": len(text),
        "cjk_chars": len(CJK.findall(text)),
        "latin_words": len(re.findall(r"[A-Za-z][A-Za-z\-']+", text)),
    }


def sha1_16(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def strip_pua(text: str) -> str:
    """Drop private-use glyphs some PDFs use for bullets."""
    return "".join(ch for ch in text if not (0xE000 <= ord(ch) <= 0xF8FF))
