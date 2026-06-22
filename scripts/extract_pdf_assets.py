#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

import fitz


MIN_WIDTH = 110
MIN_HEIGHT = 70
MIN_AREA = 9000
MERGE_GAP = 16


def main():
    if len(sys.argv) != 3:
        print("usage: extract_pdf_assets.py <pdf-path> <output-dir>", file=sys.stderr)
        return 2

    pdf_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    for old_file in output_dir.glob("*.png"):
        old_file.unlink()

    max_pages = int(os.environ.get("ASSET_MAX_PAGES", "40"))
    max_charts = int(os.environ.get("ASSET_MAX_CHARTS", "80"))
    page_target_width = int(os.environ.get("ASSET_PAGE_TARGET_WIDTH", "860"))
    chart_target_width = int(os.environ.get("ASSET_CHART_TARGET_WIDTH", "760"))

    doc = fitz.open(pdf_path)
    charts = []
    pages = []

    for page_index in range(min(len(doc), max_pages)):
        page = doc[page_index]
        page_number = page_index + 1

        page_file = f"page-{page_number:03}.png"
        page_width, page_height = save_region(
            page,
            page.rect,
            output_dir / page_file,
            target_width=page_target_width,
        )
        pages.append(
            {
                "kind": "page",
                "page": page_number,
                "file": page_file,
                "width": page_width,
                "height": page_height,
                "box": serialize_rect(page.rect),
                "pageBox": serialize_rect(page.rect),
                "label": f"page {page_number}",
            }
        )

        rects = collect_visual_rects(page)
        clusters = merge_rects(rects, page.rect)

        for chart_index, rect in enumerate(clusters, start=1):
            if len(charts) >= max_charts:
                break
            if not is_candidate(rect, page.rect):
                continue

            chart_file = f"chart-p{page_number:03}-{chart_index:02}.png"
            chart_width, chart_height = save_region(
                page,
                rect,
                output_dir / chart_file,
                target_width=chart_target_width,
            )
            charts.append(
                {
                    "kind": "chart",
                    "page": page_number,
                    "file": chart_file,
                    "width": chart_width,
                    "height": chart_height,
                    "box": serialize_rect(rect),
                    "pageBox": serialize_rect(page.rect),
                    "label": f"page {page_number} candidate {chart_index}",
                }
            )

    manifest = {
        "version": 1,
        "pageCount": len(doc),
        "charts": charts,
        "pages": pages,
    }

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


def collect_visual_rects(page):
    image_rects = []
    for image in page.get_images(full=True):
        xref = image[0]
        for rect in page.get_image_rects(xref):
            if rect and rect.is_valid and not rect.is_empty and is_candidate(rect, page.rect):
                image_rects.append(fitz.Rect(rect))

    if image_rects:
        return image_rects

    vector_rects = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect or not rect.is_valid or rect.is_empty:
            continue
        if rect.get_area() / page.rect.get_area() > 0.35:
            continue
        if rect.get_area() < MIN_AREA:
            continue
        vector_rects.append(fitz.Rect(rect))

    return vector_rects


def merge_rects(rects, page_rect):
    merged = []

    for rect in rects:
        clipped = inflate(rect & page_rect, 4) & page_rect
        if clipped.is_empty:
            continue

        did_merge = False
        for index, existing in enumerate(merged):
            if are_close(existing, clipped):
                merged[index] = (existing | clipped) & page_rect
                did_merge = True
                break

        if not did_merge:
            merged.append(clipped)

    changed = True
    while changed:
        changed = False
        next_rects = []
        while merged:
            current = merged.pop(0)
            index = 0
            while index < len(merged):
                if are_close(current, merged[index]):
                    current = (current | merged.pop(index)) & page_rect
                    changed = True
                else:
                    index += 1
            next_rects.append(current)
        merged = next_rects

    merged.sort(key=lambda rect: (rect.y0, rect.x0))
    return merged


def are_close(first, second):
    return inflate(first, MERGE_GAP).intersects(second)


def inflate(rect, amount):
    return fitz.Rect(
        rect.x0 - amount,
        rect.y0 - amount,
        rect.x1 + amount,
        rect.y1 + amount,
    )


def is_candidate(rect, page_rect):
    if rect.width < MIN_WIDTH or rect.height < MIN_HEIGHT:
        return False
    if rect.get_area() < MIN_AREA:
        return False
    if rect.get_area() / page_rect.get_area() > 0.82:
        return False
    return True


def save_region(page, rect, output_path, target_width):
    rect = rect & page.rect
    zoom = min(3.0, max(1.0, target_width / max(rect.width, 1)))
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
    pixmap.save(output_path)
    return pixmap.width, pixmap.height


def serialize_rect(rect):
    return {
        "x0": round(rect.x0, 2),
        "y0": round(rect.y0, 2),
        "x1": round(rect.x1, 2),
        "y1": round(rect.y1, 2),
        "width": round(rect.width, 2),
        "height": round(rect.height, 2),
    }


if __name__ == "__main__":
    raise SystemExit(main())
