#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf-order: dependency-free PDF text extraction with faithful reading order.

Parses PDF objects, content streams and ToUnicode CMaps using only the Python
standard library, then reconstructs reading order with a recursive XY-cut so
multi-column pages are not spliced line-by-line across the gutter.

Every emitted block carries its page number and bbox so a reviewer can point
back at the original page region.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import zlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------
# Lexer / object model
# --------------------------------------------------------------------------

WHITESPACE = b"\x00\t\n\x0c\r "
DELIMS = b"()<>[]{}/%"


class Name(str):
    """A PDF name object (/Something)."""


@dataclass(frozen=True)
class Ref:
    num: int
    gen: int


class PDFString(bytes):
    """A PDF string object, kept as raw bytes."""


class Lexer:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def skip_ws(self) -> None:
        data = self.data
        n = len(data)
        while self.pos < n:
            c = data[self.pos]
            if c in WHITESPACE:
                self.pos += 1
            elif c == 0x25:  # '%' comment
                while self.pos < n and data[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                return

    def parse(self) -> Any:
        self.skip_ws()
        if self.pos >= len(self.data):
            raise EOFError("unexpected end of data")
        data = self.data
        c = data[self.pos : self.pos + 1]

        if c == b"/":
            return self._parse_name()
        if c == b"(":
            return self._parse_literal_string()
        if c == b"<":
            if data[self.pos : self.pos + 2] == b"<<":
                return self._parse_dict()
            return self._parse_hex_string()
        if c == b"[":
            return self._parse_array()
        if c in (b"]", b">", b")", b"}"):
            self.pos += 1
            return None

        tok = self._read_token()
        value = self._token_value(tok)

        # Indirect reference: <num> <gen> R
        if isinstance(value, int) and not isinstance(value, bool):
            save = self.pos
            try:
                self.skip_ws()
                tok2 = self._read_token()
                if tok2.isdigit():
                    self.skip_ws()
                    tok3 = self._read_token()
                    if tok3 == b"R":
                        return Ref(value, int(tok2))
            except Exception:
                pass
            self.pos = save
        return value

    def _read_token(self) -> bytes:
        start = self.pos
        data = self.data
        n = len(data)
        while self.pos < n:
            if data[self.pos] in WHITESPACE or data[self.pos] in DELIMS:
                break
            self.pos += 1
        return data[start : self.pos]

    def _token_value(self, tok: bytes) -> Any:
        if tok == b"true":
            return True
        if tok == b"false":
            return False
        if tok == b"null":
            return None
        try:
            if b"." in tok:
                return float(tok)
            return int(tok)
        except ValueError:
            return tok.decode("latin-1", "replace")

    def _parse_name(self) -> Name:
        self.pos += 1
        start = self.pos
        data = self.data
        n = len(data)
        while self.pos < n and data[self.pos] not in WHITESPACE and data[self.pos] not in DELIMS:
            self.pos += 1
        raw = data[start : self.pos]
        # #xx escapes
        if b"#" in raw:
            raw = re.sub(
                b"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw
            )
        return Name(raw.decode("latin-1", "replace"))

    def _parse_literal_string(self) -> PDFString:
        self.pos += 1
        depth = 1
        out = bytearray()
        data = self.data
        n = len(data)
        while self.pos < n:
            c = data[self.pos]
            if c == 0x5C:  # backslash
                self.pos += 1
                if self.pos >= n:
                    break
                e = data[self.pos]
                mapping = {
                    ord("n"): 0x0A,
                    ord("r"): 0x0D,
                    ord("t"): 0x09,
                    ord("b"): 0x08,
                    ord("f"): 0x0C,
                    ord("("): 0x28,
                    ord(")"): 0x29,
                    ord("\\"): 0x5C,
                }
                if e in mapping:
                    out.append(mapping[e])
                    self.pos += 1
                elif e in b"01234567":
                    oct_digits = bytearray()
                    while (
                        self.pos < n
                        and len(oct_digits) < 3
                        and data[self.pos] in b"01234567"
                    ):
                        oct_digits.append(data[self.pos])
                        self.pos += 1
                    out.append(int(oct_digits, 8) & 0xFF)
                elif e in b"\r\n":
                    if e == 0x0D and self.pos + 1 < n and data[self.pos + 1] == 0x0A:
                        self.pos += 1
                    self.pos += 1
                else:
                    out.append(e)
                    self.pos += 1
                continue
            if c == 0x28:
                depth += 1
                out.append(c)
                self.pos += 1
                continue
            if c == 0x29:
                depth -= 1
                self.pos += 1
                if depth == 0:
                    break
                out.append(c)
                continue
            out.append(c)
            self.pos += 1
        return PDFString(bytes(out))

    def _parse_hex_string(self) -> PDFString:
        self.pos += 1
        end = self.data.find(b">", self.pos)
        if end == -1:
            end = len(self.data)
        raw = re.sub(rb"[^0-9A-Fa-f]", b"", self.data[self.pos : end])
        self.pos = end + 1
        if len(raw) % 2:
            raw += b"0"
        try:
            return PDFString(bytes.fromhex(raw.decode("ascii")))
        except ValueError:
            return PDFString(b"")

    def _parse_array(self) -> List[Any]:
        self.pos += 1
        out: List[Any] = []
        while True:
            self.skip_ws()
            if self.pos >= len(self.data):
                break
            if self.data[self.pos] == 0x5D:  # ']'
                self.pos += 1
                break
            before = self.pos
            item = self.parse()
            out.append(item)
            if self.pos == before:
                self.pos += 1
        return out

    def _parse_dict(self) -> Dict[Any, Any]:
        self.pos += 2
        out: Dict[Any, Any] = {}
        while True:
            self.skip_ws()
            if self.pos >= len(self.data):
                break
            if self.data[self.pos : self.pos + 2] == b">>":
                self.pos += 2
                break
            before = self.pos
            key = self.parse()
            if not isinstance(key, Name):
                if self.pos == before:
                    self.pos += 1
                continue
            val = self.parse()
            out[str(key)] = val
        return out


# --------------------------------------------------------------------------
# Stream filters
# --------------------------------------------------------------------------


def _flate(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error:
        pass
    # tolerate truncated / raw-deflate streams
    try:
        return zlib.decompressobj().decompress(data)
    except zlib.error:
        pass
    try:
        return zlib.decompressobj(-15).decompress(data)
    except zlib.error:
        return b""


def _ascii_hex(data: bytes) -> bytes:
    raw = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
    if len(raw) % 2:
        raw += b"0"
    try:
        return bytes.fromhex(raw.decode("ascii"))
    except ValueError:
        return b""


def _ascii85(data: bytes) -> bytes:
    data = data.strip()
    if data.startswith(b"<~"):
        data = data[2:]
    if data.endswith(b"~>"):
        data = data[:-2]
    try:
        import base64

        return base64.a85decode(data, adobe=False, ignorechars=b" \t\n\r\v")
    except Exception:
        return b""


def _lzw(data: bytes, early: int = 1) -> bytes:
    out = bytearray()
    dict_size = 256
    table = {i: bytes([i]) for i in range(256)}
    bitpos = 0
    width = 9
    prev: Optional[bytes] = None

    def read_code() -> Optional[int]:
        nonlocal bitpos
        if (bitpos + width) > len(data) * 8:
            return None
        val = 0
        for _ in range(width):
            byte = data[bitpos >> 3]
            bit = (byte >> (7 - (bitpos & 7))) & 1
            val = (val << 1) | bit
            bitpos += 1
        return val

    while True:
        code = read_code()
        if code is None:
            break
        if code == 256:
            table = {i: bytes([i]) for i in range(256)}
            dict_size = 256
            width = 9
            prev = None
            continue
        if code == 257:
            break
        if prev is None:
            entry = table.get(code, b"")
        elif code in table:
            entry = table[code]
        else:
            entry = prev + prev[:1]
        out += entry
        if prev is not None:
            table[dict_size] = prev + entry[:1]
            dict_size += 1
            if dict_size + early >= (1 << width) and width < 12:
                width += 1
        prev = entry
    return bytes(out)


def decode_stream(stream: "PDFStream", doc: "Document") -> bytes:
    data = stream.raw
    filters = doc.resolve(stream.dict.get("Filter"))
    params = doc.resolve(stream.dict.get("DecodeParms"))
    if filters is None:
        return data
    if not isinstance(filters, list):
        filters = [filters]
        params = [params]
    elif not isinstance(params, list):
        params = [params] * len(filters)
    for i, f in enumerate(filters):
        f = str(doc.resolve(f) or "")
        p = doc.resolve(params[i]) if i < len(params) else None
        if f in ("FlateDecode", "Fl"):
            data = _flate(data)
        elif f in ("ASCIIHexDecode", "AHx"):
            data = _ascii_hex(data)
        elif f in ("ASCII85Decode", "A85"):
            data = _ascii85(data)
        elif f in ("LZWDecode", "LZW"):
            early = 1
            if isinstance(p, dict) and "EarlyChange" in p:
                early = int(p["EarlyChange"])
            data = _lzw(data, early)
        elif f in ("DCTDecode", "JPXDecode", "CCITTFaxDecode", "JBIG2Decode"):
            return b""  # image data, no text
        else:
            return b""
    return data


class PDFStream:
    __slots__ = ("dict", "raw")

    def __init__(self, d: Dict[str, Any], raw: bytes) -> None:
        self.dict = d
        self.raw = raw

    def decoded(self, doc: "Document") -> bytes:
        return decode_stream(self, doc)


# --------------------------------------------------------------------------
# Document
# --------------------------------------------------------------------------

OBJ_RE = re.compile(rb"(?<![0-9])(\d{1,10})\s+(\d{1,5})\s+obj\b")


class Document:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offsets: Dict[Tuple[int, int], int] = {}
        for m in OBJ_RE.finditer(data):
            self.offsets[(int(m.group(1)), int(m.group(2)))] = m.end()
        self._cache: Dict[Tuple[int, int], Any] = {}
        self.warnings: List[str] = []

    def resolve(self, obj: Any) -> Any:
        seen = 0
        while isinstance(obj, Ref) and seen < 32:
            obj = self.get(obj.num, obj.gen)
            seen += 1
        return obj

    def get(self, num: int, gen: int = 0) -> Any:
        key = (num, gen)
        if key in self._cache:
            return self._cache[key]
        pos = self.offsets.get(key)
        if pos is None:
            # try any generation for this object number
            for (n, g), p in self.offsets.items():
                if n == num:
                    pos = p
                    break
        if pos is None:
            return None
        lex = Lexer(self.data, pos)
        try:
            value = lex.parse()
        except Exception:
            return None
        # stream?
        lex.skip_ws()
        if isinstance(value, dict) and self.data[lex.pos : lex.pos + 6] == b"stream":
            p = lex.pos + 6
            if self.data[p : p + 2] == b"\r\n":
                p += 2
            elif self.data[p : p + 1] in (b"\n", b"\r"):
                p += 1
            end = self.data.find(b"endstream", p)
            if end == -1:
                end = len(self.data)
            raw = self.data[p:end]
            # trim the EOL that precedes endstream
            if raw.endswith(b"\r\n"):
                raw = raw[:-2]
            elif raw.endswith(b"\n") or raw.endswith(b"\r"):
                raw = raw[:-1]
            length = value.get("Length")
            if isinstance(length, Ref):
                length = self.get(length.num, length.gen)
            if isinstance(length, int) and 0 < length <= len(raw):
                raw = raw[:length]
            value = PDFStream(value, raw)
        self._cache[key] = value
        return value

    # ---- pages -------------------------------------------------
    def pages(self) -> List[Dict[str, Any]]:
        found: List[Tuple[int, int, Dict[str, Any]]] = []
        for (num, gen) in self.offsets:
            obj = self.get(num, gen)
            d = obj.dict if isinstance(obj, PDFStream) else obj
            if isinstance(d, dict) and str(d.get("Type")) == "Page":
                found.append((num, gen, d))
        found.sort(key=lambda t: t[0])
        if not found:
            self.warnings.append("no /Type /Page objects found; document may be encrypted or malformed")
        return [d for _, _, d in found]


# --------------------------------------------------------------------------
# Fonts / ToUnicode CMaps
# --------------------------------------------------------------------------



def _decode_utf16be(b: bytes) -> str:
    try:
        return b.decode("utf-16-be")
    except UnicodeDecodeError:
        return ""


def parse_cmap(text: bytes) -> Tuple[Dict[int, str], int]:
    """Return (code->unicode map, code byte width)."""
    mapping: Dict[int, str] = {}
    width = 1
    s = text.decode("latin-1", "replace")

    def hexval(h: str) -> Tuple[int, int]:
        h = re.sub(r"[^0-9A-Fa-f]", "", h)
        nbytes = max(1, len(h) // 2)
        return int(h, 16) if h else 0, nbytes

    for block in re.findall(r"begincodespacerange(.*?)endcodespacerange", s, re.S):
        for lo, _hi in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            width = max(width, max(1, len(lo) // 2))

    for block in re.findall(r"beginbfchar(.*?)endbfchar", s, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            code, nbytes = hexval(src)
            width = max(width, nbytes)
            raw = re.sub(r"[^0-9A-Fa-f]", "", dst)
            if len(raw) % 4:
                raw = raw.zfill((len(raw) // 4 + 1) * 4)
            try:
                mapping[code] = _decode_utf16be(bytes.fromhex(raw))
            except ValueError:
                mapping[code] = ""

    for block in re.findall(r"beginbfrange(.*?)endbfrange", s, re.S):
        # <lo> <hi> <dst>
        for lo, hi, dst in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
        ):
            lo_i, nbytes = hexval(lo)
            hi_i, _ = hexval(hi)
            width = max(width, nbytes)
            base_raw = re.sub(r"[^0-9A-Fa-f]", "", dst)
            base = int(base_raw, 16) if base_raw else 0
            for k in range(lo_i, min(hi_i, lo_i + 65535) + 1):
                val = base + (k - lo_i)
                raw = format(val, "0%dX" % max(4, len(base_raw)))
                try:
                    mapping[k] = _decode_utf16be(bytes.fromhex(raw))
                except ValueError:
                    mapping[k] = ""
        # <lo> <hi> [ <d1> <d2> ... ]
        for lo, hi, arr in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S
        ):
            lo_i, nbytes = hexval(lo)
            width = max(width, nbytes)
            items = re.findall(r"<([0-9A-Fa-f]*)>", arr)
            for off, item in enumerate(items):
                raw = re.sub(r"[^0-9A-Fa-f]", "", item)
                if len(raw) % 4:
                    raw = raw.zfill((len(raw) // 4 + 1) * 4)
                try:
                    mapping[lo_i + off] = _decode_utf16be(bytes.fromhex(raw))
                except ValueError:
                    mapping[lo_i + off] = ""
    return mapping, width


class Font:
    def __init__(self, doc: Document, spec: Dict[str, Any]) -> None:
        self.doc = doc
        self.spec = spec or {}
        self.subtype = str(doc.resolve(self.spec.get("Subtype")) or "")
        self.encoding = str(doc.resolve(self.spec.get("Encoding")) or "")
        self.tounicode: Dict[int, str] = {}
        self.width = 1
        self.first_char = None
        self.widths: Optional[List[float]] = None
        self.missing_width = None
        tu = doc.resolve(self.spec.get("ToUnicode"))
        if isinstance(tu, PDFStream):
            self.tounicode, self.width = parse_cmap(tu.decoded(doc))
        if self.subtype == "Type0" and not self.tounicode:
            self.width = 2
        if self.subtype == "Type0":
            self.width = max(self.width, 2)
        else:
            # simple (single-byte) fonts: codes are always one byte
            self.width = 1

        fc = doc.resolve(self.spec.get("FirstChar"))
        ws = doc.resolve(self.spec.get("Widths"))
        mw = doc.resolve(self.spec.get("MissingWidth"))
        if isinstance(fc, int) and isinstance(ws, list):
            self.first_char = fc
            vals: List[float] = []
            for w in ws:
                w = doc.resolve(w)
                vals.append(float(w) if isinstance(w, (int, float)) else 0.0)
            self.widths = vals
        if isinstance(mw, (int, float)):
            self.missing_width = float(mw)

    def advance(self, raw: bytes) -> float:
        """Total glyph advance in unscaled text space units (1/1000 em * size)."""
        if self.widths is None or self.first_char is None:
            return len(raw) * 0.5
        total = 0.0
        for b in raw:
            idx = b - self.first_char
            if 0 <= idx < len(self.widths):
                total += self.widths[idx]
            else:
                total += self.missing_width or 500.0
        return total / 1000.0


    def decode(self, raw: bytes) -> str:
        if not raw:
            return ""
        if self.tounicode:
            out = []
            step = self.width
            if step < 1:
                step = 1
            for i in range(0, len(raw) - step + 1, step):
                code = int.from_bytes(raw[i : i + step], "big")
                ch = self.tounicode.get(code)
                if ch is None:
                    ch = "\ufffd"
                out.append(ch)
            return "".join(out)
        if self.subtype == "Type0":
            return "\ufffd" * (len(raw) // 2)
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            return raw.decode("latin-1", "replace")


# --------------------------------------------------------------------------
# Content stream interpretation
# --------------------------------------------------------------------------


@dataclass
class ShowOp:
    text: str
    x: float
    y: float
    size: float
    font: str
    page: int
    end_x: float = 0.0


def _mul(m1: Tuple[float, ...], m2: Tuple[float, ...]) -> Tuple[float, ...]:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def interpret_content(
    doc: Document,
    data: bytes,
    resources: Dict[str, Any],
    page_no: int,
    ctm: Tuple[float, ...] = IDENTITY,
    depth: int = 0,
    warnings: Optional[List[str]] = None,
) -> List[ShowOp]:
    """Walk a content stream and return positioned text-show operations."""
    if warnings is None:
        warnings = []
    if depth > 6:
        return []
    fonts_raw = doc.resolve((resources or {}).get("Font")) or {}
    if not isinstance(fonts_raw, dict):
        fonts_raw = {}
    font_cache: Dict[str, Font] = {}

    def font_for(nm: str) -> Font:
        if nm not in font_cache:
            spec = doc.resolve(fonts_raw.get(nm))
            font_cache[nm] = Font(doc, spec if isinstance(spec, dict) else {})
        return font_cache[nm]

    ops: List[ShowOp] = []
    lex = Lexer(data)
    operands: List[Any] = []

    tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    tlm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    leading = 0.0
    size = 12.0
    cur_font: Optional[Font] = None
    cur_name = ""
    stack: List[Any] = []

    def show(raw: bytes) -> None:
        nonlocal tm
        f = cur_font
        text = f.decode(raw) if f else raw.decode("latin-1", "replace")
        if not text:
            return
        m = _mul(tuple(tm), ctm)
        eff = abs(tm[0]) * size or size
        units = f.advance(raw) if f else len(raw) * 0.5
        advance = units * size  # unscaled text-space units
        x = m[4]
        y = m[5]
        # horizontal advance as it appears on the page
        scale = math.hypot(m[0], m[1]) or 1.0
        ops.append(ShowOp(text, x, y, eff, cur_name, page_no, x + advance * scale))
        moved = _mul((1.0, 0.0, 0.0, 1.0, advance, 0.0), tuple(tm))
        tm = list(moved)

    def next_line(dy: Optional[float] = None) -> None:
        nonlocal tm, tlm
        d = -leading if dy is None else dy
        tlm = list(_mul((1.0, 0.0, 0.0, 1.0, 0.0, d), tuple(tlm)))
        tm = list(tlm)

    while True:
        try:
            lex.skip_ws()
            if lex.pos >= len(data):
                break
            before = lex.pos
            obj = lex.parse()
        except EOFError:
            break
        except Exception:
            lex.pos = before + 1
            continue
        if lex.pos == before:
            lex.pos = before + 1

        if isinstance(obj, (Name, PDFString)) or not isinstance(obj, str):
            operands.append(obj)
            continue

        op = obj
        if op == "BI":
            end = data.find(b"EI", lex.pos)
            lex.pos = end + 2 if end != -1 else len(data)
            operands = []
            continue

        try:
            if op == "q":
                stack.append((list(tm), list(tlm), leading, size, cur_font, cur_name, ctm))
            elif op == "Q":
                if stack:
                    tm_, tlm_, leading, size, cur_font, cur_name, ctm = stack.pop()
                    tm, tlm = list(tm_), list(tlm_)
            elif op == "cm" and len(operands) >= 6:
                ctm = _mul(tuple(float(x) for x in operands[-6:]), ctm)
            elif op == "BT":
                tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
                tlm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            elif op == "ET":
                pass
            elif op == "Tf" and len(operands) >= 2:
                cur_name = str(operands[-2])
                cur_font = font_for(cur_name)
                try:
                    size = float(operands[-1])
                except (TypeError, ValueError):
                    size = 12.0
                if size <= 0:
                    size = 12.0
            elif op == "TL" and operands:
                try:
                    leading = float(operands[-1])
                except (TypeError, ValueError):
                    pass
            elif op == "Tm" and len(operands) >= 6:
                vals = [float(x) for x in operands[-6:]]
                tm = vals
                tlm = list(vals)
            elif op in ("Td", "TD") and len(operands) >= 2:
                tx, ty = float(operands[-2]), float(operands[-1])
                if op == "TD":
                    leading = -ty
                tlm = list(_mul((1.0, 0.0, 0.0, 1.0, tx, ty), tuple(tlm)))
                tm = list(tlm)
            elif op == "T*":
                next_line()
            elif op == "Tj" and operands and isinstance(operands[-1], PDFString):
                show(bytes(operands[-1]))
            elif op == "TJ" and operands and isinstance(operands[-1], list):
                for item in operands[-1]:
                    if isinstance(item, PDFString):
                        show(bytes(item))
                    elif isinstance(item, (int, float)):
                        # kerning adjustment; approximate as horizontal shift
                        m = _mul(tuple(tm), ctm)
                        shift = -float(item) / 1000.0 * size
                        tm = list(_mul((1.0, 0.0, 0.0, 1.0, shift, 0.0), tuple(tm)))
            elif op == "'" and operands and isinstance(operands[-1], PDFString):
                next_line()
                show(bytes(operands[-1]))
            elif op == '"' and len(operands) >= 3 and isinstance(operands[-1], PDFString):
                next_line()
                show(bytes(operands[-1]))
            elif op == "Do" and operands:
                nm = str(operands[-1])
                xobjs = doc.resolve((resources or {}).get("XObject")) or {}
                if isinstance(xobjs, dict) and nm in xobjs:
                    xo = doc.resolve(xobjs[nm])
                    if isinstance(xo, PDFStream) and str(
                        doc.resolve(xo.dict.get("Subtype")) or ""
                    ) == "Form":
                        sub_res = doc.resolve(xo.dict.get("Resources")) or resources
                        sub_ctm = ctm
                        mat = doc.resolve(xo.dict.get("Matrix"))
                        if isinstance(mat, list) and len(mat) == 6:
                            try:
                                sub_ctm = _mul(tuple(float(v) for v in mat), ctm)
                            except (TypeError, ValueError):
                                sub_ctm = ctm
                        ops.extend(
                            interpret_content(
                                doc,
                                xo.decoded(doc),
                                sub_res if isinstance(sub_res, dict) else resources,
                                page_no,
                                sub_ctm,
                                depth + 1,
                                warnings,
                            )
                        )
        except Exception:
            pass
        operands = []
    return ops


# --------------------------------------------------------------------------
# Layout: lines, blocks, XY-cut reading order
# --------------------------------------------------------------------------


@dataclass
class Line:
    text: str
    x0: float
    x1: float
    y: float
    size: float
    page: int

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y - self.size * 0.25, self.x1, self.y + self.size * 0.85)


def build_lines(ops: List[ShowOp]) -> List[Line]:
    if not ops:
        return []
    # group by baseline within a tolerance derived from font size
    ops_sorted = sorted(ops, key=lambda o: (-o.y, o.x))
    groups: List[List[ShowOp]] = []
    for o in ops_sorted:
        placed = False
        if groups:
            ref = groups[-1][0]
            tol = max(2.0, 0.45 * max(o.size, ref.size))
            if abs(o.y - ref.y) <= tol:
                groups[-1].append(o)
                placed = True
        if not placed:
            groups.append([o])

    lines: List[Line] = []
    for g in groups:
        g = sorted(g, key=lambda o: o.x)
        # Split a same-baseline group wherever the horizontal advance leaves a
        # gap wide enough to be a column gutter rather than a word space. Without
        # this, text from two columns merges into one line and reading order is
        # lost before layout analysis ever runs.
        segments: List[List[ShowOp]] = []
        for o in g:
            if segments:
                prev = segments[-1][-1]
                prev_end = prev.end_x
                gap = o.x - prev_end
                limit = max(0.9 * max(prev.size, o.size), 6.0)
                if gap > limit:
                    segments.append([o])
                    continue
                segments[-1].append(o)
            else:
                segments.append([o])

        for seg in segments:
            text = "".join(o.text for o in seg)
            # collapse runs of spaces introduced by disconnected show ops
            text = re.sub(r"[ \t]{2,}", " ", text).strip()
            if not text:
                continue
            x0 = min(o.x for o in seg)
            x1 = max(o.end_x for o in seg)
            size = max(o.size for o in seg)
            y = max(o.y for o in seg)
            lines.append(Line(text, x0, x1, y, size, seg[0].page))
    return lines


def _empty_gaps(intervals, lo, hi, min_gap):
    """Maximal empty intervals along one axis, given (start, end) spans."""
    if not intervals:
        return []
    ivs = sorted(intervals)
    gaps = []
    cursor = lo
    for a, b in ivs:
        if a - cursor >= min_gap:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if hi - cursor >= min_gap:
        gaps.append((cursor, hi))
    return gaps


def _page_extent(lines):
    x0 = min(ln.bbox[0] for ln in lines)
    x1 = max(ln.bbox[2] for ln in lines)
    y0 = min(ln.bbox[1] for ln in lines)
    y1 = max(ln.bbox[3] for ln in lines)
    return x0, x1, y0, y1


def _coverage_runs(lines, lo, hi, limit, min_width):
    """x-intervals crossed by at most `limit` line boxes, at 1pt resolution."""
    if hi - lo < min_width:
        return []
    n = int(hi - lo) + 1
    counts = [0] * n
    ivs = sorted((max(ln.bbox[0], lo), min(ln.bbox[2], hi)) for ln in lines)
    for a, b in ivs:
        ia = max(0, int(round(a - lo)))
        ib = min(n, int(round(b - lo)))
        for i in range(ia, ib):
            counts[i] += 1
    runs = []
    i = 0
    while i < n:
        if counts[i] <= limit:
            j = i
            while j < n and counts[j] <= limit:
                j += 1
            if (j - i) >= min_width:
                runs.append((lo + i, lo + j - 1))
            i = j
        else:
            i += 1
    return runs


def _best_vertical_split(lines, pad):
    """A gutter is a narrow band crossed by only a few (spanning) lines.

    Empty-interval detection fails on real papers because captions and author
    blocks overlap the gutter; counting crossings is robust to them.
    """
    if len(lines) < 4:
        return None
    x0, x1, _, _ = _page_extent(lines)
    width_total = max(1.0, x1 - x0)
    mid = (x0 + x1) / 2.0
    limit = max(1, int(0.15 * len(lines)))
    runs = _coverage_runs(lines, x0, x1, limit, max(pad, 6.0))

    best = None
    for gs, ge in runs:
        cut = (gs + ge) / 2.0
        if abs(cut - mid) / width_total > 0.30:
            continue
        # Partition on the cut, not on the run edges: a line may end inside the
        # low-coverage band and still belong entirely to the left column.
        left = [ln for ln in lines if ln.bbox[2] <= cut]
        right = [ln for ln in lines if ln.bbox[0] >= cut]
        spans = [ln for ln in lines if ln.bbox[0] < cut < ln.bbox[2]]
        if len(left) < 2 or len(right) < 2:
            continue
        crossing_ratio = len(spans) / float(len(lines))
        if crossing_ratio > 0.35:
            continue
        gap_w = ge - gs
        score = gap_w / width_total - crossing_ratio * 0.45
        if best is None or score > best[0]:
            best = (score, cut, left, right, spans, gap_w)
    return best


def _best_horizontal_split(lines, pad):
    if len(lines) < 3:
        return None
    _, _, y0, y1 = _page_extent(lines)
    height_total = max(1.0, y1 - y0)
    gaps = _empty_gaps([(ln.bbox[1], ln.bbox[3]) for ln in lines], y0, y1, pad)
    best = None
    for gs, ge in gaps:
        upper = [ln for ln in lines if ln.bbox[1] >= ge]
        lower = [ln for ln in lines if ln.bbox[3] <= gs]
        if not upper or not lower:
            continue
        if len(upper) + len(lower) != len(lines):
            continue
        gap_h = ge - gs
        score = gap_h / height_total
        if best is None or score > best[0]:
            best = (score, upper, lower, gap_h)
    return best


def reading_order(lines, pad=8.0, page=None, depth=0):
    """Recursive XY-cut: split on the widest gap, vertical preferred on ties."""
    if len(lines) <= 2 or depth > 32:
        return sorted(lines, key=lambda ln: (-round(ln.y, 1), ln.x0))

    pw = ph = None
    if page:
        pw, ph = page
    if not pw or not ph:
        x0, x1, y0, y1 = _page_extent(lines)
        pw, ph = max(1.0, x1 - x0), max(1.0, y1 - y0)

    v = _best_vertical_split(lines, pad)
    h = _best_horizontal_split(lines, pad)

    # normalise both candidate gaps to the page dimension they cut across
    v_score = (v[5] / pw) if v else -1.0
    h_score = (h[3] / ph) if h else -1.0

    if v and v_score >= h_score * 0.9:
        _, cut, left, right, spans, _ = v
        above = [s for s in spans if s.y > max(l.y for l in left + right) + pad]
        below = [s for s in spans if s.y < min(l.y for l in left + right) - pad]
        middle = [s for s in spans if s not in above and s not in below]
        out = []
        if above:
            out += reading_order(above, pad, page, depth + 1)
        out += reading_order(left, pad, page, depth + 1)
        if middle:
            out += sorted(middle, key=lambda ln: (-round(ln.y, 1), ln.x0))
        out += reading_order(right, pad, page, depth + 1)
        if below:
            out += reading_order(below, pad, page, depth + 1)
        return out

    if h:
        _, upper, lower, _ = h
        return reading_order(upper, pad, page, depth + 1) + reading_order(
            lower, pad, page, depth + 1
        )

    return sorted(lines, key=lambda ln: (-round(ln.y, 1), ln.x0))


def group_blocks(lines: List[Line], gap_factor: float = 1.6) -> List[List[Line]]:
    blocks: List[List[Line]] = []
    for ln in lines:
        if not blocks:
            blocks.append([ln])
            continue
        prev = blocks[-1][-1]
        gap = prev.y - ln.y
        if gap <= max(prev.size, ln.size) * gap_factor and abs(ln.x0 - prev.x0) < 200:
            blocks[-1].append(ln)
        else:
            blocks.append([ln])
    return blocks


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def extract(
    path: str,
    max_pages: Optional[int] = None,
    include_text: bool = True,
) -> Dict[str, Any]:
    with open(path, "rb") as fh:
        data = fh.read()

    doc = Document(data)
    pages = doc.pages()
    warnings: List[str] = list(doc.warnings)
    uncertainty: List[str] = []

    if not pages:
        return {
            "input_id": _input_id(path, data),
            "status": "failed",
            "page_count": 0,
            "pages": [],
            "warnings": warnings or ["no pages parsed"],
            "uncertainty": ["document could not be parsed as a text PDF"],
        }

    page_out: List[Dict[str, Any]] = []
    total_chars = 0
    total_ops = 0

    for idx, page in enumerate(pages, start=1):
        if max_pages and idx > max_pages:
            break
        res = doc.resolve(page.get("Resources")) or {}
        if not isinstance(res, dict):
            res = {}
        contents = doc.resolve(page.get("Contents"))
        chunks: List[bytes] = []
        if isinstance(contents, PDFStream):
            chunks.append(contents.decoded(doc))
        elif isinstance(contents, list):
            for c in contents:
                c = doc.resolve(c)
                if isinstance(c, PDFStream):
                    chunks.append(c.decoded(doc))
        cdata = b"\n".join(chunks)

        ops = interpret_content(doc, cdata, res, idx, warnings=warnings)
        total_ops += len(ops)
        lines = build_lines(ops)

        mbox = doc.resolve(page.get("MediaBox"))
        width = height = None
        if isinstance(mbox, list) and len(mbox) == 4:
            try:
                x0, y0, x1, y1 = (float(doc.resolve(v)) for v in mbox)
                width, height = abs(x1 - x0), abs(y1 - y0)
            except (TypeError, ValueError):
                pass

        ordered = reading_order(lines, page=(width, height))

        # A figure or table spanning the gutter can split the page into bands
        # and let right-column text slip between left-column blocks. Stable
        # partition restores one left-then-right pass without moving spanning
        # lines out of their band.
        columns = _count_columns(lines)
        cut = _column_cut(lines) if columns >= 2 else None
        if cut is not None:
            ordered = [ln for ln in ordered if not (ln.x0 >= cut)] + [
                ln for ln in ordered if ln.x0 >= cut
            ]

        blocks = group_blocks(ordered)

        block_objs = []
        for bi, blk in enumerate(blocks):
            text = " ".join(ln.text for ln in blk).strip()
            if not text:
                continue
            total_chars += len(text)
            xs0 = min(ln.bbox[0] for ln in blk)
            ys0 = min(ln.bbox[1] for ln in blk)
            xs1 = max(ln.bbox[2] for ln in blk)
            ys1 = max(ln.bbox[3] for ln in blk)
            block_objs.append(
                {
                    "id": f"p{idx}-b{bi}",
                    "order": len(block_objs),
                    "type": "text",
                    "bbox": [round(xs0, 2), round(ys0, 2), round(xs1, 2), round(ys1, 2)],
                    "font_size": round(max(ln.size for ln in blk), 2),
                    "text": text,
                    "line_count": len(blk),
                }
            )

        page_out.append(
            {
                "page": idx,
                "width": round(width, 2) if width else None,
                "height": round(height, 2) if height else None,
                "layout": {"columns": columns, "order": "xy_cut"},
                "block_count": len(block_objs),
                "blocks": block_objs,
            }
        )
        if not block_objs and ops:
            uncertainty.append(
                f"page {idx}: {len(ops)} text operations but no assembled lines"
            )
        if not ops:
            uncertainty.append(f"page {idx}: no extractable text layer (scan or vector outlines)")

    if total_ops == 0:
        warnings.append("no text-showing operators found in any page content stream")

    status = "success"
    if not page_out or total_chars == 0:
        status = "failed"
    elif uncertainty:
        status = "partial"

    result: Dict[str, Any] = {
        "input_id": _input_id(path, data),
        "source": {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "status": status,
        "page_count": len(page_out),
        "text_char_count": total_chars,
        "pages": page_out,
        "warnings": warnings,
        "uncertainty": uncertainty,
    }
    if include_text:
        result["text"] = "\n".join(
            "\n".join(b["text"] for b in p["blocks"]) for p in page_out
        )
    return result


def _column_cut(lines):
    """Cut x of the dominant gutter, or None when the page is single column."""
    if len(lines) < 4:
        return None
    x0, x1, _, _ = _page_extent(lines)
    span = max(1.0, x1 - x0)
    body = [ln for ln in lines if (ln.bbox[2] - ln.bbox[0]) < 0.62 * span] or lines
    split = _best_vertical_split(body, 8.0)
    return split[1] if split else None


def _count_columns(lines):
    if len(lines) < 4:
        return 1
    # Full-width title/abstract lines span the gutter; measure the column count
    # on the body lines only, or every two-column page reports one column.
    x0, x1, _, _ = _page_extent(lines)
    span = max(1.0, x1 - x0)
    body = [ln for ln in lines if (ln.bbox[2] - ln.bbox[0]) < 0.62 * span]
    if len(body) < 4:
        body = lines
    split = _best_vertical_split(body, 8.0)
    if not split:
        return 1
    _, _, left, right, _spans, _w = split
    # Table cells and callout boxes look like extra columns; only recurse into
    # a side that carries enough lines to be a real text column.
    nl = _count_columns(left) if len(left) >= 5 else 1
    nr = _count_columns(right) if len(right) >= 5 else 1
    return min(nl + nr, 3)


def _input_id(path: str, data: bytes) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", path.replace("\\", "/").split("/")[-1])
    return f"{base}#{hashlib.sha256(data).hexdigest()[:12]}"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pdf_parse",
        description="Extract PDF text with reading order, page and bbox anchors (stdlib only).",
    )
    ap.add_argument("pdf", help="input PDF path")
    ap.add_argument("-o", "--out", help="output JSON path (default: stdout)")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--no-text", action="store_true", help="omit the flat text field")
    ap.add_argument("--quiet", action="store_true", help="suppress the summary line")
    args = ap.parse_args(argv)

    try:
        result = extract(args.pdf, args.max_pages, not args.no_text)
    except FileNotFoundError:
        print(f"error: no such file: {args.pdf}", file=sys.stderr)
        return 2
    except Exception as exc:  # keep the skill honest about failure
        result = {
            "input_id": args.pdf,
            "status": "failed",
            "pages": [],
            "warnings": [f"{type(exc).__name__}: {exc}"],
            "uncertainty": ["parser raised; no result produced"],
        }

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    else:
        sys.stdout.write(payload + "\n")

    if not args.quiet:
        print(
            f"pdf_order: {result.get('status')} pages={result.get('page_count')} "
            f"chars={result.get('text_char_count', 0)}",
            file=sys.stderr,
        )
    return 0 if result.get("status") in ("success", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
