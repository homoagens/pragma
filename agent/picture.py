# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""An image the answer points at, drawn in the terminal.

A reply is shown as Markdown, and Markdown in a terminal has no way to show
an image: `![Monthly sales](chart.png)` came out as "🌆 Monthly sales". The
person who asked to see a chart saw its title, and the model, which had
written the image into its reply, told them "here is the chart". Asked again,
it filled its reply with base64, which showed nothing either.

So an image the answer points at is drawn under the paragraph that names it,
two pixels to a character: `▀`, the upper pixel its colour and the lower one
its background. It is coarse - a chart's bars and colours read, its small
labels mostly do not - and the line under it names the file, to be opened for
a close look.

ONLY A FILE IN THE WORKSPACE. Not a page on the web, which would be a request
nobody asked for, and not an image written out as data, which a model will
otherwise fill with bytes it cannot know. A path that leads out of the
workspace is not followed.

Pillow reads the image when it is installed, whatever its format. Pragma does
not need it for anything else, so when it is missing a PNG is read here, with
zlib, and other formats are named and left undrawn.
"""

from __future__ import annotations

import os
import re
import struct
import urllib.parse
import zlib
from functools import lru_cache
from operator import mul

SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

# As wide as the window allows, up to this: wider, a picture of a few hundred
# pixels is not any clearer, and it is one more thing pushing the reply up.
MAX_COLS = 100

# Files past these are not read. The pixel limit is for the reader here,
# which decodes in Python: past it the person would wait seconds for a
# thumbnail.
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 4_000_000

# A Markdown image: ![alt](target) or ![alt](<target with spaces>), with an
# optional title after the target.
_IMAGE = re.compile(r"!\[[^\]\n]*\]\(\s*(?:<([^<>\n]+)>|([^\s()]+))"
                    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)")
# What is quoted rather than shown: a fence, closed or not, and a code span.
_FENCE = re.compile(r"^[ \t]*(```|~~~).*?(?:^[ \t]*\1|\Z)", re.M | re.S)
_SPAN = re.compile(r"`[^`\n]*`")


class Unreadable(Exception):
    """Why an image could not be drawn, in words for the person."""


# ── which images ────────────────────────────────────────────────────────────

def workspace() -> str:
    """The folder of the open session: images are looked for in it."""
    try:
        import checkpoint
        root = checkpoint.root()
        if root:
            return str(root)
    except Exception:
        pass
    return os.getcwd()


def found(text: str, root: str = "") -> list[str]:
    """The image files in the workspace this Markdown shows, in order, once each."""
    root = root or workspace()
    shown = _SPAN.sub("", _FENCE.sub("", text or ""))
    out: list[str] = []
    for m in _IMAGE.finditer(shown):
        path = _local(m.group(1) or m.group(2) or "", root)
        if path and path not in out:
            out.append(path)
    return out


def _local(target: str, root: str) -> str:
    """The workspace file a link names, or "": never a page, never data."""
    target = target.strip()
    if target.lower().startswith("file://"):
        target = urllib.parse.unquote(target[7:])
    elif re.match(r"^[a-z][\w+.-]*:", target, re.I) and not re.match(r"^[a-z]:[\\/]", target, re.I):
        return ""                                    # http:, data:, ... but C:\ is a path
    if not target.lower().endswith(SUFFIXES):
        return ""
    path = os.path.expanduser(target)
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    try:
        path, base = os.path.realpath(path), os.path.realpath(root)
        if os.path.commonpath([path, base]) != base or not os.path.isfile(path):
            return ""
    except (ValueError, OSError):
        return ""
    return path


# ── drawing ─────────────────────────────────────────────────────────────────

class Picture:
    """The image at `path`, drawn to fit the window, with its name under it.

    It never fails to print: an image that cannot be drawn is a line that
    says which file it was and why.
    """

    def __init__(self, path: str, root: str = ""):
        self.path = path
        root = root or workspace()
        try:
            self.name = os.path.relpath(path, root).replace(os.sep, "/")
        except ValueError:
            self.name = path

    def __rich_console__(self, console, options):
        from rich.segment import Segment
        from rich.style import Style
        dim = Style(color="bright_black")
        try:
            if console.color_system not in ("truecolor", "256"):
                raise Unreadable("this terminal has too few colours for a picture")
            try:
                "▀▄".encode(console.encoding or "utf-8")
            except (UnicodeError, LookupError):
                raise Unreadable("this terminal cannot print the characters it is drawn with")
            try:
                height = console.size.height
            except Exception:
                height = 24
            size, pixels = read(self.path, min(MAX_COLS, options.max_width), max(8, height - 4))
            rows = list(_segments(pixels))
            caption = f"{self.name} · {size[0]}×{size[1]}"
        except Unreadable as e:
            rows, caption = [], f"{self.name} · not drawn: {e}"
        except Exception as e:                        # a file that is not what it says
            rows, caption = [], f"{self.name} · not drawn: {type(e).__name__}"
        try:
            caption.encode(console.encoding or "utf-8")
        except (UnicodeError, LookupError):
            caption = caption.replace("·", "-").replace("×", "x")
        for row in rows:
            yield from row
            yield Segment.line()
        yield Segment(caption, dim)
        yield Segment.line()


def read(path: str, cols: int, rows: int) -> tuple[tuple[int, int], list[list[tuple]]]:
    """((width, height), pixels): the image's own size, and its pixels as
    (r, g, b, a), scaled down to fit `cols` columns and `rows` rows of two
    pixels each. Raises Unreadable."""
    if os.path.getsize(path) > MAX_BYTES:
        raise Unreadable("the file is too large")
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        width, height, channels, lines = png(path)
        size = _fit(width, height, cols, rows)
        return (width, height), _scaled(width, height, channels, lines, *size)
    return _with_pillow(path, cols, rows)


def _fit(width: int, height: int, cols: int, rows: int) -> tuple[int, int]:
    """(columns, pixel rows) the picture takes: never larger than the image."""
    cols = max(1, min(width, cols))
    tall = max(1, min(height, round(height * cols / width)))
    if (tall + 1) // 2 > rows:
        tall = rows * 2
        cols = max(1, min(cols, round(width * tall / height)))
    return cols, tall


def _with_pillow(path: str, cols: int, rows: int):
    from PIL import Image
    try:
        with Image.open(path) as im:
            size = im.size
            w, h = _fit(*size, cols, rows)
            if im.format == "JPEG" and im.mode == "RGB":
                im.draft("RGB", (w, h))              # read at a fraction of its size
            box = getattr(Image, "Resampling", Image).BOX
            small = im.convert("RGBA").resize((w, h), box)
            data = list(small.getdata())
    except (OSError, ValueError, getattr(Image, "DecompressionBombError", OSError)) as e:
        raise Unreadable(str(e) or "Pillow could not read it")
    return size, [data[y * w:(y + 1) * w] for y in range(h)]


def _segments(pixels: list[list[tuple]]):
    """One list of segments per row of characters: ▀ for two pixels, ▄ when
    only the lower one is there, a space when neither is. A pixel more than
    half transparent is left to the terminal's own background."""
    from rich.color import Color
    from rich.segment import Segment
    from rich.style import Style

    styles: dict = {}

    def style(fg, bg):
        key = (fg, bg)
        if key not in styles:
            styles[key] = Style(color=Color.from_rgb(*fg) if fg else None,
                                bgcolor=Color.from_rgb(*bg) if bg else None)
        return styles[key]

    for y in range(0, len(pixels), 2):
        top = pixels[y]
        low = pixels[y + 1] if y + 1 < len(pixels) else None
        row, run, count = [], None, 0
        for x, t in enumerate(top):
            b = low[x] if low is not None else None
            up = t[:3] if t[3] >= 128 else None
            down = b[:3] if b is not None and b[3] >= 128 else None
            if up is not None:
                cell = ("▀", up, down)
            elif down is not None:
                cell = ("▄", down, None)
            else:
                cell = (" ", None, None)
            if cell == run:
                count += 1
                continue
            if run is not None:
                row.append(Segment(run[0] * count, style(run[1], run[2])))
            run, count = cell, 1
        if run is not None:
            row.append(Segment(run[0] * count, style(run[1], run[2])))
        yield row


def _scaled(width: int, height: int, channels: int, lines: list[bytes],
            cols: int, tall: int) -> list[list[tuple]]:
    """The image shrunk to cols x tall, each pixel the mean of those under it.

    With an alpha channel the colours are weighed by it: a transparent pixel
    keeps whatever colour it was stored with, black as often as not, and
    counted like the others it darkened every edge it touched.
    """
    def spans(n, parts):
        return [(i * n // parts, max(i * n // parts + 1, (i + 1) * n // parts)) for i in range(parts)]

    alpha = channels in (2, 4)
    tints = channels - 1 if alpha else channels
    xs, out = spans(width, cols), []
    for y0, y1 in spans(height, tall):
        acc = [0] * (cols * channels)
        for line in lines[y0:y1]:
            for c, (x0, x1) in enumerate(xs):
                seg, at = line[x0 * channels:x1 * channels], c * channels
                if not alpha:
                    for k in range(channels):
                        acc[at + k] += sum(seg[k::channels])
                    continue
                a = seg[tints::channels]
                acc[at + tints] += sum(a)
                if a.count(255) == len(a):
                    for k in range(tints):
                        acc[at + k] += 255 * sum(seg[k::channels])
                elif any(a):
                    for k in range(tints):
                        acc[at + k] += sum(map(mul, seg[k::channels], a))
        row = []
        for c, (x0, x1) in enumerate(xs):
            n, at = (y1 - y0) * (x1 - x0), c * channels
            if alpha:
                weight = acc[at + tints]
                v = [s // weight if weight else 0 for s in acc[at:at + tints]] + [weight // n]
            else:
                v = [s // n for s in acc[at:at + channels]]
            if channels == 1:
                row.append((v[0], v[0], v[0], 255))
            elif channels == 2:
                row.append((v[0], v[0], v[0], v[1]))
            elif channels == 3:
                row.append((v[0], v[1], v[2], 255))
            else:
                row.append(tuple(v))
        out.append(row)
    return out


# ── a PNG, without Pillow ───────────────────────────────────────────────────

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}       # colour type -> samples per pixel


def png(path: str) -> tuple[int, int, int, list[bytes]]:
    """(width, height, channels, lines): a PNG as rows of 8-bit samples, one
    to four per pixel - grey, grey and alpha, RGB, RGBA. Raises Unreadable."""
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(_SIGNATURE):
        raise Unreadable("only PNG can be drawn without Pillow installed")
    header, palette, transparent, idat, pos = None, b"", b"", [], 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparent = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise Unreadable("the PNG has no header")
    width, height, depth, colour, _, _, interlaced = header
    samples = _SAMPLES.get(colour)
    if samples is None or depth not in (1, 2, 4, 8, 16) or not width or not height:
        raise Unreadable("a kind of PNG only Pillow reads")
    if interlaced:
        raise Unreadable("an interlaced PNG, which only Pillow reads")
    if width * height > MAX_PIXELS:
        raise Unreadable(f"{width}×{height} is too large to draw without Pillow installed")
    bits = samples * depth
    bpp, stride = max(1, bits // 8), (width * bits + 7) // 8
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        raise Unreadable("the PNG is damaged")
    if len(raw) < height * (stride + 1):
        raise Unreadable("the PNG is cut short")

    lines, prev = [], bytes(stride)
    for y in range(height):
        at = y * (stride + 1)
        prev = _unfilter(raw[at], raw[at + 1:at + 1 + stride], prev, bpp)
        lines.append(prev)

    if depth == 16:                                  # the high byte of each sample
        lines = [line[0::2] for line in lines]
    elif depth < 8:
        table = _unpacked(depth, colour == 0)
        lines = [b"".join(table[b] for b in line)[:width] for line in lines]
    channels = samples
    if colour == 3:                                  # indices into the palette
        channels = 4 if transparent else 3
        colours = [palette[3 * i:3 * i + 3].ljust(3, b"\0")
                   + (bytes([transparent[i] if i < len(transparent) else 255])
                      if transparent else b"")
                   for i in range(256)]
        lines = [b"".join(colours[i] for i in line) for line in lines]
    return width, height, channels, lines


@lru_cache(maxsize=None)
def _unpacked(depth: int, grey: bool) -> list[bytes]:
    """For each byte of a 1-, 2- or 4-bit image, the samples in it: grey
    levels stretched to 0-255, palette indices as they are."""
    top = (1 << depth) - 1
    table = []
    for byte in range(256):
        values = [(byte >> shift) & top for shift in range(8 - depth, -1, -depth)]
        table.append(bytes(v * 255 // top if grey else v for v in values))
    return table


@lru_cache(maxsize=64)
def _masks(n: int) -> tuple[int, int, int]:
    return (int.from_bytes(b"\x7f" * n, "little"), int.from_bytes(b"\x80" * n, "little"),
            (1 << 8 * n) - 1)


def _add(a: int, b: int, n: int) -> int:
    """Two rows of n bytes added byte by byte, each sum modulo 256, as two
    big integers: the low seven bits are added with room to spare, the top
    bit is put back by hand, and no carry crosses into the next byte."""
    lo, hi, _ = _masks(n)
    return ((a & lo) + (b & lo)) ^ ((a ^ b) & hi)


def _unfilter(kind: int, line: bytes, prev: bytes, bpp: int) -> bytes:
    """One row of a PNG as it was before the encoder filtered it.

    None, Up and Sub are done on whole rows at once, as integers - Sub as a
    running sum taken in doubling strides. Average and Paeth depend on the
    byte just decoded, and go one byte at a time.
    """
    n = len(line)
    if kind == 0:
        return line
    if kind == 2:
        return _add(int.from_bytes(line, "little"), int.from_bytes(prev, "little"),
                    n).to_bytes(n, "little")
    if kind == 1:
        full = _masks(n)[2]
        v, step = int.from_bytes(line, "little"), bpp
        while step < n:
            v = _add(v, (v << 8 * step) & full, n)
            step *= 2
        return v.to_bytes(n, "little")
    out = bytearray(line)
    if kind == 3:
        for i in range(min(bpp, n)):
            out[i] = (out[i] + (prev[i] >> 1)) & 255
        for i in range(bpp, n):
            out[i] = (out[i] + ((out[i - bpp] + prev[i]) >> 1)) & 255
        return bytes(out)
    if kind == 4:
        for i in range(min(bpp, n)):
            out[i] = (out[i] + prev[i]) & 255
        for i in range(bpp, n):
            a, b, c = out[i - bpp], prev[i], prev[i - bpp]
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - c - c)
            if pa <= pb and pa <= pc:
                out[i] = (out[i] + a) & 255
            elif pb <= pc:
                out[i] = (out[i] + b) & 255
            else:
                out[i] = (out[i] + c) & 255
        return bytes(out)
    raise Unreadable("the PNG is damaged")
