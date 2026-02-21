import os
import sys
import tempfile
import win32com.client
#pip install pywin32
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QPixmap
import gc

def add_slide_with_qpixmap(ppt_path, slide_title, slide_text, pixmap_images, image_positions):
    if len(pixmap_images) != 3:
        raise ValueError("Exactly three QPixmap objects must be provided.")

    # Convert QPixmap objects to temporary image files
    temp_files = []
    for i, pixmap in enumerate(pixmap_images):
        temp_path = os.path.join(tempfile.gettempdir(), f"temp_image_{i}.png")
        pixmap.save(temp_path, "PNG")
        temp_files.append(temp_path)

    # Connect to PowerPoint application
    ppt_app = win32com.client.Dispatch("PowerPoint.Application")
    ppt_app.Visible = True

    # Open or create the presentation
    if not os.path.exists(ppt_path):
        presentation = ppt_app.Presentations.Add()
        presentation.SaveAs(ppt_path)
    else:
        presentation = None
        for pres in ppt_app.Presentations:
            if os.path.normcase(pres.FullName) == os.path.normcase(ppt_path):
                presentation = pres
                break
        if presentation is None:
            presentation = ppt_app.Presentations.Open(ppt_path, ReadOnly=False, Untitled=False, WithWindow=True)

    # Add a new blank slide (layout index may vary; here 12 is assumed to be blank)
    num_slides = presentation.Slides.Count
    blank_layout = 12
    slide = presentation.Slides.Add(num_slides + 1, blank_layout)

    # Add title and text boxes
    title_box = slide.Shapes.AddTextbox(Orientation=1, Left=50, Top=15, Width=600, Height=50)
    title_box.TextFrame.TextRange.Text = slide_title
    text_box = slide.Shapes.AddTextbox(Orientation=1, Left=50, Top=40, Width=600, Height=100)
    text_box.TextFrame.TextRange.Text = slide_text
    

    for temp_path, pos in zip(temp_files, image_positions):
        left, top, width, height = pos
        slide.Shapes.AddPicture(FileName=temp_path,
                                  LinkToFile=False,
                                  SaveWithDocument=True,
                                  Left=left,
                                  Top=top,
                                  Width=width,
                                  Height=height)

    presentation.Save()

    # Clean up COM objects
    del presentation, ppt_app
    gc.collect()

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

    add_slide_with_qpixmap(ppt_file, title, text, [image1, image2, image3])
    
    # Do not call app.exec_() to avoid blocking; close the application instead.
    widget.close()
    app.exit()
