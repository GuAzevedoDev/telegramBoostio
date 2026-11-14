import asyncio
import logging
import os

from datetime import datetime, timezone
from difflib import SequenceMatcher
from time import perf_counter

from dotenv import load_dotenv
from telethon import TelegramClient, events

from services.confere_texto_service import ConfereTextoService
from services.confere_duplicada_service import ConfereDuplicadaService
from services.troca_afiliado_service import TrocaAfiliadoService
from services.formata_mensagem_service import FormataMensagemService
from services.enviar_mensagem_service import EnviarMensagemService
from services.marca_dagua_service import MarcaDaguaService


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
MAX_TEXTOS_VISTOS = 500
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
marca_dagua = MarcaDaguaService()


# ==========================================
# CONCORRÊNCIA
# ==========================================

# Limita apenas os envios simultâneos; filtro e duplicata são
# instantâneos e nunca esperam uma promoção lenta.
semaforo = asyncio.Semaphore(MAX_PROCESSAMENTOS)

# Última versão vista de cada mensagem de origem (só para registrar edições)
textos_vistos: dict[tuple, str] = {}


# ==========================================
# PROCESSAMENTO DE UMA PROMOÇÃO
# ==========================================

async def processar_promocao(client, mensagem, origem=None):
    """Retorna True se a promoção foi publicada e confirmada pelo Telegram."""

    # 1. Filtro de hardware (CPU puro: chamada direta, sem thread)
    if not confere_texto.executar(mensagem):
        logger.info("Descartada pelo filtro de hardware")
        return False

    # 2. Duplicata: atômica (sem await), compara com a última publicada
    #    e com as promoções em envio no momento.
    reserva = confere_duplicada.reservar(mensagem)

    if reserva is None:
        logger.info("Promoção duplicada ignorada")
        return False

    publicada = False
    foto = None

    try:
        # 3. Foto com marca d'água, em paralelo com a troca de afiliados
        #    (vídeos seguem por referência, sem download)
        if origem is not None and origem.photo:
            foto = asyncio.create_task(marca_dagua.preparar(client, origem))

        # 4. Troca de afiliados (mantida em thread: pode fazer I/O)
        mensagem = await asyncio.to_thread(
            troca_afiliado.executar,
            mensagem
        )

        # 5. Padrão visual BOOSTio
        mensagem = formata_mensagem.executar(mensagem)

        # 6. Envio
        imagem = await foto if foto else None

        async with semaforo:
            await enviar_mensagem.executar(
                client,
                mensagem,
                origem=origem,
                imagem=imagem
            )

        publicada = True

    finally:
        if foto and not foto.done():
            foto.cancel()

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

    textos_vistos[(event.chat_id, event.id)] = mensagem
    if len(textos_vistos) > MAX_TEXTOS_VISTOS:
        textos_vistos.pop(next(iter(textos_vistos)))

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
# EDIÇÕES DAS MENSAGENS DE ORIGEM (apenas registro)
# ==========================================

def _mudancas(antes: str, depois: str, limite: int = 200) -> str:
    """Resume só os trechos que mudaram entre duas versões do texto."""
    a, b = antes.split(), depois.split()
    partes = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            partes.append(f"'{' '.join(a[i1:i2])}' -> '{' '.join(b[j1:j2])}'")
    return " | ".join(partes)[:limite]


@client.on(events.MessageEdited(chats=CANAIS))
async def promocao_editada(event):

    chave = (event.chat_id, event.id)
    antes = textos_vistos.get(chave)
    depois = event.raw_text or ""
    textos_vistos[chave] = depois

    edit_date = event.message.edit_date
    apos = (
        (edit_date - event.message.date).total_seconds()
        if edit_date else 0
    )

    if antes is None:
        logger.info(
            "EDITADA | Canal: %s | ID: %s | +%.0fs | versão anterior não vista",
            event.chat_id, event.id, apos
        )
        return

    similaridade = confere_duplicada.similaridade(
        confere_duplicada.normalizar(antes),
        confere_duplicada.normalizar(depois)
    )

    logger.info(
        "EDITADA | Canal: %s | ID: %s | +%.0fs | similaridade: %.0f%% | "
        "link antes/depois: %s/%s | texto antes/depois: %s/%s chars",
        event.chat_id, event.id, apos, similaridade * 100,
        "http" in antes, "http" in depois, len(antes), len(depois)
    )

    if antes != depois:
        logger.info("EDITADA | ID: %s | mudou: %s", event.id, _mudancas(antes, depois))


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