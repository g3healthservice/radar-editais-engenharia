#!/usr/bin/env python3
"""
Radar de editais de engenharia civil / obras / reforma predial no PNCP.

Varre a API pública de consulta do PNCP (todas as contratações com
recebimento de proposta em aberto, Brasil inteiro), filtra por palavras-chave
de engenharia civil e classifica esfera de governo, se aceita Ata de Registro
de Preços (SRP) e indícios de fonte de recurso (MAC/PAP, fundo de saúde,
emenda parlamentar, recursos próprios etc.) a partir do texto disponível.

Uso: python3 buscar_editais.py
Gera: dataset.json (dados completos), novos.json (itens novos desde a
última execução, para o e-mail) e atualiza estado.json (para o diff).
"""
import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

API_BASE = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
PAGE_SIZE = 50
HERE = Path(__file__).resolve().parent
ESTADO_PATH = HERE / "estado.json"
DATASET_PATH = HERE / "dataset.json"
NOVOS_PATH = HERE / "novos.json"

ESFERA_NOMES = {"F": "Federal", "E": "Estadual", "M": "Municipal", "N": "Não informado"}
PODER_NOMES = {"E": "Executivo", "L": "Legislativo", "J": "Judiciário", "N": "Não informado"}


def normalizar(txt):
    if not txt:
        return ""
    nfkd = unicodedata.normalize("NFKD", txt)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.lower()


# Padrões fortes o bastante para não precisar de contexto adicional.
PADROES_DIRETOS = [
    r"reform", r"amplia", r"engenharia civil", r"obras? civ",
    r"obra de engenharia", r"execucao de obra", r"edificac",
    r"impermeabiliza", r"pintura predial", r"cobertura metalica",
    r"revitalizac", r"readequac", r"construcao civil",
]

# Padrões que só valem quando aparecem perto de um termo "predial/edifício".
PADROES_COM_CONTEXTO = [
    (r"manuten\w*", r"predial|edific|telhado|cobertura|estrutural|fachada|instalac\w* (eletric|hidraulic)"),
    (r"construc\w* de", r"unidade|posto|hospital|escola|creche|centro|predio|sede|quadra|ginasio|praca|\bubs\b|\bupa\b|\bcras\b|\bcreas\b"),
    (r"recuperac\w*", r"estrutural|predial|edific"),
    (r"adequac\w*", r"predial|acessibilidade|arquitet"),
    (r"acessibilidade", r"predial|arquitet|fisica"),
    (r"instalac\w* predi", r""),
]

_re_diretos = [re.compile(p) for p in PADROES_DIRETOS]
_re_contexto = [(re.compile(a), re.compile(b) if b else None) for a, b in PADROES_COM_CONTEXTO]


def eh_engenharia_civil(objeto):
    txt = normalizar(objeto)
    for r in _re_diretos:
        if r.search(txt):
            return True
    for r_a, r_b in _re_contexto:
        if r_a.search(txt) and (r_b is None or r_b.search(txt)):
            return True
    return False


FONTE_KEYWORDS = [
    (re.compile(r"\bMAC\b"), "MAC (Média e Alta Complexidade)"),
    (re.compile(r"\bPAP\b"), "PAP"),
    (re.compile(r"\bFNS\b|Fundo Nacional de Sa[uú]de", re.I), "Fundo Nacional de Saúde"),
    (re.compile(r"Fundo Municipal de Sa[uú]de|\bFMS\b", re.I), "Fundo Municipal de Saúde"),
    (re.compile(r"Fundo Estadual de Sa[uú]de|\bFES\b", re.I), "Fundo Estadual de Saúde"),
    (re.compile(r"emenda parlamentar", re.I), "Emenda parlamentar"),
    (re.compile(r"conv[eê]nio", re.I), "Convênio"),
    (re.compile(r"recursos? pr[oó]prios?", re.I), "Recursos próprios"),
    (re.compile(r"recursos? do tesouro", re.I), "Recursos do Tesouro"),
    (re.compile(r"bloco de custeio", re.I), "Bloco de custeio SUS"),
]


def identificar_fonte(objeto, info_complementar):
    texto = f"{objeto or ''} {info_complementar or ''}"
    achados = []
    for regex, nome in FONTE_KEYWORDS:
        if regex.search(texto) and nome not in achados:
            achados.append(nome)
    return achados or ["Não identificado no texto (conferir edital)"]


# Alguns WAFs/servidores tratam o User-Agent padrão do Python (Python-urllib) vindo de
# IP de datacenter com hostilidade (timeout no connect). Um UA de navegador evita isso.
HEADERS = {
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
}
MAX_TENTATIVAS = 6
# Se mais que esta fração das páginas falhar, abortamos sem publicar (não sobrescreve
# a última base boa com um resultado parcial enganoso).
LIMITE_FALHAS = 0.08


def buscar_pagina(pagina, data_final):
    """Retorna o JSON da página, ou None se falhar após todas as tentativas."""
    url = f"{API_BASE}?dataFinal={data_final}&pagina={pagina}&tamanhoPagina={PAGE_SIZE}"
    req = urllib.request.Request(url, headers=HEADERS)
    for tentativa in range(MAX_TENTATIVAS):
        ultima = tentativa == MAX_TENTATIVAS - 1
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429 and not ultima:
                espera = int(e.headers.get("Retry-After", 5 * (tentativa + 1)))
                time.sleep(espera)
                continue
            if e.code >= 500 and not ultima:
                time.sleep(3 * (tentativa + 1))
                continue
            return None
        except (urllib.error.URLError, OSError, TimeoutError, socket.timeout):
            # cobre timeouts de connect/read e quedas de conexão (no Python 3.9
            # socket.timeout não é subclasse de TimeoutError).
            if ultima:
                return None
            time.sleep(3 * (tentativa + 1))
    return None


def coletar_tudo():
    data_final = (date.today() + timedelta(days=365 * 3)).strftime("%Y%m%d")
    primeira = buscar_pagina(1, data_final)
    if primeira is None:
        raise RuntimeError("Não foi possível obter a primeira página do PNCP (API indisponível).")
    total_paginas = primeira.get("totalPaginas", 1)
    total_registros = primeira.get("totalRegistros", 0)
    print(f"Total de contratações com proposta aberta no Brasil: {total_registros} ({total_paginas} páginas)")

    # MAX_PAGINAS: override apenas para teste local rápido (não usado em produção).
    limite = int(os.environ.get("MAX_PAGINAS", "0")) or total_paginas
    limite = min(limite, total_paginas)

    todos = list(primeira.get("data", []))
    falhas = 0
    for pagina in range(2, limite + 1):
        d = buscar_pagina(pagina, data_final)
        if d is None:
            falhas += 1
            print(f"  [aviso] página {pagina} falhou após {MAX_TENTATIVAS} tentativas — pulando")
        else:
            todos.extend(d.get("data", []))
        if pagina % 50 == 0:
            print(f"  ...página {pagina}/{limite} ({falhas} falhas até aqui)")
        time.sleep(0.35)

    if limite > 1 and falhas / (limite - 1) > LIMITE_FALHAS:
        raise RuntimeError(
            f"Muitas páginas falharam ({falhas}/{limite - 1} = "
            f"{100 * falhas / (limite - 1):.0f}%) — abortando sem publicar para não gerar base parcial."
        )
    if falhas:
        print(f"Concluído com {falhas} página(s) pulada(s) de {limite - 1} — dentro do tolerável.")
    return todos, total_registros


# Alguns órgãos preenchem o valor estimado com um sentinela (ex.: 9.999.999.999.999,99)
# ou valores absurdos. Acima de R$ 1 trilhão para uma única contratação é lixo — trata como
# "não informado" para não distorcer o total do dashboard.
LIMITE_VALOR_ABSURDO = 1e12


def sanitizar_valor(v):
    if v is None or v <= 0 or v >= LIMITE_VALOR_ABSURDO:
        return None
    return v


def classificar(item):
    org = item.get("orgaoEntidade", {})
    uni = item.get("unidadeOrgao", {})
    objeto = item.get("objetoCompra", "")
    info = item.get("informacaoComplementar", "")
    return {
        "numeroControlePNCP": item.get("numeroControlePNCP"),
        "orgao": org.get("razaoSocial"),
        "cnpj": org.get("cnpj"),
        "esfera": ESFERA_NOMES.get(org.get("esferaId"), "Não informado"),
        "poder": PODER_NOMES.get(org.get("poderId"), "Não informado"),
        "unidade": uni.get("nomeUnidade"),
        "municipio": uni.get("municipioNome"),
        "uf": uni.get("ufSigla"),
        "codigoIbge": uni.get("codigoIbge"),
        "objeto": objeto,
        "modalidade": item.get("modalidadeNome"),
        "srp": bool(item.get("srp")),
        "valorEstimado": sanitizar_valor(item.get("valorTotalEstimado")),
        "dataEncerramentoProposta": item.get("dataEncerramentoProposta"),
        "dataPublicacaoPncp": item.get("dataPublicacaoPncp"),
        "fonteRecurso": identificar_fonte(objeto, info),
        "linkEdital": item.get("linkSistemaOrigem"),
        "processo": item.get("processo"),
    }


def main():
    brutos, total_geral = coletar_tudo()
    filtrados = [classificar(i) for i in brutos if eh_engenharia_civil(i.get("objetoCompra", ""))]
    filtrados.sort(key=lambda x: (x["dataEncerramentoProposta"] or "9999"))

    ids_atuais = {i["numeroControlePNCP"] for i in filtrados}
    estado_anterior = set()
    if ESTADO_PATH.exists():
        estado_anterior = set(json.loads(ESTADO_PATH.read_text()).get("ids", []))

    novos = [i for i in filtrados if i["numeroControlePNCP"] not in estado_anterior]

    dataset = {
        "build": int(time.time()),
        "geradoEm": date.today().isoformat(),
        "totalAbertoBrasil": total_geral,
        "totalEngenhariaCivil": len(filtrados),
        "itens": filtrados,
    }
    DATASET_PATH.write_text(json.dumps(dataset, ensure_ascii=False, indent=0), encoding="utf-8")
    NOVOS_PATH.write_text(json.dumps(novos, ensure_ascii=False, indent=0), encoding="utf-8")
    ESTADO_PATH.write_text(json.dumps({"ids": sorted(ids_atuais)}, ensure_ascii=False), encoding="utf-8")

    print(f"Filtrados (engenharia civil/reforma/obras): {len(filtrados)}")
    print(f"Novos desde a última execução: {len(novos)}")
    print(f"TEM_NOVOS={1 if novos else 0}")


if __name__ == "__main__":
    sys.exit(main())
