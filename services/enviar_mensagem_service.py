class EnviarMensagemService:
  def executar(app,mensagem:str):
    app.send_message("Ofertas - BOOSTio", mensagem)
    print(mensagem)