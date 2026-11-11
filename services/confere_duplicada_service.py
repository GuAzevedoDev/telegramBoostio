import asyncio
import json
import logging
import os
import re
from difflib import SequenceMatcher
from itertools import count

from services.texto_util import URL_RE, remover_emojis, sem_acentos

logger = logging.getLogger("BOOSTio.duplicada")


class ConfereDuplicadaService:
    """
    Compara cada promoção com a última efetivamente publicada.

    Fluxo: reservar() -> (enviar) -> confirmar() | liberar().

    reservar() é síncrono (sem await), logo atômico no asyncio: duas
    mensagens simultâneas nunca passam juntas, pois cada reserva em andamento
    também entra na comparação. Nenhum lock é mantido durante o envio.
    """

    LIMITE_SIMILARIDADE = 0.80
    MAX_CARACTERES = 1500

    def __init__(self, arquivo: str = "data/ultima_enviada.json"):
        self._arquivo = arquivo
        self._ultima = self._carregar()
        self._reservas: dict[int, str] = {}
        self._ids = count(1)
        self._lock_escrita = asyncio.Lock()

    # ---------- normalização / similaridade ----------

    @staticmethod
    def normalizar(texto: str) -> str:
        texto = URL_RE.sub(" ", texto)
        texto = sem_acentos(remover_emojis(texto).lower())
        texto = re.sub(r"[\W_]+", " ", texto)
        return texto.strip()[:ConfereDuplicadaService.MAX_CARACTERES]

    @classmethod
    def similaridade(cls, a: str, b: str) -> float:
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        sm = SequenceMatcher(None, a, b, autojunk=False)
        # limites superiores baratos evitam o cálculo completo
        if (sm.real_quick_ratio() < cls.LIMITE_SIMILARIDADE
                or sm.quick_ratio() < cls.LIMITE_SIMILARIDADE):
            return 0.0
        return sm.ratio()

    # ---------- API ----------

    def reservar(self, mensagem: str) -> int | None:
        """Devolve um token de reserva, ou None se for duplicada."""
        texto = self.normalizar(mensagem)
        if not texto:
            return None

        referencias = list(self._reservas.values())
        if self._ultima:
            referencias.append(self._ultima)

        for ref in referencias:
            if self.similaridade(texto, ref) >= self.LIMITE_SIMILARIDADE:
                return None

        token = next(self._ids)
        self._reservas[token] = texto
        return token

    async def confirmar(self, token: int):
        """Chamar somente depois do Telegram confirmar a publicação."""
        texto = self._reservas.pop(token, None)
        if texto is None:
            return
        self._ultima = texto
        async with self._lock_escrita:
            await asyncio.to_thread(self._gravar, self._ultima)

    def liberar(self, token: int):
        """Envio falhou ou foi descartado: não conta como publicada."""
        self._reservas.pop(token, None)

    # ---------- persistência ----------

    def _carregar(self) -> str:
        try:
            with open(self._arquivo, encoding="utf-8") as f:
                return json.load(f).get("texto", "")
        except FileNotFoundError:
            return ""
        except (OSError, ValueError):
            logger.exception("Histórico ilegível; iniciando vazio")
            return ""

    def _gravar(self, texto: str):
        pasta = os.path.dirname(self._arquivo)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        tmp = self._arquivo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"texto": texto}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._arquivo)
