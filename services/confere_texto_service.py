import unicodedata
import re

class ConfereTextoService:

  PALAVRAS_CHAVES = [
        # Processadores
        "processador", "ryzen", "intel core",
        "core i3", "core i5", "core i7", "core i9",
        "core ultra", "threadripper",

        # Placas de vídeo
        "placa de video", "gpu", "geforce",
        "rtx", "gtx", "radeon", "rx 6600",
        "rx 7600", "rx 9060", "rx 9070",

        # Placas-mãe
        "placa mae", "motherboard",
        "b450", "b550", "b650", "b850",
        "x570", "x670", "x870",
        "a520", "a620", "am4", "am5",

        # Memórias
        "memoria ram", "ddr4", "ddr5",
        "fury beast", "corsair vengeance",

        # Armazenamento
        "ssd", "nvme", "hd interno",
        "hdd", "m.2", "sata",

        # Fontes
        "fonte atx", "fonte gamer",
        "fonte modular", "80 plus",

        # Gabinetes
        "gabinete", "mid tower", "full tower",

        # Refrigeração
        "water cooler", "air cooler",
        "cpu cooler", "pasta termica",
        "ventoinha",

        # Monitores
        "monitor", "ultragear", "odyssey",

        # Periféricos
        "mouse", "teclado", "headset",
        "mousepad", "webcam", "microfone",

        # Computadores
        "pc gamer", "computador gamer",
        "mini pc", "notebook gamer"
    ]
 
  def executar(self, mensagem: str) -> bool:
    mensagem = self.normalizar(mensagem)

    return any(
            re.search(
                rf"(?<!\w){re.escape(self.normalizar(palavra))}(?!\w)",
                mensagem
            )
            for palavra in self.PALAVRAS_CHAVES
        )

  @staticmethod
  def normalizar(texto: str) -> str:
    texto = texto.lower()
  
    return "".join(
              caractere
              for caractere in unicodedata.normalize("NFD", texto)
              if unicodedata.category(caractere) != "Mn"
          )
  