import os
from dotenv import load_dotenv
from pyrogram import Client

from services.confere_texto_service import ConfereTextoService
from services.troca_afiliado_service import TrocaAfiliadoService

load_dotenv()

api_id = int(os.getenv("api_id"))
api_hash = os.getenv("api_hash")  

grupos = [-1001371796882,-1001686905299,-1001703989430]

with Client('teste', api_id=api_id, api_hash=api_hash) as app:
  mensagens = app.get_chat_history(grupos[0], limit=1)    
  lista_msg = list(mensagens)
      
  if lista_msg:
    mensagem = lista_msg[0].text

    if ConfereTextoService().executar()(mensagem):
      mensagem = TrocaAfiliadoService().executar(mensagem)
      print(mensagem)
