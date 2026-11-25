
"""Busca do mapeamento sistematico no Scopus (campo TITLE-ABS-KEY).

Reexecutavel. Le a chave de acesso da variavel de ambiente ELSEVIER_API_KEY.
Gravacao incremental por expressao: uma reexecucao pula os codigos ja
presentes no CSV de saida, de modo que a interrupcao nao perde trabalho.
"""
import csv, json, os, sys, time, urllib.error, urllib.parse, urllib.request

BASE      = "https://api.elsevier.com/content/search/scopus"
PAGINA    = 25      # maximo aceito pela interface
TETO_NAV  = 5000    # start deve permanecer abaixo deste valor
ANO_INI   = 2014
ANO_FIM   = 2027
TENTATIVAS= 5
TIMEOUT   = 120

DIR   = os.path.dirname(os.path.abspath(__file__))
PROT  = os.path.join(DIR, "protocolo_msl.json")
SAIDA = os.path.join(DIR, "busca_bruta.csv")
META  = os.path.join(DIR, "busca_meta.json")

COLS = ["codigo","eixo","fatia","eid","doi","titulo","ano","veiculo","tipo",
        "subtipo","citacoes","issn","volume","paginas","autores","afiliacao"]


def _get(params):
    url = BASE + "?" + urllib.parse.urlencode(params)
    for t in range(TENTATIVAS):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and t < TENTATIVAS - 1:
                time.sleep(5 * (t + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if t < TENTATIVAS - 1:
                time.sleep(5 * (t + 1)); continue
            raise


def total(query, key):
    d = _get({"query": query, "count": 1, "apiKey": key})
    return int(d["search-results"]["opensearch:totalResults"])


def _linha(e, codigo, eixo, fatia):
    autores = e.get("dc:creator") or ""
    return {
        "codigo": codigo, "eixo": eixo, "fatia": fatia,
        "eid": e.get("eid",""), "doi": e.get("prism:doi",""),
        "titulo": (e.get("dc:title") or "").replace("\n", " ").strip(),
        "ano": (e.get("prism:coverDate") or "")[:4],
        "veiculo": e.get("prism:publicationName",""),
        "tipo": e.get("prism:aggregationType",""),
        "subtipo": e.get("subtypeDescription",""),
        "citacoes": e.get("citedby-count",""),
        "issn": e.get("prism:issn","") or e.get("prism:isbn","") or "",
        "volume": e.get("prism:volume",""), "paginas": e.get("prism:pageRange",""),
        "autores": autores,
        "afiliacao": (e.get("affiliation") or [{}])[0].get("affilname","") if e.get("affiliation") else "",
    }


def recupera(query, codigo, eixo, fatia, key, escrever):
    """Pagina uma consulta por inteiro. Devolve (declarado, recuperado)."""
    decl = total(query, key)
    visto, start = 0, 0
    while start < min(decl, TETO_NAV):
        d = _get({"query": query, "count": PAGINA, "start": start,
                  "apiKey": key, "sort": "coverDate"})
        ent = d["search-results"].get("entry", [])
        if not ent or "error" in ent[0]:
            break
        escrever([_linha(e, codigo, eixo, fatia) for e in ent])
        visto += len(ent); start += PAGINA
    return decl, visto


def main():
    key = os.environ.get("ELSEVIER_API_KEY")
    if not key:
        sys.exit("ELSEVIER_API_KEY ausente no ambiente.")
    prot = json.load(open(PROT, encoding="utf-8"))

    feitos = set()
    if os.path.exists(SAIDA):
        with open(SAIDA, encoding="utf-8") as f:
            feitos = {r["codigo"] for r in csv.DictReader(f)}
    novo = not os.path.exists(SAIDA)
    fh = open(SAIDA, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=COLS)
    if novo:
        w.writeheader()

    def escrever(linhas):
        w.writerows(linhas); fh.flush()

    meta = json.load(open(META, encoding="utf-8")) if os.path.exists(META) else {}
    meta.setdefault("expressoes", {})

    for e in prot["expressoes"]:
        cod = e["codigo"]
        if cod in feitos:
            print(f"{cod}: ja recuperada, pulando", flush=True); continue
        q = e["expressao"] + f" AND PUBYEAR > {ANO_INI - 1}"
        decl = total(q, key)
        reg = {"declarado": decl, "fatias": []}
        if decl < TETO_NAV:
            d, v = recupera(q, cod, e["eixo"], "integral", key, escrever)
            reg["recuperado"] = v
            reg["fatias"].append({"fatia": "integral", "declarado": d, "recuperado": v})
        else:                                   # fatiamento por ano
            tot_v = 0
            for ano in range(ANO_INI, ANO_FIM + 1):
                qa = e["expressao"] + f" AND PUBYEAR = {ano}"
                d, v = recupera(qa, cod, e["eixo"], str(ano), key, escrever)
                tot_v += v
                reg["fatias"].append({"fatia": str(ano), "declarado": d, "recuperado": v})
            reg["recuperado"] = tot_v
        reg["integral"] = reg["recuperado"] >= min(decl, TETO_NAV)
        meta["expressoes"][cod] = reg
        json.dump(meta, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{cod}: declarado {decl}, recuperado {reg['recuperado']}"
              f"{'' if reg['integral'] else '  <<< INCOMPLETA'}", flush=True)

    fh.close()
    tot_d = sum(r["declarado"] for r in meta["expressoes"].values())
    tot_r = sum(r["recuperado"] for r in meta["expressoes"].values())
    meta["totais"] = {"declarado": tot_d, "recuperado": tot_r,
                      "expressoes": len(meta["expressoes"])}
    json.dump(meta, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\\nTOTAL declarado {tot_d} | recuperado {tot_r}")


if __name__ == "__main__":
    main()
