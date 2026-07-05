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
from datetime import date, datetime, timedelta
from pathlib import Path

API_PROPOSTA = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
API_PUBLICACAO = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
PAGE_SIZE = 50
HERE = Path(__file__).resolve().parent
ESTADO_PATH = HERE / "estado.json"
DATASET_PATH = HERE / "dataset.json"
NOVOS_PATH = HERE / "novos.json"

# Modo incremental: janela de dias (para trás) de publicações a re-buscar a cada execução.
# Cobre o atraso D-3 do PNCP e eventuais execuções que falharam. Roda em ~10-15 min.
LOOKBACK_DIAS = 5
# Modalidades iteradas no incremental (o endpoint /publicacao exige informar a modalidade).
# Escolhidas a partir da distribuição real das obras na base completa: Concorrência
# Eletrônica (4)=65%, Pregão Eletrônico (6)=19%, Credenciamento (12)=8%, Concorrência
# Presencial (5)=2.6%, Pré-qualificação (11)=2.1%, Pregão Presencial (7)=0.3% → ~97% de
# cobertura. Dispensa (8) e Inexigibilidade (9) têm volume gigante e quase nenhuma obra —
# ficam de fora do incremental (são capturadas pelo bootstrap --full).
MODALIDADES = [4, 6, 12, 5, 11, 7]

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
MAX_TENTATIVAS = 4
REQ_TIMEOUT = 25  # falha rápido em página morta; retries cobrem instabilidade
PAUSA_ENTRE_PAGINAS = 0.5  # espaçar reduz 429 e, no total, tende a ser mais rápido
# Se mais que esta fração das páginas falhar, abortamos sem publicar (não sobrescreve
# a última base boa com um resultado parcial enganoso).
LIMITE_FALHAS = 0.08


# Estrutura vazia (usada para HTTP 204 / corpo vazio = "sem resultados", não é falha).
VAZIO = {"data": [], "totalPaginas": 0, "totalRegistros": 0}


def _buscar_url(url):
    """Retorna o JSON da URL (ou VAZIO para 204/sem conteúdo), ou None se falhar."""
    req = urllib.request.Request(url, headers=HEADERS)
    for tentativa in range(MAX_TENTATIVAS):
        ultima = tentativa == MAX_TENTATIVAS - 1
        try:
            with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as resp:
                if resp.status == 204:
                    return VAZIO
                corpo = resp.read().decode("utf-8").strip()
                return json.loads(corpo) if corpo else VAZIO
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


def _coletar_paginado(primeira_url, url_para_pagina, rotulo):
    """Coleta todas as páginas de uma consulta paginada, tolerando falhas de página."""
    primeira = _buscar_url(primeira_url)
    if primeira is None:
        raise RuntimeError(f"Não foi possível obter a primeira página do PNCP ({rotulo}).")
    total_paginas = primeira.get("totalPaginas", 1) or 1
    total_registros = primeira.get("totalRegistros", 0) or 0

    limite = int(os.environ.get("MAX_PAGINAS", "0")) or total_paginas
    limite = min(limite, total_paginas)

    todos = list(primeira.get("data", []) or [])
    falhas = 0
    for pagina in range(2, limite + 1):
        d = _buscar_url(url_para_pagina(pagina))
        if d is None:
            falhas += 1
            print(f"  [aviso] {rotulo} página {pagina} falhou — pulando", flush=True)
        else:
            todos.extend(d.get("data", []) or [])
        time.sleep(PAUSA_ENTRE_PAGINAS)

    if limite > 1 and falhas / (limite - 1) > LIMITE_FALHAS:
        raise RuntimeError(
            f"Muitas páginas falharam em {rotulo} ({falhas}/{limite - 1}) — abortando."
        )
    return todos, total_registros


def coletar_full():
    """Bootstrap: varre TODAS as contratações com proposta em aberto (Brasil, ~660 páginas)."""
    data_final = (date.today() + timedelta(days=365 * 3)).strftime("%Y%m%d")

    def url(p):
        return f"{API_PROPOSTA}?dataFinal={data_final}&pagina={p}&tamanhoPagina={PAGE_SIZE}"

    print("Modo FULL: varredura completa de propostas abertas (Brasil).", flush=True)
    brutos, total = _coletar_paginado(url(1), url, "proposta")
    print(f"Coletados {len(brutos)} registros (total aberto Brasil: {total}).", flush=True)
    return brutos, total


def coletar_incremental():
    """Incremental: busca publicações dos últimos LOOKBACK_DIAS dias, por modalidade.

    Volume pequeno (dezenas de páginas) — roda em poucos minutos e evita o bloqueio
    por volume que a varredura completa sofre nos IPs do GitHub Actions.
    """
    di = (date.today() - timedelta(days=LOOKBACK_DIAS)).strftime("%Y%m%d")
    df = date.today().strftime("%Y%m%d")
    print(f"Modo INCREMENTAL: publicações de {di} a {df}, por modalidade.", flush=True)

    brutos = []
    for mod in MODALIDADES:
        base = f"{API_PUBLICACAO}?dataInicial={di}&dataFinal={df}&codigoModalidadeContratacao={mod}"

        def url(p, base=base):
            return f"{base}&pagina={p}&tamanhoPagina={PAGE_SIZE}"

        primeira = _buscar_url(url(1))
        if primeira is None or not primeira.get("data"):
            continue
        parciais, _ = _coletar_paginado(url(1), url, f"publicacao mod {mod}")
        brutos.extend(parciais)
        print(f"  modalidade {mod}: {len(parciais)} registros", flush=True)
        time.sleep(PAUSA_ENTRE_PAGINAS)

    # Dedup por numeroControlePNCP (uma contratação pode vir repetida entre páginas).
    vistos, unicos = set(), []
    for it in brutos:
        nc = it.get("numeroControlePNCP")
        if nc and nc not in vistos:
            vistos.add(nc)
            unicos.append(it)
    print(f"Incremental: {len(unicos)} contratações únicas na janela.", flush=True)
    return unicos


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


def ainda_aberta(item, agora_iso):
    """True se a proposta ainda está em aberto (encerramento no futuro ou desconhecido)."""
    dt = item.get("dataEncerramentoProposta")
    return (dt is None) or (dt >= agora_iso)


def main():
    modo_full = "--full" in sys.argv

    # Base acumulada existente (dataset.json versionado no repo).
    base = {}
    if DATASET_PATH.exists():
        try:
            for i in json.loads(DATASET_PATH.read_text()).get("itens", []):
                base[i["numeroControlePNCP"]] = i
        except Exception:
            base = {}

    ids_antes = set(base.keys())

    if modo_full:
        brutos, _ = coletar_full()
        # No full, a base é substituída pelo conjunto recém-varrido.
        base = {}
    else:
        brutos = coletar_incremental()

    # Filtra engenharia civil e mescla na base (adiciona/atualiza por id).
    novos_engenharia = 0
    for it in brutos:
        if eh_engenharia_civil(it.get("objetoCompra", "")):
            reg = classificar(it)
            base[reg["numeroControlePNCP"]] = reg
            novos_engenharia += 1

    # Poda: remove contratações cuja proposta já encerrou (não estão mais abertas).
    agora_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    itens = [i for i in base.values() if ainda_aberta(i, agora_iso)]
    itens.sort(key=lambda x: (x["dataEncerramentoProposta"] or "9999"))

    # Novos para o e-mail: engenharia que apareceu AGORA (não estava na base) e está aberta.
    novos = [i for i in itens if i["numeroControlePNCP"] not in ids_antes]

    dataset = {
        "build": int(time.time()),
        "geradoEm": date.today().isoformat(),
        "modo": "full" if modo_full else "incremental",
        "totalEngenhariaCivil": len(itens),
        "itens": itens,
    }
    DATASET_PATH.write_text(json.dumps(dataset, ensure_ascii=False, indent=0), encoding="utf-8")
    NOVOS_PATH.write_text(json.dumps(novos, ensure_ascii=False, indent=0), encoding="utf-8")
    ESTADO_PATH.write_text(json.dumps({"ids": sorted(base.keys())}, ensure_ascii=False), encoding="utf-8")

    print(f"Editais de engenharia em aberto na base: {len(itens)}")
    print(f"Novos nesta execução: {len(novos)}")
    print(f"TEM_NOVOS={1 if novos else 0}")


if __name__ == "__main__":
    sys.exit(main())
