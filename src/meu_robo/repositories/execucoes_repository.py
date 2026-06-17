from meu_robo.db import get_connection


def iniciar_execucao(plataforma: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execucoes_robo (plataforma, status)
                VALUES (%s, 'rodando')
                RETURNING id
                """,
                (plataforma,),
            )
            row = cur.fetchone()

    return row["id"]


def finalizar_execucao(
    execucao_id: int,
    status: str,
    vagas_encontradas: int,
    vagas_novas: int,
    vagas_duplicadas: int,
    mensagem_erro: str | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE execucoes_robo
                SET finalizada_em = NOW(),
                    status = %s,
                    vagas_encontradas = %s,
                    vagas_novas = %s,
                    vagas_duplicadas = %s,
                    mensagem_erro = %s
                WHERE id = %s
                """,
                (
                    status,
                    vagas_encontradas,
                    vagas_novas,
                    vagas_duplicadas,
                    mensagem_erro,
                    execucao_id,
                ),
            )


def registrar_erro(
    execucao_id: int,
    mensagem_erro: str,
    titulo_busca_id: int | None = None,
    localidade_busca_id: int | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erros_execucao (
                    execucao_id,
                    titulo_busca_id,
                    localidade_busca_id,
                    mensagem_erro
                )
                VALUES (%s, %s, %s, %s)
                """,
                (execucao_id, titulo_busca_id, localidade_busca_id, mensagem_erro),
            )


def ultima_execucao() -> dict | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, plataforma, iniciada_em, finalizada_em, status,
                       vagas_encontradas, vagas_novas, vagas_duplicadas, mensagem_erro
                FROM execucoes_robo
                ORDER BY iniciada_em DESC
                LIMIT 1
                """
            )

            return cur.fetchone()


def listar_erros(execucao_id: int) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.id, e.mensagem_erro, e.criado_em,
                       t.titulo,
                       l.localidade
                FROM erros_execucao e
                LEFT JOIN titulos_busca t ON t.id = e.titulo_busca_id
                LEFT JOIN localidades_busca l ON l.id = e.localidade_busca_id
                WHERE e.execucao_id = %s
                ORDER BY e.criado_em DESC
                """,
                (execucao_id,),
            )

            return cur.fetchall()
