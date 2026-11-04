import os
from dotenv import load_dotenv
from pyrogram import Client,filters

from services.confere_texto_service import ConfereTextoService
from services.troca_afiliado_service import TrocaAfiliadoService
from services.enviar_mensagem_service import EnviarMensagemService

load_dotenv()

api_id = int(os.getenv("api_id"))
api_hash = os.getenv("api_hash")  

grupos = [
    -1001371796882,
    -1001686905299,
    -1001703989430
]

app = Client("teste", api_id=api_id, api_hash=api_hash)

@app.on_message(filters.chat(grupos))
def nova_promocao(client, message):

    mensagem = message.text or message.caption

    if not mensagem:
        return

    if ConfereTextoService().executar(mensagem):
        mensagem = TrocaAfiliadoService().executar(mensagem)
        EnviarMensagemService().executar(mensagem)

app.run()
      
