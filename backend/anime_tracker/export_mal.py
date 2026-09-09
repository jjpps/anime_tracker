"""Gera o XML no formato de export do MyAnimeList.

Importável em myanimelist.net/import.php e em anilist.co/settings/import.

Duas diferenças em relação ao exemplo do CrunchyExporter:

  1. **`series_animedb_id` é preenchido.** Lá o campo vai vazio e o import
     depende de casar por título, que é o passo mais frágil de tudo. Aqui o id
     vem do catálogo cruzado e passa pelo double check contra a API do MAL.

  2. **Uma entrada por obra, não por temporada da CR.** One Piece tem 24
     "temporadas" na Crunchyroll e uma única obra no MAL; emitir 24 nós com o
     mesmo `series_animedb_id` faria o import brigar consigo mesmo.
"""

import logging
import xml.etree.ElementTree as ET

from .progress import progresso_da_temporada

log = logging.getLogger("anime_tracker.export")

# só o que o import realmente usa; o resto do formato é ruído histórico
STATUS_ASSISTINDO = "Watching"
STATUS_COMPLETO = "Completed"
STATUS_PLANEJADO = "Plan to Watch"


def status_de(assistidos, total):
    if not assistidos:
        return STATUS_PLANEJADO
    if total and assistidos >= total:
        return STATUS_COMPLETO
    return STATUS_ASSISTINDO


def agrupar_por_obra(linhas, assistidos_por_temporada):
    """Consolida temporadas da CR em uma entrada por mal_id.

    Quando várias temporadas apontam para a mesma obra, vence o maior
    progresso: são arcos da mesma numeração, não coisas distintas."""
    por_obra = {}
    for linha in linhas:
        chave = linha["mal_id"]
        assistidos = assistidos_por_temporada.get(
            (linha["series_id"], linha["season_number"]), set()
        )
        # o total da obra no MAL tem prioridade sobre a contagem da CR
        total = linha["mal_episodes"] or linha["anilist_episodes"] or 0
        progresso = progresso_da_temporada(assistidos, total)

        atual = por_obra.get(chave)
        if atual is None or progresso > atual["progresso"]:
            por_obra[chave] = {
                "mal_id": chave,
                "titulo": linha["mal_title"] or linha["anilist_title"] or linha["series_title"],
                "total": total,
                "progresso": progresso,
                "temporadas": 1 if atual is None else atual["temporadas"] + 1,
            }
        elif atual is not None:
            atual["temporadas"] += 1
    return list(por_obra.values())


def montar_xml(entradas):
    raiz = ET.Element("myanimelist")
    info = ET.SubElement(raiz, "myinfo")
    ET.SubElement(info, "user_export_type").text = "1"  # 1 = anime
    ET.SubElement(info, "user_total_anime").text = str(len(entradas))

    for e in entradas:
        no = ET.SubElement(raiz, "anime")
        ET.SubElement(no, "series_animedb_id").text = str(e["mal_id"])
        ET.SubElement(no, "series_title").text = e["titulo"]
        ET.SubElement(no, "series_episodes").text = str(e["total"] or 0)
        ET.SubElement(no, "my_watched_episodes").text = str(e["progresso"])
        ET.SubElement(no, "my_status").text = status_de(e["progresso"], e["total"])
        ET.SubElement(no, "my_score").text = "0"
        # sem isso o MAL ignora a linha quando o anime já está na lista
        ET.SubElement(no, "update_on_import").text = "1"

    arvore = ET.ElementTree(raiz)
    ET.indent(arvore, space="  ")
    return arvore


def exportar(conn, caminho, apenas_confirmados=False):
    """Escreve o XML e devolve o resumo do que entrou."""
    from . import db
    from .progress import watched_by_season

    historico = [dict(r) for r in conn.execute("SELECT * FROM watch_history")]
    for e in historico:
        e["fully_watched"] = bool(e["fully_watched"])
    assistidos = watched_by_season(historico)

    linhas = db.matches_para_exportar(conn)
    if apenas_confirmados:
        linhas = [linha for linha in linhas if linha["review_status"] == "confirmed"]

    entradas = agrupar_por_obra(linhas, assistidos)
    montar_xml(entradas).write(caminho, encoding="utf-8", xml_declaration=True)

    resumo = {
        "arquivo": str(caminho),
        "obras": len(entradas),
        "temporadas": len(linhas),
        "completas": sum(1 for e in entradas if status_de(e["progresso"], e["total"]) == STATUS_COMPLETO),
        "assistindo": sum(1 for e in entradas if status_de(e["progresso"], e["total"]) == STATUS_ASSISTINDO),
        "planejadas": sum(1 for e in entradas if status_de(e["progresso"], e["total"]) == STATUS_PLANEJADO),
    }
    log.info("XML gerado: %(obras)d obras de %(temporadas)d temporadas em %(arquivo)s", resumo)
    return resumo
