from meu_robo.db import get_connection

MODOS_CORRESPONDENCIA = ("generica", "exata")


def criar_titulo(titulo: str, modo_correspondencia: str = "generica") -> int:
    if modo_correspondencia not in MODOS_CORRESPONDENCIA:
        raise ValueError(f"Modo de correspondência inválido: {modo_correspondencia}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO titulos_busca (titulo, modo_correspondencia)
                VALUES (%s, %s)
                ON CONFLICT (titulo)
                DO UPDATE SET
                    modo_correspondencia = EXCLUDED.modo_correspondencia,
                    atualizado_em = NOW()
                RETURNING id
                """,
                (titulo.strip(), modo_correspondencia),
            )

            row = cur.fetchone()

    return row["id"]


def listar_titulos() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, titulo, modo_correspondencia, ativo, criado_em, atualizado_em
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
                SELECT id, titulo, modo_correspondencia
                FROM titulos_busca
                WHERE ativo = TRUE
                ORDER BY titulo
                """
            )

            return cur.fetchall()
