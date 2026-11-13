import hashlib
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, quote, urlsplit

import requests

from services.texto_util import URL_RE, remover_emojis, sem_acentos

logger = logging.getLogger("BOOSTio.afiliado")


class ErroGeradorML(Exception):
    """O gerador oficial de links da ML não devolveu um link."""


class TrocaAfiliadoService:
    """
    Troca links de Shopee e Mercado Livre pelos links de afiliado do BOOSTio.
    Qualquer outro link, ou qualquer falha, mantém o link original.
    Roda em thread (requests síncrono), chamado via asyncio.to_thread.
    """

    SHOPEE_API = "https://open-api.affiliate.shopee.com.br/graphql"
    SHOPEE_HOSTS = ("shopee.com.br",)
    SHOPEE_CURTOS = ("s.shopee.com.br", "shope.ee", "shp.ee")
    ML_HOSTS = ("mercadolivre.com.br", "mercadolivre.com")
    ML_CURTOS = ("meli.la",)
    # bloco de métricas da página /social/ do afiliado: contém o produto
    _ML_SOCIAL_RE = re.compile(
        r'"landing":"affiliate-profile","trigger":\{[^}]*?"item_id":"(?P<item>[^"]*)"'
        r'[^}]*?"product_id":"(?P<produto>[^"]*)"')
    ML_GERADOR_PAGINA = "https://www.mercadolivre.com.br/afiliados/linkbuilder"
    ML_GERADOR_API = (
        "https://www.mercadolivre.com.br/affiliate-program/api/v2/"
        "affiliates/linkbuilder/createLink"
    )
    ML_CSRF_TTL = 600
    _ML_CSRF_RE = (
        re.compile(r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"'),
        re.compile(r'<meta[^>]+content="([^"]+)"[^>]+name="csrf-token"'),
    )
    # página /social/<afiliado>/lists: todos os produtos recomendados, com o nome no endereço
    _ML_LISTA_RE = re.compile(r'href="https://www\.mercadolivre\.com\.br/([a-z0-9-]+)/p/(MLB\d+)')
    _STOP = frozenset(
        "de da do das dos com para por em no na e a o as os um uma ate r rs reais "
        "cupom cupons frete gratis oferta promocao pix vista parcelas sem juros off "
        "desconto link comprar compre aqui".split())
    ML_LISTA_SCORE_MIN = 0.40      # similaridade mínima (cosseno de palavras)
    ML_LISTA_MARGEM = 0.12         # vantagem mínima sobre o 2º colocado
    ML_PAGINA_MAX = 1_500_000
    ML_MATT_TOOL_PADRAO = "74191004"
    ML_PARAMS_MANTIDOS = ("pdp_filters",)  # escolhe a oferta no catálogo (/p/)

    # A ML só entrega o bloco com o produto a clientes tipo navegador
    # (uso autorizado pelo dono do projeto).
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    TIMEOUT = 3
    CACHE_MAX = 1024

    def __init__(self):
        self._shopee_id = os.getenv("SHOPEE_APP_ID")
        self._shopee_secret = os.getenv("SHOPEE_SECRET")
        self._ml_etiqueta = os.getenv("ML_ETIQUETA")
        self._ml_tool = os.getenv("ML_MATT_TOOL", self.ML_MATT_TOOL_PADRAO)
        self._sessao = requests.Session()
        self._sessao.headers["User-Agent"] = self.USER_AGENT
        self._ml_cookie = os.getenv("ML_COOKIE")
        self._sessao_ml = self._criar_sessao_ml(self._ml_cookie)
        self._csrf = None
        self._csrf_ts = 0.0
        self._lock_csrf = threading.Lock()
        self._cache: dict[str, str] = {}
        self._cache_ml: dict[str, str] = {}   # produto -> link oficial gerado
        self._pool = ThreadPoolExecutor(max_workers=4)

    # ---------- API ----------

    def aquecer(self):
        """Abre as conexões TLS (Shopee e Mercado Livre) na inicialização."""
        for url in (self.SHOPEE_API, "https://meli.la/", "https://www.mercadolivre.com.br/"):
            try:
                self._sessao.head(url, timeout=self.TIMEOUT)
            except requests.RequestException:
                pass
        if self._sessao_ml:
            try:
                self._ml_csrf()
            except Exception as erro:
                logger.error("Gerador oficial da ML indisponível: %s", erro)

    def executar(self, mensagem: str) -> str:
        # a pontuação final não faz parte da URL
        urls = list(dict.fromkeys(l.rstrip(".,;)") for l in URL_RE.findall(mensagem)))

        if len(urls) > 1:  # links independentes: trocas em paralelo
            novos = list(self._pool.map(lambda u: self._trocar(u, mensagem), urls))
        else:
            novos = [self._trocar(u, mensagem) for u in urls]

        for url, novo in zip(urls, novos):
            if novo != url:
                mensagem = mensagem.replace(url, novo)
        return mensagem

    # ---------- roteamento ----------

    def _trocar(self, url: str, contexto: str = "") -> str:
        if url in self._cache:
            return self._cache[url]

        host = (urlsplit(url).hostname or "").lower()
        try:
            if self._eh(host, self.SHOPEE_HOSTS + self.SHOPEE_CURTOS):
                novo = self._shopee(url, host)
            elif self._eh(host, self.ML_HOSTS + self.ML_CURTOS):
                novo = self._mercado_livre(url, contexto)
            else:
                novo = url
        except Exception:
            logger.exception("Falha ao trocar afiliado; mantendo link original")
            return url  # falhas não entram no cache

        if len(self._cache) >= self.CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        # não ficam em cache: o link de contingência da ML (tenta o oficial de
        # novo na próxima) e links curtos da ML, que dependem do texto da mensagem
        contextual = self._eh(host, self.ML_CURTOS) or "/social/" in url
        if not (contextual or (self._sessao_ml and "matt_word=" in novo)):
            self._cache[url] = novo
        return novo

    @staticmethod
    def _eh(host: str, dominios) -> bool:
        return any(host == d or host.endswith("." + d) for d in dominios)

    # ---------- Mercado Livre ----------

    def _mercado_livre(self, url: str, contexto: str = "") -> str:
        if not self._ml_etiqueta:
            logger.warning("ML_ETIQUETA ausente; link mantido")
            return url

        partes = urlsplit(url)
        host = (partes.hostname or "").lower()
        eh_curto = host in self.ML_CURTOS or partes.path.startswith(("/social/", "/sec/"))

        if eh_curto:
            # link de afiliado de terceiros: descobre o produto pela página
            produto = self._produto_do_link_social(url, contexto)
            if not produto:
                logger.warning("Produto não identificado em %s", url)
                return url
            return self._ml_final(f"https://www.mercadolivre.com.br{produto}")

        if not re.search(r"MLB-?\d+", partes.path):
            return url

        query = parse_qs(partes.query)
        mantidos = {k: query[k][0] for k in self.ML_PARAMS_MANTIDOS if k in query}
        return self._ml_final(f"https://{partes.hostname}{partes.path}", mantidos)

    def _ml_final(self, base: str, extras: dict | None = None) -> str:
        """Link oficial (conta venda); sem cookie ou em falha, o parametrizado."""
        if self._sessao_ml:
            url = base + ("?" + "&".join(
                f"{k}={quote(v, safe='')}" for k, v in extras.items()) if extras else "")
            if url in self._cache_ml:
                return self._cache_ml[url]
            try:
                link = self._ml_oficial(url)
                if len(self._cache_ml) >= self.CACHE_MAX:
                    self._cache_ml.pop(next(iter(self._cache_ml)))
                self._cache_ml[url] = link
                return link
            except Exception as erro:
                logger.error(
                    "Gerador oficial da ML falhou (%s); usando link parametrizado", erro)
        return self._link_afiliado(base, extras)

    # ---------- gerador oficial da ML (sessão do dono do projeto) ----------

    @classmethod
    def _criar_sessao_ml(cls, cookie: str | None):
        if not cookie:
            return None
        sessao = requests.Session()
        sessao.headers["User-Agent"] = cls.USER_AGENT
        for par in cookie.split(";"):
            nome, _, valor = par.strip().partition("=")
            if nome:
                sessao.cookies.set(nome, valor, domain=".mercadolivre.com.br")
        return sessao

    def _ml_csrf(self, forcar: bool = False) -> str:
        with self._lock_csrf:
            if not forcar and self._csrf and time.time() - self._csrf_ts < self.ML_CSRF_TTL:
                return self._csrf
            resp = self._sessao_ml.get(self.ML_GERADOR_PAGINA, timeout=5)
            if "login" in resp.url or "account-verification" in resp.url:
                raise ErroGeradorML("ML_COOKIE inválido ou expirado")
            for padrao in self._ML_CSRF_RE:
                m = padrao.search(resp.text)
                if m:
                    self._csrf, self._csrf_ts = m.group(1), time.time()
                    return self._csrf
            raise ErroGeradorML("token CSRF não encontrado na página do gerador")

    def _ml_oficial(self, url: str) -> str:
        for tentativa in (1, 2):
            resp = self._sessao_ml.post(
                self.ML_GERADOR_API,
                json={"urls": [url], "tag": self._ml_etiqueta},
                headers={
                    "Accept": "application/json",
                    "x-csrf-token": self._ml_csrf(forcar=tentativa == 2),
                    "Origin": "https://www.mercadolivre.com.br",
                    "Referer": self.ML_GERADOR_PAGINA,
                },
                timeout=5,
            )
            if resp.status_code in (401, 403) and tentativa == 1:
                continue  # token vencido: renova e repete uma vez
            resp.raise_for_status()
            itens = resp.json().get("urls") or []
            link = itens[0].get("short_url") if itens else None
            if not link:
                raise ErroGeradorML("resposta sem short_url")
            return link
        raise ErroGeradorML("acesso negado pelo gerador")

    def _link_afiliado(self, base: str, extras: dict | None = None) -> str:
        params = [f"{k}={quote(v, safe='')}" for k, v in (extras or {}).items()]
        params += [f"matt_word={self._ml_etiqueta}", f"matt_tool={self._ml_tool}"]
        return f"{base}?{'&'.join(params)}"

    def _produto_do_link_social(self, url: str, contexto: str = "") -> str | None:
        """Caminho do produto (/p/MLB...) que o link social divulga."""
        buffer = ""
        with self._sessao.get(url, stream=True, timeout=self.TIMEOUT) as resp:
            # produto único: o bloco de métricas está no início do HTML
            for pedaco in resp.iter_content(32768, decode_unicode=False):
                buffer += pedaco.decode("utf-8", "ignore")
                m = self._ML_SOCIAL_RE.search(buffer)
                if m:
                    if m["produto"].startswith("MLB"):
                        return f"/p/{m['produto']}"
                    if m["item"].startswith("MLB"):
                        return f"/{m['item'][:3]}-{m['item'][3:]}"
                    return None
                if len(buffer) > self.ML_PAGINA_MAX:
                    break
        # página de lista (vários produtos): casa o nome da mensagem com a lista
        return self._produto_por_titulo(buffer, contexto)

    @classmethod
    def _tokens(cls, texto: str) -> set[str]:
        texto = sem_acentos(remover_emojis(URL_RE.sub(" ", texto)).lower())
        return {t for t in re.findall(r"[a-z0-9]+", texto)
                if len(t) > 1 and t not in cls._STOP}

    def _produto_por_titulo(self, html: str, contexto: str) -> str | None:
        """Só devolve um produto se o casamento for claro; senão, None."""
        msg = self._tokens(contexto)
        if not msg:
            return None

        candidatos = {}
        for slug, pid in self._ML_LISTA_RE.findall(html):
            candidatos.setdefault(pid, slug)

        pontuados = []
        for pid, slug in candidatos.items():
            tokens = self._tokens(slug.replace("-", " "))
            comuns = msg & tokens
            if len(comuns) >= 3 and tokens:
                pontuados.append((len(comuns) / (len(msg) * len(tokens)) ** 0.5, pid))

        pontuados.sort(reverse=True)
        if not pontuados or pontuados[0][0] < self.ML_LISTA_SCORE_MIN:
            return None
        if len(pontuados) > 1 and pontuados[0][0] - pontuados[1][0] < self.ML_LISTA_MARGEM:
            logger.warning("Casamento ambíguo na lista; link mantido")
            return None
        return f"/p/{pontuados[0][1]}"

    # ---------- Shopee ----------

    def _shopee(self, url: str, host: str) -> str:
        if not (self._shopee_id and self._shopee_secret):
            logger.warning("Credenciais da Shopee ausentes; link mantido")
            return url

        # O link curto vai direto à API (sem seguir redirects até a página
        # do produto, que levava ~1s). Links longos perdem a query de rastreio.
        original = url
        if host not in self.SHOPEE_CURTOS:
            url = url.split("?")[0]

        payload = json.dumps({
            "query": "mutation{generateShortLink(input:{originUrl:%s}){shortLink}}"
                     % json.dumps(url)
        }, separators=(",", ":"))

        ts = str(int(time.time()))
        assinatura = hashlib.sha256(
            f"{self._shopee_id}{ts}{payload}{self._shopee_secret}".encode()
        ).hexdigest()

        resp = self._sessao.post(
            self.SHOPEE_API,
            data=payload.encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": (
                    f"SHA256 Credential={self._shopee_id}, "
                    f"Timestamp={ts}, Signature={assinatura}"
                ),
            },
            timeout=self.TIMEOUT,
        )
        dados = resp.json()
        link = (((dados.get("data") or {}).get("generateShortLink") or {})
                .get("shortLink"))
        if not link:
            logger.warning("Shopee não retornou link: %s", dados.get("errors"))
            return original
        return link
