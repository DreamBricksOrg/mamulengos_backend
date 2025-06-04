import qrcode
import io

def generate_qr_code(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white").convert('RGB')

    pixels = img.load()
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            if pixels[x, y] == (255, 255, 255):
                pixels[x, y] = (227, 217, 185)

    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    return img_bytes
