"""Create the original synthetic Phase 0 PDF corpus, without network access.

Usage: <isolated-evaluator-python> eval/build_corpus.py --output corpus
The PDF skill's artifact-operation marker must be run by the caller first.
This program never reads or modifies project sources or supplied PDFs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import sys
import textwrap

import pikepdf
from PIL import Image, ImageDraw, ImageFont
import reportlab
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


SEED = 461203
random.seed(SEED)
FIXED_DATE = "2026-10-15T12:00:00Z"
PAGE = (612, 792)
FONT = "SyntheticVera"
FONT_BOLD = "SyntheticVeraBold"
INK = colors.HexColor("#172b3d")
BLUE = colors.HexColor("#235c85")
LIGHT = colors.HexColor("#edf3f6")
PROVENANCE = {
    "kind": "original-synthetic",
    "author": "PDF Remediator Phase 0 evaluation",
    "content_notice": "Fictional educational test material; no real research or private book content.",
    "redistribution": "Original fixture text and drawings may be shared with the evaluation corpus. Embedded Bitstream Vera fonts retain their bundled license; see assets/LICENSE.txt.",
    "seed": SEED,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register_fonts(out: Path) -> dict:
    font_dir = Path(reportlab.__file__).parent / "fonts"
    regular, bold = font_dir / "Vera.ttf", font_dir / "VeraBd.ttf"
    if not regular.is_file() or not bold.is_file():
        raise RuntimeError("Bundled reportlab Bitstream Vera fonts are required; no system font substitution is permitted.")
    pdfmetrics.registerFont(TTFont(FONT, str(regular)))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold)))
    assets = out / "assets"
    assets.mkdir(exist_ok=True)
    license_path = font_dir / "bitstream-vera-license.txt"
    if not license_path.is_file():
        license_path = font_dir / "Vera-License.txt"
    if not license_path.is_file():
        # Common reportlab distributions call the bundled license simply LICENSE.txt.
        candidates = sorted(font_dir.glob("*icense*")) + sorted(font_dir.glob("*ICENSE*"))
        license_path = candidates[0] if candidates else None
    if license_path is not None:
        (assets / "LICENSE.txt").write_bytes(license_path.read_bytes())
    else:
        raise RuntimeError("Unable to find the embedded Bitstream Vera license; inspect reportlab/fonts before redistribution.")
    return {"regular_sha256": sha256(regular), "bold_sha256": sha256(bold), "source": "reportlab/fonts", "license_sha256": sha256(assets / "LICENSE.txt")}


def new_canvas(path: Path, title: str, size=PAGE, embedded=True):
    c = canvas.Canvas(str(path), pagesize=size, pageCompression=1, invariant=1,
                      initialFontName=FONT if embedded else "Helvetica")
    c.setTitle(title)
    c.setAuthor("PDF Remediator synthetic evaluation corpus")
    c.setSubject("Original synthetic accessibility and preservation test fixture")
    c.setCreator("build_corpus.py / reportlab; deterministic seed 461203")
    return c


def title(c, text, y=735, size=20, embedded=True):
    c.setFillColor(INK)
    c.setFont(FONT_BOLD if embedded else "Helvetica-Bold", size)
    c.drawString(48, y, text)
    return y - size - 15


def para(c, text, x=48, y=680, width=516, size=11, leading=16, font=FONT):
    c.setFillColor(INK)
    c.setFont(font, size)
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if pdfmetrics.stringWidth(candidate, font, size) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y - 7


def footer(c, page, width=612):
    c.setFillColor(BLUE)
    c.setFont(FONT, 8)
    c.drawString(48, 28, "SYNTHETIC TEST MATERIAL")
    c.drawRightString(width - 48, 28, str(page))


def image_asset() -> Image.Image:
    im = Image.new("RGB", (420, 210), "#f7fafb")
    d = ImageDraw.Draw(im)
    d.ellipse((35, 35, 175, 175), fill="#d78025", outline="#7b3e09", width=4)
    d.rectangle((240, 35, 380, 175), fill="#2b7598", outline="#173d52", width=4)
    return im


def table(c, rows, x=48, y=640, widths=(210, 150, 150), row_height=27, header=True):
    for ri, row in enumerate(rows):
        if ri == 0 and header:
            c.setFillColor(LIGHT)
            c.rect(x, y-row_height, sum(widths), row_height, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#8ba1af"))
        c.setLineWidth(0.5)
        c.line(x, y, x+sum(widths), y)
        at = x
        for ci, value in enumerate(row):
            c.setFillColor(INK)
            c.setFont(FONT_BOLD if ri == 0 and header else FONT, 9)
            c.drawString(at+6, y-row_height+10, str(value))
            c.line(at, y, at, y-row_height)
            at += widths[ci]
        c.line(at, y, at, y-row_height)
        y -= row_height
    c.line(x, y, x+sum(widths), y)
    return y-18


def complex_table(c, x=48, y=600):
    """Draw actual two-level grouped headers and merged row-category cells."""
    widths=(110,130,135,135)
    h=30
    edges=[x]
    for width in widths:
        edges.append(edges[-1]+width)
    c.setFillColor(LIGHT)
    c.rect(x,y-2*h,sum(widths),2*h,stroke=0,fill=1)
    c.setStrokeColor(colors.HexColor("#8ba1af"));c.setLineWidth(.6)
    # Season and location span the two header rows; Water groups low/high.
    c.rect(x,y-6*h,sum(widths),6*h,stroke=1,fill=0)
    for edge in edges[1:3]:c.line(edge,y,edge,y-6*h)
    c.line(edges[3],y-h,edges[3],y-6*h)
    c.line(edges[2],y-h,edges[4],y-h)
    c.line(x,y-2*h,edges[4],y-2*h)
    c.line(edges[1],y-3*h,edges[4],y-3*h)
    c.line(x,y-4*h,edges[4],y-4*h)
    c.line(edges[1],y-5*h,edges[4],y-5*h)
    c.setFillColor(INK);c.setFont(FONT_BOLD,10)
    c.drawString(x+7,y-36,"Season")
    c.drawString(edges[1]+7,y-36,"Location")
    c.drawCentredString((edges[2]+edges[4])/2,y-20,"Water observations")
    c.drawString(edges[2]+7,y-50,"Low")
    c.drawString(edges[3]+7,y-50,"High")
    c.setFont(FONT,10)
    c.drawString(x+7,y-96,"Spring")
    c.drawString(x+7,y-156,"Autumn")
    for ri,(location,low,high) in enumerate((("North",4,9),("South",7,10),("North",6,8),("South",5,11))):
        yy=y-(ri+3)*h+11
        for ci,value in enumerate((location,low,high),start=1):c.drawString(edges[ci]+7,yy,str(value))


def pdf_features(path: Path) -> dict:
    with pikepdf.open(path) as pdf:
        outlines = pdf.Root.get("/Outlines")
        return {
            "page_count": len(pdf.pages),
            "page_dimensions_pt": [[float(v) for v in p.MediaBox] for p in pdf.pages],
            "bookmarks": int(outlines.get("/Count", 0)) if outlines else 0,
            "page_labels": str(pdf.Root.get("/PageLabels", "")),
            "has_acroform": "/AcroForm" in pdf.Root,
            "has_structure_root": "/StructTreeRoot" in pdf.Root,
        }


def add_labels(path: Path, book=False):
    temp = path.with_suffix(".labels.pdf")
    with pikepdf.open(path) as pdf:
        nums = [0, pikepdf.Dictionary(S=pikepdf.Name.r, St=1)] if book else [0, pikepdf.Dictionary(S=pikepdf.Name.D, St=1)]
        if book:
            nums += [2, pikepdf.Dictionary(S=pikepdf.Name.D, St=1)]
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array(nums))
        pdf.save(temp, deterministic_id=True)
    os.replace(temp, path)


def simple(path: Path, embedded=True):
    c = new_canvas(path, "Simple synthetic reading: embedded fonts" if embedded else "Simple synthetic reading: standard fonts", embedded=embedded)
    title(c, "A short synthetic reading", embedded=embedded)
    para(c, "SIMPLE-ANCHOR-ALPHA. A librarian places three blue cards beside a reading lamp. Each card records a different observation about a fictional garden.", y=670, font=FONT if embedded else "Helvetica")
    para(c, "SIMPLE-ANCHOR-OMEGA. The final observation remains visible and selectable. This original text exists only to test document preservation.", y=590, font=FONT if embedded else "Helvetica")
    if embedded:
        footer(c, 1)
    c.showPage()
    c.save()


def structured(path: Path, asset):
    c = new_canvas(path, "Synthetic structured chapter with tables, lists, and figures")
    title(c, "Chapter 1. Observing the garden")
    para(c, "STRUCTURED-CHAPTER-START. These fictional observations exercise headings, nested lists, a link, and a simple table.", y=680)
    title(c, "1.1 Materials", y=605, size=14)
    for text, x, y in [("1. Prepare a notebook.", 55, 570), ("a. Label the first page.", 77, 546), ("b. Record the date.", 77, 522), ("2. Compare the observations.", 55, 498)]:
        para(c, text, x=x, y=y)
    title(c, "Table 1. Observation counts", y=445, size=13)
    table(c, [("Location", "Morning", "Afternoon"), ("North plot", "12", "18"), ("South plot", "8", "11")], y=420)
    para(c, "Link: W3C accessibility overview", y=275)
    c.linkURL("https://www.w3.org/WAI/", (48, 270, 300, 290), relative=0, thickness=0)
    footer(c, 1); c.showPage()
    title(c, "1.2 Two parallel observations")
    for col, x in enumerate((48, 318)):
        y=680
        for i in range(5):
            y = para(c, f"COLUMN-{col+1}-ITEM-{i+1}. The fictional observer compares shade, water, and leaf color in a carefully recorded sequence. Reading should finish this column before the next.", x=x, y=y, width=245, size=10, leading=14)
    c.line(48, 145, 230, 145)
    para(c, "NOTE-1. The garden and measurements are invented.", y=126, size=8, leading=11)
    footer(c, 2); c.showPage()
    title(c, "1.3 Two uses of one drawing")
    c.drawImage(asset, 90, 460, width=420, height=210)
    para(c, "FIGURE-CONTEXT-A. Figure 1. Orange circle and blue square represent two garden plots.", y=435)
    c.drawImage(asset, 195, 200, width=210, height=105)
    para(c, "FIGURE-CONTEXT-B. Figure 2. The same drawing now represents two archive bins. Its description must follow this different context.", y=175)
    footer(c, 3); c.showPage()
    title(c, "1.4 Complex table for manual review")
    para(c, "COMPLEX-TABLE-ANCHOR. This grouped table requires explicit relationships between the two-level headings and data cells.", y=680)
    complex_table(c)
    para(c, "STRUCTURED-CHAPTER-END. Header associations, list semantics, figure meaning, link structure, and reading order require review.", y=390)
    footer(c, 4); c.showPage(); c.save()
    add_labels(path)


def book(path: Path, asset):
    c = new_canvas(path, "Methods for Careful Reading: a 200-page synthetic book")
    chapter_names = ["Observation", "Questions", "Records", "Grouping", "Comparison", "Sequence", "Evidence", "Context", "Description", "Relationships", "Revision", "Navigation", "Review", "Reflection"]
    two_column_pages = {30, 31, 90, 91, 150, 151}
    note_pages = {10, 44, 88, 132, 176}
    figure_pages = {40, 110}
    for page in range(1, 201):
        if page == 1:
            title(c, "Methods for Careful Reading", y=625, size=25)
            para(c, "An original synthetic book for PDF accessibility evaluation", y=565, size=14)
            para(c, "BOOK-PAGE-001. All people, settings, observations, and data in this fixture are fictional. This is test material, not a textbook or research source.", y=470)
            c.bookmarkPage("cover"); c.addOutlineEntry("Synthetic book title", "cover", level=0)
        elif page == 2:
            title(c, "Contents")
            c.bookmarkPage("contents"); c.addOutlineEntry("Contents", "contents", level=0)
            para(c, "BOOK-PAGE-002. Logical page numbers begin with page 1 after these two front-matter pages.", y=690)
            y=625
            for ch, name in enumerate(chapter_names):
                c.setFont(FONT, 11)
                c.drawString(55, y, f"Chapter {ch+1}. {name}")
                c.drawRightString(550, y, str(1+ch*14))
                c.linkRect("", f"chapter-{ch+1}", (50, y-4, 557, y+14), relative=0, thickness=0)
                y-=29
            c.drawString(55, y-10, "Index"); c.drawRightString(550, y-10, "197")
        elif page >= 199:
            title(c, "Index" if page == 199 else "Index, continued")
            if page == 199:
                c.bookmarkPage("index"); c.addOutlineEntry("Index", "index", level=0)
            para(c, f"BOOK-PAGE-{page:03d}. Synthetic subject index.", y=690)
            terms = chapter_names[:7] if page == 199 else chapter_names[7:]
            for k, term in enumerate(terms):
                para(c, f"{term}, {1+(k+(0 if page==199 else 7))*14}, {5+(k+(0 if page==199 else 7))*14}", y=630-k*48)
            if page == 200:
                para(c, "BOOK-FINAL-ANCHOR. The last visible sentence of the synthetic book must survive every processing stage.", y=150)
        else:
            ch = (page-3)//14
            opening = (page-3)%14 == 0
            c.setFillColor(BLUE); c.setFont(FONT, 8)
            header = "Methods for Careful Reading" if page%2==0 else f"Synthetic Book / Chapter {ch+1}"
            c.drawString(48, 761, header)
            c.setStrokeColor(colors.HexColor("#a7bbc7")); c.line(48, 751, 564, 751)
            if opening:
                title(c, f"Chapter {ch+1}. {chapter_names[ch]}", y=704, size=21)
                c.bookmarkPage(f"chapter-{ch+1}"); c.addOutlineEntry(f"Chapter {ch+1}. {chapter_names[ch]}", f"chapter-{ch+1}", level=0)
            else:
                title(c, f"{ch+1}.{(page-3)%14+1} A closer observation", y=714, size=15)
            para(c, f"BOOK-PAGE-{page:03d}. Chapter {ch+1}, {chapter_names[ch].lower()}. Every page carries a unique content anchor.", y=665, size=10, leading=14)
            if page in {20,21}:
                para(c, "CROSSPAGE-TABLE-01. Table 2. Fictional archive counts" + (" (continued)." if page==21 else " (continues on next page)."), y=603)
                start = 1 if page==20 else 13
                table(c, [("Archive shelf", "Cards", "Boxes")] + [(f"Shelf {i:02d}", i*3, i+2) for i in range(start, start+12)], y=555, row_height=27)
                para(c, f"CROSSPAGE-ROWS-{start:02d}-{start+11:02d}. These rows belong to one conceptual table.", y=175)
            elif page in figure_pages:
                c.drawImage(asset, 90, 350, width=420, height=210)
                context = "plot comparison" if page==40 else "archive classification"
                para(c, f"BOOK-FIGURE-{page}. Figure {1 if page==40 else 2}. An orange circle and blue square illustrate {context}. The shared image bytes do not determine the description.", y=320)
                para(c, "Repeated content can be meaningful. The phrase Careful reading needs context is body content here and must remain in the reading sequence.", y=225)
            elif page in two_column_pages:
                for col, x in enumerate((48, 318)):
                    y=602
                    for part in range(5):
                        y=para(c, f"BOOK-COLUMN-{page}-{col+1}-{part+1}. An observer compares a sequence of fictional records. Each detail has a place in this column and remains part of the chapter's argument.", x=x, y=y, width=245, size=9, leading=13)
            else:
                y=600
                for part in range(7):
                    word = random.choice(("record", "comparison", "context", "sequence", "description", "question"))
                    y=para(c, f"PASSAGE-{page:03d}-{part+1}. This synthetic {word} links a small observation to the chapter's purpose. A reader checks the surrounding sentence, compares the earlier account, and records a clear reason for the conclusion. The invented example protects private material while exposing lost or reordered content.", y=y, size=10, leading=14)
                if page in note_pages:
                    para(c, f"NOTE-REFERENCE-{page}. The qualification in note 1 below applies to this page's invented account.", y=142, size=8, leading=10)
                    c.line(48, 110, 240, 110)
                    para(c, f"BOOK-NOTE-{page}. This footnote qualifies the fictional observation and belongs after its reference.", y=93, size=8, leading=10)
            # Repeated asset in a Form XObject tests occurrence-sensitive artifact decisions.
            if page == 3:
                c.beginForm("running-mark", 0, 0, 12, 12)
                c.setFillColor(BLUE); c.circle(6, 6, 5, stroke=0, fill=1)
                c.endForm()
            c.saveState(); c.translate(550, 755); c.doForm("running-mark"); c.restoreState()
        footer(c, page-2 if page>2 else ("i" if page==1 else "ii"))
        c.showPage()
    c.save(); add_labels(path, book=True)


def scan_image() -> Image.Image:
    # Pixel-only text uses the same licensed font, with no hidden PDF text layer.
    font_path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    im = Image.new("RGB", (1400, 1200), "white")
    d = ImageDraw.Draw(im)
    f1, f2 = ImageFont.truetype(str(font_path), 48), ImageFont.truetype(str(font_path), 32)
    d.text((80, 90), "A synthetic scanned reading", fill="#172b3d", font=f1)
    lines = ["SCAN-ANCHOR-ALPHA.", "The orange notebook contains seven observations.", "A careful reader preserves every visible line.", "These words exist only as image pixels in this PDF.", "SCAN-ANCHOR-OMEGA."]
    for i, line in enumerate(lines):
        d.text((80, 220+i*135), line, fill="#172b3d", font=f2)
    return im


def scans(path: Path, mixed=False):
    c=new_canvas(path, "Synthetic mixed same-page scan and digital text" if mixed else "Synthetic image-only scanned page")
    scan=ImageReader(scan_image())
    if mixed:
        title(c, "Mixed digital and scanned content")
        para(c, "MIXED-DIGITAL-ANCHOR. This selectable introduction sits on the same page as scanned text. Page-level skip-text OCR must not imply the image text was recognized.", y=685)
        c.drawImage(scan, 48, 120, width=516, height=442.3)
    else:
        c.drawImage(scan, 0, 130, width=612, height=524.57)
    c.showPage(); c.save()


CONTROL_TEXT = [
    ("H1", "A tagged synthetic control", 720, 19),
    ("P", "CONTROL-ANCHOR-ALPHA. Every visible line has a structure link.", 650, 11),
    ("P", "CONTROL-ANCHOR-OMEGA. This final sentence detects content loss.", 610, 11),
]


def tag_control(path: Path, lost=False):
    c=new_canvas(path, "Tagged structural positive control")
    included=CONTROL_TEXT[:-1] if lost else CONTROL_TEXT
    for mcid, (role, text, y, size) in enumerate(included):
        c._code.append(f"/{role} <</MCID {mcid}>> BDC")
        c.setFillColor(INK); c.setFont(FONT_BOLD if role=="H1" else FONT, size)
        c.drawString(48, y, text)
        c._code.append("EMC")
    c.showPage(); c.save()
    temp=path.with_suffix(".tagged.pdf")
    with pikepdf.open(path) as pdf:
        page=pdf.pages[0]
        root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        doc=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
        elems=[]
        for mcid,(role,_,_,_) in enumerate(included):
            elems.append(pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name('/'+role), P=doc, Pg=page.obj, K=mcid)))
        doc.K=pikepdf.Array(elems)
        root.K=doc
        root.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Array(elems)])))
        root.ParentTreeNextKey=len(elems)
        page.StructParents=0
        page.Tabs=pikepdf.Name.S
        pdf.Root.StructTreeRoot=root
        pdf.Root.MarkInfo=pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang=pikepdf.String("en-US")
        pdf.Root.ViewerPreferences=pikepdf.Dictionary(DisplayDocTitle=True)
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            meta["dc:title"]="Tagged structural positive control"
            meta["dc:creator"]=["PDF Remediator synthetic evaluation corpus"]
            meta["dc:description"]="Original synthetic structural evaluator control; human semantic assessment remains required."
            meta["pdfuaid:part"]="1"
            meta["xmp:CreateDate"]=FIXED_DATE
            meta["xmp:ModifyDate"]=FIXED_DATE
            meta["xmp:MetadataDate"]=FIXED_DATE
        pdf.save(temp, deterministic_id=True)
    os.replace(temp,path)



def tagged_figure_control(path: Path):
    """Bounded source-only occurrence control, not a reproduced ODL result.

    Reuses the original structured chapter's drawing and two caption meanings.
    Two distinct Figure elements deliberately have no Alt; every visible text
    and image operation is linked. No engine, model, or historical PDF is read.
    Lists, links, and tables from the larger chapter are outside this control.
    """
    c = new_canvas(path, "Synthetic chapter figure occurrence control")
    asset = ImageReader(image_asset())
    roles = ["H1", "Figure", "Caption", "Figure", "Caption"]
    c._code.append("/H1 <</MCID 0>> BDC")
    title(c, "Two uses of one drawing")
    c._code.append("EMC")
    for image_mcid, caption_mcid, x, y, width, height, caption in (
        (1, 2, 90, 460, 420, 210,
         "FIGURE-CONTEXT-A. Figure 1. Orange circle and blue square represent two garden plots."),
        (3, 4, 195, 200, 210, 105,
         "FIGURE-CONTEXT-B. Figure 2. The same drawing now represents two archive bins."),
    ):
        c._code.append(f"/Figure <</MCID {image_mcid}>> BDC")
        c.drawImage(asset, x, y, width=width, height=height)
        c._code.append("EMC")
        c._code.append(f"/Caption <</MCID {caption_mcid}>> BDC")
        para(c, caption, y=y-25)
        c._code.append("EMC")
    c.showPage()
    c.save()
    temporary = path.with_suffix(".tagged.pdf")
    with pikepdf.open(path) as pdf:
        page = pdf.pages[0]
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
        elements = [pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name('/'+role),
            P=document, Pg=page.obj, K=mcid)) for mcid, role in enumerate(roles)]
        document.K = pikepdf.Array(elements)
        root.K = document
        root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(
            Nums=pikepdf.Array([0, pikepdf.Array(elements)])))
        root.ParentTreeNextKey = 1
        page.StructParents = 0
        page.Tabs = pikepdf.Name.S
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang = "en-US"
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.save(temporary, deterministic_id=True)
    os.replace(temporary, path)


def tag_variants(control: Path, phantom: Path, incomplete: Path):
    with pikepdf.open(control) as pdf:
        # Keep visible text but remove all content marking. Tree existence is insufficient.
        data=pdf.pages[0].Contents.read_bytes()
        data=re.sub(rb"/(?:H1|P)\s*<<\s*/MCID\s+\d+\s*>>\s*BDC", b"", data)
        data=data.replace(b"EMC",b"")
        pdf.pages[0].Contents=pdf.make_stream(data)
        pdf.save(phantom, deterministic_id=True)
    with pikepdf.open(control) as pdf:
        # Two valid MCIDs remain, but the final visible paragraph is unmarked.
        data=pdf.pages[0].Contents.read_bytes()
        data=re.sub(rb"/P\s*<<\s*/MCID\s+2\s*>>\s*BDC(.*?)EMC", rb"\1", data, flags=re.S)
        pdf.pages[0].Contents=pdf.make_stream(data)
        doc=pdf.Root.StructTreeRoot.K
        doc.K=pikepdf.Array(list(doc.K)[:2])
        pdf.Root.StructTreeRoot.ParentTree.Nums[1]=pikepdf.Array(list(doc.K))
        pdf.save(incomplete, deterministic_id=True)


def mis_mapping(source: Path, path: Path):
    changed=0
    with pikepdf.open(source) as pdf:
        for font in pdf.pages[0].Resources.Font.values():
            if "/ToUnicode" not in font:
                continue
            cmap=font.ToUnicode.read_bytes()
            new=re.sub(rb"(<43>\s*)<0043>", rb"\g<1><005A>", cmap)
            if new != cmap:
                font.ToUnicode=pdf.make_stream(new)
                changed+=1
        if not changed:
            raise RuntimeError("Expected a Vera ToUnicode C mapping for deliberately corrupted font control")
        pdf.save(path,deterministic_id=True)


def detection_fixtures(out: Path):
    c=new_canvas(out/"forms-detect-only.pdf", "Synthetic interactive form: detection-only")
    title(c,"Synthetic interactive form")
    para(c,"FORM-DETECT-ANCHOR. This fixture requires form preservation and accessibility work beyond the first supported workflow.",y=680)
    c.setFont(FONT,11);c.drawString(48,590,"Reader name:")
    c.acroForm.textfield(name="reader_name",tooltip="Reader name",x=160,y=576,width=280,height=25,borderStyle="inset",forceBorder=True,fontName="Helvetica",fontSize=11,value="Synthetic Reader")
    c.showPage();c.save()
    c=new_canvas(out/"slides-detect-only.pdf","Synthetic slide deck: detection-only",size=(960,540))
    for i in range(1,4):
        title(c,f"Synthetic slide {i}",y=455,size=30)
        para(c,f"SLIDE-ANCHOR-{i}. A fictional presentation with short statements, large type, and a wide page shape.",y=360,width=820,size=20,leading=30)
        footer(c,i,width=960);c.showPage()
    c.save()
    c=new_canvas(out/"equation-detect-only.pdf","Synthetic equation: detection-only")
    title(c,"A synthetic mathematical relationship")
    para(c,"EQUATION-DETECT-ANCHOR. The following expression needs meaningful mathematical semantics, not merely separated glyphs.",y=680)
    c.setFont(FONT,30);c.drawString(200,550,"E = mc")
    c.setFont(FONT,17);c.drawString(313,568,"2")
    para(c,"The energy label equals the mass label times a squared speed label. All symbols are test material.",y=460)
    c.showPage();c.save()
    c=new_canvas(out/"intentional-blank.pdf","Synthetic reading followed by an intentional blank page")
    title(c,"An intentional blank follows")
    para(c,"BLANK-CONTROL-ANCHOR. Page two is deliberately empty. A blank page is not automatically an untagged-content failure.",y=680)
    c.showPage();c.showPage();c.save()


def fixture(fid, filename, pages, anchors, features, blockers, expected_status="needs-manual", **extra):
    return {
        "id":fid,"path":filename,"expected_page_count":pages,
        "provenance":dict(PROVENANCE),
        "expected":{
            "text_anchors":anchors,"features":features,"blockers":blockers,
            "raw_product_status":expected_status,
            "human_review":"pending; synthetic ground truth supplies intent, not certification",
            "preservation":{"page_count":"exact","page_dimensions_pt":"exact","visible_content":"all pages compared with the pinned renderer","normalized_text":"no lost visible digital text; scan text requires OCR-specific comparison","bookmarks":"preserve when present","page_labels":"preserve when present","annotations":"preserve when present"},
            **extra,
        },
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=Path("corpus"))
    args=ap.parse_args()
    out=args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty corpus directory: {out}")
    out.mkdir(parents=True,exist_ok=True)
    fonts=register_fonts(out)
    asset_im=image_asset()
    asset_im.save(out/"assets"/"repeated-shapes.png",compress_level=9)
    asset=ImageReader(asset_im)
    simple(out/"simple-embedded.pdf")
    simple(out/"simple-standard-unembedded.pdf",embedded=False)
    structured(out/"structured-chapter.pdf",asset)
    book(out/"synthetic-book-200.pdf",asset)
    scans(out/"scan-only.pdf")
    scans(out/"mixed-same-page.pdf",mixed=True)
    tag_control(out/"tagged-control.pdf")
    tag_control(out/"deliberate-content-loss.pdf",lost=True)
    tag_variants(out/"tagged-control.pdf",out/"phantom-tree.pdf",out/"incomplete-tags.pdf")
    mis_mapping(out/"tagged-control.pdf",out/"mis-mapped-font.pdf")
    detection_fixtures(out)
    anchors=[t[1].split(".")[0]+"." for t in CONTROL_TEXT[1:]]
    fixtures=[
        fixture("simple_embedded","simple-embedded.pdf",1,["SIMPLE-ANCHOR-ALPHA.","SIMPLE-ANCHOR-OMEGA."],["born-digital","embedded TrueType","untagged"],["untagged content"]),
        fixture("simple_unembedded","simple-standard-unembedded.pdf",1,["SIMPLE-ANCHOR-ALPHA.","SIMPLE-ANCHOR-OMEGA."],["born-digital","standard unembedded fonts","untagged"],["font embedding","untagged content"]),
        fixture("structured_chapter","structured-chapter.pdf",4,["STRUCTURED-CHAPTER-START.","COLUMN-1-ITEM-1.","COLUMN-2-ITEM-5.","NOTE-1.","FIGURE-CONTEXT-A.","FIGURE-CONTEXT-B.","COMPLEX-TABLE-ANCHOR.","STRUCTURED-CHAPTER-END."],["headings","nested list","simple table","complex table","two columns","footnote","captioned figures","repeated asset with different contexts","URI annotation","page labels"],["untagged content","table associations require review","figure meaning requires review","reading order requires review"],relationships={"nested_list":"two child items a/b belong under item 1","columns":"read left column completely, then right","figure_1_context":"garden plots","figure_2_context":"archive bins","complex_table":"Water observations spans Low/High columns; Season and Location span two header rows; Spring/Autumn each span two data rows."}),
        fixture("book_200","synthetic-book-200.pdf",200,[f"BOOK-PAGE-{i:03d}." for i in range(1,201)]+["BOOK-FINAL-ANCHOR."],["14 chapters","alternating running headers","footer page numbers","chapter opening pages","shared Form XObject","two columns","cross-page table","footnotes","captioned figures","shared image different contexts","contents","index","bookmarks","logical roman and decimal page labels"],["untagged content","running furniture artifact decisions","cross-page table","semantic review"],relationships={"chapter_openings":[3+i*14 for i in range(14)],"cross_page_table":{"id":"CROSSPAGE-TABLE-01","physical_pages":[20,21],"row_ranges":[[1,12],[13,24]],"repeated_header":"Archive shelf / Cards / Boxes"},"two_column_pages":[30,31,90,91,150,151],"notes_pages":[10,44,88,132,176],"figure_occurrences":[{"page":40,"context":"plot comparison"},{"page":110,"context":"archive classification"}],"running_headers":"physical pages 3-198, alternate by physical-page parity; artifact candidate only","meaningful_repeated_phrase":"Careful reading needs context is real body content on figure pages","logical_labels":"i, ii, then 1 through 198"}),
        fixture("scan_only","scan-only.pdf",1,[],["image-only scan","raster text"],["OCR required","OCR recognition review","untagged content"],ocr_visible_anchors=["SCAN-ANCHOR-ALPHA.","SCAN-ANCHOR-OMEGA."],classification={"1":"scan"}),
        fixture("mixed_same_page","mixed-same-page.pdf",1,["MIXED-DIGITAL-ANCHOR."],["digital and scanned text on the same page"],["mixed-page OCR route required","OCR recognition review","untagged content"],ocr_visible_anchors=["SCAN-ANCHOR-ALPHA.","SCAN-ANCHOR-OMEGA."],classification={"1":"mixed-digital-and-scan"}),
        fixture("tagged_control","tagged-control.pdf",1,anchors,["embedded TrueType","three MCIDs","H1 then P then P","StructTreeRoot","ParentTree","title","language","PDFUA declaration"],[],expected_status="control-only",structure={"scope":"positive structural control; strict PDF/UA result must be established independently","semantic_roles":["Document","H1","P","P"],"content_mcid_count":3,"parent_tree_keys":[0],"fully_linked":True},limitations=["A supplied PDF/UA declaration is not proof of validation.","The fixture is known-good for specified structural ground truth; validator and human results remain separately recorded."]),
        fixture("phantom_tree","phantom-tree.pdf",1,anchors,["structure tree present","no marked-content links","visible content preserved"],["phantom structure tree"],expected_status="failed",derived_from="tagged_control",structure={"content_mcid_count":0,"fully_linked":False}),
        fixture("incomplete_tags","incomplete-tags.pdf",1,anchors,["two valid content links","final visible paragraph unmarked"],["incomplete content coverage"],derived_from="tagged_control",structure={"content_mcid_count":2,"fully_linked":False}),
        fixture("content_loss","deliberate-content-loss.pdf",1,[anchors[0]],["valid-looking reduced tree","final paragraph removed"],["deliberate content loss"],expected_status="failed",derived_from="tagged_control",comparison_reference="tagged-control.pdf",must_fail={"text_fidelity":True,"render_fidelity":True},missing_anchor=anchors[1]),
        fixture("mis_mapped_font","mis-mapped-font.pdf",1,[],["embedded font","C maps to Z in ToUnicode","unchanged visible glyphs"],["deliberately incorrect Unicode mapping"],derived_from="tagged_control",comparison_reference="tagged-control.pdf",must_fail={"unicode_mapping_fidelity":True},visual_fidelity_expected="identical to tagged-control.pdf; extraction differs"),
        fixture("form","forms-detect-only.pdf",1,["FORM-DETECT-ANCHOR."],["AcroForm text field","Widget annotation"],["forms detection-only","form field font is standard Helvetica"],field_expectations={"reader_name":"Synthetic Reader"}),
        fixture("slides","slides-detect-only.pdf",3,[f"SLIDE-ANCHOR-{i}." for i in range(1,4)],["landscape 960x540","slide-like content"],["slides detection-only"]),
        fixture("equation","equation-detect-only.pdf",1,["EQUATION-DETECT-ANCHOR."],["visually positioned superscript","equation"],["equations detection-only"]),
        fixture("blank","intentional-blank.pdf",2,["BLANK-CONTROL-ANCHOR."],["intentional truly blank second page"],["first page untagged"],classification={"1":"digital","2":"blank"}),
    ]
    for f in fixtures:
        path=out/f["path"]
        f["sha256"]=sha256(path)
        f["size_bytes"]=path.stat().st_size
        f["observed_baseline"]=pdf_features(path)
        if f["observed_baseline"]["page_count"] != f["expected_page_count"]:
            raise AssertionError(f"Page count differs from ground truth for {f['id']}")
    manifest={
        "schema_version":"phase0-corpus-1.0","corpus_name":"PDF Remediator original synthetic feasibility corpus",
        "generated_at_fixed":FIXED_DATE,"seed":SEED,"generator":"eval/build_corpus.py",
        "generator_sha256":sha256(Path(__file__)),"provenance":PROVENANCE,
        "runtime":{"python":platform.python_version(),"platform":platform.platform(),"packages":{name:importlib.metadata.version(name) for name in ("reportlab","pikepdf","Pillow")}},
        "fonts":fonts,"asset_sha256":sha256(out/"assets"/"repeated-shapes.png"),
        "limitations":["No representative real-book excerpts were provided or copied; book evidence remains provisional.","No fixture is declared PDF/UA compliant until an explicit pinned validator run is recorded.","Raw untagged fixture statuses describe their known limitations, not predicted engine outcomes.","No screenshots or visual checks are implied by successful generation; perform pinned render comparisons and inspect representative pages.","Synthetic OCR pixels are clean and do not represent difficult scans or every recognition error mode.","Ground-truth semantic and fidelity expectations are independent of any selected engine."],
        "fixtures":fixtures,
    }
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(out),"fixture_count":len(fixtures),"total_pages":sum(f["expected_page_count"] for f in fixtures),"manifest_sha256":sha256(out/"manifest.json")},indent=2))


if __name__=="__main__":
    main()
