BEGIN;

ALTER TABLE titulos_busca
    ADD COLUMN IF NOT EXISTS modo_correspondencia TEXT NOT NULL DEFAULT 'generica';

ALTER TABLE titulos_busca
    DROP CONSTRAINT IF EXISTS ck_titulos_busca_modo_correspondencia;

ALTER TABLE titulos_busca
    ADD CONSTRAINT ck_titulos_busca_modo_correspondencia
        CHECK (modo_correspondencia IN ('generica', 'exata'));

CREATE INDEX IF NOT EXISTS idx_titulos_busca_modo_correspondencia
    ON titulos_busca (modo_correspondencia);

COMMIT;
