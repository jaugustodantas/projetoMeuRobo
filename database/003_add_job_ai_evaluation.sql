-- Adiciona campos para avaliação automática de aderência das vagas ao currículo.
-- Execute conectado ao banco PostgreSQL do projeto:
--
-- psql -U projeto_meu_robo_user -d projeto_meu_robo -f database/003_add_job_ai_evaluation.sql

BEGIN;

ALTER TABLE vagas
    ADD COLUMN IF NOT EXISTS recomendacao_ia TEXT,
    ADD COLUMN IF NOT EXISTS justificativa_ia TEXT,
    ADD COLUMN IF NOT EXISTS pontos_positivos_ia TEXT,
    ADD COLUMN IF NOT EXISTS pontos_alerta_ia TEXT,
    ADD COLUMN IF NOT EXISTS tecnologias_ia TEXT,
    ADD COLUMN IF NOT EXISTS senioridade_ia TEXT,
    ADD COLUMN IF NOT EXISTS analisada_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS erro_analise_ia TEXT;

CREATE INDEX IF NOT EXISTS idx_vagas_recomendacao_ia
    ON vagas (recomendacao_ia);

CREATE INDEX IF NOT EXISTS idx_vagas_analisada_em
    ON vagas (analisada_em);

COMMIT;
