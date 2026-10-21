"""
verify_qr.py - prove the setup card's QR code is actually scannable.

A QR that a phone cannot read is worse than no QR at all: the user scans it
and gets nothing. This decodes the inline SVG with OpenCV's QRCodeDetector
and checks the payload matches the playlist URL printed on the page.

The module grid is recovered from the SVG path data (qrcode's SvgPathImage
emits one absolute subpath per dark module), then rendered to a PNG with a
quiet zone and decoded.

Usage: python verify_qr.py [dist/setup.html]
"""

import os
import re
import sys

import cv2
import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))


def matrix_from_svg(svg_text):
    d = re.search(r'\sd="([^"]+)"', svg_text)
    if not d:
        return None
    path = d.group(1)
    rects = []
    for m in re.finditer(
            r"M\s*([\d.]+)\s*,\s*([\d.]+)\s*H\s*([\d.]+)\s*V\s*([\d.]+)\s*H", path):
        x, y, x2, y2 = (float(g) for g in m.groups())
        if x2 > x and y2 > y:
            rects.append((x, y, x2 - x, y2 - y))
    if not rects:
        for m in re.finditer(
                r"M\s*([\d.]+)\s+([\d.]+)\s+h\s*([\d.]+)\s+v\s*([\d.]+)", path):
            x, y, w, h = (float(g) for g in m.groups())
            if w > 0 and h > 0:
                rects.append((x, y, w, h))
    if not rects:
        return None
    unit = min(min(r[2], r[3]) for r in rects)
    span = max(max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects))
    n = int(round(span / unit))
    grid = [[0] * n for _ in range(n)]
    for x, y, w, h in rects:
        cx, cy = int(round(x / unit)), int(round(y / unit))
        cw, ch = int(round(w / unit)), int(round(h / unit))
        for dy in range(ch):
            for dx in range(cw):
                if 0 <= cy + dy < n and 0 <= cx + dx < n:
                    grid[cy + dy][cx + dx] = 1
    return grid


def matrix_to_png(grid, path, scale=12, quiet=4):
    n = len(grid)
    size = (n + quiet * 2) * scale
    img = np.full((size, size), 255, dtype=np.uint8)
    for y in range(n):
        for x in range(n):
            if grid[y][x]:
                y0 = (y + quiet) * scale
                x0 = (x + quiet) * scale
                img[y0:y0 + scale, x0:x0 + scale] = 0
    cv2.imwrite(path, img)
    return path


def main():
    setup = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "setup.html")
    if not os.path.isfile(setup):
        print("FAIL: %s not found" % setup)
        return 1
    html = open(setup, encoding="utf-8").read()
    svgs = re.findall(r"<svg[^>]*>.*?</svg>", html, re.S)
    if not svgs:
        print("FAIL: no inline SVG QR in %s" % setup)
        return 1

    expected = re.search(r'<p class="url" id="m3u">([^<]+)</p>', html)
    expected = expected.group(1) if expected else None
    print("expected playlist URL: %s" % expected)

    for i, svg in enumerate(svgs):
        grid = matrix_from_svg(svg)
        if not grid:
            print("  svg %d: could not rebuild the module matrix" % i)
            continue
        png = os.path.join(OUT, "_qr_check_%d.png" % i)
        matrix_to_png(grid, png)
        img = cv2.imread(png)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        print("  svg %d: %sx%s modules -> decoded %r"
              % (i, len(grid), len(grid[0]), data))
        if data and expected and data.strip() == expected.strip():
            print("PASS: the QR decodes to the playlist URL")
            return 0
        print("  MISMATCH")
    print("FAIL: no QR in the setup card decodes to the playlist URL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
