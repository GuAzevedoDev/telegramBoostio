class ConfereDuplicadaService:

    def __init__(self):
        self.mensagens_enviadas = set()

    def executar(self, mensagem: str) -> bool:
        mensagem = mensagem.strip().lower()

        if mensagem in self.mensagens_enviadas:
            return True

        self.mensagens_enviadas.add(mensagem)
        return False