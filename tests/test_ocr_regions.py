"""Independent geometric and workload contracts; synthetic pixels only."""
import hashlib
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from pdf_remediator import ocr_regions as cc


class RegionContracts(unittest.TestCase):
    def canvas(self, size=(600, 300)):
        result = Image.new('RGB', size, 'white')
        self.addCleanup(result.close)
        return result

    def glyphs(self, image, boxes):
        draw = ImageDraw.Draw(image)
        for box in boxes:
            draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill='black')

    def test_blank_and_isolated_speckle_do_not_propose_text(self):
        image = self.canvas()
        ImageDraw.Draw(image).point([(2, 2), (200, 50), (400, 250)], fill='black')
        self.assertEqual(cc.regions(image), [])

    def test_horizontal_line_splits_words_but_keeps_line_proposal(self):
        image = self.canvas()
        self.glyphs(image, [(10, 40, 18, 60), (22, 40, 30, 60), (50, 40, 58, 60), (62, 40, 70, 60)])
        proposals = cc.regions(image)
        lines = [row for row in proposals if row['kind'] == 'line']
        words = [row for row in proposals if row['kind'] == 'word']
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(words), 2)
        self.assertEqual(lines[0]['count'], 4)
        self.assertEqual({row['line_id'] for row in proposals}, {0})
        self.assertLessEqual(lines[0]['bounds'][0], 10)
        self.assertGreaterEqual(lines[0]['bounds'][2], 70)

    def test_different_font_heights_share_a_baseline(self):
        image = self.canvas()
        self.glyphs(image, [(10, 60, 18, 80), (22, 60, 30, 80), (40, 40, 60, 80), (64, 40, 84, 80)])
        lines = [row for row in cc.regions(image) if row['kind'] == 'line']
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['count'], 4)

    def test_stacked_lines_do_not_merge(self):
        image = self.canvas()
        self.glyphs(image, [(10, 20, 18, 40), (22, 20, 30, 40), (10, 60, 18, 80), (22, 60, 30, 80)])
        lines = [row for row in cc.regions(image) if row['kind'] == 'line']
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(row['count'] == 2 for row in lines))

    def test_dot_is_retained_with_stem(self):
        image = self.canvas()
        self.glyphs(image, [(12, 20, 16, 24), (12, 28, 16, 48), (24, 28, 32, 48)])
        lines = [row for row in cc.regions(image) if row['kind'] == 'line']
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['count'], 3)
        self.assertLessEqual(lines[0]['bounds'][1], 20)

    def test_narrow_letter_survives_page_rule_and_frame_filter(self):
        image = self.canvas()
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, 597, 297), outline='black', width=1)
        draw.line((5, 270, 590, 270), fill='black', width=2)
        self.glyphs(image, [(30, 30, 32, 70), (42, 30, 52, 70)])
        result = cc.analyze(image)
        self.assertEqual(result['measurements']['discarded']['rule'], 1)
        self.assertEqual(result['measurements']['discarded']['frame'], 1)
        lines = [row for row in result['regions'] if row['kind'] == 'line']
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['count'], 2)

    def test_quarter_turn_returns_horizontal_word_candidates(self):
        image = self.canvas((300, 600))
        self.glyphs(image, [(100, 10, 130, 25), (100, 30, 130, 45), (100, 50, 130, 65)])
        rotated = image.transpose(Image.Transpose.ROTATE_90)
        self.addCleanup(rotated.close)
        lines = [row for row in cc.regions(rotated) if row['kind'] == 'line']
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['count'], 3)
        box = lines[0]['bounds']
        self.assertGreater(box[2] - box[0], box[3] - box[1])

    def test_oversized_narrow_letter_survives_non_page_spanning_filter(self):
        image = self.canvas((600, 400))
        self.glyphs(image, [(30, 30, 33, 150), (48, 30, 80, 150)])
        result = cc.analyze(image)
        self.assertEqual(result['measurements']['discarded']['rule'], 0)
        lines = [row for row in result['regions'] if row['kind'] == 'line']
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['count'], 2)

    def test_real_font_pixels_are_proposed_without_input_mutation(self):
        image = self.canvas()
        ImageDraw.Draw(image).text((20, 50), 'Plain example words', font=ImageFont.load_default(size=32), fill='black')
        before = hashlib.sha256(image.tobytes()).hexdigest()
        proposals = cc.regions(image)
        self.assertTrue(any(row['kind'] == 'line' and row['count'] > 5 for row in proposals))
        self.assertEqual(before, hashlib.sha256(image.tobytes()).hexdigest())

    def test_thumbnail_bounds_map_to_input_coordinates(self):
        image = self.canvas((3600, 2400))
        self.glyphs(image, [(1000, 500, 1020, 560), (1040, 500, 1060, 560)])
        result = cc.analyze(image)
        self.assertEqual(result['measurements']['thumbnail_size'], [1800, 1200])
        line = next(row for row in result['regions'] if row['kind'] == 'line')
        self.assertLessEqual(line['bounds'][0], 1000)
        self.assertGreaterEqual(line['bounds'][2], 1060)
        for row in result['regions']:
            x0, y0, x1, y1 = row['bounds']
            self.assertTrue(0 <= x0 < x1 <= 3600 and 0 <= y0 < y1 <= 2400)

    def test_output_proposals_are_capped(self):
        image = self.canvas((800, 1600))
        self.glyphs(image, [(10, 20 + n * 20, 20, 30 + n * 20) for n in range(70)])
        result = cc.analyze(image)
        self.assertEqual(len(result['regions']), 64)
        self.assertGreater(result['measurements']['truncated_proposals'], 0)

    def test_component_budget_refuses_untrusted_noise(self):
        image = self.canvas((1000, 1000))
        draw = ImageDraw.Draw(image)
        for y in range(0, 1000, 3):
            for x in range(0, 1000, 3):
                draw.point((x, y), fill='black')
        with self.assertRaisesRegex(cc.RegionLimit, 'component budget'):
            cc.regions(image)

    def test_run_budget_fails_closed(self):
        image = self.canvas((100, 100))
        self.glyphs(image, [(10, 10, 30, 90)])
        with patch.object(cc, 'MAX_RUNS', 10), self.assertRaisesRegex(cc.RegionLimit, 'run budget'):
            cc.regions(image)

    def test_adjacency_budget_fails_closed(self):
        image = self.canvas()
        self.glyphs(image, [(10 + n * 6, 10, 13 + n * 6, 30) for n in range(10)])
        with patch.object(cc, 'MAX_PAIRS', 2), self.assertRaisesRegex(cc.RegionLimit, 'adjacency budget'):
            cc.regions(image)

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            cc.regions(None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
