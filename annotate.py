# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""PNG に再編集可能な注釈を付けるための .drawio.png 変換ツール。

  uv run annotate.py init image.png            # -> image.drawio.png (元ピクセルそのまま + 図データ)
  (draw.io Desktop で image.drawio.png を開いて注釈を追加・保存)
  uv run annotate.py export image.drawio.png   # 元ピクセル + 注釈を合成し、元と同じサイズで上書き
  uv run annotate.py check image.drawio.png --ref image.png
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import struct
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

from PIL import Image

DRAWIO_EXE = Path(os.environ.get("DRAWIO_EXE", r"C:\Program Files\draw.io\draw.io.exe"))
PNG_SIG = b"\x89PNG\r\n\x1a\n"
DIAGRAM_KEYS = {b"mxfile", b"mxGraphModel"}
BG_CELL_ID = "background-image"
ANCHOR_ID = "__export_anchor"


def read_chunks(data: bytes) -> list[tuple[bytes, bytes, bytes]]:
    """Return (type, payload, raw_chunk_bytes) list."""
    if not data.startswith(PNG_SIG):
        raise ValueError("not a PNG file")
    chunks = []
    pos = len(PNG_SIG)
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        chunks.append((ctype, data[pos + 8 : pos + 8 + length], data[pos : pos + 12 + length]))
        pos += 12 + length
    return chunks


def is_diagram_chunk(ctype: bytes, payload: bytes) -> bool:
    return ctype in (b"tEXt", b"zTXt", b"iTXt") and payload.split(b"\0", 1)[0] in DIAGRAM_KEYS


def make_chunk(ctype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + ctype + payload + struct.pack(">I", zlib.crc32(ctype + payload))


def with_diagram(png: bytes, diagram_raw: list[bytes]) -> bytes:
    """Replace diagram chunks in png; draw.io stops reading metadata at the first IDAT."""
    out = bytearray(PNG_SIG)
    for ctype, payload, raw in read_chunks(png):
        if is_diagram_chunk(ctype, payload):
            continue
        out += raw
        if ctype == b"IHDR":
            out += b"".join(diagram_raw)
    return bytes(out)


def encode_diagram_chunk(xml: str) -> bytes:
    body = zlib.compress(urllib.parse.quote(xml, safe="").encode("ascii"))
    return make_chunk(b"zTXt", b"mxGraphModel\0\0" + body)


def diagram_chunks(data: bytes) -> list[bytes]:
    return [raw for ctype, payload, raw in read_chunks(data) if is_diagram_chunk(ctype, payload)]


def extract_xml(data: bytes) -> str:
    for ctype, payload, _ in read_chunks(data):
        if not is_diagram_chunk(ctype, payload):
            continue
        rest = payload.split(b"\0", 1)[1]
        if ctype == b"tEXt":
            text = rest.decode("latin-1")
        elif ctype == b"zTXt":
            text = zlib.decompress(rest[1:]).decode("latin-1")
        else:
            flag, body = rest[0], rest[2:].split(b"\0", 2)[2]
            text = (zlib.decompress(body) if flag else body).decode("utf-8")
        return decompress_diagrams(urllib.parse.unquote(text))
    raise ValueError("draw.io diagram data not found in PNG")


def decompress_diagrams(xml: str) -> str:
    """Expand draw.io's compressed <diagram> bodies (base64 + raw deflate + urlencode)."""
    root = ET.fromstring(xml)
    if root.tag == "mxGraphModel":
        return xml
    for diagram in root.iter("diagram"):
        body = (diagram.text or "").strip()
        if body and len(diagram) == 0:
            raw = zlib.decompress(base64.b64decode(body), -15)
            diagram.text = None
            diagram.append(ET.fromstring(urllib.parse.unquote(raw.decode("utf-8"))))
    return ET.tostring(root, encoding="unicode")


def find_background(root: ET.Element) -> tuple[ET.Element, ET.Element]:
    """Return (graph <root> element, background cell) of the first page."""
    graph_root = root.find(".//mxGraphModel/root") if root.tag != "mxGraphModel" else root.find("root")
    for cell in graph_root.iter("mxCell"):
        if cell.get("id") == BG_CELL_ID:
            return graph_root, cell
    raise ValueError("background image cell not found (was this created by init?)")


def background_png(cell: ET.Element) -> bytes:
    for part in cell.get("style", "").split(";"):
        if part.startswith("image=data:image/png,"):
            return base64.b64decode(part.split(",", 1)[1])
    raise ValueError("background image data not found")


def build_xml(png: bytes, w: int, h: int) -> str:
    b64 = base64.b64encode(png).decode("ascii")
    # draw.io style uses ';' as separator, so the data URI is written with ',' only.
    style = f"shape=image;image=data:image/png,{b64};imageAspect=0;locked=1;"
    mxfile = ET.Element("mxfile", host="annotate.py")
    diagram = ET.SubElement(mxfile, "diagram", id="page-1", name="Page-1")
    model = ET.SubElement(diagram, "mxGraphModel", grid="0", page="0", pageWidth=str(w), pageHeight=str(h))
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    cell = ET.SubElement(root, "mxCell", id=BG_CELL_ID, value="", style=style, vertex="1", parent="1")
    ET.SubElement(cell, "mxGeometry", x="0", y="0", width=str(w), height=str(h), **{"as": "geometry"})
    return ET.tostring(mxfile, encoding="unicode")


def drawio_export(src: Path, dst: Path) -> None:
    if not DRAWIO_EXE.exists():
        sys.exit(f"draw.io not found: {DRAWIO_EXE} (set DRAWIO_EXE)")
    cmd = [str(DRAWIO_EXE), "--force-device-scale-factor=1", "-x", "-f", "png", "-t", "-b", "0", "-s", "1",
           "-o", str(dst.resolve()), str(src.resolve())]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not dst.exists():
        sys.exit(f"draw.io export failed ({res.returncode}): {res.stderr or res.stdout}")


def content_bbox(graph_root: ET.Element) -> tuple[float, float, float, float]:
    """Rough absolute bbox of all cells (labels/strokes may exceed it; caller adds margin)."""
    cells = {c.get("id"): c for c in graph_root.iter("mxCell")}

    def origin(cid: str | None) -> tuple[float, float]:
        x = y = 0.0
        while cid in cells:
            geo = cells[cid].find("mxGeometry")
            if cells[cid].get("vertex") == "1" and geo is not None:
                x += float(geo.get("x", 0))
                y += float(geo.get("y", 0))
            cid = cells[cid].get("parent")
        return x, y

    xs, ys = [], []
    for cell in cells.values():
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        ox, oy = origin(cell.get("parent"))
        if cell.get("vertex") == "1":
            x, y = ox + float(geo.get("x", 0)), oy + float(geo.get("y", 0))
            xs += [x, x + float(geo.get("width", 0))]
            ys += [y, y + float(geo.get("height", 0))]
        for pt in geo.iter("mxPoint"):
            xs.append(ox + float(pt.get("x", 0)))
            ys.append(oy + float(pt.get("y", 0)))
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)


def shift_top_level(graph_root: ET.Element, d: float = 0.5) -> None:
    """draw.io samples pixel j at [j-0.5, j+0.5]; shifting by +0.5 aligns cells to the pixel grid."""
    cells = {c.get("id"): c for c in graph_root.iter("mxCell")}
    for cell in cells.values():
        parent = cells.get(cell.get("parent"))
        if parent is None or parent.get("vertex") == "1" or parent.get("edge") == "1":
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        if cell.get("vertex") == "1":
            geo.set("x", str(float(geo.get("x", 0)) + d))
            geo.set("y", str(float(geo.get("y", 0)) + d))
        for pt in geo.iter("mxPoint"):
            if pt.get("as") != "offset":
                pt.set("x", str(float(pt.get("x", 0)) + d))
                pt.set("y", str(float(pt.get("y", 0)) + d))


def render_annotations(xml: str, size: tuple[int, int]) -> Image.Image | None:
    """Render everything except the background image as a transparent WxH layer."""
    w, h = size
    mxfile = ET.fromstring(xml)
    graph_root, bg = find_background(mxfile)
    parent = bg.get("parent")
    graph_root.remove(bg)
    if not any(c.get("vertex") == "1" or c.get("edge") == "1" for c in graph_root.iter("mxCell")):
        return None

    x0, y0, x1, y1 = content_bbox(graph_root)
    shift_top_level(graph_root)
    margin = 50
    with tempfile.TemporaryDirectory() as td:
        for _ in range(4):
            ax = int(min(0, x0)) - margin
            ay = int(min(0, y0)) - margin
            aw = int(max(w, x1)) + margin - ax
            ah = int(max(h, y1)) + margin - ay
            # An invisible anchor fixes the export bounds so the crop offset is known.
            anchor = ET.SubElement(graph_root, "mxCell", id=ANCHOR_ID, value="",
                                   style="fillColor=none;strokeColor=none;", vertex="1", parent=parent)
            ET.SubElement(anchor, "mxGeometry", x=str(ax), y=str(ay),
                          width=str(aw), height=str(ah), **{"as": "geometry"})
            src = Path(td) / "annotations.drawio"
            src.write_text(ET.tostring(mxfile, encoding="unicode"), encoding="utf-8")
            out = Path(td) / "annotations.png"
            drawio_export(src, out)
            graph_root.remove(anchor)
            with Image.open(out) as im:
                if im.size == (aw + 2, ah + 2):
                    left, top = 1 - ax, 1 - ay
                    return im.convert("RGBA").crop((left, top, left + w, top + h))
            margin *= 2
    sys.exit("could not fix export bounds (annotations far outside the image?)")


def cmd_init(args: argparse.Namespace) -> None:
    src = Path(args.image)
    dst = Path(args.output) if args.output else src.with_name(src.stem + ".drawio.png")
    if dst.exists() and not args.force:
        sys.exit(f"{dst} already exists (use --force)")
    png = src.read_bytes()
    with Image.open(io.BytesIO(png)) as im:
        w, h = im.size
    dst.write_bytes(with_diagram(png, [encode_diagram_chunk(build_xml(png, w, h))]))
    print(f"created {dst} ({w}x{h})")


def cmd_export(args: argparse.Namespace) -> None:
    src = Path(args.drawio_png)
    dst = Path(args.output) if args.output else src
    data = src.read_bytes()
    xml = extract_xml(data)
    base_png = background_png(find_background(ET.fromstring(xml))[1])
    base = Image.open(io.BytesIO(base_png))
    layer = render_annotations(xml, base.size)
    if layer is None:
        out_png = base_png
    else:
        has_alpha = base.mode in ("RGBA", "LA", "PA") or "transparency" in base.info
        merged = Image.alpha_composite(base.convert("RGBA"), layer)
        if not has_alpha:
            merged = merged.convert("RGB")
        buf = io.BytesIO()
        merged.save(buf, format="PNG", dpi=base.info.get("dpi", (96, 96)))
        out_png = buf.getvalue()
    dst.write_bytes(with_diagram(out_png, diagram_chunks(data)))
    print(f"exported {dst} ({base.width}x{base.height})")


def cmd_check(args: argparse.Namespace) -> None:
    data = Path(args.drawio_png).read_bytes()
    ok = True
    if not diagram_chunks(data):
        print("NG: no embedded diagram")
        ok = False
    with Image.open(io.BytesIO(data)) as im:
        size = im.size
    if args.ref:
        with Image.open(args.ref) as ref:
            expected = ref.size
    else:
        expected = Image.open(io.BytesIO(background_png(find_background(ET.fromstring(extract_xml(data)))[1]))).size
    if size != expected:
        print(f"NG: size {size} != {expected}")
        ok = False
    print("OK" if ok else "FAILED", f"{size[0]}x{size[1]}")
    sys.exit(0 if ok else 1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("init", help="PNG -> .drawio.png")
    s.add_argument("image")
    s.add_argument("-o", "--output")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("export", help="flatten annotations onto the original pixels")
    s.add_argument("drawio_png")
    s.add_argument("-o", "--output", help="default: overwrite input")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("check", help="verify size and embedded diagram")
    s.add_argument("drawio_png")
    s.add_argument("--ref", help="original PNG to compare size with")
    s.set_defaults(func=cmd_check)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
