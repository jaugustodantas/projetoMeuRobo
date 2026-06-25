from meu_robo.db import get_connection


def obter_configuracao() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT permitir_remoto, permitir_hibrido, permitir_presencial,
                       palavras_titulo_bloqueadas, empresas_bloqueadas,
                       localidades_bloqueadas, atualizado_em
                FROM linkedin_search_config
                WHERE id = 1
                """
            )
            row = cur.fetchone()

            if row:
                return row

            cur.execute(
                """
                INSERT INTO linkedin_search_config (
                    id,
                    permitir_remoto,
                    permitir_hibrido,
                    permitir_presencial,
                    palavras_titulo_bloqueadas,
                    empresas_bloqueadas,
                    localidades_bloqueadas
                )
                VALUES (1, FALSE, FALSE, TRUE, '', '', '')
                RETURNING permitir_remoto, permitir_hibrido, permitir_presencial,
                          palavras_titulo_bloqueadas, empresas_bloqueadas,
                          localidades_bloqueadas, atualizado_em
                """
            )
            return cur.fetchone()


def atualizar_configuracao(
    permitir_remoto: bool,
    permitir_hibrido: bool,
    permitir_presencial: bool,
    palavras_titulo_bloqueadas: str,
    empresas_bloqueadas: str,
    localidades_bloqueadas: str,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO linkedin_search_config (
                    id,
                    permitir_remoto,
                    permitir_hibrido,
                    permitir_presencial,
                    palavras_titulo_bloqueadas,
                    empresas_bloqueadas,
                    localidades_bloqueadas,
                    atualizado_em
                )
                VALUES (1, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE
                SET permitir_remoto = EXCLUDED.permitir_remoto,
                    permitir_hibrido = EXCLUDED.permitir_hibrido,
                    permitir_presencial = EXCLUDED.permitir_presencial,
                    palavras_titulo_bloqueadas = EXCLUDED.palavras_titulo_bloqueadas,
                    empresas_bloqueadas = EXCLUDED.empresas_bloqueadas,
                    localidades_bloqueadas = EXCLUDED.localidades_bloqueadas,
                    atualizado_em = NOW()
                """,
                (
                    permitir_remoto,
                    permitir_hibrido,
                    permitir_presencial,
                    palavras_titulo_bloqueadas.strip(),
                    empresas_bloqueadas.strip(),
                    localidades_bloqueadas.strip(),
                ),
            )
