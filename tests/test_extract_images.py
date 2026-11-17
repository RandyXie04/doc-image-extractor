# -*- coding: utf-8 -*-
"""
測試文件圖片提取與灰階轉換功能 (DOCX / PDF)
- 驗證 Word (.docx) 刪除圖片後不會被重複提取
- 驗證含 Alpha 透明通道圖片轉灰階時不會填充黑底
- 驗證 PDF 圖片提取及灰階轉換
"""

import io
import os
import shutil
import tempfile
import unittest
import zipfile
from PIL import Image

import docx
import fitz

from src.scripts.extract_images import (
    IMAGE_EXTENSIONS,
    extract_from_docx,
    extract_from_pdf,
    extract_from_pdf_with_manifest,
    convert_to_grayscale_helper,
    process_document_images,
)


class TestExtractImages(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_extract_img_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_docx_deleted_image_not_extracted(self):
        """測試 Word 中已被刪除的圖片不會被提取"""
        # 1. 建立兩張測試圖片
        img1_path = os.path.join(self.test_dir, "img1.png")
        img2_path = os.path.join(self.test_dir, "img2.png")
        Image.new("RGB", (20, 20), (255, 0, 0)).save(img1_path)
        Image.new("RGB", (20, 20), (0, 255, 0)).save(img2_path)

        # 2. 建立含有兩張圖的 Word 文件
        two_img_docx = os.path.join(self.test_dir, "two.docx")
        doc = docx.Document()
        doc.add_paragraph("Img1").add_run().add_picture(img1_path)
        doc.add_paragraph("Img2").add_run().add_picture(img2_path)
        doc.save(two_img_docx)

        # 3. 模擬使用者在 Word 刪除 Img2，Word ZIP 內部 media/image2.png 仍殘留，但 document.xml 移除
        deleted_docx = os.path.join(self.test_dir, "deleted.docx")
        with zipfile.ZipFile(two_img_docx, "r") as z_in:
            doc_xml = z_in.read("word/document.xml").decode("utf-8")
            p2_start = doc_xml.find("<w:p><w:r><w:t>Img2")
            p2_end = doc_xml.find("</w:p><w:sectPr") + len("</w:p>")
            doc_xml_modified = doc_xml[:p2_start] + doc_xml[p2_end:]

            with zipfile.ZipFile(deleted_docx, "w") as z_out:
                for item in z_in.infolist():
                    if item.filename == "word/document.xml":
                        z_out.writestr(item, doc_xml_modified.encode("utf-8"))
                    else:
                        z_out.writestr(item, z_in.read(item.filename))

        # 4. 驗證提取時只提取 active 的圖片 (只有 1 張，不含被刪除的 img2)
        out_dir = os.path.join(self.test_dir, "out_deleted")
        count = extract_from_docx(deleted_docx, out_dir)
        self.assertEqual(count, 1)
        files = os.listdir(out_dir)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0], "image_0001.png")

    def test_docx_transparent_png_grayscale_preserves_alpha(self):
        """測試含 Alpha 透明通道的 PNG 轉灰階時保留透明度，透明處不轉黑"""
        trans_png_path = os.path.join(self.test_dir, "trans.png")
        t_img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))  # 全透明黑底
        t_img.putpixel((10, 10), (255, 0, 0, 255))          # 中央紅色不透明點
        t_img.save(trans_png_path)

        doc_path = os.path.join(self.test_dir, "trans_doc.docx")
        doc = docx.Document()
        doc.add_paragraph().add_run().add_picture(trans_png_path)
        doc.save(doc_path)

        out_dir = os.path.join(self.test_dir, "out_gray")
        count = extract_from_docx(doc_path, out_dir, to_grayscale=True)
        self.assertEqual(count, 1)

        result_path = os.path.join(out_dir, "image_0001.png")
        res = Image.open(result_path)

        # 模式應為 LA (灰階 + Alpha)
        self.assertEqual(res.mode, "LA")
        # 透明像素 (0,0) 的 Alpha 應為 0 (保持透明)，且亮度為 255 (白底防護，不填充黑)
        l_val, a_val = res.getpixel((0, 0))
        self.assertEqual(a_val, 0)
        self.assertEqual(l_val, 255)
        # 內容像素 (10,10) 應為不透明且轉為灰階
        l_dot, a_dot = res.getpixel((10, 10))
        self.assertEqual(a_dot, 255)
        self.assertEqual(l_dot, 76)  # 255*0.299 ≈ 76

    def test_pdf_transparent_png_grayscale(self):
        """測試 PDF 提取透明圖片轉灰階保留透明度"""
        trans_png_path = os.path.join(self.test_dir, "pdf_trans.png")
        t_img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
        t_img.putpixel((30, 30), (0, 255, 0, 255))
        t_img.save(trans_png_path)

        pdf_path = os.path.join(self.test_dir, "test.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_image(fitz.Rect(50, 50, 150, 150), filename=trans_png_path)
        doc.save(pdf_path)
        doc.close()

        out_dir = os.path.join(self.test_dir, "out_pdf_gray")
        count = extract_from_pdf(pdf_path, out_dir, to_grayscale=True)
        self.assertEqual(count, 1)

        files = os.listdir(out_dir)
        self.assertEqual(len(files), 1)
        res = Image.open(os.path.join(out_dir, files[0]))
        self.assertEqual(res.mode, "LA")
        l_bg, a_bg = res.getpixel((0, 0))
        self.assertEqual(a_bg, 0)
        self.assertEqual(l_bg, 255)

    def test_grayscale_helper_unsupported_alpha_format(self):
        """測試轉為不支援透明度的格式 (如 JPG) 時，透明處合成白底而非黑底"""
        t_img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        t_img.putpixel((5, 5), (0, 0, 255, 255))
        res = convert_to_grayscale_helper(t_img, ".jpg")
        self.assertEqual(res.mode, "L")
        # 透明處合成到白底後亮度應為 255
        self.assertEqual(res.getpixel((0, 0)), 255)
        # 藍色處轉灰階亮度應為 29 (255*0.114)
        self.assertEqual(res.getpixel((5, 5)), 29)

    def test_docx_duplicate_image_references_all_extracted(self):
        """測試 Word 中同一圖檔於不同位置被多次引用時，預設全部提取每一張"""
        img_path = os.path.join(self.test_dir, "shared.png")
        Image.new("RGB", (20, 20), (120, 180, 240)).save(img_path)

        doc_path = os.path.join(self.test_dir, "multi_ref.docx")
        doc = docx.Document()
        doc.add_paragraph("Paragraph 1").add_run().add_picture(img_path)
        doc.add_paragraph("Paragraph 2 without image")
        doc.add_paragraph("Paragraph 3").add_run().add_picture(img_path)
        doc.save(doc_path)

        # 1. 預設模式 (every_occurrence) 應提取 2 張圖
        out_every = os.path.join(self.test_dir, "out_every")
        count_every = extract_from_docx(doc_path, out_every)
        self.assertEqual(count_every, 2)
        files_every = sorted(os.listdir(out_every))
        self.assertEqual(files_every, ["image_0001.png", "image_0002.png"])

        # 2. 指定 unique 模式時僅提取 1 張圖
        out_unique = os.path.join(self.test_dir, "out_unique")
        count_unique = extract_from_docx(doc_path, out_unique, duplicate_policy="unique")
        self.assertEqual(count_unique, 1)
        files_unique = sorted(os.listdir(out_unique))
        self.assertEqual(files_unique, ["image_0001.png"])

    def test_docx_alternate_content_fallback_not_double_counted(self):
        """測試 Word 的 AlternateContent (Choice + Fallback) 不會被誤判為重複引用兩次"""
        img_path = os.path.join(self.test_dir, "single.png")
        Image.new("RGB", (20, 20), (200, 50, 50)).save(img_path)

        base_docx = os.path.join(self.test_dir, "base.docx")
        doc = docx.Document()
        doc.add_paragraph("Img").add_run().add_picture(img_path)
        doc.save(base_docx)

        # 將 drawing 封裝入 AlternateContent (含 Choice 與 Fallback)
        ac_docx = os.path.join(self.test_dir, "ac.docx")
        with zipfile.ZipFile(base_docx, "r") as z_in:
            doc_xml = z_in.read("word/document.xml").decode("utf-8")
            draw_start = doc_xml.find("<w:drawing>")
            draw_end = doc_xml.find("</w:drawing>") + len("</w:drawing>")
            drawing_xml = doc_xml[draw_start:draw_end]

            ac_xml = (
                f'<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
                f'<mc:Choice Requires="wps">{drawing_xml}</mc:Choice>'
                f'<mc:Fallback>{drawing_xml}</mc:Fallback>'
                f'</mc:AlternateContent>'
            )
            doc_xml_modified = doc_xml[:draw_start] + ac_xml + doc_xml[draw_end:]

            with zipfile.ZipFile(ac_docx, "w") as z_out:
                for item in z_in.infolist():
                    if item.filename == "word/document.xml":
                        z_out.writestr(item, doc_xml_modified.encode("utf-8"))
                    else:
                        z_out.writestr(item, z_in.read(item.filename))

        out_ac = os.path.join(self.test_dir, "out_ac")
        count = extract_from_docx(ac_docx, out_ac)
        # 即使含 Choice 與 Fallback，單一圖片應仍只提取 1 張，不可誤計為 2 張
        self.assertEqual(count, 1)
        self.assertEqual(os.listdir(out_ac), ["image_0001.png"])

    def test_docx_process_document_images_pipeline(self):
        """測試 process_document_images 整合流程自動打包多引用圖片"""
        img_path = os.path.join(self.test_dir, "pipeline_img.png")
        Image.new("RGB", (20, 20), (0, 100, 200)).save(img_path)

        doc_path = os.path.join(self.test_dir, "pipeline_doc.docx")
        doc = docx.Document()
        doc.add_paragraph("P1").add_run().add_picture(img_path)
        doc.add_paragraph("P2").add_run().add_picture(img_path)
        doc.save(doc_path)

        zip_out = os.path.join(self.test_dir, "result.zip")
        temp_extract = os.path.join(self.test_dir, "temp_extract")
        count, out_zip = process_document_images(doc_path, zip_out, temp_extract)
        self.assertEqual(count, 2)
        self.assertTrue(os.path.exists(out_zip))

        with zipfile.ZipFile(out_zip, "r") as z:
            extracted_names = sorted(z.namelist())
            self.assertEqual(extracted_names, ["image_0001.png", "image_0002.png"])

    def test_docx_vml_bmp_and_dib_normalization(self):
        """測試 VML v:imagedata .bmp 與 .dib (含檔頭及無檔頭) 正規化輸出為 .bmp"""
        self.assertIn(".dib", IMAGE_EXTENSIONS)

        bmp_buf = io.BytesIO()
        Image.new("RGB", (24, 24), (10, 120, 230)).save(bmp_buf, format="BMP")
        bmp_bytes = bmp_buf.getvalue()

        headered_dib_bytes = bmp_bytes
        raw_dib_bytes = bmp_bytes[14:]  # 剝除 BITMAPFILEHEADER 的純 DIB

        docx_path = os.path.join(self.test_dir, "vml_dib.docx")
        with zipfile.ZipFile(docx_path, "w") as z:
            z.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
            )
            z.writestr(
                "word/drawings/vmlDrawing1.vml",
                '<xml xmlns:v="urn:schemas-microsoft-com:vml" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<v:shape id="s1"><v:imagedata r:id="rId1"/></v:shape>'
                '<v:shape id="s2"><v:imagedata r:id="rId2"/></v:shape>'
                '<v:shape id="s3"><v:imagedata r:id="rId3"/></v:shape>'
                "</xml>",
            )
            z.writestr(
                "word/drawings/_rels/vmlDrawing1.vml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/pic1.bmp"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/pic2.dib"/>'
                '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/pic3.dib"/>'
                "</Relationships>",
            )
            z.writestr("word/media/pic1.bmp", bmp_bytes)
            z.writestr("word/media/pic2.dib", headered_dib_bytes)
            z.writestr("word/media/pic3.dib", raw_dib_bytes)

        out_dir = os.path.join(self.test_dir, "out_vml_dib")
        count = extract_from_docx(docx_path, out_dir)
        self.assertEqual(count, 3)
        files = sorted(os.listdir(out_dir))
        self.assertEqual(files, ["image_0001.bmp", "image_0002.bmp", "image_0003.bmp"])
        for fname in files:
            with Image.open(os.path.join(out_dir, fname)) as im:
                self.assertEqual(im.format, "BMP")
                self.assertEqual(im.size, (24, 24))

        out_gray = os.path.join(self.test_dir, "out_vml_dib_gray")
        count_gray = extract_from_docx(docx_path, out_gray, to_grayscale=True)
        self.assertEqual(count_gray, 3)
        for fname in sorted(os.listdir(out_gray)):
            with Image.open(os.path.join(out_gray, fname)) as im:
                self.assertEqual(im.format, "BMP")
                self.assertEqual(im.mode, "L")

    def test_docx_rels_normalization_strict_ooxml_and_fallback(self):
        """測試 .rels 反斜線、大小寫、word/media 相對路徑、Strict OOXML 及 parsed_any_xml=True 時的備用回退"""
        bmp_buf = io.BytesIO()
        Image.new("RGB", (18, 18), (50, 60, 70)).save(bmp_buf, format="BMP")
        bmp_bytes = bmp_buf.getvalue()

        # 1. Strict OOXML + 反斜線 + 大小寫不一致 + word/media/ 無前導斜線
        docx_norm = os.path.join(self.test_dir, "rels_norm.docx")
        with zipfile.ZipFile(docx_norm, "w") as z:
            z.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/main" '
                'xmlns:r="http://purl.oclc.org/ooxml/officeDocument/relationships">'
                '<w:body><w:p><w:r><w:pict r:id="rId1"/><w:pict r:id="rId2"/></w:r></w:p></w:body>'
                "</w:document>",
            )
            z.writestr(
                "word/_rels/document.xml.rels",
                '<Relationships xmlns="http://purl.oclc.org/ooxml/officeDocument/relationships">'
                '<Relationship Id="rId1" Target="MEDIA\\Image%20One.BMP"/>'
                '<Relationship Id="rId2" Target="word/media/ImageTwo.BMP"/>'
                "</Relationships>",
            )
            z.writestr("word/media/image one.bmp", bmp_bytes)
            z.writestr("word/media/imagetwo.bmp", bmp_bytes)

        out_norm = os.path.join(self.test_dir, "out_norm")
        self.assertEqual(extract_from_docx(docx_norm, out_norm), 2)
        self.assertEqual(sorted(os.listdir(out_norm)), ["image_0001.bmp", "image_0002.bmp"])

        # 2. parsed_any_xml=True 但 active_images 為空時，仍應回退掃描 word/media/
        docx_fallback = os.path.join(self.test_dir, "fallback.docx")
        with zipfile.ZipFile(docx_fallback, "w") as z:
            z.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>No image ref in XML</w:t></w:r></w:p></w:body>"
                "</w:document>",
            )
            z.writestr("word/media/orphan.bmp", bmp_bytes)
            z.writestr("word/media/not_image.txt", b"ignored")

        out_fb = os.path.join(self.test_dir, "out_fb")
        self.assertEqual(extract_from_docx(docx_fallback, out_fb), 1)
        self.assertEqual(os.listdir(out_fb), ["image_0001.bmp"])

    def test_docx_alternate_content_non_raster_choice_keeps_bmp_fallback(self):
        """測試 AlternateContent 的 Choice 不含圖片關聯時保留 Fallback 內的 BMP"""
        bmp_buf = io.BytesIO()
        Image.new("RGB", (20, 20), (15, 180, 90)).save(bmp_buf, format="BMP")

        docx_path = os.path.join(self.test_dir, "ac_non_raster.docx")
        with zipfile.ZipFile(docx_path, "w") as z:
            z.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                'xmlns:v="urn:schemas-microsoft-com:vml" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                "<w:body><w:p><w:r>"
                "<mc:AlternateContent>"
                '<mc:Choice Requires="wps"><w:drawing><w:t>Vector shape only</w:t></w:drawing></mc:Choice>'
                '<mc:Fallback><w:pict><v:shape><v:imagedata r:id="rId1"/></v:shape></w:pict></mc:Fallback>'
                "</mc:AlternateContent>"
                "</w:r></w:p></w:body></w:document>",
            )
            z.writestr(
                "word/_rels/document.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="media/fallback.bmp"/>'
                "</Relationships>",
            )
            z.writestr("word/media/fallback.bmp", bmp_buf.getvalue())

        out_dir = os.path.join(self.test_dir, "out_ac_bmp")
        count = extract_from_docx(docx_path, out_dir)
        self.assertEqual(count, 1)
        self.assertEqual(os.listdir(out_dir), ["image_0001.bmp"])

    def test_docx_existing_slot_advances_without_inflating_count(self):
        """測試目標目錄已有 image_0001.png 時自動遞增槽位且回傳實際提取數"""
        img_path = os.path.join(self.test_dir, "s.png")
        Image.new("RGB", (20, 20), (1, 2, 3)).save(img_path)

        doc_path = os.path.join(self.test_dir, "slot.docx")
        doc = docx.Document()
        doc.add_paragraph().add_run().add_picture(img_path)
        doc.save(doc_path)

        out_dir = os.path.join(self.test_dir, "out_slot")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "image_0001.png"), "wb") as f:
            f.write(b"existing")

        count = extract_from_docx(doc_path, out_dir)
        self.assertEqual(count, 1)
        self.assertEqual(sorted(os.listdir(out_dir)), ["image_0001.png", "image_0002.png"])

    def test_pdf_devicegray_la_and_inverted_decode(self):
        """測試 PDF DeviceGray (n=1)、DeviceGray+SMask (LA, n=2) 與反轉 Decode 圖片在灰階與彩色模式均不崩潰"""
        pdf_path = os.path.join(self.test_dir, "gray_la.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=500)

        pix_gray = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 24, 24), False)
        pix_gray.set_rect(pix_gray.irect, (120,))
        page.insert_image(fitz.Rect(20, 20, 80, 80), pixmap=pix_gray)

        pix_la = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 24, 24), True)
        pix_la.set_rect(pix_la.irect, (80, 200))
        page.insert_image(fitz.Rect(20, 120, 80, 180), pixmap=pix_la)

        pix_inv = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 24, 24), False)
        pix_inv.set_rect(pix_inv.irect, (0,))
        page.insert_image(fitz.Rect(20, 220, 80, 280), pixmap=pix_inv)

        imgs = page.get_images(full=True)
        doc.xref_set_key(imgs[0][0], "ColorSpace", "/DeviceGray")
        doc.xref_set_key(imgs[1][0], "ColorSpace", "/DeviceGray")
        doc.xref_set_key(imgs[2][0], "ColorSpace", "/DeviceGray")
        doc.xref_set_key(imgs[2][0], "Decode", "[1 0]")
        doc.save(pdf_path)
        doc.close()

        for gray_flag, subdir in [(False, "out_pdf_color"), (True, "out_pdf_gray")]:
            out_dir = os.path.join(self.test_dir, subdir)
            count = extract_from_pdf(pdf_path, out_dir, to_grayscale=gray_flag)
            self.assertEqual(count, 3)
            files = sorted(os.listdir(out_dir))
            self.assertEqual(
                files,
                ["image_p0001_001.png", "image_p0001_002.png", "image_p0001_003.tif"],
            )
            with Image.open(os.path.join(out_dir, "image_p0001_001.png")) as im1:
                self.assertEqual(im1.mode, "L")
            with Image.open(os.path.join(out_dir, "image_p0001_002.png")) as im2:
                self.assertEqual(im2.mode, "LA")
            with Image.open(os.path.join(out_dir, "image_p0001_003.tif")) as im3:
                self.assertEqual(im3.mode, "L")

    def test_pdf_small_16x16_threshold(self):
        """測試預設 min_width=16, min_height=16 可提取 16x16 小圖並過濾 15x15"""
        img16 = os.path.join(self.test_dir, "img16.png")
        img15 = os.path.join(self.test_dir, "img15.png")
        Image.new("RGB", (16, 16), (255, 0, 0)).save(img16)
        Image.new("RGB", (15, 15), (0, 255, 0)).save(img15)

        pdf_path = os.path.join(self.test_dir, "small.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_image(fitz.Rect(20, 20, 40, 40), filename=img15)
        page.insert_image(fitz.Rect(60, 20, 80, 40), filename=img16)
        doc.save(pdf_path)
        doc.close()

        out_dir = os.path.join(self.test_dir, "out_small")
        count = extract_from_pdf(pdf_path, out_dir)
        self.assertEqual(count, 1)
        self.assertEqual(os.listdir(out_dir), ["image_p0001_001.png"])

    def test_pdf_duplicate_xref_reading_order_and_manifest(self):
        """測試同頁重複 xref 不覆寫、依閱讀順序 (y0, x0) 排序，並驗證 manifest 結構"""
        img_dup = os.path.join(self.test_dir, "dup.png")
        img_mid = os.path.join(self.test_dir, "mid.png")
        Image.new("RGB", (24, 24), (200, 10, 10)).save(img_dup)
        Image.new("RGB", (24, 24), (10, 200, 10)).save(img_mid)

        pdf_path = os.path.join(self.test_dir, "order.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        # 故意先插入下方 (y0=300)，再插中間 (y0=200)，最後插上方重複圖 (y0=100)
        page.insert_image(fitz.Rect(50, 300, 100, 350), filename=img_dup)
        page.insert_image(fitz.Rect(50, 200, 100, 250), filename=img_mid)
        page.insert_image(fitz.Rect(50, 100, 100, 150), filename=img_dup)
        doc.save(pdf_path)
        doc.close()

        out_every = os.path.join(self.test_dir, "out_order_every")
        count, manifest = extract_from_pdf_with_manifest(pdf_path, out_every)
        self.assertEqual(count, 3)
        self.assertEqual(len(manifest), 3)
        self.assertEqual(
            sorted(os.listdir(out_every)),
            ["image_p0001_001.png", "image_p0001_002.png", "image_p0001_003.png"],
        )

        # 驗證閱讀順序 (y0: 100 -> 200 -> 300) 與 manifest 欄位
        self.assertEqual([m["seq"] for m in manifest], [1, 2, 3])
        self.assertTrue(all(m["page_num"] == 1 for m in manifest))
        self.assertTrue(all(os.path.isfile(m["path"]) for m in manifest))
        y0s = [m["bbox"][1] for m in manifest]
        self.assertEqual(y0s, [100.0, 200.0, 300.0])

        # 頂部/底部為紅色 dup，中間為綠色 mid
        with Image.open(manifest[0]["path"]) as im_top:
            self.assertEqual(im_top.convert("RGB").getpixel((12, 12)), (200, 10, 10))
        with Image.open(manifest[1]["path"]) as im_mid:
            self.assertEqual(im_mid.convert("RGB").getpixel((12, 12)), (10, 200, 10))
        with Image.open(manifest[2]["path"]) as im_bot:
            self.assertEqual(im_bot.convert("RGB").getpixel((12, 12)), (200, 10, 10))

        # unique 模式應只保留 2 張不重複 xref
        out_unique = os.path.join(self.test_dir, "out_order_unique")
        count_u, manifest_u = extract_from_pdf_with_manifest(pdf_path, out_unique, duplicate_policy="unique")
        self.assertEqual(count_u, 2)
        self.assertEqual(len(manifest_u), 2)
        self.assertEqual(sorted(os.listdir(out_unique)), ["image_p0001_001.png", "image_p0001_002.png"])


if __name__ == "__main__":
    unittest.main()
