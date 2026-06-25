import re
import unicodedata

TERMOS_EXCLUIDOS_TITULO = (
    "aprendiz",
    "estagio",
    "estagiario",
    "estagiaria",
    "intern",
    "internship",
    "jovem aprendiz",
    "trainee",
)

TERMOS_COMPATIVEIS_POR_BUSCA = {
    "analista": ("analista", "analyst"),
    "coordenador": ("coordenador", "coordenadora", "coordinator"),
    "lider de equipe": ("lider", "leader", "team leader", "lead"),
    "supervisor": ("supervisor", "supervisora"),
}

MODO_CORRESPONDENCIA_GENERICA = "generica"
MODO_CORRESPONDENCIA_EXATA = "exata"


def normalizar_texto(texto: str | None) -> str:
    if not texto:
        return ""

    texto_normalizado = unicodedata.normalize("NFKD", texto)
    texto_sem_acento = "".join(
        caractere
        for caractere in texto_normalizado
        if not unicodedata.combining(caractere)
    )
    texto_limpo = re.sub(r"[^a-zA-Z0-9]+", " ", texto_sem_acento.lower())
    return re.sub(r"\s+", " ", texto_limpo).strip()


def _contem_termo(texto: str, termo: str) -> bool:
    termo_normalizado = normalizar_texto(termo)
    if not termo_normalizado:
        return False

    padrao = rf"(^|\s){re.escape(termo_normalizado)}(\s|$)"
    return re.search(padrao, texto) is not None


def _quebrar_lista_texto(valor: str | None) -> list[str]:
    if not valor:
        return []
    return [normalizar_texto(item) for item in valor.splitlines() if normalizar_texto(item)]


def _detectar_modalidade(
    titulo_vaga: str | None,
    localidade: str | None,
    descricao_vaga: str | None,
) -> str:
    texto = normalizar_texto(" ".join(filter(None, [titulo_vaga, localidade, descricao_vaga])))

    if any(termo in texto for termo in ("hibrido", "hybrid")):
        return "hibrido"
    if any(termo in texto for termo in ("remoto", "remota", "remote", "home office", "work from home")):
        return "remoto"
    return "presencial"


def _obter_termo_principal_generico(busca_normalizada: str) -> str:
    return busca_normalizada.split(" ", 1)[0].strip()


def vaga_compativel_com_busca(
    titulo_busca: str,
    titulo_vaga: str | None,
    modo_correspondencia: str = MODO_CORRESPONDENCIA_GENERICA,
) -> bool:
    titulo_normalizado = normalizar_texto(titulo_vaga)
    if not titulo_normalizado:
        return False

    if any(_contem_termo(titulo_normalizado, termo) for termo in TERMOS_EXCLUIDOS_TITULO):
        return False

    busca_normalizada = normalizar_texto(titulo_busca)

    if modo_correspondencia == MODO_CORRESPONDENCIA_EXATA:
        return _contem_termo(titulo_normalizado, busca_normalizada)

    termo_principal = _obter_termo_principal_generico(busca_normalizada)
    if not termo_principal:
        return False

    return _contem_termo(titulo_normalizado, termo_principal)


def vaga_aprovada_por_configuracao_linkedin(
    config: dict,
    titulo_vaga: str | None,
    empresa: str | None,
    localidade: str | None,
    descricao_vaga: str | None,
) -> bool:
    modalidade = _detectar_modalidade(titulo_vaga, localidade, descricao_vaga)
    permitidos = {
        "remoto": bool(config.get("permitir_remoto")),
        "hibrido": bool(config.get("permitir_hibrido")),
        "presencial": bool(config.get("permitir_presencial")),
    }

    if not permitidos.get(modalidade, False):
        return False

    titulo_normalizado = normalizar_texto(titulo_vaga)
    empresa_normalizada = normalizar_texto(empresa)
    localidade_normalizada = normalizar_texto(localidade)

    if any(_contem_termo(titulo_normalizado, termo) for termo in _quebrar_lista_texto(config.get("palavras_titulo_bloqueadas"))):
        return False
    if any(_contem_termo(empresa_normalizada, termo) for termo in _quebrar_lista_texto(config.get("empresas_bloqueadas"))):
        return False
    if any(_contem_termo(localidade_normalizada, termo) for termo in _quebrar_lista_texto(config.get("localidades_bloqueadas"))):
        return False

    return True
