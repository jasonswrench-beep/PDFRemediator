"""Independent coordinate, optical-agreement and bounded-input contracts."""
import math
import pytest
from PIL import Image, ImageDraw
from pdf_remediator.ocr_angles import base_region_limit, candidate_records, inverse_point, parse_hocr, refinement_crop, select_words


@pytest.mark.parametrize('angle,rotated,point,expected', [
    (0,(100,60),(10,20),(10,20)), (90,(60,100),(0,0),(100,0)),
    (180,(100,60),(0,0),(100,60)), (270,(60,100),(0,0),(0,60)),
    (90,(60,100),(30,50),(50,30))])
def test_inverse_maps_known_cardinal_corners(angle,rotated,point,expected):
    assert inverse_point(point,angle,(100,60),rotated)==pytest.approx(expected)


def test_inverse_maps_expanded_oblique_center_and_thumbnail_scale():
    assert inverse_point((80,70),35,(100,60),(160,140),.5)==pytest.approx((100,60))


@pytest.mark.parametrize('point,angle,scale', [((math.nan,0),0,1),((0,0),math.inf,1),((0,0),0,0),((0,0),0,-1)])
def test_nonfinite_or_invalid_transform_is_refused(point,angle,scale):
    with pytest.raises(ValueError):inverse_point(point,angle,(100,60),(100,60),scale)


def word(text,confidence=90,attempt=0,psm=7,box=(10,20,60,40),angle=0):
    left,top,right,bottom=box;cx,cy=(left+right)/2,(top+bottom)/2
    cosine,sine=math.cos(math.radians(angle)),math.sin(math.radians(angle))
    quad=[(cx+cosine*(x-cx)-sine*(y-cy),cy+sine*(x-cx)+cosine*(y-cy))
          for x,y in ((left,top),(right,top),(right,bottom),(left,bottom))]
    measured=[min(p[0] for p in quad),min(p[1] for p in quad),max(p[0] for p in quad),max(p[1] for p in quad)]
    return {'text':text,'confidence':confidence,'attempt':attempt,'raw_word_index':0,
            'psm':psm,'box':measured,'quad':quad,'angle':angle,'height':bottom-top}


@pytest.fixture
def blank_source():
    with Image.new('RGB',(512,512),'white') as image:
        yield image


def pair(text,confidence=90,attempt=0,box=(10,20,60,40),angle=0):
    return [word(text,confidence,attempt,7,box,angle),word(text,confidence-1,attempt+1,13,box,angle)]


def test_isolated_high_confidence_wrong_orientation_loses_to_agreement(blank_source):
    selected=select_words(pair('Harbor',84)+[word('Cipher',98,8,7,angle=180)],source_image=blank_source)
    assert [w['text'] for w in selected]==['Harbor']
    assert selected[0]['agreement_votes']==2


def test_same_psm_duplicate_crops_do_not_fake_independent_agreement(blank_source):
    assert select_words([word('Harbor',90,0,7),word('Harbor',95,1,7)],source_image=blank_source)==[]


def test_distinct_conditioned_rasters_can_corroborate_the_same_native_word(blank_source):
    first={**word('Harbor',90,0,7),'raster_sha256':'a'*64}
    second={**word('HARBOR',65,1,7),'raster_sha256':'b'*64}
    selected=select_words([first,second],source_image=blank_source)
    assert [w['text'] for w in selected]==['Harbor']
    assert selected[0]['agreement_votes']==2


def test_repeated_identical_raster_and_psm_cannot_inflate_agreement(blank_source):
    first={**word('Harbor',90,0,7),'raster_sha256':'a'*64}
    assert select_words([first,{**first,'attempt':1,'confidence':95}],source_image=blank_source)==[]


def test_distant_occurrence_cannot_supply_missing_spatial_agreement(blank_source):
    assert select_words([word('Harbor',90),word('Harbor',90,1,13,(200,200,250,220))],source_image=blank_source)==[]


def test_case_variants_keep_literal_best_native_text(blank_source):
    assert [w['text'] for w in select_words([word('Harbor,',92),word('HARBOR',81,1,13)],source_image=blank_source)]==['Harbor,']


@pytest.mark.parametrize('text,confidence', [('Q',99),('///',99),('Ha\x00rb',99),('Harbor',60)])
def test_unusable_candidates_do_not_become_pdf_text(text,confidence,blank_source):
    assert select_words(pair(text,confidence),source_image=blank_source)==[]


def test_tilted_line_keeps_word_order_despite_reversed_top_coordinates(blank_source):
    candidates=[]
    for i,(text,x,y) in enumerate([('Quartz',100,200),('River',200,150),('Atlas',300,100)]):
        candidates.extend(pair(text,90,i*2,(x,y,x+60,y+20),-math.degrees(math.atan(.5))))
    assert [w['text'] for w in select_words(candidates,source_image=blank_source)]==['Quartz','River','Atlas']


def trace(**changes):
    return {'number':0,'angle':0,'psm':7,'crop_box':[10,20,50,40],'working_size':[100,100],
            'rotated_size':[100,100],'scale':1,'resize':[2,2],'raster_size':[104,64],'padding':12,
            'raster_sha256':'a'*64,**changes}


def test_resize_crop_and_padding_map_to_measured_source_ink():
    result=candidate_records([{'text':'Quartz','confidence':95,'bbox':[12,12,92,52]}],trace(),(100,100))[0]
    assert result['box']==[10,20,50,40]
    assert result['quad']==[(10,20),(50,20),(50,40),(10,40)]
    assert result['raw_word_index']==0


def test_horizontal_conditioning_uses_separate_axis_scales():
    result=candidate_records([{'text':'Quartz','confidence':95,'bbox':[12,12,132,52]}],
                             trace(resize=[3,2],raster_size=[144,64]),(100,100))[0]
    assert result['box']==[10,20,50,40]


def test_native_refinement_canonicalizes_blank_proposal_margins_without_changing_ink():
    with Image.new('RGB',(200,100),'white') as frame:
        draw=ImageDraw.Draw(frame)
        draw.rectangle((45,25,154,74),fill='black')
        original=frame.tobytes()
        first=refinement_crop(frame,{'rotated_box':[40,20,160,80]},frame.size,1)
        second=refinement_crop(frame,{'rotated_box':[38,19,158,81]},frame.size,1)
        assert first==second==[43,23,157,77]
        assert frame.tobytes()==original


def test_native_refinement_never_invents_ink_on_a_blank_crop():
    with Image.new('RGB',(200,100),'white') as frame:
        assert refinement_crop(frame,{'rotated_box':[40,20,160,80]},frame.size,1) is None


def test_ordinary_regions_have_a_bounded_separate_budget_for_small_horizontal_words():
    assert base_region_limit(0)==32
    assert all(base_region_limit(angle)==12 for angle in (-45,-25,25,45,90,180,270))


def test_recognition_outside_candidate_raster_fails_closed():
    with pytest.raises(ValueError):candidate_records([{'text':'Quartz','confidence':95,'bbox':[0,0,120,60]}],trace(),(100,100))


def test_expansion_whitespace_outside_original_is_rejected():
    assert candidate_records([{'text':'Quartz','confidence':95,'bbox':[12,12,92,52]}],
                             trace(crop_box=[150,20,190,40]),(100,100))==[]


def test_hocr_retains_native_text_confidence_and_bounds(tmp_path):
    path=tmp_path/'native.hocr'
    path.write_text('<html><span class="ocrx_word" title="bbox 2 3 40 20; x_wconf 91">Quartz &amp; River</span></html>',encoding='utf-8')
    assert parse_hocr(path)==[{'text':'Quartz & River','bbox':[2,3,40,20],'confidence':91}]


@pytest.mark.parametrize('title',['bbox 2 3 40 20','bbox 2 3 1 20; x_wconf 91','bbox 2 3 40 20; x_wconf 101'])
def test_malformed_hocr_is_refused(tmp_path,title):
    path=tmp_path/'native.hocr';path.write_text(f'<html><span class="ocrx_word" title="{title}">Quartz</span></html>',encoding='utf-8')
    with pytest.raises(ValueError):parse_hocr(path)
