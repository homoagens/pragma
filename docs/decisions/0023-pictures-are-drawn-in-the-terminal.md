# 23. Pictures are drawn in the terminal

- **Date:** 2026-10-14
- **Status:** accepted
- **Where:** [`agent/picture.py`](../../agent/picture.py), [`core/tools/show_image/`](../../core/tools/show_image/README.md), [`agent/harness.py`](../../agent/harness.py), [`agent/ledger.py`](../../agent/ledger.py)

## Context

An answer that wrote `![chart](chart.png)` was drawn by the terminal as an
icon and the image's name, and the agent took it that the person had seen
the chart. Asked to show one, it tried to install a viewer, or wrote the
image out as base64. A line in the prompt was not enough to stop either.

## Decision

Pragma draws the image itself, in two ways.

- An image file in the workspace that the answer shows, as Markdown, is
  drawn under the paragraph that names it.
- `show_image`, a tool offered only in a conversation, draws a file under
  its own step, and tells the agent what the person saw.

Each character cell is two pixels, one above the other, in the terminal's
own colours. PNG and JPEG are read in plain Python, so nothing has to be
installed; Pillow is used when it is there. An image already drawn in a turn
is not drawn again.

## Consequences

- The picture is coarse: shapes and colours show, small text does not. The
  tool says so to the agent.
- A terminal that offers 256 colours rather than millions draws it with
  halos.
- A single task run from a script is not offered the tool: nobody is there
  to see. Where a picture cannot be drawn, the agent is told why and gives
  the file's path instead.
- Image protocols that draw real pixels (Sixel and others) are not used.
- Interlaced PNGs and some JPEGs (CMYK, 12-bit, arithmetic coding) are not
  drawn, and a line says why. A progressive JPEG is drawn from its first,
  coarse pass, which at this size is enough.
