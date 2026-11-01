"""Bounded ruled-table conditioning of recognition pixels, never PDF painting."""
from contextlib import ExitStack
import hashlib
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

PROFILE_VERSION = 'ruled-table-recognition-1'
MAX_PIXELS = 40_000_000
MAX_LINES = 128
MAX_GRIDS = 12


def _groups(values):
    start = None
    for index, value in enumerate([*values, 0]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            yield start, index
            start = None


def _segments(closed, horizontal, vertical, width, height, dpi):
    thickness = max(5, min(16, round(dpi * .04)))
    min_h, min_v = max(100, round(width * .12)), max(45, round(dpi * .18))
    hs, vs = [], []
    for y0, y1 in _groups(horizontal.getprojection()[1]):
        if y1 - y0 > thickness:
            continue
        with horizontal.crop((0, y0, width, y1)) as band:
            cores = list(_groups(band.getprojection()[0]))
        for x0, x1 in cores:
            if x1 - x0 < min_h * .2:
                continue
            left, right = max(0, round(x0 - min_h / 2)), min(width, round(x1 + min_h / 2))
            with closed.crop((left, y0, right, y1)) as band:
                runs = list(_groups(band.getprojection()[0]))
            anchored = [run for run in runs if run[0] <= (x0 + x1) / 2 - left < run[1]]
            if anchored:
                start, end = anchored[0]
                hs.append((max(0, left + start - 1), max(0, y0 - 1), min(width, left + end + 1), min(height, y1 + 1)))
    for x0, x1 in _groups(vertical.getprojection()[0]):
        if x1 - x0 > thickness:
            continue
        with vertical.crop((x0, 0, x1, height)) as band:
            cores = list(_groups(band.getprojection()[1]))
        for y0, y1 in cores:
            if y1 - y0 < min_v * .2:
                continue
            top, bottom = max(0, round(y0 - min_v / 2)), min(height, round(y1 + min_v / 2))
            with closed.crop((x0, top, x1, bottom)) as band:
                runs = list(_groups(band.getprojection()[1]))
            anchored = [run for run in runs if run[0] <= (y0 + y1) / 2 - top < run[1]]
            if anchored:
                start, end = anchored[0]
                vs.append((max(0, x0 - 1), max(0, top + start - 1), min(width, x1 + 1), min(height, top + end + 1)))
    if len(hs) + len(vs) > MAX_LINES:
        raise ValueError('Ruled-table OCR profile exceeds its supported ruling-line count.')
    return hs, vs, thickness


def _grids(hs, vs, width, tolerance):
    edges = {i: set() for i in range(len(hs) + len(vs))}
    for i, horizontal in enumerate(hs):
        for j, vertical in enumerate(vs):
            if (horizontal[0] - tolerance <= (vertical[0] + vertical[2]) / 2 <= horizontal[2] + tolerance
                    and vertical[1] - tolerance <= (horizontal[1] + horizontal[3]) / 2 <= vertical[3] + tolerance):
                edges[i].add(len(hs) + j)
                edges[len(hs) + j].add(i)
    result, seen = [], set()
    for start in edges:
        if start in seen:
            continue
        stack, identifiers = [start], set()
        while stack:
            current = stack.pop()
            if current in identifiers:
                continue
            identifiers.add(current)
            seen.add(current)
            stack.extend(edges[current] - identifiers)
        horizontal = [hs[i] for i in sorted(identifiers) if i < len(hs)]
        vertical = [vs[i - len(hs)] for i in sorted(identifiers) if i >= len(hs)]
        if len(horizontal) < 3 or len(vertical) < 3:
            continue
        boxes = horizontal + vertical
        bounds = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        if bounds[2] - bounds[0] >= width * .2:
            result.append({'bounds': bounds, 'horizontal': horizontal, 'vertical': vertical})
    if len(result) > MAX_GRIDS:
        raise ValueError('Ruled-table OCR profile exceeds its supported table count.')
    return result


def filter_table_lines(image):
    """Return an owned image and geometric proof; leave the input untouched.

    Long line cores are trimmed to contiguous source-ink segments. Merged cells
    therefore do not acquire fictional full-width/full-height ruling masks.
    Dense dark-colored header backgrounds are normalized only inside detected
    grids; sparse colored text and all pixels outside those grids stay intact.
    """
    width, height = image.size
    if min(width, height) < 1 or width * height > MAX_PIXELS:
        raise ValueError('Ruled-table OCR profile supports recognition images up to 40 million pixels.')
    dpi = float(image.info.get('dpi', (300, 300))[0])
    if not math.isfinite(dpi) or not 50 <= dpi <= 1200:
        raise ValueError('Ruled-table OCR profile requires a supported finite image resolution.')
    with ExitStack() as stack:
        keep = stack.enter_context
        rgb = keep(image.convert('RGB'))
        gray = keep(ImageOps.grayscale(image))
        dark = keep(gray.point(lambda p: 255 if p < 100 else 0))
        closed = keep(dark.filter(ImageFilter.MaxFilter(3)))
        horizontal = keep(closed.filter(ImageFilter.BoxBlur((max(100, round(width * .12)) / 2, 0))).point(lambda p: 255 if p >= 232 else 0))
        vertical = keep(closed.filter(ImageFilter.BoxBlur((0, max(45, round(dpi * .18)) / 2))).point(lambda p: 255 if p >= 232 else 0))
        hs, vs, thickness = _segments(closed, horizontal, vertical, width, height, dpi)
        grids = _grids(hs, vs, width, thickness)
        ruling = keep(Image.new('L', image.size))
        gridmask = keep(Image.new('L', image.size))
        rules, regions = ImageDraw.Draw(ruling), ImageDraw.Draw(gridmask)
        for grid in grids:
            regions.rectangle((grid['bounds'][0], grid['bounds'][1], grid['bounds'][2] - 1, grid['bounds'][3] - 1), fill=255)
            for box in grid['horizontal'] + grid['vertical']:
                rules.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
        ruling_fraction = ruling.histogram()[255] / (width * height)
        if ruling_fraction > .05:
            raise ValueError('Ruled-table OCR profile refuses an excessive recognition ruling mask.')
        result = rgb.copy()
        result.info = dict(image.info)
        try:
            header_pixels, normalized_header, dominant = 0, False, None
            if grids:
                bands = [keep(band) for band in rgb.split()]
                high = keep(ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2]))
                low = keep(ImageChops.darker(ImageChops.darker(bands[0], bands[1]), bands[2]))
                colored = keep(ImageChops.subtract(high, low).point(lambda p: 255 if p > 40 else 0))
                colored = keep(ImageChops.multiply(colored, gridmask).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9)))
                colored = keep(ImageChops.multiply(colored, gridmask))
                if colored.histogram()[255] <= min(2_000_000, width * height * .15):
                    dense = keep(colored.filter(ImageFilter.BoxBlur((max(15, dpi * .1), max(6, dpi * .03)))).point(lambda p: 255 if p >= 232 else 0))
                    dense = keep(ImageChops.multiply(dense, colored))
                    for _ in range(MAX_GRIDS):
                        index = dense.tobytes().find(b'\xff')
                        if index < 0:
                            break
                        ImageDraw.floodfill(colored, (index % width, index // width), 128)
                        selected = keep(colored.point(lambda p: 255 if p == 128 else 0))
                        dense = keep(ImageChops.subtract(dense, selected))
                    header = keep(colored.point(lambda p: 255 if p == 128 else 0))
                    histogram = gray.histogram(mask=header)
                    header_pixels = sum(histogram)
                    dominant = max(range(240), key=lambda value: histogram[value])
                    cut = (dominant + 255) / 2
                    light = sum(histogram[round(cut):])
                    if header_pixels and dominant < 180 and .005 < light / header_pixels < .25 and dense.getbbox() is None:
                        normalized = keep(gray.point(lambda p: 0 if p > cut else 255).convert('RGB'))
                        result.paste(normalized, (0, 0), header)
                        normalized_header = True
            result.paste('white', (0, 0), ruling)
            difference = keep(ImageChops.difference(rgb, result))
            channels = [keep(band) for band in difference.split()]
            changed = keep(ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2]).point(lambda p: 255 if p else 0))
            outside = keep(ImageChops.multiply(changed, keep(ImageOps.invert(gridmask))))
            fraction = changed.histogram()[255] / (width * height)
            if outside.getbbox() is not None or fraction > .12:
                raise ValueError('Ruled-table OCR profile exceeded its source-bound recognition regions.')
            proof = {'profile_version': PROFILE_VERSION, 'status': 'filtered' if grids else 'no-grid',
                     'image_size': list(image.size), 'dpi': dpi, 'grids': grids, 'horizontal_candidates': len(hs), 'vertical_candidates': len(vs),
                     'ruling_mask_fraction': ruling_fraction, 'changed_recognition_fraction': fraction, 'changed_recognition_bbox': changed.getbbox(),
                     'header_pixels': header_pixels, 'header_normalized': normalized_header, 'header_dominant_luma': dominant,
                     'outside_detected_grids_unchanged': True, 'input_RGB_pixels_sha256': hashlib.sha256(rgb.tobytes()).hexdigest(),
                     'output_RGB_pixels_sha256': hashlib.sha256(result.tobytes()).hexdigest(),
                     'scope': 'Recognition pixels only; source PDF painting is not changed. Accuracy, completeness, table associations and reading order require review.'}
            return result, proof
        except BaseException:
            result.close()
            raise
