# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

from src.scripts.md_to_docx import rewrite_markdown_image_paths
from src.scripts.pdf_image_extractor import extract_pdf_images


class TestImageUnification(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_img_unify_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_sample_png(self, name: str, size=(60, 60), color=(255, 0, 0)) -> str:
        path = os.path.join(self.temp_dir, name)
        Image.new("RGB", size, color).save(path)
        return path

    def test_sparse_block_idx_produces_contiguous_reading_order_names(self):
        """Sparse block_idx (e.g. 5 then 0, or reversed reading order) yields contiguous image_p0001_001..002."""
        pdf_path = os.path.join(self.temp_dir, "two_imgs.pdf")
        out_dir = os.path.join(self.temp_dir, "out")

        img_top = self._make_sample_png("top.png", color=(255, 0, 0))
        img_bot = self._make_sample_png("bot.png", color=(0, 0, 255))

        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.insert_image(fitz.Rect(50, 50, 150, 150), filename=img_top)
        page.insert_image(fitz.Rect(50, 300, 150, 400), filename=img_bot)
        doc.save(pdf_path)
        doc.close()

        # Pass blocks in reverse vertical order with sparse Surya-like block_idx (0 at bottom, 5 at top)
        image_blocks = [
            {
                "page_num": 1,
                "block_idx": 0,
                "bbox": [50, 300, 150, 400],
                "page_w": 400.0,
                "page_h": 600.0,
            },
            {
                "page_num": 1,
                "block_idx": 5,
                "bbox": [50, 50, 150, 150],
                "page_w": 400.0,
                "page_h": 600.0,
            },
        ]

        results = extract_pdf_images(pdf_path, image_blocks, out_dir)

        # Returned dict still keyed by original (page_num, block_idx)
        self.assertIn((1, 5), results)
        self.assertIn((1, 0), results)

        # Top block (block_idx=5, y=50) must get seq=001; bottom block (block_idx=0, y=300) gets seq=002
        self.assertEqual(os.path.basename(results[(1, 5)]), "image_p0001_001.png")
        self.assertEqual(os.path.basename(results[(1, 0)]), "image_p0001_002.png")
        self.assertEqual(
            sorted(os.listdir(out_dir)),
            ["image_p0001_001.png", "image_p0001_002.png"],
        )

    def test_vector_only_pdf_runs_300dpi_fallback_even_when_extracted_count_zero(self):
        """Vector-only PDF (extracted_count == 0) must still run Phase B 300 DPI fallback."""
        pdf_path = os.path.join(self.temp_dir, "vector_only.pdf")
        out_dir = os.path.join(self.temp_dir, "out_vec")

        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.draw_rect(fitz.Rect(60, 100, 260, 250), color=(0, 0, 0), fill=(0.2, 0.5, 0.8), width=2)
        doc.save(pdf_path)
        doc.close()

        image_blocks = [
            {
                "page_num": 1,
                "block_idx": 7,
                "bbox": [60, 100, 260, 250],
                "page_w": 400.0,
                "page_h": 600.0,
            }
        ]

        fake_mod = types.SimpleNamespace(
            extract_from_pdf_with_manifest=lambda *args, **kwargs: (0, [])
        )
        with patch("src.scripts.pdf_image_extractor._import_extract_images_module", return_value=fake_mod):
            results = extract_pdf_images(pdf_path, image_blocks, out_dir)

        self.assertIn((1, 7), results)
        dst = results[(1, 7)]
        self.assertEqual(os.path.basename(dst), "image_p0001_001.png")
        self.assertTrue(os.path.exists(dst))

        with Image.open(dst) as im:
            # 200pt x 150pt at 300 DPI -> ~833 x 625 px (well above 72 DPI)
            self.assertGreater(im.width, 700)
            self.assertGreater(im.height, 500)

    def test_manifest_decoupling_ignores_filename_xref_regex(self):
        """extract_pdf_images resolves xrefs from manifest even when temp filenames lack 'xref'."""
        pdf_path = os.path.join(self.temp_dir, "manifest_decouple.pdf")
        out_dir = os.path.join(self.temp_dir, "out_manifest")

        src_img = self._make_sample_png("source.png", size=(80, 80), color=(10, 200, 50))
        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.insert_image(fitz.Rect(40, 80, 160, 200), filename=src_img)
        xref = page.get_images(full=True)[0][0]
        doc.save(pdf_path)
        doc.close()

        def fake_extract_with_manifest(pdf_p, tmp_out, **kwargs):
            # Filename has NO xref token at all; only manifest carries (page_num, xref, path)
            opaque_path = os.path.join(tmp_out, "opaque_blob_001.png")
            shutil.copy2(src_img, opaque_path)
            manifest = [
                {
                    "page_num": 1,
                    "seq": 1,
                    "xref": xref,
                    "bbox": (40.0, 80.0, 160.0, 200.0),
                    "path": opaque_path,
                }
            ]
            return 1, manifest

        fake_mod = types.SimpleNamespace(
            extract_from_pdf_with_manifest=fake_extract_with_manifest
        )
        image_blocks = [
            {
                "page_num": 1,
                "block_idx": 3,
                "bbox": [40, 80, 160, 200],
                "page_w": 400.0,
                "page_h": 600.0,
            }
        ]

        with patch("src.scripts.pdf_image_extractor._import_extract_images_module", return_value=fake_mod):
            results = extract_pdf_images(pdf_path, image_blocks, out_dir)

        self.assertIn((1, 3), results)
        self.assertEqual(os.path.basename(results[(1, 3)]), "image_p0001_001.png")
        with Image.open(results[(1, 3)]) as im:
            self.assertEqual(im.size, (80, 80))

    def test_md_to_docx_clears_internal_image_alt_text(self):
        """md_to_docx clears image_/page_ prefixes and all supported image extension alt texts."""
        images_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        md = "\n".join(
            [
                "![image_p0001_001.bmp](images/image_p0001_001.bmp)",
                "![image_p0001_001.tif](images/image_p0001_001.tif)",
                "![image_0001.bmp](images/image_0001.bmp)",
                "![page_0002_001.png](images/image_p0002_001.png)",
                "![scan_raw.dib](images/scan_raw.dib)",
                "![diagram.tiff](images/diagram.tiff)",
                "![anim.gif](images/anim.gif)",
                "![圖1 實驗結果](images/image_p0001_001.png){width=80%}",
            ]
        )

        rewritten = rewrite_markdown_image_paths(md, md_base_dir=self.temp_dir, default_img_width="80%")
        lines = rewritten.splitlines()

        self.assertEqual(lines[0], "![](images/image_p0001_001.bmp){width=80%}")
        self.assertEqual(lines[1], "![](images/image_p0001_001.tif){width=80%}")
        self.assertEqual(lines[2], "![](images/image_0001.bmp){width=80%}")
        self.assertEqual(lines[3], "![](images/image_p0002_001.png){width=80%}")
        self.assertEqual(lines[4], "![](images/scan_raw.dib){width=80%}")
        self.assertEqual(lines[5], "![](images/diagram.tiff){width=80%}")
        self.assertEqual(lines[6], "![](images/anim.gif){width=80%}")
        self.assertEqual(lines[7], "![圖1 實驗結果](images/image_p0001_001.png){width=80%}")


if __name__ == "__main__":
    unittest.main()
