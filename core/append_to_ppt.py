import os
import sys
import tempfile
import win32com.client
import pythoncom
#pip install pywin32
# from PyQt5.QtWidgets import QApplication, QWidget
# from PyQt5.QtGui import QPixmap
import gc


def _add_slide_with_image_files(
    ppt_path,
    slide_title,
    slide_text,
    image_files,
    image_sizes,
    image_positions=None,
    comments_text="",
):
    """Append one slide using already-materialized image files.

    The caller owns the image files.  Keeping the COM work independent from
    Qt image objects lets scan finalization run outside the GUI thread.
    """
    presentation = None
    ppt_app = None
    pythoncom.CoInitialize()

    try:
        ppt_app = win32com.client.Dispatch("PowerPoint.Application")
        ppt_app.Visible = True

        if not os.path.exists(ppt_path):
            presentation = ppt_app.Presentations.Add()
            presentation.SaveAs(ppt_path)
        else:
            for pres in ppt_app.Presentations:
                if os.path.normcase(pres.FullName) == os.path.normcase(ppt_path):
                    presentation = pres
                    break
            if presentation is None:
                presentation = ppt_app.Presentations.Open(
                    ppt_path, ReadOnly=False, Untitled=False, WithWindow=True
                )

        num_slides = presentation.Slides.Count
        slide = presentation.Slides.Add(num_slides + 1, 12)
        slide_width = presentation.PageSetup.SlideWidth
        slide_height = presentation.PageSetup.SlideHeight

        title_box = slide.Shapes.AddTextbox(
            Orientation=1, Left=20, Top=10, Width=slide_width - 40, Height=24
        )
        title_box.TextFrame.TextRange.Text = slide_title
        title_box.TextFrame.TextRange.Font.Bold = True
        title_box.TextFrame.TextRange.Font.Size = 16

        meta_box = slide.Shapes.AddTextbox(
            Orientation=1, Left=20, Top=34, Width=slide_width - 40, Height=18
        )
        meta_box.TextFrame.TextRange.Text = slide_text
        meta_box.TextFrame.TextRange.Font.Size = 11

        if image_positions is None:
            margin = 20
            content_top = 60
            comments_width = max(200, slide_width * 0.28)
            image_box_width = slide_width - comments_width - (3 * margin)
            image_box_height = slide_height - content_top - margin
            image_box_left = margin
            image_box_top = content_top

            src_w = max(float(image_sizes[0][0]), 1.0)
            src_h = max(float(image_sizes[0][1]), 1.0)
            scale = min(image_box_width / src_w, image_box_height / src_h)
            draw_w = src_w * scale
            draw_h = src_h * scale
            draw_left = image_box_left + (image_box_width - draw_w) / 2
            draw_top = image_box_top + (image_box_height - draw_h) / 2

            slide.Shapes.AddPicture(
                FileName=image_files[0],
                LinkToFile=False,
                SaveWithDocument=True,
                Left=draw_left,
                Top=draw_top,
                Width=draw_w,
                Height=draw_h,
            )

            comments_left = image_box_left + image_box_width + margin
            comments_height = slide_height - content_top - margin
            comments_value = (
                comments_text.strip()
                if comments_text and comments_text.strip()
                else "No comments."
            )
            comments_box = slide.Shapes.AddTextbox(
                Orientation=1,
                Left=comments_left,
                Top=content_top,
                Width=comments_width,
                Height=comments_height,
            )
            comments_box.TextFrame.WordWrap = True
            comments_box.TextFrame.TextRange.Text = f"Comments:\n{comments_value}"
            comments_box.TextFrame.TextRange.Font.Size = 11
        else:
            for image_file, image_size, pos in zip(
                image_files, image_sizes, image_positions
            ):
                left, top, width, height = pos
                src_w = max(float(image_size[0]), 1.0)
                src_h = max(float(image_size[1]), 1.0)
                scale = min(width / src_w, height / src_h)
                draw_w = src_w * scale
                draw_h = src_h * scale
                draw_left = left + (width - draw_w) / 2
                draw_top = top + (height - draw_h) / 2
                slide.Shapes.AddPicture(
                    FileName=image_file,
                    LinkToFile=False,
                    SaveWithDocument=True,
                    Left=draw_left,
                    Top=draw_top,
                    Width=draw_w,
                    Height=draw_h,
                )
            if comments_text and comments_text.strip():
                comments_box = slide.Shapes.AddTextbox(
                    Orientation=1,
                    Left=20,
                    Top=slide_height - 70,
                    Width=slide_width - 40,
                    Height=50,
                )
                comments_box.TextFrame.WordWrap = True
                comments_box.TextFrame.TextRange.Text = (
                    f"Comments: {comments_text.strip()}"
                )
                comments_box.TextFrame.TextRange.Font.Size = 11

        presentation.Save()
    finally:
        if presentation is not None:
            del presentation
        if ppt_app is not None:
            del ppt_app
        gc.collect()
        pythoncom.CoUninitialize()


def add_slide_with_png_bytes(
    ppt_path,
    slide_title,
    slide_text,
    png_images,
    image_sizes,
    image_positions=None,
    comments_text="",
):
    """Append a slide from immutable PNG payloads in a worker thread."""
    if not png_images:
        raise ValueError("At least one PNG image must be provided.")
    if len(png_images) != len(image_sizes):
        raise ValueError("image_sizes must match png_images length.")
    if image_positions is None and len(png_images) != 1:
        raise ValueError("When image_positions is omitted, provide exactly one image.")
    if image_positions is not None and len(image_positions) != len(png_images):
        raise ValueError("image_positions must match png_images length.")

    temp_files = []
    try:
        for index, image in enumerate(png_images):
            handle = tempfile.NamedTemporaryFile(
                prefix=f"zmeter_scan_{os.getpid()}_{index}_",
                suffix=".png",
                delete=False,
            )
            try:
                handle.write(bytes(image))
            finally:
                handle.close()
            temp_files.append(handle.name)

        _add_slide_with_image_files(
            ppt_path,
            slide_title,
            slide_text,
            temp_files,
            image_sizes,
            image_positions=image_positions,
            comments_text=comments_text,
        )
    finally:
        for temp_path in temp_files:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def add_slide_with_qpixmap(
    ppt_path,
    slide_title,
    slide_text,
    pixmap_images,
    image_positions=None,
    comments_text="",
):
    if not pixmap_images:
        raise ValueError("At least one QPixmap object must be provided.")
    if image_positions is None and len(pixmap_images) != 1:
        raise ValueError("When image_positions is omitted, provide exactly one QPixmap.")
    if image_positions is not None and len(image_positions) != len(pixmap_images):
        raise ValueError("image_positions must match pixmap_images length.")

    temp_files = []
    try:
        # Convert QPixmap objects to temporary image files
        for i, pixmap in enumerate(pixmap_images):
            temp_path = os.path.join(tempfile.gettempdir(), f"temp_image_{os.getpid()}_{i}.png")
            if not pixmap.save(temp_path, "PNG"):
                raise RuntimeError("Failed to convert QPixmap to PNG before adding to slide.")
            temp_files.append(temp_path)

        _add_slide_with_image_files(
            ppt_path,
            slide_title,
            slide_text,
            temp_files,
            tuple((pixmap.width(), pixmap.height()) for pixmap in pixmap_images),
            image_positions=image_positions,
            comments_text=comments_text,
        )
    finally:
        for temp_path in temp_files:
            try:
                os.remove(temp_path)
            except OSError:
                pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = QWidget()
    widget.resize(300, 200)
    widget.show()
    app.processEvents()

    # Grab images from the widget
    image1 = widget.grab()
    image2 = widget.grab()
    image3 = widget.grab()

    ppt_file = r"C:\Users\moham\OneDrive\Documents\test_presentation.pptx"
    title = "Slide with QPixmap Images"
    text = "This slide contains three images grabbed from PyQt widgets."

    add_slide_with_qpixmap(
        ppt_file,
        title,
        text,
        [image1, image2, image3],
        image_positions=[(20, 90, 320, 220), (360, 90, 320, 220), (20, 330, 320, 180)],
    )
    
    # Do not call app.exec_() to avoid blocking; close the application instead.
    widget.close()
    app.exit()
