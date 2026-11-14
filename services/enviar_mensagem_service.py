import asyncio
import io
import logging

from telethon.errors import FloodWaitError

logger = logging.getLogger("BOOSTio.envio")


class EnviarMensagemService:

    CANAL_DESTINO = -1004483617616
    MAX_ESPERA_FLOOD = 30

    async def executar(self, client, mensagem: str, origem=None, imagem=None):
        """
        Retorna somente quando o Telegram confirmou a publicação.
        `imagem` (bytes) substitui a foto da origem, já com a marca d'água.
        """
        try:
            return await self._enviar(client, mensagem, origem, imagem)
        except FloodWaitError as erro:
            if erro.seconds > self.MAX_ESPERA_FLOOD:
                raise
            logger.warning("FloodWait: aguardando %ss", erro.seconds)
            await asyncio.sleep(erro.seconds + 1)
            return await self._enviar(client, mensagem, origem, imagem)

    async def _enviar(self, client, mensagem: str, origem, imagem=None):
        if imagem is not None:
            arquivo = io.BytesIO(imagem)  # novo a cada tentativa (reenvio após FloodWait)
            arquivo.name = "promocao.jpg"
            return await client.send_file(
                self.CANAL_DESTINO,
                file=arquivo,
                caption=mensagem,
                parse_mode="html"
            )

        # Sem marca d'água (vídeo ou falha): reenvio por referência, sem download.
        midia = origem.photo or origem.video if origem is not None else None

        if midia:
            return await client.send_file(
                self.CANAL_DESTINO,
                file=midia,
                caption=mensagem,
                parse_mode="html"
            )

        return await client.send_message(
            self.CANAL_DESTINO,
            mensagem,
            parse_mode="html",
            link_preview=False
        )
