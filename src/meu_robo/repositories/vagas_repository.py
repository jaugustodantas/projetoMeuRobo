from urllib.parse import parse_qs, urlparse

from psycopg import sql

from meu_robo.db import get_connection

STATUS_VAGAS = (
    "encontrada",
    "vou_aplicar",
    "aplicada",
    "entrevista",
    "recusada",
    "descartada",
)


def normalizar_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)

    if "linkedin.com" in parsed.netloc:
        current_job_id = parse_qs(parsed.query).get("currentJobId", [""])[0]
        if current_job_id.isdigit():
            return f"https://www.linkedin.com/jobs/view/{current_job_id}"

    if "linkedin.com" in parsed.netloc and "/jobs/view/" in parsed.path:
        parts = [part for part in parsed.path.split("/") if part]
        try:
            job_id = parts[parts.index("view") + 1]
            if job_id.isdigit():
                return f"https://www.linkedin.com/jobs/view/{job_id}"
        except (ValueError, IndexError):
            return url.split("?", 1)[0].rstrip("/")

    if "linkedin.com" in parsed.netloc and "/jobs-guest/jobs/api/jobPosting/" in parsed.path:
        job_id = parsed.path.rstrip("/").split("/")[-1]
        if job_id.isdigit():
            return f"https://www.linkedin.com/jobs/view/{job_id}"

    if "indeed." in parsed.netloc:
        job_key = parse_qs(parsed.query).get("jk", [""])[0].strip()
        if job_key:
            return f"https://br.indeed.com/viewjob?jk={job_key}"

    return url.split("?", 1)[0].rstrip("/")


def salvar_vaga(
    url: str,
    plataforma: str,
    titulo_busca_id: int,
    localidade_busca_id: int,
    execucao_robo_id: int | None = None,
    titulo_vaga: str | None = None,
) -> tuple[int, bool]:
    url_normalizada = normalizar_url(url)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vagas (
                    url,
                    titulo_vaga,
                    plataforma,
                    titulo_busca_id,
                    localidade_busca_id,
                    execucao_robo_id
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING
                RETURNING id
                """,
                (
                    url_normalizada,
                    titulo_vaga,
                    plataforma,
                    titulo_busca_id,
                    localidade_busca_id,
                    execucao_robo_id,
                ),
            )
            row = cur.fetchone()

            if row:
                return row["id"], True

            cur.execute("SELECT id FROM vagas WHERE url = %s", (url_normalizada,))
            existing = cur.fetchone()

    return existing["id"], False


def atualizar_status(vaga_id: int, status: str) -> None:
    if status not in STATUS_VAGAS:
        raise ValueError(f"Status inválido: {status}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE vagas
                SET status = %s, atualizada_em = NOW()
                WHERE id = %s
                """,
                (status, vaga_id),
            )


def atualizar_nota(vaga_id: int, nota_aderencia: int | None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE vagas
                SET nota_aderencia = %s, atualizada_em = NOW()
                WHERE id = %s
                """,
                (nota_aderencia, vaga_id),
            )


def atualizar_dados_extraidos(
    vaga_id: int,
    titulo_vaga: str | None = None,
    empresa: str | None = None,
    localidade_extraida: str | None = None,
    descricao_vaga: str | None = None,
    url_acessivel: bool | None = None,
    erro_extracao: str | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE vagas
                SET titulo_vaga = COALESCE(%s, titulo_vaga),
                    empresa = %s,
                    localidade_extraida = %s,
                    descricao_vaga = %s,
                    conteudo_extraido_em = NOW(),
                    url_acessivel = %s,
                    erro_extracao = %s,
                    atualizada_em = NOW()
                WHERE id = %s
                """,
                (
                    titulo_vaga,
                    empresa,
                    localidade_extraida,
                    descricao_vaga,
                    url_acessivel,
                    erro_extracao,
                    vaga_id,
                ),
            )


def listar_vagas(filtros: dict | None = None) -> list[dict]:
    filtros = filtros or {}
    clauses = []
    values = []

    if filtros.get("status"):
        clauses.append("v.status = %s")
        values.append(filtros["status"])

    if filtros.get("plataforma"):
        clauses.append("v.plataforma = %s")
        values.append(filtros["plataforma"])

    if filtros.get("titulo_busca_id"):
        clauses.append("v.titulo_busca_id = %s")
        values.append(int(filtros["titulo_busca_id"]))

    if filtros.get("localidade_busca_id"):
        clauses.append("v.localidade_busca_id = %s")
        values.append(int(filtros["localidade_busca_id"]))

    if filtros.get("nota_minima") not in (None, ""):
        clauses.append("v.nota_aderencia >= %s")
        values.append(int(filtros["nota_minima"]))

    if filtros.get("texto"):
        clauses.append(
            """
            (
                v.url ILIKE %s
                OR COALESCE(v.titulo_vaga, '') ILIKE %s
                OR COALESCE(v.empresa, '') ILIKE %s
                OR COALESCE(v.descricao_vaga, '') ILIKE %s
            )
            """
        )
        term = f"%{filtros['texto']}%"
        values.extend([term, term, term, term])

    where = sql.SQL("")
    if clauses:
        where = sql.SQL("WHERE ") + sql.SQL(" AND ").join(sql.SQL(c) for c in clauses)

    query = sql.SQL(
        """
        SELECT v.id, v.url, v.titulo_vaga, v.empresa, v.localidade_extraida,
               v.descricao_vaga, v.conteudo_extraido_em, v.url_acessivel,
               v.erro_extracao, v.plataforma, v.status,
               v.nota_aderencia, v.encontrada_em, v.atualizada_em,
               t.titulo AS titulo_busca,
               l.localidade AS localidade_busca
        FROM vagas v
        LEFT JOIN titulos_busca t ON t.id = v.titulo_busca_id
        LEFT JOIN localidades_busca l ON l.id = v.localidade_busca_id
        {where}
        ORDER BY v.encontrada_em DESC, v.id DESC
        """
    ).format(where=where)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
            return cur.fetchall()


def contar_vagas_por_status() -> dict[str, int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM vagas
                GROUP BY status
                """
            )
            rows = cur.fetchall()

    totals = {status: 0 for status in STATUS_VAGAS}
    totals.update({row["status"]: row["total"] for row in rows})
    return totals
