import asyncio

try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os
from dotenv import load_dotenv
from pyrogram import Client, filters

from services.confere_texto_service import ConfereTextoService
from services.troca_afiliado_service import TrocaAfiliadoService
from services.enviar_mensagem_service import EnviarMensagemService
from services.confere_duplicada_service import ConfereDuplicadaService

load_dotenv()


api_id = int(os.getenv("api_id") or 0)
api_hash = os.getenv("api_hash")  

grupos = [
    -1001371796882,
    -1001686905299,
    -1001703989430
]

app = Client("boostio_user", api_id=api_id, api_hash=api_hash)

confere_duplicada = ConfereDuplicadaService()

@app.on_message(filters.channel)
def nova_promocao(client, message):
    print("PUBLICAÇÃO RECEBIDA!", flush=True)
    print("Canal:", message.chat.title, flush=True)
    print("ID:", message.chat.id, flush=True)
    print("Mensagem:", message.text or message.caption, flush=True)
    print("-" * 40, flush=True)

app.run()
