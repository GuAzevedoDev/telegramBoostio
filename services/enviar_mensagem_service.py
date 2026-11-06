from io import BytesIO


class EnviarMensagemService:

    CANAL_DESTINO = -1004483617616

    async def executar(self, client, mensagem: str, origem=None):

        if origem is not None and origem.photo:
            await client.send_file(
                self.CANAL_DESTINO,
                file=origem.media,
                caption=mensagem,
                parse_mode=None
            )
        else:
            await client.send_message(
                self.CANAL_DESTINO,
                mensagem,
                parse_mode=None,
                link_preview=False
            )