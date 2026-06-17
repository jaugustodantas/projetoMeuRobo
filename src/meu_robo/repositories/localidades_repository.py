from meu_robo.db import get_connection


def criar_localidade(localidade: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO localidades_busca (localidade)
                VALUES (%s)
                ON CONFLICT (localidade)
                DO UPDATE SET atualizado_em = NOW()
                RETURNING id
                """,
                (localidade.strip(),),
            )

            row = cur.fetchone()

    return row["id"]


def listar_localidades() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, localidade, ativo, criado_em, atualizado_em
                FROM localidades_busca
                ORDER BY localidade
                """
            )

            return cur.fetchall()


def alterar_ativo(localidade_id: int, ativo: bool) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE localidades_busca
                SET ativo = %s, atualizado_em = NOW()
                WHERE id = %s
                """,
                (ativo, localidade_id),
            )


def excluir_localidade(localidade_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM localidades_busca WHERE id = %s", (localidade_id,))


def listar_localidades_ativas() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, localidade
                FROM localidades_busca
                WHERE ativo = TRUE
                ORDER BY localidade
                """
            )

            return cur.fetchall()
