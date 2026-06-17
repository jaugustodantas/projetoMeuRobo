from meu_robo.db import get_connection


def criar_titulo(titulo: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO titulos_busca (titulo)
                VALUES (%s)
                ON CONFLICT (titulo)
                DO UPDATE SET atualizado_em = NOW()
                RETURNING id
                """,
                (titulo.strip(),),
            )

            row = cur.fetchone()

    return row["id"]


def listar_titulos() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, titulo, ativo, criado_em, atualizado_em
                FROM titulos_busca
                ORDER BY titulo
                """
            )

            return cur.fetchall()


def alterar_ativo(titulo_id: int, ativo: bool) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE titulos_busca
                SET ativo = %s, atualizado_em = NOW()
                WHERE id = %s
                """,
                (ativo, titulo_id),
            )


def excluir_titulo(titulo_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM titulos_busca WHERE id = %s", (titulo_id,))


def listar_titulos_ativos() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, titulo
                FROM titulos_busca
                WHERE ativo = TRUE
                ORDER BY titulo
                """
            )

            return cur.fetchall()
