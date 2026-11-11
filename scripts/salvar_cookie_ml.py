"""Salva o cookie da sessão da ML no .env (linha ML_COOKIE), sem exibi-lo."""
import getpass
import os

ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

cookie = getpass.getpass("Cole o valor do cabeçalho Cookie (não aparece na tela): ").strip()
cookie = cookie.removeprefix("Cookie:").removeprefix("cookie:").strip()
if "=" not in cookie or "\n" in cookie:
    raise SystemExit("Valor inválido: cole só o conteúdo do cabeçalho Cookie, em uma linha.")

linhas = open(ENV, encoding="utf-8").read().splitlines() if os.path.exists(ENV) else []
linhas = [l for l in linhas if not l.startswith("ML_COOKIE=")]
linhas.append(f"ML_COOKIE={cookie}")
with open(ENV, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas) + "\n")
os.chmod(ENV, 0o600)
print(f"ML_COOKIE salvo no .env ({len(cookie)} caracteres).")
