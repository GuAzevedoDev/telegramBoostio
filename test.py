import asyncio
import os

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.raw.types import UpdateNewChannelMessage, Message as RawMessage

load_dotenv()

api_id = int(os.getenv("api_id"))
api_hash = os.getenv("api_hash")

# Canais que queremos monitorar
CANAIS = [
    -1001371796882,  # La Promotion
    -1001686905299,
    -1001703989430
]

app = Client(
    "boostio_user",
    api_id=api_id,
    api_hash=api_hash
)


# TESTE 1: Mensagens processadas pelo Pyrogram
@app.on_message(group=0)
def receber_mensagem(client, message):

    if message.chat.id not in CANAIS:
        return

    print("\n========== MENSAGEM ==========", flush=True)
    print("Canal:", message.chat.title, flush=True)
    print("ID Canal:", message.chat.id, flush=True)
    print("ID Mensagem:", message.id, flush=True)
    print("Texto:", message.text or message.caption, flush=True)
    print("==============================\n", flush=True)


# TESTE 2: Atualizações brutas do Telegram
@app.on_raw_update(group=1)
def receber_atualizacao(client, update, users, chats):

    if not isinstance(update, UpdateNewChannelMessage):
        return

    raw_message = update.message

    # Ignora eventos de serviço, como entrada de membros
    if not isinstance(raw_message, RawMessage):
        return

    peer = raw_message.peer_id

    if not hasattr(peer, "channel_id"):
        return

    canal_id = int(f"-100{peer.channel_id}")

    if canal_id not in CANAIS:
        return

    print("\n========== RAW UPDATE ==========", flush=True)
    print("Canal ID:", canal_id, flush=True)
    print("Mensagem ID:", raw_message.id, flush=True)
    print("Texto:", raw_message.message, flush=True)
    print("================================\n", flush=True)


if __name__ == "__main__":

    print("Iniciando monitoramento BOOSTio...")
    print("Canais monitorados:", CANAIS)

    app.run()