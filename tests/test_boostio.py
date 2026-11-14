import asyncio
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as app  # noqa: E402
from services.confere_duplicada_service import ConfereDuplicadaService  # noqa: E402
from services.formata_mensagem_service import FormataMensagemService  # noqa: E402

BASE = (
    "🔥💥 PROMOÇÃO 🔥\n"
    "🖥️ Placa mãe MSI A520M-A PRO\n"
    "💰 Por R$ 332,00 no Pix\n"
    "🎟️ Cupons: https://exemplo.com/cupons\n"
    "🛒 Compre aqui: https://loja.com/produto?a=1&b=2\n"
)


class FakeClient:
    def __init__(self, falhar=False, atraso=0.0):
        self.enviados, self.falhar, self.atraso = [], falhar, atraso

    async def send_message(self, destino, texto, **kw):
        await asyncio.sleep(self.atraso)
        if self.falhar:
            raise RuntimeError("falha de rede")
        self.enviados.append(("texto", texto))

    async def send_file(self, destino, file, caption, **kw):
        await asyncio.sleep(self.atraso)
        if self.falhar:
            raise RuntimeError("falha de rede")
        self.enviados.append(("midia", file, caption))


def novo_dup(tmp):
    return ConfereDuplicadaService(os.path.join(tmp, "u.json"))


def preparar(tmp):
    app.confere_duplicada = novo_dup(tmp)
    return app.confere_duplicada


class Duplicatas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_identica(self):
        d = novo_dup(self.tmp)
        t = d.reservar(BASE)
        asyncio.run(d.confirmar(t))
        self.assertIsNone(d.reservar(BASE))

    def test_emoji_pontuacao_caixa(self):
        d = novo_dup(self.tmp)
        asyncio.run(d.confirmar(d.reservar(BASE)))
        variante = BASE.replace("🔥", "⚡").upper().replace(": ", " - ")
        self.assertIsNone(d.reservar(variante))

    def test_preco_alterado(self):
        d = novo_dup(self.tmp)
        asyncio.run(d.confirmar(d.reservar(BASE)))
        self.assertIsNone(d.reservar(BASE.replace("332,00", "329,90")))

    def test_acima_80(self):
        d = novo_dup(self.tmp)
        a = "Placa-mae MSI A520M-A PRO com frete gratis por R$ 332 na loja Kabum hoje"
        b = "Placa-mae MSI A520M-A PRO com frete gratis por R$ 332 na loja Pichau hoje"
        self.assertGreaterEqual(d.similaridade(d.normalizar(a), d.normalizar(b)), 0.8)
        asyncio.run(d.confirmar(d.reservar(a)))
        self.assertIsNone(d.reservar(b))

    def test_abaixo_80(self):
        d = novo_dup(self.tmp)
        asyncio.run(d.confirmar(d.reservar(BASE)))
        outra = "SSD Kingston NV2 1TB NVMe por R$ 349,90 https://loja.com/ssd"
        self.assertLess(d.similaridade(d.normalizar(BASE), d.normalizar(outra)), 0.8)
        self.assertIsNotNone(d.reservar(outra))

    def test_reinicio(self):
        d = novo_dup(self.tmp)
        asyncio.run(d.confirmar(d.reservar(BASE)))
        d2 = novo_dup(self.tmp)  # "reinicia"
        self.assertIsNone(d2.reservar(BASE))

    def test_referencia_e_ultima_publicada(self):
        # B foi reservada mas falhou: A (similar a B) ainda pode ser publicada
        d = novo_dup(self.tmp)
        t = d.reservar(BASE)
        d.liberar(t)
        self.assertIsNotNone(d.reservar(BASE))

    def test_tempo_comparacao(self):
        d = novo_dup(self.tmp)
        a = d.normalizar(BASE * 3)
        b = d.normalizar(BASE.replace("A520M", "B550M") * 3)
        t = time.perf_counter()
        for _ in range(200):
            d.similaridade(a, b)
        ms = (time.perf_counter() - t) / 200 * 1000
        print(f"\n  similaridade: {ms:.3f} ms/comparação")
        self.assertLess(ms, 5)


class Fluxo(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dup = preparar(self.tmp)

    async def test_envio_sem_imagem_e_afiliado(self):
        c = FakeClient()
        original = app.troca_afiliado
        app.troca_afiliado = SimpleNamespace(
            executar=lambda m: m.replace("loja.com", "afiliado.loja.com/ref123"))
        try:
            self.assertTrue(await app.processar_promocao(c, BASE, None))
        finally:
            app.troca_afiliado = original
        tipo, texto = c.enviados[0]
        self.assertEqual(tipo, "texto")
        print("\n" + texto)
        self.assertNotIn("🔥💥", texto)
        self.assertIn("🔷 <b>Comprar:</b>\nhttps://afiliado.loja.com/ref123/produto?a=1&amp;b=2", texto)
        self.assertNotIn("https://loja.com", texto)
        self.assertIn("R$ 332,00", texto)

    async def test_envio_com_imagem(self):
        c = FakeClient()
        origem = SimpleNamespace(photo="FOTO", video=None)
        await app.processar_promocao(c, BASE, origem)
        self.assertEqual(c.enviados[0][0:2], ("midia", "FOTO"))

    async def test_falha_nao_registra(self):
        c = FakeClient(falhar=True)
        with self.assertRaises(RuntimeError):
            await app.processar_promocao(c, BASE, None)
        self.assertEqual(self.dup._ultima, "")
        self.assertFalse(os.path.exists(self.dup._arquivo))
        ok = FakeClient()
        self.assertTrue(await app.processar_promocao(ok, BASE, None))  # reenvio permitido

    async def test_simultaneas_sem_duplicar(self):
        c = FakeClient(atraso=0.2)
        res = await asyncio.gather(*[
            app.processar_promocao(c, BASE.replace("332,00", f"33{i},00"), None)
            for i in range(10)
        ])
        self.assertEqual(sum(res), 1)
        self.assertEqual(len(c.enviados), 1)

    async def test_simultaneas_distintas_e_lentas_em_paralelo(self):
        c = FakeClient(atraso=0.3)
        msgs = [
            "SSD Kingston NV2 1TB NVMe R$ 349 https://a.com/1",
            "Monitor Samsung Odyssey G5 27 polegadas R$ 1.299 https://b.com/2",
            "Gabinete Gamer Redragon Wheeljack mid tower R$ 289 https://c.com/3",
            "Mouse Logitech G203 R$ 99 https://d.com/4",
        ]
        t = time.perf_counter()
        res = await asyncio.gather(*[app.processar_promocao(c, m, None) for m in msgs])
        dt = time.perf_counter() - t
        print(f"\n  4 promoções distintas (0,3s cada): {dt:.2f}s")
        self.assertEqual(sum(res), 4)
        self.assertLess(dt, 0.6)

    async def test_falha_em_andamento_libera_reserva(self):
        c_ruim, c_bom = FakeClient(falhar=True, atraso=0.1), FakeClient()
        r = await asyncio.gather(
            app.processar_promocao(c_ruim, BASE, None),
            app.processar_promocao(c_bom, BASE, None),
            return_exceptions=True)
        self.assertIsInstance(r[0], RuntimeError)
        self.assertIs(r[1], False)  # limitação documentada


class Formatacao(unittest.TestCase):
    f = FormataMensagemService()

    def test_sem_invencao(self):
        s = self.f.executar("Mouse Logitech G203 https://x.com/1")
        self.assertNotIn("R$", s)
        self.assertNotIn("Cupom", s)
        self.assertIn("<b>MOUSE</b>", s)

    def test_de_por_cupom_desconto(self):
        s = self.f.executar("🔥 RTX 4060 de R$ 2.200,00 por R$ 1.899,00 15% OFF\nCupom: BOOST10\nhttps://l.com/g")
        print("\n" + s)
        self.assertIn("<b>PLACA DE VÍDEO</b>", s)
        self.assertIn("<code>BOOST10</code>", s)
        self.assertIn("15% OFF", s)
        self.assertIn("De <s>R$ 2.200,00</s>", s)

    def test_preco_nao_e_cortado_em_tres_digitos(self):
        casos = [
            ("Ryzen 5 5600 por R$ 1912,00 no Pix", "R$ 1912,00"),
            ("SSD 1TB por R$ 12345,90", "R$ 12345,90"),
            ("RTX 4060 de R$ 2400 por R$ 1899", "R$ 1899"),
            ("SSD por R$ 1.912,50", "R$ 1.912,50"),
            ("Cabo por R$99", "R$ 99"),
        ]
        for msg, esperado in casos:
            self.assertIn(f"<b>{esperado}</b>", self.f.executar(msg + "\nhttps://x.com/a"), msg)

    def test_codigo_de_cupom_com_um_link_e_compra(self):
        for msg in ("Processador AMD Ryzen 7 9800X3D - R$ 1912 -Cupom: 11DO11X3D https://tidd.ly/4z6o2xd",
                    "Processador AMD Ryzen 7 9800X3D R$ 1912\nCupom: 11DO11X3D\nhttps://tidd.ly/4z6o2xd"):
            s = self.f.executar(msg)
            self.assertIn("<b>Comprar:</b>\nhttps://tidd.ly/4z6o2xd", s)
            self.assertNotIn("Cupons disponíveis", s)
            self.assertIn("<code>11DO11X3D</code>", s)

    def test_so_emojis_da_paleta(self):
        from services.texto_util import remover_emojis
        permitidos = set("🔷🔹🟦🔵⚪")
        amostras = [
            "🧠💥 Processador AMD Ryzen 5 5500 de R$ 900 por R$ 699 15% OFF Cupom: BOOST10 https://a.com/x",
            "Mouse Logitech G203 R$ 99 https://b.com/y",
            "RTX 4060 Gigabyte por R$ 1.899 no pix\nCupons: https://c.com/cupons\nhttps://c.com/p",
            "Monitor LG 27 R$ 899",
        ]
        for a in amostras:
            saida = self.f.executar(a)
            usados = {c for c in saida if remover_emojis(c) == "" and c not in "\u200d\ufe0f"
                      and c not in "▬"}
            self.assertLessEqual(usados, permitidos, saida)

    def test_html_escapado(self):
        self.assertIn("&lt;b&gt;", self.f.executar("SSD <b>x</b> 1TB"))


class Afiliado(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from services.troca_afiliado_service import TrocaAfiliadoService
        env = {"SHOPEE_APP_ID": "123", "SHOPEE_SECRET": "segredo", "ML_ETIQUETA": "minhaetiqueta", "ML_COOKIE": ""}
        with mock.patch.dict(os.environ, env):
            self.s = TrocaAfiliadoService()
        self.chamadas = []

        def post(url, data, headers, timeout):
            self.chamadas.append((data, headers))
            r = mock.Mock()
            r.json.return_value = {"data": {"generateShortLink": {"shortLink": "https://s.shopee.com.br/MINHA"}}}
            return r
        self.s._sessao.post = post

    def test_ml_produto(self):
        url = "https://www.mercadolivre.com.br/ryzen/p/MLB19444510?pdp_filters=item_id%3AMLB521&matt_tool=83591963&gclid=abc"
        out = self.s.executar(f"Ryzen {url}")
        self.assertIn("/p/MLB19444510?pdp_filters=item_id%3AMLB521&matt_word=minhaetiqueta&matt_tool=74191004", out)
        self.assertNotIn("gclid", out)
        self.assertNotIn("83591963", out)

    def test_ml_meli_la_produto_pela_pagina_social(self):
        from unittest import mock
        html = ('x<script>melidata("add","event_data",{"landing":"affiliate-profile",'
                '"trigger":{"category_id":"MLB1693","item_id":"","product_id":"MLB19444510",'
                '"user_product_id":"NOT_APPLY"}});</script>').encode()
        resp = mock.MagicMock()
        resp.__enter__.return_value.iter_content.return_value = [html]
        self.s._sessao.get = lambda *a, **k: resp
        out = self.s.executar("Ryzen https://meli.la/abc")
        self.assertIn("https://www.mercadolivre.com.br/p/MLB19444510?matt_word=minhaetiqueta&matt_tool=74191004", out)

    def _com_gerador_oficial(self):
        from unittest import mock
        from services.troca_afiliado_service import TrocaAfiliadoService
        env = {"ML_ETIQUETA": "minhaetiqueta", "ML_COOKIE": "_d2id=abc; ssid=xyz"}
        with mock.patch.dict(os.environ, env):
            s = TrocaAfiliadoService()
        pagina = mock.Mock(url="https://www.mercadolivre.com.br/afiliados/linkbuilder",
                           text='<meta name="csrf-token" content="TOKEN123">')
        s._sessao_ml.get = lambda *a, **k: pagina
        return s

    def test_ml_oficial_devolve_short_url(self):
        from unittest import mock
        s = self._com_gerador_oficial()
        chamadas = []
        def post(url, json, headers, timeout):
            chamadas.append((json, headers))
            r = mock.Mock(status_code=200)
            r.json.return_value = {"urls": [{"short_url": "https://meli.la/OFICIAL"}]}
            return r
        s._sessao_ml.post = post
        out = s.executar("Ryzen https://www.mercadolivre.com.br/ryzen/p/MLB19444510?gclid=x")
        self.assertIn("https://meli.la/OFICIAL", out)
        self.assertEqual(chamadas[0][0], {"urls": ["https://www.mercadolivre.com.br/ryzen/p/MLB19444510"], "tag": "minhaetiqueta"})
        self.assertEqual(chamadas[0][1]["x-csrf-token"], "TOKEN123")
        s.executar("Ryzen https://www.mercadolivre.com.br/ryzen/p/MLB19444510?gclid=x")
        self.assertEqual(len(chamadas), 1)  # cache

    def test_ml_oficial_falha_usa_parametrizado_sem_cache(self):
        s = self._com_gerador_oficial()
        def post(*a, **k):
            raise ConnectionError("fora")
        s._sessao_ml.post = post
        msg = "https://www.mercadolivre.com.br/ryzen/p/MLB19444510"
        out = s.executar(msg)
        self.assertIn("matt_word=minhaetiqueta", out)
        self.assertNotIn(msg, s._cache)

    def test_ml_cookie_expirado(self):
        from unittest import mock
        s = self._com_gerador_oficial()
        s._sessao_ml.get = lambda *a, **k: mock.Mock(url="https://www.mercadolivre.com.br/login", text="")
        out = s.executar("https://www.mercadolivre.com.br/ryzen/p/MLB19444510")
        self.assertIn("matt_word=minhaetiqueta", out)

    LISTA_HTML = "".join(
        f'<a href="https://www.mercadolivre.com.br/{slug}/p/{pid}?x=1">' for slug, pid in [
            ("notebook-acer-aspire-go-15-ag15-51p-59sm-intel-core-i5-120u-8gb-ram-256gb-ssd-linux", "MLB78838496"),
            ("celular-samsung-galaxy-s25-ultra-5g-256gb-12gb-cam-quad-cor-prata", "MLB45524778"),
            ("celular-samsung-galaxy-s26-fe-128gb-8gb-ram-tela-67-grafite", "MLB78949324"),
            ("carregador-portatil-power-bank-basike-20000mah-225w-rapido", "MLB52327865"),
        ]).encode()

    def _resolver_lista(self, mensagem):
        from unittest import mock
        s = self._com_gerador_oficial()
        resp = mock.MagicMock()
        resp.__enter__.return_value.iter_content.return_value = [self.LISTA_HTML]
        s._sessao.get = lambda *a, **k: resp
        s._ml_oficial = lambda url: "OFICIAL<" + url.rsplit("/", 1)[-1] + ">"
        return s.executar(mensagem)

    def test_lista_casa_produto_pelo_titulo(self):
        out = self._resolver_lista(
            "Notebook Acer Aspire Go 15 Intel Core i5 8GB 256GB SSD por R$ 2.199 https://meli.la/lista")
        self.assertIn("OFICIAL<MLB78838496>", out)

    def test_lista_sem_casamento_mantem_original(self):
        msg = "SSD Kingston NV2 1TB NVMe por R$ 349 https://meli.la/lista"
        self.assertEqual(self._resolver_lista(msg), msg)

    def test_lista_ambigua_mantem_original(self):
        msg = "Celular Samsung Galaxy em oferta https://meli.la/lista"
        out = self._resolver_lista(msg)
        self.assertEqual(out, msg)

    def test_ml_social_sem_produto_mantem(self):
        from unittest import mock
        resp = mock.MagicMock()
        resp.__enter__.return_value.iter_content.return_value = [b"<html>sem bloco</html>"]
        self.s._sessao.get = lambda *a, **k: resp
        msg = "https://meli.la/abc"
        self.assertEqual(self.s.executar(msg), msg)

    def test_ml_social_e_outros_inalterados(self):
        msg = "https://kabum.com.br/p/1 https://www.mercadolivre.com.br/institucional"
        self.assertEqual(self.s.executar(msg), msg)

    def test_shopee_assinatura_e_troca(self):
        import hashlib
        out = self.s.executar("Mouse https://shopee.com.br/produto-i.1.2?x=1")
        self.assertIn("https://s.shopee.com.br/MINHA", out)
        data, headers = self.chamadas[0]
        ts = headers["Authorization"].split("Timestamp=")[1].split(",")[0]
        sig = hashlib.sha256(f"123{ts}{data.decode()}segredo".encode()).hexdigest()
        self.assertIn(sig, headers["Authorization"])
        self.s.executar("Mouse https://shopee.com.br/produto-i.1.2?x=1")
        self.assertEqual(len(self.chamadas), 1)  # cache

    def test_falha_mantem_original(self):
        def post(*a, **k):
            raise TimeoutError()
        self.s._sessao.post = post
        msg = "https://shopee.com.br/x-i.1.2"
        self.assertEqual(self.s.executar(msg), msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
