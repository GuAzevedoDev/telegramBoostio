import re

class TrocaAfiliadoService():
  def executar(mensagem: str):
    padrao = r'(https?://[^\s]+)'
    links = re.findall(padrao, mensagem)

    if not links:
        return mensagem  # Se não houver link, retorna a mensagem original em vez de vazio

    for link in links:
        # CORREÇÃO: É necessário reatribuir o valor modificado à variável
        mensagem = mensagem.replace(link, f'{link} alterado')

    return mensagem