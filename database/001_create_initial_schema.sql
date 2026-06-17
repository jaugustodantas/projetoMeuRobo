-- Schema inicial do projetoMeuRobo.
-- Execute este arquivo conectado ao banco PostgreSQL do projeto.
--
-- Exemplo, a partir da raiz do projeto:
-- psql -U projeto_meu_robo_user -d projeto_meu_robo -f database/001_create_initial_schema.sql

BEGIN;

CREATE TABLE IF NOT EXISTS titulos_busca (
    id BIGSERIAL PRIMARY KEY,
    titulo TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_titulos_busca_titulo UNIQUE (titulo)
);

CREATE TABLE IF NOT EXISTS localidades_busca (
    id BIGSERIAL PRIMARY KEY,
    localidade TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_localidades_busca_localidade UNIQUE (localidade)
);

CREATE TABLE IF NOT EXISTS execucoes_robo (
    id BIGSERIAL PRIMARY KEY,
    plataforma TEXT NOT NULL,
    iniciada_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalizada_em TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'rodando',
    vagas_encontradas INTEGER NOT NULL DEFAULT 0,
    vagas_novas INTEGER NOT NULL DEFAULT 0,
    vagas_duplicadas INTEGER NOT NULL DEFAULT 0,
    mensagem_erro TEXT,
    CONSTRAINT ck_execucoes_robo_plataforma
        CHECK (plataforma IN ('linkedin', 'indeed')),
    CONSTRAINT ck_execucoes_robo_status
        CHECK (status IN ('rodando', 'finalizada', 'finalizada_com_erros', 'falhou')),
    CONSTRAINT ck_execucoes_robo_contadores
        CHECK (
            vagas_encontradas >= 0
            AND vagas_novas >= 0
            AND vagas_duplicadas >= 0
        )
);

CREATE TABLE IF NOT EXISTS vagas (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    titulo_vaga TEXT,
    empresa TEXT,
    localidade_extraida TEXT,
    descricao_vaga TEXT,
    conteudo_extraido_em TIMESTAMPTZ,
    url_acessivel BOOLEAN,
    erro_extracao TEXT,
    plataforma TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'encontrada',
    nota_aderencia INTEGER,
    titulo_busca_id BIGINT REFERENCES titulos_busca(id) ON DELETE SET NULL,
    localidade_busca_id BIGINT REFERENCES localidades_busca(id) ON DELETE SET NULL,
    execucao_robo_id BIGINT REFERENCES execucoes_robo(id) ON DELETE SET NULL,
    encontrada_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizada_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_vagas_url UNIQUE (url),
    CONSTRAINT ck_vagas_plataforma
        CHECK (plataforma IN ('linkedin', 'indeed')),
    CONSTRAINT ck_vagas_status
        CHECK (
            status IN (
                'encontrada',
                'vou_aplicar',
                'aplicada',
                'entrevista',
                'recusada',
                'descartada'
            )
        ),
    CONSTRAINT ck_vagas_nota_aderencia
        CHECK (nota_aderencia IS NULL OR nota_aderencia BETWEEN 0 AND 10)
);

CREATE TABLE IF NOT EXISTS erros_execucao (
    id BIGSERIAL PRIMARY KEY,
    execucao_id BIGINT NOT NULL REFERENCES execucoes_robo(id) ON DELETE CASCADE,
    titulo_busca_id BIGINT REFERENCES titulos_busca(id) ON DELETE SET NULL,
    localidade_busca_id BIGINT REFERENCES localidades_busca(id) ON DELETE SET NULL,
    mensagem_erro TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_titulos_busca_ativo
    ON titulos_busca (ativo);

CREATE INDEX IF NOT EXISTS idx_localidades_busca_ativo
    ON localidades_busca (ativo);

CREATE INDEX IF NOT EXISTS idx_vagas_status
    ON vagas (status);

CREATE INDEX IF NOT EXISTS idx_vagas_plataforma
    ON vagas (plataforma);

CREATE INDEX IF NOT EXISTS idx_vagas_nota_aderencia
    ON vagas (nota_aderencia);

CREATE INDEX IF NOT EXISTS idx_vagas_url_acessivel
    ON vagas (url_acessivel);

CREATE INDEX IF NOT EXISTS idx_vagas_encontrada_em
    ON vagas (encontrada_em);

CREATE INDEX IF NOT EXISTS idx_vagas_titulo_busca_id
    ON vagas (titulo_busca_id);

CREATE INDEX IF NOT EXISTS idx_vagas_localidade_busca_id
    ON vagas (localidade_busca_id);

CREATE INDEX IF NOT EXISTS idx_vagas_execucao_robo_id
    ON vagas (execucao_robo_id);

CREATE INDEX IF NOT EXISTS idx_erros_execucao_execucao_id
    ON erros_execucao (execucao_id);

COMMIT;
