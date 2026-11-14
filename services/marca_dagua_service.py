import asyncio
import io
import logging
import os

from PIL import Image, ImageOps

logger = logging.getLogger("BOOSTio.marca_dagua")

ICONE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "boostio_icone.png"
)


class MarcaDaguaService:
    """
    Aplica o ícone da BOOSTio no canto inferior direito das fotos.

    Qualquer falha devolve None e o envio segue com a foto original: a
    marca d'água nunca impede a publicação de uma promoção.
    """

    LARGURA_RELATIVA = 0.15   # largura do ícone em relação à foto
    LARGURA_MINIMA = 60       # em pixels, para continuar legível
    MARGEM_RELATIVA = 0.025   # distância da borda, em relação à largura
    OPACIDADE = 0.90
    QUALIDADE_JPEG = 90

    def __init__(self, caminho_icone: str = ICONE):
        self._icone = Image.open(caminho_icone).convert("RGBA")

    async def preparar(self, client, origem) -> bytes | None:
        """Baixa a foto da mensagem e devolve o JPEG com a marca d'água."""
        try:
            dados = await client.download_media(origem, file=bytes)
            if not dados:
                return None
            return await asyncio.to_thread(self.aplicar, dados)
        except Exception:
            logger.exception("Marca d'água falhou; enviando a foto original")
            return None

    def aplicar(self, dados: bytes) -> bytes:
        foto = ImageOps.exif_transpose(Image.open(io.BytesIO(dados))).convert("RGBA")
        largura, altura = foto.size

        lado = max(self.LARGURA_MINIMA, round(largura * self.LARGURA_RELATIVA))
        lado = min(lado, largura, round(altura * 1.77))  # cabe em fotos baixas
        icone = self._icone.resize(
            (lado, round(lado * self._icone.height / self._icone.width)),
            Image.LANCZOS
        )
        alfa = icone.getchannel("A").point(lambda a: round(a * self.OPACIDADE))
        icone.putalpha(alfa)

        margem = round(largura * self.MARGEM_RELATIVA)
        posicao = (largura - icone.width - margem, altura - icone.height - margem)
        foto.alpha_composite(icone, (max(posicao[0], 0), max(posicao[1], 0)))

        saida = io.BytesIO()
        foto.convert("RGB").save(saida, "JPEG", quality=self.QUALIDADE_JPEG, optimize=True)
        return saida.getvalue()
