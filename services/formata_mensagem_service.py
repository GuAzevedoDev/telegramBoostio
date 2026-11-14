import re
from html import escape

from services.texto_util import URL_RE, remover_emojis, sem_acentos


class FormataMensagemService:
    """
    Converte o texto original de uma promoção no padrão visual BOOSTio.
    Só usa informações presentes no texto; nada é inventado.
    Saída em HTML (parse_mode="html") com todo o conteúdo escapado.
    """

    # Paleta BOOSTio (logo): predominância do azul. Só emojis azuis ou brancos,
    # exceto o ingresso do código de cupom (não existe cupom azul no Unicode).
    CABECALHO = "🔷 <b>OFERTA BOOSTio</b>"
    DIVISOR = "▬▬▬▬▬▬▬▬▬▬▬▬"
    E_CATEGORIA = "🔹"
    E_PRECO = "🟦"
    E_PRECO_ANTIGO = "⚪"
    E_DESCONTO = "🔵"
    E_CUPOM = "🔹"
    E_CODIGO = "🎟️"
    E_COMPRAR = "🔷"
    MAX_TITULO = 200

    # Ordem importa: o primeiro grupo que casar define o rótulo da categoria.
    CATEGORIAS = [
        ("PLACA-MÃE", ["placa mae", "motherboard", "b450", "b550", "b650", "b850",
                       "x570", "x670", "x870", "a520", "a620"]),
        ("PLACA DE VÍDEO", ["placa de video", "gpu", "geforce", "rtx", "gtx", "radeon",
                            "rx 6600", "rx 7600", "rx 9060", "rx 9070"]),
        ("PROCESSADOR", ["processador", "ryzen", "intel core", "core i3", "core i5",
                         "core i7", "core i9", "core ultra", "threadripper"]),
        ("MEMÓRIA RAM", ["memoria ram", "ddr4", "ddr5", "fury beast", "vengeance"]),
        ("ARMAZENAMENTO", ["ssd", "nvme", "hd interno", "hdd", "m.2", "sata"]),
        ("FONTE", ["fonte atx", "fonte gamer", "fonte modular", "fonte", "80 plus"]),
        ("GABINETE", ["gabinete", "mid tower", "full tower"]),
        ("REFRIGERAÇÃO", ["water cooler", "air cooler", "cpu cooler", "cooler",
                          "pasta termica", "ventoinha"]),
        ("MONITOR", ["monitor", "ultragear", "odyssey"]),
        ("MOUSE", ["mousepad", "mouse"]),
        ("TECLADO", ["teclado"]),
        ("HEADSET", ["headset"]),
        ("WEBCAM", ["webcam"]),
        ("MICROFONE", ["microfone"]),
        ("PC", ["pc gamer", "computador gamer", "mini pc", "notebook gamer"]),
    ]

    _CATEGORIAS = [
        (rotulo, re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(p) for p in palavras) + r")(?!\w)"))
        for rotulo, palavras in CATEGORIAS
    ]

    # milhar com ponto (1.912,50) ou sem (1912,50); centavos opcionais
    _VALOR = r"R\$\s?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?"
    _PRECO_RE = re.compile(_VALOR, re.I)
    _DE_POR_RE = re.compile(
        rf"\bde\s+({_VALOR})\s+(?:por|a|para)\s+({_VALOR})", re.I)
    _POR_RE = re.compile(rf"\b(?:por|apenas|so|somente)\s+({_VALOR})", re.I)
    _DESCONTO_RE = re.compile(
        r"(\d{1,2})\s?%\s*(?:off|de desconto|desconto)|(?:off|desconto)\s*(?:de)?\s*(\d{1,2})\s?%",
        re.I)
    _CUPOM_RE = re.compile(
        r"(?i:cupom|cupon|cupons|codigo)\s*(?:de desconto)?\s*[:\-]?\s*([A-Z0-9]{4,20})\b")
    _CUPOM_PALAVRA_RE = re.compile(r"cupo(?:m|n|ns)\b|cupoes|codigo", re.I)
    _RUIDO_RE = re.compile(
        r"\b(?:por|de|apenas|so|somente|no|na|pix|a vista|cartao|boleto|ate|"
        r"oferta|promocao|promo|achado|imperdivel|menor preco|agora|hoje)\b",
        re.I)
    _PIX_RE = re.compile(r"\bpix\b", re.I)

    def executar(self, mensagem: str) -> str:
        limpo = remover_emojis(mensagem)

        links_compra, links_cupom = self._extrair_links(limpo)
        sem_links = URL_RE.sub("", limpo)
        linhas = [self._limpar_linha(l) for l in sem_links.splitlines()]
        linhas = [l for l in linhas if l]

        preco, preco_antigo, no_pix = self._extrair_preco(sem_links)
        desconto = self._extrair_desconto(sem_links)
        codigo = self._extrair_codigo(sem_links)
        titulo = self._extrair_titulo(linhas)

        # "Cupom: CODIGO <link>": com código explícito, o link é o do produto
        if codigo and not links_compra:
            links_compra, links_cupom = links_cupom, []

        partes = [self.CABECALHO, self.DIVISOR, ""]

        categoria = self._categoria(titulo, sem_links) if titulo else None
        if categoria:
            partes.append(f"{self.E_CATEGORIA} <b>{categoria}</b>")
        if titulo:
            partes.append(f"<b>{escape(titulo)}</b>")

        if preco:
            partes.append("")
            if preco_antigo:
                partes.append(f"{self.E_PRECO_ANTIGO} De <s>{escape(preco_antigo)}</s>")
            linha = f"{self.E_PRECO} {'Por ' if preco_antigo else ''}<b>{escape(preco)}</b>"
            if no_pix:
                linha += " no Pix"
            partes.append(linha)

        if desconto:
            partes.append(f"{self.E_DESCONTO} <b>{escape(desconto)} OFF</b>")

        if codigo or links_cupom:
            partes.append("")
            if codigo:
                partes.append(f"{self.E_CODIGO} Cupom: <code>{escape(codigo)}</code>")
            if links_cupom:
                partes.append(f"{self.E_CUPOM} Cupons disponíveis:")
                partes.extend(escape(l) for l in links_cupom)

        if links_compra:
            partes.append("")
            partes.append(f"{self.E_COMPRAR} <b>Comprar:</b>")
            partes.extend(escape(l) for l in links_compra)

        return "\n".join(partes).strip()

    # ---------- extração ----------

    @staticmethod
    def _limpar_linha(linha: str) -> str:
        linha = re.sub(r"[*_~`#]+", "", linha)
        linha = re.sub(r"^[\s\-–—•·|:]+", "", linha)
        return re.sub(r"\s+", " ", linha).strip()

    def _extrair_links(self, texto: str):
        compra, cupom = [], []
        linhas = texto.splitlines()
        for i, linha in enumerate(linhas):
            for url in URL_RE.findall(linha):
                url = url.rstrip(".,;)")
                propria = URL_RE.sub("", linha)
                # linha só com o link herda o rótulo da linha anterior
                if not re.search(r"[^\W\d_]{3}", propria) and i:
                    propria = linhas[i - 1] + " " + propria
                contexto = sem_acentos(propria).lower()
                destino = cupom if self._CUPOM_PALAVRA_RE.search(contexto) else compra
                if url not in compra and url not in cupom:
                    destino.append(url)
        return compra, cupom

    def _extrair_preco(self, texto: str):
        m = self._DE_POR_RE.search(texto)
        if m:
            antigo, preco = self._fmt_preco(m.group(1)), self._fmt_preco(m.group(2))
            return preco, antigo, self._tem_pix(texto, m.group(2))

        m = self._POR_RE.search(texto)
        if m:
            return self._fmt_preco(m.group(1)), None, self._tem_pix(texto, m.group(1))

        m = self._PRECO_RE.search(texto)
        if m:
            return self._fmt_preco(m.group(0)), None, self._tem_pix(texto, m.group(0))
        return None, None, False

    def _tem_pix(self, texto: str, valor: str) -> bool:
        for linha in texto.splitlines():
            if valor in linha and self._PIX_RE.search(sem_acentos(linha)):
                return True
        return False

    @staticmethod
    def _fmt_preco(valor: str) -> str:
        return "R$ " + re.sub(r"^R\$\s?", "", valor, flags=re.I)

    def _extrair_desconto(self, texto: str):
        m = self._DESCONTO_RE.search(texto)
        return f"{m.group(1) or m.group(2)}%" if m else None

    def _extrair_codigo(self, texto: str):
        m = self._CUPOM_RE.search(sem_acentos(texto))
        return m.group(1) if m else None

    def _extrair_titulo(self, linhas: list[str]):
        for linha in linhas:
            base = sem_acentos(linha).lower()
            if self._CUPOM_PALAVRA_RE.search(base):
                continue
            titulo = self._PRECO_RE.sub("", linha)
            titulo = self._DESCONTO_RE.sub("", titulo)
            residuo = self._RUIDO_RE.sub("", sem_acentos(titulo).lower())
            if len(re.findall(r"[a-z]", residuo)) < 3:
                continue
            # remove "por"/"de"/"no pix" soltos nas pontas, preservando o produto
            titulo = re.sub(
                r"(?i)(?:\b(?:por|de|apenas|so|só|somente|no pix|à vista|a vista)\b[\s:\-–—]*)+$",
                "", titulo.strip())
            titulo = re.sub(r"(?i)^(?:oferta|promoção|promocao|promo)\b[\s:\-–—!]*", "", titulo)
            titulo = re.sub(r"[\s\-–—:|,;!]+$", "", titulo).strip()
            if titulo:
                return titulo[: self.MAX_TITULO]
        return None

    def _categoria(self, titulo: str, texto: str):
        for alvo in (sem_acentos(titulo).lower(), sem_acentos(texto).lower()):
            for rotulo, regex in self._CATEGORIAS:
                if regex.search(alvo):
                    return rotulo
        return None
