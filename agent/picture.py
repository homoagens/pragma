# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""An image drawn in the terminal, for the person to see.

A reply is shown as Markdown, and Markdown in a terminal has no way to show
an image: `![Monthly sales](chart.png)` came out as "🌆 Monthly sales". The
person who asked to see a chart saw its title, and the model, which had
written the image into its reply, told them "here is the chart". Asked again,
it filled its reply with base64, which showed nothing either; asked a third
time, it went looking for an image viewer to install.

So an image is drawn here, two pixels to a character: `▀`, the upper pixel
its colour and the lower one its background. It is coarse - a chart's bars
and colours read, its small labels mostly do not - and the line under it
names the file, to be opened for a close look. Two things draw one:

- THE `show_image` TOOL, in a conversation: the picture comes under the step
  that asked for it, and what was drawn goes back to the agent - which is
  also what tells the critic the image was shown. A weak model asked to show
  an image looks for a tool to do it, and this is the one it finds.
- AN IMAGE IN THE ANSWER, written as Markdown, is drawn under the paragraph
  that names it - unless the tool drew it in the same turn. Only a file in
  the workspace: not a page on the web, which would be a request nobody
  asked for, and not an image written out as data, which a model will fill
  with bytes it cannot know.

Pillow reads the image when it is installed, whatever its format. Pragma does
not need it for anything else, so when it is missing PNG and JPEG are read
here, in Python: see png() and jpeg().
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

# Files past these are not read. The pixel limits are for the readers here,
# which decode in Python: past them the person would wait seconds for a
# thumbnail. A JPEG of the same size costs less, since only as much of it is
# decoded as the picture needs.
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 4_000_000
MAX_JPEG_PIXELS = 25_000_000

# A Markdown image: ![alt](target) or ![alt](<target with spaces>), with an
# optional title after the target.
_IMAGE = re.compile(r"!\[[^\]\n]*\]\(\s*(?:<([^<>\n]+)>|([^\s()]+))"
                    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)")
# What is quoted rather than shown: a fence, closed or not, and a code span.
_FENCE = re.compile(r"^[ \t]*(```|~~~).*?(?:^[ \t]*\1|\Z)", re.M | re.S)
_SPAN = re.compile(r"`[^`\n]*`")


class Unreadable(Exception):
    """Why an image could not be drawn, in words for the person."""


# What has been drawn in this turn, so that an image the tool showed is not
# drawn again under the answer that mentions it. The harness forgets at the
# start of every turn.
_drawn: set[str] = set()


def forget() -> None:
    _drawn.clear()


def drawn(path: str) -> bool:
    return os.path.realpath(path) in _drawn


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
    says which file it was and why. prepare() reads it ahead of printing,
    for a caller that has to know whether it will be drawn.
    """

    def __init__(self, path: str, root: str = ""):
        self.path = path
        self.name = _name(path, root or workspace())
        self.rows: list | None = None
        self.size = (0, 0)
        self.cols = 0
        self.why = ""

    def prepare(self, console, width: int) -> bool:
        """Read the image for this console, at most `width` columns wide:
        whether there is a picture to draw. `why` says why not."""
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
            self.size, pixels = read(self.path, min(MAX_COLS, width), max(8, height - 4))
            self.rows = list(_segments(pixels))
            self.cols = len(pixels[0]) if pixels else 0
        except Unreadable as e:
            self.rows, self.why = [], str(e)
        except Exception as e:                        # a file that is not what it says
            self.rows, self.why = [], f"it could not be read ({type(e).__name__})"
        if self.rows:
            _drawn.add(os.path.realpath(self.path))
        return bool(self.rows)

    def __rich_console__(self, console, options):
        from rich.segment import Segment
        from rich.style import Style
        if self.rows is None:
            self.prepare(console, options.max_width)
        caption = (f"{self.name} · {self.size[0]}×{self.size[1]}" if self.rows
                   else f"{self.name} · not drawn: {self.why}")
        try:
            caption.encode(console.encoding or "utf-8")
        except (UnicodeError, LookupError):
            caption = caption.replace("·", "-").replace("×", "x")
        for row in self.rows:
            yield from row
            yield Segment.line()
        yield Segment(caption, Style(color="bright_black"))
        yield Segment.line()


def _name(path: str, root: str) -> str:
    """A path as the person reads it: from the workspace when it is in it."""
    try:
        inside = os.path.relpath(path, root)
        if not inside.startswith(".."):
            return inside.replace(os.sep, "/")
    except ValueError:
        pass
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def read(path: str, cols: int, rows: int) -> tuple[tuple[int, int], list[list[tuple]]]:
    """((width, height), pixels): the image's own size, and its pixels as
    (r, g, b, a), scaled down to fit `cols` columns and `rows` rows of two
    pixels each. Raises Unreadable."""
    if not os.path.isfile(path):
        raise Unreadable("there is no such file")
    if os.path.getsize(path) > MAX_BYTES:
        raise Unreadable("the file is too large")
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return _without_pillow(path, cols, rows)
    return _with_pillow(path, cols, rows)


def _without_pillow(path: str, cols: int, rows: int):
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(_SIGNATURE):
        width, height, channels, lines = png(path)
        wide, tall = width, height
    elif head.startswith(b"\xff\xd8"):
        width, height, wide, tall, channels, lines = jpeg(path, cols, rows)
    else:
        raise Unreadable("only PNG and JPEG are drawn without Pillow installed")
    size = _fit(width, height, cols, rows)
    if size[0] > wide or size[1] > tall:             # a progressive JPEG, read at 1/8
        size = _fit(wide, tall, cols, rows)
    return (width, height), _scaled(wide, tall, channels, lines, *size)


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
            data = list(small.get_flattened_data() if hasattr(small, "get_flattened_data")
                        else small.getdata())
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
        raise Unreadable("not a PNG")
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


# ── a JPEG, without Pillow ──────────────────────────────────────────────────
#
# A JPEG keeps each 8x8 block of each colour component as 64 frequencies,
# Huffman-coded, and the first of them is the block's mean. A picture of a
# hundred columns needs a few thousand pixels, so the image is decoded at the
# smallest scale that still has them: at 1/8 a block IS its first frequency,
# with no transform to compute, and at 1/4 or 1/2 only the frequencies that a
# 2x2 or 4x4 block can show are used. What is paid in full is reading the
# codes, every one of them, since each is found only after the one before.

# Where the k-th frequency of a block, in the order they are stored, sits in
# the 8x8 grid: row * 8 + column.
_ZIGZAG = (0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33,
           40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36,
           29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54,
           47, 55, 62, 63)
_ONES = tuple((1 << n) - 1 for n in range(65))
_WORD = struct.Struct(">I").unpack_from
# Where the coded data of a scan ends: a marker that is neither a stuffed
# zero nor a restart.
_END_OF_SCAN = re.compile(rb"\xff[^\x00\xd0-\xd7]")
_RESTART = re.compile(rb"\xff[\xd0-\xd7]")


def jpeg(path: str, cols: int, rows: int) -> tuple[int, int, int, int, int, list[bytes]]:
    """(width, height, decoded width, decoded height, channels, lines): a
    JPEG decoded just large enough for a picture of `cols` x `rows`.

    Baseline JPEGs are read whole. A progressive one stores the block means
    in its first pass, and is drawn from that pass alone, at 1/8. Raises
    Unreadable.
    """
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"\xff\xd8"):
        raise Unreadable("not a JPEG")
    quant: dict = {}
    codes: dict = {}
    frame = None
    restart, adobe, pos = 0, None, 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise Unreadable("the JPEG is damaged")
        marker = data[pos + 1]
        if marker == 0xFF:                               # a fill byte
            pos += 1
            continue
        if marker == 0xD9:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:     # no length follows these
            pos += 2
            continue
        length = (data[pos + 2] << 8) | data[pos + 3]
        body, pos = data[pos + 4:pos + 2 + length], pos + 2 + length
        if marker == 0xDB:
            _quantisers(body, quant)
        elif marker == 0xC4:
            _code_tables(body, codes)
        elif marker == 0xDD:
            restart = (body[0] << 8) | body[1]
        elif marker == 0xEE and body.startswith(b"Adobe") and len(body) > 11:
            adobe = body[11]
        elif marker in (0xC0, 0xC1, 0xC2):
            frame = _Frame(body, marker == 0xC2, cols, rows)
        elif 0xC3 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            raise Unreadable("a kind of JPEG only Pillow reads")
        elif marker == 0xDA:
            if frame is None:
                raise Unreadable("the JPEG is damaged")
            end = _END_OF_SCAN.search(data, pos)
            end = end.start() if end else len(data)
            frame.scan(body, data[pos:end], quant, codes, restart)
            pos = end
    if frame is None or not frame.scanned:
        raise Unreadable("the JPEG has no image in it")
    return frame.pixels(adobe)


def _quantisers(body: bytes, quant: dict) -> None:
    """The quantisation tables of a DQT segment, in stored order."""
    i = 0
    while i < len(body):
        wide, slot = body[i] >> 4, body[i] & 15
        if wide:
            quant[slot] = struct.unpack(">64H", body[i + 1:i + 129])
            i += 129
        else:
            quant[slot] = tuple(body[i + 1:i + 65])
            i += 65


def _code_tables(body: bytes, codes: dict) -> None:
    """The Huffman tables of a DHT segment, keyed ("dc" | "ac", slot)."""
    i = 0
    while i + 17 <= len(body):
        kind, slot = body[i] >> 4, body[i] & 15
        counts = body[i + 1:i + 17]
        symbols = body[i + 17:i + 17 + sum(counts)]
        i += 17 + sum(counts)
        codes[("ac" if kind else "dc", slot)] = _huffman(counts, symbols)


def _huffman(counts: bytes, symbols: bytes) -> tuple:
    """(look, longest, start, first, symbols): a code of up to nine bits is
    found in `look` by the nine bits ahead; a longer one, length by length,
    the way the standard describes it."""
    look: list = [None] * 512
    longest, start, first = [-1] * 17, [0] * 17, [0] * 17
    code = k = 0
    for length in range(1, 17):
        n = counts[length - 1]
        start[length], first[length] = k, code
        for _ in range(n):
            if length <= 9:
                spare = 9 - length
                for tail in range(1 << spare):
                    look[(code << spare) | tail] = (length, symbols[k])
            code += 1
            k += 1
        if n:
            longest[length] = code - 1
        code <<= 1
    return look, longest, start, first, symbols


def _long_code(acc: int, bits: int, table: tuple) -> tuple[int, int]:
    _, longest, start, first, symbols = table
    for length in range(10, 17):
        code = (acc >> (bits - length)) & _ONES[length]
        if code <= longest[length]:
            return length, symbols[start[length] + code - first[length]]
    raise Unreadable("the JPEG is damaged")


@lru_cache(maxsize=None)
def _basis(n: int) -> dict:
    """For each frequency an n x n block can show - by its place in the 8x8
    grid - what it adds to each of the block's n*n samples per unit."""
    import math
    out = {}
    for place in range(64):
        v, u = divmod(place, 8)
        if u >= n or v >= n:
            continue
        cu = 0.5 * (math.sqrt(0.5) if u == 0 else 1.0)
        cv = 0.5 * (math.sqrt(0.5) if v == 0 else 1.0)
        out[place] = [cv * math.cos((2 * y + 1) * v * math.pi / (2 * n))
                      * cu * math.cos((2 * x + 1) * u * math.pi / (2 * n))
                      for y in range(n) for x in range(n)]
    return out


@lru_cache(maxsize=None)
def _kept(n: int) -> tuple:
    """Which of the 64 stored frequencies an n x n block uses."""
    basis = _basis(n)
    return tuple(_ZIGZAG[k] in basis for k in range(64))


class _Frame:
    """The image a JPEG describes, filled in one scan at a time."""

    def __init__(self, body: bytes, progressive: bool, cols: int, rows: int):
        precision, height, width, count = struct.unpack(">BHHB", body[:6])
        if precision != 8:
            raise Unreadable("a JPEG of 12-bit samples, which only Pillow reads")
        if count not in (1, 3):
            raise Unreadable("a CMYK JPEG, which only Pillow reads")
        if not width or not height:
            raise Unreadable("a kind of JPEG only Pillow reads")
        if width * height > MAX_JPEG_PIXELS:
            raise Unreadable(f"{width}×{height} is too large to draw without Pillow installed")
        self.width, self.height, self.progressive = width, height, progressive
        self.ids, self.h, self.v, self.slots = [], [], [], []
        for i in range(count):
            cid, hv, slot = body[6 + 3 * i:9 + 3 * i]
            if not (1 <= hv >> 4 <= 4 and 1 <= hv & 15 <= 4):
                raise Unreadable("the JPEG is damaged")
            self.ids.append(cid)
            self.h.append(hv >> 4)
            self.v.append(hv & 15)
            self.slots.append(slot)
        self.hmax, self.vmax = max(self.h), max(self.v)
        self.across = -(-width // (8 * self.hmax))
        self.down = -(-height // (8 * self.vmax))
        want = _fit(width, height, cols, rows)
        self.n = 1 if progressive else next(
            n for n in (1, 2, 4, 8)
            if -(-width * n // 8) >= want[0] and -(-height * n // 8) >= want[1])
        n = self.n
        self.planes = [[bytearray(b"\x80" * (self.across * h * n)) for _ in range(self.down * v * n)]
                       for h, v in zip(self.h, self.v)]
        self.scanned = False

    def scan(self, header: bytes, data: bytes, quant: dict, codes: dict, restart: int) -> None:
        count = header[0]
        members = []
        for i in range(count):
            cid, slots = header[1 + 2 * i], header[2 + 2 * i]
            if cid not in self.ids:
                raise Unreadable("the JPEG is damaged")
            members.append((self.ids.index(cid), slots >> 4, slots & 15))
        first, shifts = header[1 + 2 * count], header[3 + 2 * count]
        shift = shifts & 15
        if self.progressive:
            # Only the first pass of the block means: the rest refine what a
            # picture this size cannot show.
            if first != 0 or shifts >> 4:
                return
            ac = False
        else:
            ac, shift = True, 0
        tables = {}
        for c, dc, ac_slot in members:
            if ("dc", dc) not in codes or (ac and ("ac", ac_slot) not in codes) \
                    or self.slots[c] not in quant:
                raise Unreadable("the JPEG is damaged")
            tables[c] = (codes[("dc", dc)], codes.get(("ac", ac_slot)), quant[self.slots[c]])
        if count == 1:
            # One component on its own goes block by block across its own
            # width, not by the units the components share.
            c = members[0][0]
            across = -(-(-(-self.width * self.h[c] // self.hmax)) // 8)
            down = -(-(-(-self.height * self.v[c] // self.vmax)) // 8)
            units = [(c, 1, 1, 0, 0)]
        else:
            across, down = self.across, self.down
            units = [(c, self.h[c], self.v[c], dx, dy) for c, _, _ in members
                     for dy in range(self.v[c]) for dx in range(self.h[c])]
        n = self.n
        kept, basis = _kept(n), _basis(n)
        total = across * down
        per = restart or total
        parts = _RESTART.split(data) if restart else [data]
        m = 0
        for part in parts:
            if m >= total:
                break
            buf = part.replace(b"\xff\x00", b"\xff") + bytes(16)
            size = len(buf) - 8
            pos = acc = bits = 0
            before = [0] * len(self.ids)
            stop = min(m + per, total)
            while m < stop:
                mx, my = m % across, m // across
                m += 1
                for c, hm, vm, dx, dy in units:
                    dc_table, ac_table, q = tables[c]
                    if bits < 32:
                        if pos > size:
                            raise Unreadable("the JPEG is damaged")
                        acc = ((acc & _ONES[bits]) << 32) | _WORD(buf, pos)[0]
                        pos += 4
                        bits += 32
                    hit = dc_table[0][(acc >> (bits - 9)) & 511]
                    length, s = hit if hit else _long_code(acc, bits, dc_table)
                    bits -= length
                    if s:
                        diff = (acc >> (bits - s)) & _ONES[s]
                        bits -= s
                        if diff < 1 << (s - 1):
                            diff -= _ONES[s]
                        before[c] += diff
                    found = None
                    if ac:
                        look = ac_table[0]
                        k = 1
                        while k < 64:
                            if bits < 32:
                                if pos > size:
                                    raise Unreadable("the JPEG is damaged")
                                acc = ((acc & _ONES[bits]) << 32) | _WORD(buf, pos)[0]
                                pos += 4
                                bits += 32
                            hit = look[(acc >> (bits - 9)) & 511]
                            length, rs = hit if hit else _long_code(acc, bits, ac_table)
                            bits -= length
                            s = rs & 15
                            if not s:
                                if rs != 0xF0:
                                    break                    # the rest of the block is zero
                                k += 16
                                continue
                            k += rs >> 4
                            if k > 63:
                                raise Unreadable("the JPEG is damaged")
                            if kept[k]:
                                value = (acc >> (bits - s)) & _ONES[s]
                                if value < 1 << (s - 1):
                                    value -= _ONES[s]
                                if found is None:
                                    found = []
                                found.append((_ZIGZAG[k], value * q[k]))
                            bits -= s
                            k += 1
                    self._put(c, mx * hm + dx, my * vm + dy, (before[c] << shift) * q[0], found, basis)
        self.scanned = True

    def _put(self, c: int, bx: int, by: int, mean: int, found, basis: dict) -> None:
        """One decoded block into its component's plane, as n x n samples."""
        n, plane = self.n, self.planes[c]
        x0, y0 = bx * n, by * n
        if y0 >= len(plane) or x0 >= len(plane[0]):
            return
        if n == 1:
            value = (mean + 4) // 8 + 128
            plane[y0][x0] = 0 if value < 0 else 255 if value > 255 else value
            return
        out = [mean / 8 + 128.5] * (n * n)
        for place, f in found or ():
            for i, b in enumerate(basis[place]):
                out[i] += f * b
        for y in range(n):
            plane[y0 + y][x0:x0 + n] = bytes(0 if v < 0 else 255 if v > 255 else int(v)
                                             for v in out[y * n:(y + 1) * n])

    def pixels(self, adobe) -> tuple[int, int, int, int, int, list[bytes]]:
        n = self.n
        wide, tall = -(-self.width * n // 8), -(-self.height * n // 8)
        if len(self.ids) == 1:
            return (self.width, self.height, wide, tall, 1,
                    [bytes(row[:wide]) for row in self.planes[0][:tall]])
        # Three components are luma and two of colour, unless the file says
        # they are red, green and blue.
        as_is = adobe == 0 or bytes(self.ids) == b"RGB"
        ia, ib, ic = ([x * h // self.hmax for x in range(wide)] for h in self.h)
        lines = []
        for y in range(tall):
            a, b, c = (self.planes[i][y * self.v[i] // self.vmax] for i in range(3))
            out = bytearray(3 * wide)
            if as_is:
                for x in range(wide):
                    out[3 * x:3 * x + 3] = bytes((a[ia[x]], b[ib[x]], c[ic[x]]))
            else:
                for x in range(wide):
                    luma, blue, red = a[ia[x]], b[ib[x]] - 128, c[ic[x]] - 128
                    r = int(luma + 1.402 * red + 0.5)
                    g = int(luma - 0.344136 * blue - 0.714136 * red + 0.5)
                    bl = int(luma + 1.772 * blue + 0.5)
                    out[3 * x] = 0 if r < 0 else 255 if r > 255 else r
                    out[3 * x + 1] = 0 if g < 0 else 255 if g > 255 else g
                    out[3 * x + 2] = 0 if bl < 0 else 255 if bl > 255 else bl
            lines.append(bytes(out))
        return self.width, self.height, wide, tall, 3, lines
