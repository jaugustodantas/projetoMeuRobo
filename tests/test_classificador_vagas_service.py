import unittest

from meu_robo.services.classificador_vagas_service import _normalizar_recomendacao


class NormalizarRecomendacaoTests(unittest.TestCase):
    def test_forca_alta_para_notas_altas(self) -> None:
        self.assertEqual(_normalizar_recomendacao(8, "descartar"), "alta")
        self.assertEqual(_normalizar_recomendacao(10, "media"), "alta")

    def test_forca_media_para_notas_intermediarias(self) -> None:
        self.assertEqual(_normalizar_recomendacao(6, "descartar"), "media")
        self.assertEqual(_normalizar_recomendacao(7, "alta"), "media")

    def test_preserva_baixa_quando_ha_revisao_manual(self) -> None:
        self.assertEqual(_normalizar_recomendacao(6, "baixa"), "baixa")

    def test_forca_descartar_para_notas_baixas(self) -> None:
        self.assertEqual(_normalizar_recomendacao(5, "alta"), "descartar")
        self.assertEqual(_normalizar_recomendacao(1, None), "descartar")


if __name__ == "__main__":
    unittest.main()
