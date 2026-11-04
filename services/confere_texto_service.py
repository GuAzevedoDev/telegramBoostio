class ConfereTextoService():
  def executar(mensagem: str):
    PALAVRAS_CHAVES = ["Placa de video", "Placa mãe", "Ryzen", "Mouse"]

    mensagem_minuscula = mensagem.lower()

    if any(palavra.lower() in mensagem_minuscula for palavra in PALAVRAS_CHAVES):
      return True

    return False