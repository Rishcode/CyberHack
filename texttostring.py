import pytesseract
from PIL import Image

def texttospeech(filename):
    img = Image.open(filename)
    text = pytesseract.image_to_string(img)
    print(text)

# Example usage:
texttospeech("test.png")