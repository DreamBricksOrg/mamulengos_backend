import io
import qrcode
import structlog

from fastapi import HTTPException


log = structlog.get_logger()

def generate_qr_code(data: str) -> io.BytesIO:
    """
    Gera um QR code a partir do texto/URL recebido e retorna um BytesIO com o PNG resultante.

    :param data: Texto ou URL que será codificado no QR code.
    :return: BytesIO contendo a imagem PNG do QR code.
    :raises HTTPException: Se ocorrer erro ao gerar o QR code.
    """
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        # Ajusta pixels brancos para tons personalizados, se desejado
        pixels = img.load()
        width, height = img.size
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == (255, 255, 255):
                    pixels[x, y] = (227, 217, 185)

        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)
        return img_bytes

    except Exception as e:
        log.info("Erro ao gerar QR code", error=str(e), data=data)
        raise HTTPException(status_code=500, detail="Falha ao gerar QR code")
