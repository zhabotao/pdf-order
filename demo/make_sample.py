#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate demo/sample.pdf: a two-column page with a full-width title.

The page uses Courier so every glyph advance is exactly 600/1000 em; the
declared /Widths array matches that, so line ends in the produced PDF agree
with what a parser measures. The file carries no third-party content.

This is an illustrative input, not a formal test case.
"""

import os

W, H = 595.0, 842.0
FONT_SIZE = 9.0
CHAR_W = FONT_SIZE * 0.6  # Courier: 600/1000 em

LEFT_X = 56.0
RIGHT_X = 310.0
TOP_Y = 700.0
LEADING = 13.0

TITLE = "Two-Column Demo Page"
SUBTITLE = "A synthetic input for pdf-order. No third-party content."

# Each line is wrapped to <= 43 characters so it fits a 240pt Courier column.
LEFT = [
    "This page exists only to exercise the",
    "parser: a full-width title, a subtitle,",
    "and two columns that must never be",
    "spliced. A reader that orders lines by",
    "vertical position alone will alternate",
    "between the columns and produce",
    "sentences that start on the left and",
    "finish on the right.",
    "",
    "The parser groups glyph runs into",
    "lines, splits a line wherever the",
    "horizontal advance leaves a",
    "gutter-sized gap, then cuts the page",
    "recursively on the widest band that",
    "few lines cross.",
    "",
    "Every block it emits carries a page",
    "number and a bounding box, so a",
    "reviewer can point back at the region",
    "the text came from.",
]

RIGHT = [
    "This is the right column. Its first line",
    "should follow the last line of the left",
    "column, not the first one, and the page",
    "number below should come last.",
    "",
    "The title and subtitle are wider than",
    "either column, so they are spanning",
    "elements: the parser emits them before",
    "both columns because their vertical",
    "extent sits above the column block.",
    "",
    "Known limits: vector-outline text and",
    "scanned pages with no text layer are",
    "reported as uncertainty rather than",
    "guessed at.",
]


def esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def text_block(x: float, y: float, size: float, lines, leading: float) -> str:
    out = ["BT", "/F1 %.2f Tf" % size, "%.2f %.2f Td" % (x, y)]
    for i, ln in enumerate(lines):
        if i:
            out.append("0 %.2f Td" % -leading)
        if ln:
            out.append("(%s) Tj" % esc(ln))
    out.append("ET")
    return "\n".join(out)


def build_content() -> bytes:
    parts = [text_block(LEFT_X, 780, 17, [TITLE], 20)]
    parts.append(text_block(LEFT_X, 754, 10, [SUBTITLE], 12))
    parts.append(text_block(LEFT_X, TOP_Y, FONT_SIZE, LEFT, LEADING))
    parts.append(text_block(RIGHT_X, TOP_Y, FONT_SIZE, RIGHT, LEADING))
    parts.append(text_block(287, 40, FONT_SIZE, ["1"], 12))
    return "\n".join(parts).encode("latin-1")


def build_pdf() -> bytes:
    content = build_content()
    widths = " ".join(["600"] * 256)

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.0f %.0f] "
                "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
            )
            % (W, H)
        ).encode("latin-1"),
        b"<< /Length "
        + str(len(content)).encode()
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
            b"/FirstChar 0 /LastChar 255 /Widths ["
            + widths.encode("latin-1")
            + b"] >>"
        ),
    ]

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % i).encode()
        out += body
        out += b"\nendobj\n"

    xref_pos = len(out)
    out += ("xref\n0 %d\n" % (len(objs) + 1)).encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objs) + 1, xref_pos)
    ).encode()
    return bytes(out)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "sample.pdf")
    data = build_pdf()
    with open(path, "wb") as fh:
        fh.write(data)
    print("wrote %s (%d bytes)" % (path, len(data)))


if __name__ == "__main__":
    main()
