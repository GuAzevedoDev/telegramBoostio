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

# Converte com segurança prevenindo erros se a variável sumir
api_id = int(os.getenv("api_id") or 0)
api_hash = os.getenv("api_hash")  

grupos = [
    -1001371796882,
    -1001686905299,
    -1001703989430
]

app = Client("boostio_user", api_id=api_id, api_hash=api_hash)

confere_duplicada = ConfereDuplicadaService()

@app.on_message(filters.chat(grupos))
def nova_promocao(client, message):

    mensagem = message.text or message.caption

    if not mensagem:
        return

    if not ConfereTextoService().executar(mensagem):
        return

    if confere_duplicada.executar(mensagem):
        print("Promoção duplicada!")
        return

    mensagem = TrocaAfiliadoService().executar(mensagem)

    EnviarMensagemService().executar(mensagem)

app.run()
