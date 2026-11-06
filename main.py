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
from services.enviar_mensagem_service import EnviarMensagemService


load_dotenv()

# ==========================================
# CONFIGURAÇÕES
# ==========================================

API_ID = int(os.getenv("api_id"))
API_HASH = os.getenv("api_hash")

CANAIS = [
    -1001371796882,
    -1001686905299,
    -1001703989430
]

MAX_PROCESSAMENTOS = 4
INTERVALO_SINCRONIZACAO = 15


# ==========================================
# LOGS
# ==========================================

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
enviar_mensagem = EnviarMensagemService()


# ==========================================
# CONCORRÊNCIA
# ==========================================

semaforo = asyncio.Semaphore(MAX_PROCESSAMENTOS)
lock_duplicadas = asyncio.Lock()


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

    async with semaforo:

        try:
            # 1. Verificação de hardware
            t = perf_counter()

            eh_hardware = await asyncio.to_thread(
                confere_texto.executar,
                mensagem
            )

            logger.info(
                "Filtro hardware: %.3fs",
                perf_counter() - t
            )

            if not eh_hardware:
                return

            # 2. Verificação de duplicação
            t = perf_counter()

            async with lock_duplicadas:
                duplicada = await asyncio.to_thread(
                    confere_duplicada.executar,
                    mensagem
                )

            logger.info(
                "Verificação duplicação: %.3fs",
                perf_counter() - t
            )

            if duplicada:
                logger.info("Promoção duplicada ignorada")
                return

            # 3. Troca dos links de afiliado
            t = perf_counter()

            mensagem = await asyncio.to_thread(
                troca_afiliado.executar,
                mensagem
            )

            logger.info(
                "Troca afiliado: %.3fs",
                perf_counter() - t
            )

            if not mensagem:
                return

            # 4. Envio para o BOOSTio
            t = perf_counter()

            logger.info(
                "Iniciando envio | Canal origem: %s | ID: %s",
                event.chat_id,
                event.id
            )

            await enviar_mensagem.executar(
                client,
                mensagem,
                origem=event.message
            )

            logger.info(
                "Envio Telegram: %.3fs",
                perf_counter() - t
            )

            logger.info(
                "TOTAL processamento: %.3fs",
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