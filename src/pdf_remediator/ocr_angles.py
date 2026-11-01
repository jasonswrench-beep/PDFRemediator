"""Bounded local recognition alternatives and an invisible affine text layer.

This optional profile never changes the visible page. Its crops are local OCR
inputs, and every accepted word retains an inverse map into that original page.
Confidence is a mechanical filter, never accuracy or accessibility approval.
"""
from pathlib import Path
import hashlib
import math
import re
import time
import unicodedata

from PIL import Image

VERSION = 'local-angle-recognition-3'
WORD_SEPARATOR_POLICY = 'explicit-trailing-u0020-between-selected-words-1'
MAX_PIXELS = 40_000_000
MAX_SIDE = 1800
ANGLES = (0, -45, -35, -30, -25, -20, -15, 15, 20, 25, 30, 35, 45, 90, 180, 270)
MAX_ATTEMPTS = 936
MAX_SECONDS = 120
MAX_WORDS = 4096
MIN_CONFIDENCE = 70
MAX_SOURCE_FIT_PAIRS_PER_WORD = 64
MAX_SOURCE_FIT_PAIRS = 256
MAX_SOURCE_FIT_PIXELS = 32_000_000
MAX_SOURCE_FIT_CROP_PIXELS = 4_000_000
MIN_SOURCE_FIT_INK = 64
MAX_SOURCE_FIT_INK_DIFFERENCE = 1
MAX_SOURCE_FIT_AREA_RATIO = .8
OPTIONAL_CONTROLS = ((64, 1, 7), (64, 1, 13), (64, 1.5, 7), (64, 1.5, 13))
OPTIONAL_GROUP_RESERVE_SECONDS = 26
RESCUE_PLANNING_RESERVE_SECONDS = 12
MAX_OPTIONAL_WIDTH = 4096
MAX_CONFIRMATION_PLANS = 8
MAX_CONFIRMATION_COMPARISONS = 500_000


def base_region_limit(angle):
    """Keep ordinary small words from being crowded out by angled envelopes."""
    return 32 if angle == 0 else 12


def refinement_crop(frame, word, parent_rotated_size, scale):
    """Canonicalize native ink margins without changing source glyph pixels."""
    l,t,r,b=word['rotated_box'];rw,rh=parent_rotated_size;nw,nh=frame.size
    margin=max(2,round((b-t)/scale*.035))
    bounds=[max(0,math.floor((l-rw/2)/scale+nw/2-margin)),max(0,math.floor((t-rh/2)/scale+nh/2-margin)),
            min(nw,math.ceil((r-rw/2)/scale+nw/2+margin)),min(nh,math.ceil((b-rh/2)/scale+nh/2+margin))]
    if not (bounds[0]<bounds[2] and bounds[1]<bounds[3]) or (bounds[2]-bounds[0])*(bounds[3]-bounds[1])>4_000_000:
        raise ValueError('Native word refinement exceeds its supported crop bounds.')
    with frame.crop(bounds) as crop, crop.convert('L') as gray:
        with gray.point(lambda value:255 if value<180 else 0) as ink:
            measured=ink.getbbox()
    if measured is None:
        return None
    l,t,r,b=[bounds[0]+measured[0],bounds[1]+measured[1],bounds[0]+measured[2],bounds[1]+measured[3]]
    margin=max(2,round((b-t)*.035))
    return [max(0,l-margin),max(0,t-margin),min(nw,r+margin),min(nh,b+margin)]


def inverse_point(point, angle, original_size, rotated_size, scale=1):
    """Undo Pillow's centered expanded rotation, then the working thumbnail."""
    if not all(math.isfinite(float(v)) for v in (*point, angle, *original_size, *rotated_size, scale)) or scale <= 0:
        raise ValueError('Nonfinite recognition transform.')
    x, y = point[0] - rotated_size[0] / 2, point[1] - rotated_size[1] / 2
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return ((c*x - s*y + original_size[0]/2)/scale, (s*x + c*y + original_size[1]/2)/scale)


def _bounds(quad):
    return [min(p[0] for p in quad), min(p[1] for p in quad), max(p[0] for p in quad), max(p[1] for p in quad)]


def _overlap(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    area = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
    return intersection / area if area > 0 else 0


def _quad_area(word):
    quad = word.get('quad')
    if (not isinstance(quad, (list, tuple)) or len(quad) != 4
            or any(not isinstance(point, (list, tuple)) or len(point) != 2
                   or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in point)
                   for point in quad)):
        return 0
    turns = [(b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
             for a, b, c in zip(quad, quad[1:]+quad[:1], quad[2:]+quad[:2])]
    if not (all(value > 0 for value in turns) or all(value < 0 for value in turns)):
        return 0
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(quad, quad[1:]+quad[:1]))) / 2


def _source_pair_bounds(original, alternative, size):
    quads = (original['quad'], alternative['quad'])
    if any(x < 0 or y < 0 or x > size[0] or y > size[1] for quad in quads for x, y in quad):
        return None
    boxes = [_bounds(quad) for quad in quads]
    bounds = [math.floor(min(box[0] for box in boxes)), math.floor(min(box[1] for box in boxes)),
              math.ceil(max(box[2] for box in boxes)), math.ceil(max(box[3] for box in boxes))]
    return bounds if bounds[0] < bounds[2] and bounds[1] < bounds[3] else None


def _same_source_ink(source_image, original, alternative, bounds):
    """Compare spatial dark pixels at pixel centers inside the actual quads."""
    def edges(word):
        quad = word['quad']
        return [(a[0], a[1], b[0]-a[0], b[1]-a[1]) for a, b in zip(quad, quad[1:]+quad[:1])]
    first, second = edges(original), edges(alternative)
    def inside(x, y, lines):
        crosses = [dx*(y-ay)-dy*(x-ax) for ax, ay, dx, dy in lines]
        return all(value >= -1e-6 for value in crosses) or all(value <= 1e-6 for value in crosses)
    counts = [0, 0]
    difference = 0
    width = bounds[2]-bounds[0]
    with source_image.crop(bounds) as crop, crop.convert('L') as gray:
        for index, value in enumerate(gray.tobytes()):
            if value >= 180:
                continue
            x, y = bounds[0]+index % width+.5, bounds[1]+index // width+.5
            a, b = inside(x, y, first), inside(x, y, second)
            counts[0] += a
            counts[1] += b
            difference += a != b
            if difference > MAX_SOURCE_FIT_INK_DIFFERENCE:
                return False
    return min(counts) >= MIN_SOURCE_FIT_INK and difference <= MAX_SOURCE_FIT_INK_DIFFERENCE


def _prefer_source_fit(accepted, eligible, source_image):
    """Substitute only retained qualified words with nearly identical ink.

    Compare every alternative to the original score winner; equivalence never
    chains through an earlier substitute. Unproved or over-budget words retain
    their native selection. Ink agreement still requires human completeness QA.
    """
    result = list(accepted)
    pairs_used = pixels_used = 0
    for index, original in enumerate(accepted):
        original_area = _quad_area(original)
        if original_area <= 0:
            continue
        pairs = []
        unproved = False
        for alternative in eligible:
            if (alternative['text'].casefold() != original['text'].casefold()
                    or len(alternative['text']) != len(original['text'])
                    or _overlap(original['box'], alternative['box']) <= .5):
                continue
            area = _quad_area(alternative)
            if area <= 0 or area > original_area*MAX_SOURCE_FIT_AREA_RATIO:
                continue
            # Protect both the original accepted arrangement and substitutions
            # already made during this deterministic pass.
            if any(_overlap(alternative['box'], other['box']) > .35
                   for group in (accepted, result) for j, other in enumerate(group) if j != index):
                continue
            bounds = _source_pair_bounds(original, alternative, source_image.size)
            pixels = (bounds[2]-bounds[0])*(bounds[3]-bounds[1]) if bounds else 0
            if not bounds or pixels > MAX_SOURCE_FIT_CROP_PIXELS:
                unproved = True
                break
            pairs.append((alternative, area, bounds, pixels))
            if len(pairs) > MAX_SOURCE_FIT_PAIRS_PER_WORD:
                unproved = True
                break
        total_pixels = sum(pair[3] for pair in pairs)
        if (unproved or pairs_used+len(pairs) > MAX_SOURCE_FIT_PAIRS
                or pixels_used+total_pixels > MAX_SOURCE_FIT_PIXELS):
            continue
        pairs_used += len(pairs)
        pixels_used += total_pixels
        proved = [(word, area) for word, area, bounds, _ in pairs
                  if _same_source_ink(source_image, original, word, bounds)]
        if proved:
            result[index] = min(proved, key=lambda pair: (pair[1], -pair[0]['confidence'],
                -pair[0]['agreement_votes'], abs(pair[0]['angle']), pair[0]['attempt'], pair[0]['raw_word_index']))[0]
    return result


def select_words(candidates, *, source_image):
    """Choose spatial alternatives; no document words or replacement dictionary."""
    if (not isinstance(source_image, Image.Image) or source_image.mode != 'RGB'
            or not 0 < source_image.width*source_image.height <= MAX_PIXELS):
        raise ValueError('Angle word selection requires its bounded native RGB source raster.')
    if len(candidates)>MAX_WORDS:
        raise ValueError('Angle recognition exceeded its supported candidate-word count.')
    def identity(word):
        return word['text'].casefold().strip('.,;:!?()[]{}\"\u201c\u201d\u2018\u2019')
    stable=[]
    for word in candidates:
        evidence=[other for other in candidates if other['confidence']>=60 and identity(word)==identity(other)
                  and _overlap(word['box'],other['box'])>.5]
        votes=len({(other['angle'],other['psm'],other.get('raster_sha256','')) for other in evidence})
        if votes>=2:
            stable.append({**word,'agreement_votes':votes,'selection_score':word['confidence']+min(votes,6)*4})
    accepted = []
    eligible = []
    for word in sorted(stable, key=lambda w: (-w['selection_score'], abs(w['angle']), w['attempt'], w['box'][1], w['box'][0])):
        text = word['text']
        if not (MIN_CONFIDENCE <= word['confidence'] <= 100 and 2 <= len(text) <= 128
                and sum(c.isalnum() for c in text) >= 2 and not any(unicodedata.category(c)[0] == 'C' for c in text)):
            continue
        eligible.append(word)
        if any(_overlap(word['box'], old['box']) > .35 for old in accepted):
            continue
        accepted.append(word)
        if len(accepted) > MAX_WORDS:
            raise ValueError('Angle recognition exceeded its supported word count.')
    accepted = _prefer_source_fit(accepted, eligible, source_image)
    return order_words(accepted)


def order_words(accepted):
    # Reassemble nearby words along the same measured baseline. Ordering is a
    # geometric proposal requiring review, not inferred document semantics.
    lines = []
    for word in sorted(accepted, key=lambda w: (w['box'][1], w['box'][0])):
        center = [(word['box'][0]+word['box'][2])/2, (word['box'][1]+word['box'][3])/2]
        for line in lines:
            ref = line[0]
            delta = (word['angle']-ref['angle']+180)%360-180
            if abs(delta) > 12:
                continue
            theta=math.radians(ref['angle']); normal=(-math.sin(theta),math.cos(theta))
            other=[(ref['box'][0]+ref['box'][2])/2,(ref['box'][1]+ref['box'][3])/2]
            if abs((center[0]-other[0])*normal[0]+(center[1]-other[1])*normal[1]) <= max(word['height'],ref['height'])*.65:
                line.append(word);break
        else:
            lines.append([word])
    output=[]
    for line in sorted(lines, key=lambda group: (min(w['box'][1] for w in group),min(w['box'][0] for w in group))):
        theta=math.radians(line[0]['angle'])
        line.sort(key=lambda w: ((w['box'][0]+w['box'][2])*math.cos(theta)+(w['box'][1]+w['box'][3])*math.sin(theta)))
        output.extend(line)
    return output


def exact_literal_votes(word, candidates, *, literal=None):
    """Count native controls at this position without folding or guessing case."""
    text = word['text'] if literal is None else literal
    return len({(other['angle'], other['psm'], other.get('raster_sha256', ''))
                for other in candidates if other['confidence'] >= 60 and other['text'] == text
                and _overlap(word['box'], other['box']) > .5})


def exact_supported_words(candidates):
    """Return existing whole native records meeting the stricter optional gate."""
    result = []
    for word in candidates:
        text = word['text']; votes = exact_literal_votes(word, candidates)
        if (MIN_CONFIDENCE <= word['confidence'] <= 100 and votes >= 2 and 2 <= len(text) <= 128
                and sum(char.isalnum() for char in text) >= 2
                and not any(unicodedata.category(char)[0] == 'C' for char in text)):
            result.append({**word, 'agreement_votes': votes, 'selection_score': word['confidence'] + min(votes, 6)*4})
    return sorted(result, key=lambda word: (-word['selection_score'], abs(word['angle']), word['attempt'], word['raw_word_index']))


def native_frame(native_rgb, angle):
    """Preflight a single optional native rotation before allocating it."""
    cosine, sine = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
    extent = (math.ceil(native_rgb.width*cosine + native_rgb.height*sine) + 2,
              math.ceil(native_rgb.width*sine + native_rgb.height*cosine) + 2)
    if extent[0]*extent[1] > MAX_PIXELS*2:
        raise ValueError('Optional native rotation exceeds its preallocation bound.')
    frame = native_rgb.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC, fillcolor='white')
    if frame.width*frame.height > MAX_PIXELS*2:
        frame.close()
        raise ValueError('Optional native rotation exceeds its pixel bound.')
    return frame


def canonical_confirmation_crop(frame, word, source_size):
    """Reproduce source-ink margins from the selected quad, with no initial pad."""
    cosine, sine = math.cos(math.radians(word['angle'])), math.sin(math.radians(word['angle']))
    projected = [(cosine*(x-source_size[0]/2) + sine*(y-source_size[1]/2) + frame.width/2,
                  -sine*(x-source_size[0]/2) + cosine*(y-source_size[1]/2) + frame.height/2) for x, y in word['quad']]
    box = _bounds(projected)
    bounds = [max(0, math.floor(box[0])), max(0, math.floor(box[1])),
              min(frame.width, math.ceil(box[2])), min(frame.height, math.ceil(box[3]))]
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3] or (bounds[2]-bounds[0])*(bounds[3]-bounds[1]) > MAX_SOURCE_FIT_CROP_PIXELS:
        return None
    with frame.crop(bounds) as crop, crop.convert('L') as gray, gray.point(lambda value: 255 if value < 180 else 0) as ink:
        measured = ink.getbbox()
    if measured is None:
        return None
    left, top, right, bottom = (bounds[0]+measured[0], bounds[1]+measured[1], bounds[0]+measured[2], bounds[1]+measured[3])
    margin = max(2, round((bottom-top)*.035))
    result = [max(0, left-margin), max(0, top-margin), min(frame.width, right+margin), min(frame.height, bottom+margin)]
    return result if (result[2]-result[0])*(result[3]-result[1]) <= MAX_SOURCE_FIT_CROP_PIXELS else None


def confirmation_plans(native_rgb, baseline_candidates, baseline_words):
    plans = []; comparisons = 0
    def bounded_votes(word, literal):
        nonlocal comparisons
        controls = set()
        for other in baseline_candidates:
            if comparisons >= MAX_CONFIRMATION_COMPARISONS:
                return None
            comparisons += 1
            if other['confidence'] >= 60 and other['text'] == literal and _overlap(word['box'], other['box']) > .5:
                controls.add((other['angle'], other['psm'], other.get('raster_sha256', '')))
        return len(controls)
    for index, word in enumerate(baseline_words):
        votes = bounded_votes(word, word['text'])
        if votes is None:
            return plans
        if votes >= 2:
            continue
        alternatives = set(); folded = word['text'].casefold()
        for other in baseline_candidates:
            if comparisons >= MAX_CONFIRMATION_COMPARISONS:
                return plans
            comparisons += 1
            if (other['text'] != word['text'] and len(other['text']) == len(word['text'])
                    and other['text'].casefold() == folded and _overlap(word['box'], other['box']) > .5):
                alternatives.add(other['text'])
        forms = []
        for literal in sorted(alternatives):
            votes = bounded_votes(word, literal)
            if votes is None:
                return plans
            if votes >= 2:
                forms.append(literal)
        if not forms:
            continue
        if comparisons >= MAX_CONFIRMATION_COMPARISONS:
            return plans
        with native_frame(native_rgb, word['angle']) as frame:
            bounds = canonical_confirmation_crop(frame, word, native_rgb.size)
        if bounds is None:
            continue
        plans.append({'selected_index': index, 'source_reference': {key: word[key] for key in ('attempt', 'raw_word_index', 'raster_sha256')},
                      'angle': word['angle'], 'bounds': bounds, 'kind': 'selected-word-confirmation', 'allowed_literals': sorted(forms)})
        if len(plans) == MAX_CONFIRMATION_PLANS:
            break
    return plans


def confirm_words(baseline_words, baseline_candidates, candidates, plans, *, source_image):
    """Only uniquely confirmed old literal alternatives may replace a baseline."""
    result = list(baseline_words); pairs_used = pixels_used = 0
    for plan_index, plan in enumerate(plans):
        index = plan['selected_index']; original = baseline_words[index]
        group = [word for word in candidates if word.get('phase') == 'confirmation' and word.get('plan_index') == plan_index]
        eligible = [word for word in exact_supported_words(group)
                    if word['text'] in plan['allowed_literals'] and word['angle'] == original['angle']
                    and word['text'].casefold() == original['text'].casefold() and len(word['text']) == len(original['text'])
                    and _overlap(original['box'], word['box']) > .5 and _quad_area(word) > 0
                    and exact_literal_votes(original, baseline_candidates, literal=word['text']) >= 2
                    and not any(_overlap(word['box'], other['box']) > .35
                                for words in (baseline_words, result) for j, other in enumerate(words) if j != index)]
        pairs = []; unproved = len(eligible) > MAX_SOURCE_FIT_PAIRS_PER_WORD
        for word in eligible:
            bounds = _source_pair_bounds(original, word, source_image.size)
            pixels = (bounds[2]-bounds[0])*(bounds[3]-bounds[1]) if bounds else 0
            if not bounds or pixels > MAX_SOURCE_FIT_CROP_PIXELS:
                unproved = True
                break
            pairs.append((word, bounds, pixels))
        total = sum(row[2] for row in pairs)
        if unproved or pairs_used+len(pairs) > MAX_SOURCE_FIT_PAIRS or pixels_used+total > MAX_SOURCE_FIT_PIXELS:
            continue
        pairs_used += len(pairs); pixels_used += total
        proved = [word for word, bounds, _ in pairs if _same_source_ink(source_image, original, word, bounds)]
        if len({word['text'] for word in proved}) == 1:
            result[index] = proved[0]
    return result


def add_rescue_words(confirmed_words, candidates):
    """Keep every baseline/confirmed record; optional votes apply only locally."""
    accepted = list(confirmed_words)
    plans = sorted({word['plan_index'] for word in candidates if word.get('phase') == 'rescue'})
    for plan_index in plans:
        group = [word for word in candidates if word.get('phase') == 'rescue' and word['plan_index'] == plan_index]
        for word in exact_supported_words(group):
            if not any(_overlap(word['box'], old['box']) > .35 for old in accepted):
                accepted.append(word)
                if len(accepted) > MAX_WORDS:
                    raise ValueError('Angle recognition exceeded its supported word count.')
    return order_words(accepted)


def optional_group_skip(plan, attempt_count, elapsed):
    """Reserve every control before starting; never use a partial group."""
    if attempt_count + len(OPTIONAL_CONTROLS) > MAX_ATTEMPTS:
        return 'attempt-slots'
    if elapsed + OPTIONAL_GROUP_RESERVE_SECONDS > MAX_SECONDS:
        return 'time-reserve'
    left, top, right, bottom = plan['bounds']; width, height = right-left, bottom-top
    if width <= 0 or height <= 0 or width*height > MAX_SOURCE_FIT_CROP_PIXELS:
        return 'crop-pixels'
    if any(max(1, round(width*target/height*stretch)) > MAX_OPTIONAL_WIDTH for target, stretch, _ in OPTIONAL_CONTROLS):
        return 'resized-width'
    return None


def parse_hocr(path):
    from lxml import etree
    raw=Path(path).read_bytes()
    if len(raw)>8_000_000:
        raise ValueError('Recognition result exceeds its supported size.')
    if not raw.strip():
        return []
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,recover=False))
    output=[]
    for node in root.iter():
        if 'ocrx_word' not in node.get('class','').split():
            continue
        title=node.get('title','');box=re.search(r'\bbbox (\d+) (\d+) (\d+) (\d+)\b',title)
        conf=re.search(r'\bx_wconf (\d+)\b',title)
        if not box or not conf:
            raise ValueError('Recognition word has incomplete geometry/confidence.')
        text=unicodedata.normalize('NFKC',''.join(node.itertext()).strip())
        bounds=list(map(int,box.groups()));confidence=int(conf[1])
        if bounds[0]>=bounds[2] or bounds[1]>=bounds[3] or not 0<=confidence<=100:
            raise ValueError('Recognition word has invalid geometry/confidence.')
        output.append({'text':text,'bbox':bounds,'confidence':confidence})
        if len(output)>MAX_WORDS:
            raise ValueError('Recognition candidate exceeds its word count.')
    return output


def render_invisible(words, output_pdf, size, dpi, font_path):
    """Fit glyph ink into the inverse-mapped rectangle, never an inflated AABB."""
    from fontTools.ttLib import TTFont
    from fpdf import FPDF
    from fpdf.enums import TextMode
    font=TTFont(font_path);cmap=font.getBestCmap();upem=font['head'].unitsPerEm
    if len(words) > 1 and not cmap.get(32):
        font.close()
        raise ValueError('Recognition font lacks the explicit word separator.')
    pdf=FPDF(unit='pt',format=(size[0]*72/dpi,size[1]*72/dpi))
    pdf.set_auto_page_break(False);pdf.add_page();pdf.add_font('Recognition',fname=font_path)
    pdf.text_mode=TextMode.INVISIBLE
    for index, word in enumerate(words):
        names=[cmap.get(ord(c)) for c in word['text']]
        if not all(names):
            raise ValueError('Recognition returned characters absent from the qualified embedded font.')
        glyphs=[font['glyf'][name] for name in names]
        ymin=min(getattr(g,'yMin',0) for g in glyphs);ymax=max(getattr(g,'yMax',0) for g in glyphs)
        xmin=getattr(glyphs[0],'xMin',0)
        ink_width=sum(font['hmtx'].metrics[n][0] for n in names[:-1])+getattr(glyphs[-1],'xMax',0)-xmin
        if ymax<=ymin or ink_width<=0:
            raise ValueError('Recognition has no usable glyph ink bounds.')
        l,t,r,b=word['rotated_box'];width=(r-l)/word['scale'];height=(b-t)/word['scale']
        # The working coordinates carry the native glyph-ink rectangle. Offset
        # the actual font baseline so its ink, not its advance box, fills it.
        origin=(l-xmin*(r-l)/ink_width,t+ymax*(b-t)/(ymax-ymin))
        x,y=inverse_point(origin,word['angle'],word['working_size'],word['rotated_size'],word['scale'])
        fontsize=height*72/dpi*upem/(ymax-ymin)
        stretching=100*(width*72/dpi)/(fontsize*ink_width/upem)
        if not 0<fontsize<1000 or not 1<stretching<1000:
            raise ValueError('Recognition glyph fit exceeds supported bounds.')
        pdf.set_font('Recognition',size=fontsize);pdf.set_stretching(stretching)
        with pdf.rotation(-word['angle'],x=x*72/dpi,y=y*72/dpi):
            # The added separator never enters glyph ink metrics or placement.
            pdf.text(x*72/dpi,y*72/dpi,word['text'] + (' ' if index + 1 < len(words) else ''))
    pdf.output(output_pdf);font.close()


def candidate_records(words, attempt, source_size):
    """Reconstruct original-frame words from retained native hOCR and crop trace."""
    result=[]
    sx,sy=attempt['resize'];padding=attempt['padding'];bounds=attempt['crop_box']
    for index,word in enumerate(words):
        l,t,r,b=word['bbox']
        if not (0<=l<r<=attempt['raster_size'][0] and 0<=t<b<=attempt['raster_size'][1]):
            raise ValueError('Recognition word is outside its candidate raster.')
        transformed=[bounds[0]+(l-padding)/sx,bounds[1]+(t-padding)/sy,
                     bounds[0]+(r-padding)/sx,bounds[1]+(b-padding)/sy]
        corners=[(transformed[0],transformed[1]),(transformed[2],transformed[1]),(transformed[2],transformed[3]),(transformed[0],transformed[3])]
        quad=[inverse_point(p,attempt['angle'],attempt['working_size'],attempt['rotated_size'],attempt['scale']) for p in corners]
        if any(x<0 or y<0 or x>source_size[0] or y>source_size[1] for x,y in quad):
            continue
        result.append({'text':word['text'],'confidence':word['confidence'],'box':_bounds(quad),'quad':quad,
            'attempt':attempt['number'],'raw_word_index':index,'psm':attempt['psm'],'angle':attempt['angle'],
            'raster_sha256':attempt['raster_sha256'],
            'rotated_box':transformed,'rotated_size':attempt['rotated_size'],
            'working_size':attempt['working_size'],'scale':attempt['scale'],
            'height':(transformed[3]-transformed[1])/attempt['scale']})
        if 'phase' in attempt:
            result[-1].update({key: attempt[key] for key in ('phase', 'plan_index', 'target_height')})
    return result


def recognize(input_file, output_pdf, output_text, options, regions, directory, font_path, *, rescue_module, region_module):
    """Recognize local crop alternatives under one page/process budget."""
    from ocrmypdf._exec import tesseract
    started=time.monotonic();directory=Path(directory);directory.mkdir()
    with Image.open(input_file) as native:
        size=native.size;resolution=native.info.get('dpi')
        if (size[0]*size[1]>MAX_PIXELS or not resolution or len(resolution)!=2
                or any(not math.isfinite(v) or not 50<=v<=1200 for v in resolution)
                or abs(resolution[0]-resolution[1])>1):
            raise ValueError('Angle recognition requires bounded raster dimensions and square DPI.')
        dpi=resolution[0];image=native.convert('RGB')
    input_hash=hashlib.sha256(image.tobytes()).hexdigest();native_image=image.copy()
    image.thumbnail((MAX_SIDE,MAX_SIDE),Image.Resampling.LANCZOS)
    working_size=image.size;scale=working_size[0]/size[0]
    # Thumbnail rounding can otherwise shift words on very small images.
    if abs(working_size[1]/size[1]-scale)>1/min(size):
        raise ValueError('Recognition thumbnail has inconsistent scaling.')
    candidates=[];attempts=[]

    def perform(frame,bounds,angle,frame_original,frame_scale,region,psm,stretch=1,refined_from=None,
                phase=None,plan_index=None,target_height=None):
        if len(attempts)>=MAX_ATTEMPTS or time.monotonic()-started>=MAX_SECONDS:
            raise ValueError('Angle recognition exceeded its bounded candidate budget; use a separate standard run or source repair.')
        with frame.crop(bounds) as original_crop:
            resize=min(2,64/max(1,original_crop.height)) if target_height is None else target_height/original_crop.height
            old_size=original_crop.size
            fitted_size=(max(1,round(original_crop.width*resize*stretch)),max(1,round(original_crop.height*resize)))
            with original_crop.resize(fitted_size,Image.Resampling.LANCZOS) as crop:
                resized=crop.size;padded=Image.new('RGB',(crop.width+24,crop.height+24),'white');padded.paste(crop,(12,12))
        number=len(attempts);base=directory/f'{number:03d}';raster=base.with_suffix('.png');padded.save(raster,dpi=(300,300))
        raster_size=list(padded.size);padded.close();hocr=base.with_suffix('.hocr');text=base.with_suffix('.txt')
        tesseract.generate_hocr(input_file=raster,output_hocr=hocr,output_text=text,languages=options.languages,
            engine_mode=options.tesseract.oem,tessconfig=list(options.tesseract.config),
            timeout=min(6,max(.1,MAX_SECONDS-(time.monotonic()-started))),pagesegmode=psm,
            thresholding=options.tesseract.thresholding,user_words=None,user_patterns=None,omp_thread_limit=1)
        if text.exists() and '[skipped page]' in text.read_text(encoding='utf-8'):
            raise ValueError('A local recognition candidate timed out or was skipped.')
        words=parse_hocr(hocr)
        attempt={'number':number,'angle':angle,'psm':psm,'region':region,'word_count':len(words),
            'crop_box':list(bounds),'working_size':list(frame_original),'rotated_size':list(frame.size),'scale':frame_scale,
            'resize':[resized[0]/old_size[0],resized[1]/old_size[1]],'raster_size':raster_size,'padding':12,
            'raster_sha256':hashlib.sha256(raster.read_bytes()).hexdigest(),'hocr_sha256':hashlib.sha256(hocr.read_bytes()).hexdigest()}
        if refined_from is not None:attempt['refined_from']=refined_from
        if phase is not None:
            attempt.update(phase=phase,plan_index=plan_index,target_height=target_height)
        attempts.append(attempt);mapped=candidate_records(words,attempt,size);candidates.extend(mapped)
        if len(candidates)>MAX_WORDS:
            raise ValueError('Angle recognition exceeded its supported candidate-word count.')
        return words,mapped,attempt

    for angle in ANGLES:
        rotated=image.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC,fillcolor='white')
        proposed=regions(rotated)
        if len(proposed)>64:
            raise ValueError('Angle region detector exceeds its supported count.')
        unique={tuple(region['bounds']):region for region in proposed}
        ordered=sorted(unique.values(),key=lambda region:(-region['component_count'],region['kind']!='line',region['bounds'][1],region['bounds'][0]))
        weak=[]
        for region in ordered[:base_region_limit(angle)]:
            for psm in (7,13):
                words,mapped,attempt=perform(rotated,region['bounds'],angle,working_size,scale,region,psm)
                if any(w['confidence']>=85 for w in words):
                    for word in mapped:
                        if word['confidence']>=20 and sum(c.isalnum() for c in word['text'])>=3:
                            weak.append((word,{'attempt':attempt['number'],'word_index':word['raw_word_index']}))
        refinements=[]
        for word,link in sorted(weak,key=lambda item:(-len(item[0]['text']),-item[0]['confidence'])):
            if not any(_overlap(word['box'],old['box'])>.5 for old,_ in refinements):
                refinements.append((word,link))
            if len(refinements)==8:break
        if refinements:
            native_rotated=native_image.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC,fillcolor='white')
            for word,link in refinements:
                bounds=refinement_crop(native_rotated,word,rotated.size,scale)
                if bounds is None:continue
                region={'bounds':bounds,'component_count':0,'count':0,'kind':'refined-word','line_id':-1}
                for stretch in (1,1.5):
                    for psm in (7,13):perform(native_rotated,bounds,angle,size,1,region,psm,stretch=stretch,refined_from=link)
            native_rotated.close()
        rotated.close()
    baseline_attempt_count = len(attempts)
    baseline_candidates = list(candidates)
    confirmation_trace = {'plans': None, 'attempted_plans': 0, 'budget_skipped': None}
    rescue_trace = {'proposals': None, 'attempted_plans': 0, 'budget_skipped': None}

    def skipped(index, reason):
        return {'plan_index': index, 'reason': reason, 'attempt_count': len(attempts),
                'elapsed_seconds': round(time.monotonic()-started, 6)}

    def optional_groups(plans, phase, trace):
        for plan_index, plan in enumerate(plans):
            reason = optional_group_skip(plan, len(attempts), time.monotonic()-started)
            if reason:
                trace['budget_skipped'] = skipped(plan_index, reason)
                break
            with native_frame(native_image, plan['angle']) as frame:
                count = plan.get('component_count', 0)
                region = {'bounds': plan['bounds'], 'component_count': count, 'count': count, 'kind': plan['kind'], 'line_id': -1}
                for height, stretch, psm in OPTIONAL_CONTROLS:
                    perform(frame, plan['bounds'], plan['angle'], size, 1, region, psm, stretch=stretch,
                            phase=phase, plan_index=plan_index, target_height=height)
            trace['attempted_plans'] += 1

    try:
        baseline_words = select_words(baseline_candidates, source_image=native_image)
        if time.monotonic()-started + OPTIONAL_GROUP_RESERVE_SECONDS + 2 > MAX_SECONDS:
            confirmation_trace['budget_skipped'] = skipped(0, 'time-reserve-before-confirmation-planning')
        else:
            confirmation_trace['plans'] = confirmation_plans(native_image, baseline_candidates, baseline_words)
            optional_groups(confirmation_trace['plans'], 'confirmation', confirmation_trace)
        confirmation_candidates = [word for word in candidates if word.get('phase') == 'confirmation']
        confirmed = confirm_words(baseline_words, baseline_candidates, confirmation_candidates,
                                 confirmation_trace['plans'] or [], source_image=native_image)
        if time.monotonic()-started + OPTIONAL_GROUP_RESERVE_SECONDS + RESCUE_PLANNING_RESERVE_SECONDS > MAX_SECONDS:
            rescue_trace['budget_skipped'] = skipped(0, 'time-reserve-before-rescue-planning')
        else:
            rescue_trace['proposals'] = rescue_module.proposals(native_image, confirmed, region_module)
            optional_groups(rescue_trace['proposals']['plans'], 'rescue', rescue_trace)
        selected = add_rescue_words(confirmed, [word for word in candidates if word.get('phase') == 'rescue'])
    finally:
        image.close();native_image.close()
    if not selected:
        raise ValueError('Tilted/vertical OCR found no supported high-confidence words; use a better source or manual repair.')
    render_invisible(selected,output_pdf,size,dpi,font_path)
    Path(output_text).write_text(' '.join(w['text'] for w in selected)+'\n',encoding='utf-8')
    return {'version':VERSION,'image_size':list(size),'dpi':dpi,'input_RGB_sha256':input_hash,
        'font_sha256':hashlib.sha256(Path(font_path).read_bytes()).hexdigest(),'working_size':list(working_size),
        'attempt_count':len(attempts),'attempts':attempts,'baseline_attempt_count':baseline_attempt_count,
        'confirmation_trace':confirmation_trace,'rescue_trace':rescue_trace,'selected_words':selected,
        'output_layer_sha256':hashlib.sha256(Path(output_pdf).read_bytes()).hexdigest(),
        'seconds':round(time.monotonic()-started,3),'renderer':'invisible-affine',
        'word_separator_policy':WORD_SEPARATOR_POLICY,'word_separator_count':max(0,len(selected)-1),
        'accuracy':'needs-review','completeness':'needs-review','reading_order':'needs-review'}
