BEGIN;

CREATE TABLE IF NOT EXISTS linkedin_search_config (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    permitir_remoto BOOLEAN NOT NULL DEFAULT FALSE,
    permitir_hibrido BOOLEAN NOT NULL DEFAULT FALSE,
    permitir_presencial BOOLEAN NOT NULL DEFAULT TRUE,
    palavras_titulo_bloqueadas TEXT NOT NULL DEFAULT '',
    empresas_bloqueadas TEXT NOT NULL DEFAULT '',
    localidades_bloqueadas TEXT NOT NULL DEFAULT '',
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_linkedin_search_config_singleton CHECK (id = 1)
);

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
ON CONFLICT (id) DO NOTHING;

COMMIT;
