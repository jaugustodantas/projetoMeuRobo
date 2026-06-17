-- Adiciona campos para salvar o conteudo da vaga capturado pelo navegador logado.
-- Execute conectado ao banco PostgreSQL do projeto:
--
-- psql -U projeto_meu_robo_user -d projeto_meu_robo -f database/002_add_job_extracted_content.sql

BEGIN;

ALTER TABLE vagas
    ADD COLUMN IF NOT EXISTS empresa TEXT,
    ADD COLUMN IF NOT EXISTS localidade_extraida TEXT,
    ADD COLUMN IF NOT EXISTS descricao_vaga TEXT,
    ADD COLUMN IF NOT EXISTS conteudo_extraido_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS url_acessivel BOOLEAN,
    ADD COLUMN IF NOT EXISTS erro_extracao TEXT;

CREATE INDEX IF NOT EXISTS idx_vagas_url_acessivel
    ON vagas (url_acessivel);

COMMIT;
