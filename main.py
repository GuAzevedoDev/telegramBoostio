import asyncio
import logging
import os

from datetime import datetime, timezone
from time import perf_counter

from dotenv import load_dotenv
from telethon import TelegramClient, events

from services.confere_texto_service import ConfereTextoService
from services.confere_duplicada_service import ConfereDuplicadaService
from services.troca_afiliado_service import TrocaAfiliadoService
from services.formata_mensagem_service import FormataMensagemService
from services.enviar_mensagem_service import EnviarMensagemService


load_dotenv()

# ==========================================
# CONFIGURAÇÕES
# ==========================================

API_ID = int(os.getenv("api_id"))
API_HASH = os.getenv("api_hash")

CANAIS = [
    -1001768101197,
    -1001703989430
]

MAX_PROCESSAMENTOS = 4
INTERVALO_SINCRONIZACAO = 15


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("BOOSTio")


# ==========================================
# CLIENTE TELEGRAM
# ==========================================

client = TelegramClient(
    "boostio_telethon",
    API_ID,
    API_HASH,
    receive_updates=True,
    sequential_updates=False,
    auto_reconnect=True
)


# ==========================================
# SERVIÇOS
# ==========================================

confere_texto = ConfereTextoService()
confere_duplicada = ConfereDuplicadaService()
troca_afiliado = TrocaAfiliadoService()
formata_mensagem = FormataMensagemService()
enviar_mensagem = EnviarMensagemService()


# ==========================================
# CONCORRÊNCIA
# ==========================================

# Limita apenas os envios simultâneos; filtro e duplicata são
# instantâneos e nunca esperam uma promoção lenta.
semaforo = asyncio.Semaphore(MAX_PROCESSAMENTOS)


# ==========================================
# PROCESSAMENTO DE UMA PROMOÇÃO
# ==========================================

async def processar_promocao(client, mensagem, origem=None):
    """Retorna True se a promoção foi publicada e confirmada pelo Telegram."""

    # 1. Filtro de hardware (CPU puro: chamada direta, sem thread)
    if not confere_texto.executar(mensagem):
        return False

    # 2. Duplicata: atômica (sem await), compara com a última publicada
    #    e com as promoções em envio no momento.
    reserva = confere_duplicada.reservar(mensagem)

    if reserva is None:
        logger.info("Promoção duplicada ignorada")
        return False

    publicada = False

    try:
        # 3. Troca de afiliados (mantida em thread: pode fazer I/O)
        mensagem = await asyncio.to_thread(
            troca_afiliado.executar,
            mensagem
        )

        # 4. Padrão visual BOOSTio
        mensagem = formata_mensagem.executar(mensagem)

        # 5. Envio
        async with semaforo:
            await enviar_mensagem.executar(
                client,
                mensagem,
                origem=origem
            )

        publicada = True

    finally:
        if publicada:
            # só após a confirmação do Telegram
            await confere_duplicada.confirmar(reserva)
        else:
            confere_duplicada.liberar(reserva)

    return True


# ==========================================
# RECEBIMENTO DAS PROMOÇÕES
# ==========================================

@client.on(events.NewMessage(chats=CANAIS))
async def nova_promocao(event):

    inicio = perf_counter()

    mensagem = event.raw_text

    atraso = (
        datetime.now(timezone.utc) - event.date
    ).total_seconds()

    logger.info(
        "RECEBIDA | Canal: %s | ID: %s | Atraso: %.2fs",
        event.chat_id,
        event.id,
        atraso
    )

    if not mensagem:
        return

    try:
        if await processar_promocao(client, mensagem, event.message):
            logger.info(
                "PUBLICADA | Canal: %s | ID: %s | Total: %.3fs",
                event.chat_id,
                event.id,
                perf_counter() - inicio
            )

    except Exception:
        logger.exception(
            "Erro ao processar promoção | Canal: %s | ID: %s",
            event.chat_id,
            event.id
        )


# ==========================================
# SINCRONIZAÇÃO DE ATUALIZAÇÕES
# ==========================================

async def sincronizar_atualizacoes():

    while True:

        try:
            await asyncio.sleep(
                INTERVALO_SINCRONIZACAO
            )

            await client.catch_up()

            logger.debug(
                "Solicitada recuperação de atualizações pendentes"
            )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Erro ao recuperar atualizações"
            )


# ==========================================
# INICIALIZAÇÃO
# ==========================================

async def main():

    await client.start()

    usuario = await client.get_me()

    await asyncio.to_thread(troca_afiliado.aquecer)

    logger.info("BOOSTio iniciado")
    logger.info(
        "Conectado como: %s",
        usuario.first_name
    )
    logger.info(
        "Monitorando %s canais",
        len(CANAIS)
    )
    logger.info(
        "Máximo de processamentos simultâneos: %s",
        MAX_PROCESSAMENTOS
    )

    tarefa_sincronizacao = asyncio.create_task(
        sincronizar_atualizacoes()
    )

    try:
        await client.run_until_disconnected()

    finally:
        tarefa_sincronizacao.cancel()

        await asyncio.gather(
            tarefa_sincronizacao,
            return_exceptions=True
        )

        await client.disconnect()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("BOOSTio encerrado")