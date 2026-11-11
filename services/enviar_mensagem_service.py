import asyncio
import logging

from telethon.errors import FloodWaitError

logger = logging.getLogger("BOOSTio.envio")


class EnviarMensagemService:

    CANAL_DESTINO = -1004483617616
    MAX_ESPERA_FLOOD = 30

    async def executar(self, client, mensagem: str, origem=None):
        """Retorna somente quando o Telegram confirmou a publicação."""
        try:
            return await self._enviar(client, mensagem, origem)
        except FloodWaitError as erro:
            if erro.seconds > self.MAX_ESPERA_FLOOD:
                raise
            logger.warning("FloodWait: aguardando %ss", erro.seconds)
            await asyncio.sleep(erro.seconds + 1)
            return await self._enviar(client, mensagem, origem)

    async def _enviar(self, client, mensagem: str, origem):
        # Foto/vídeo original é reenviado por referência (sem download).
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
