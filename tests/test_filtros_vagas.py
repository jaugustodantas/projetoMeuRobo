import unittest

from meu_robo.robo.filtros_vagas import (
    vaga_aprovada_por_configuracao_linkedin,
    vaga_compativel_com_busca,
)


class VagaCompativelComBuscaTests(unittest.TestCase):
    def test_aceita_titulo_analista(self) -> None:
        self.assertTrue(vaga_compativel_com_busca("Analista", "Analista de Dados Pleno"))

    def test_aceita_sinonimo_em_ingles(self) -> None:
        self.assertFalse(vaga_compativel_com_busca("Analista", "QA Analyst Senior"))

    def test_rejeita_estagio_mesmo_com_termo_compativel(self) -> None:
        self.assertFalse(vaga_compativel_com_busca("Analista", "Estágio em Analista de BI"))

    def test_rejeita_titulo_sem_relacao_com_busca(self) -> None:
        self.assertFalse(vaga_compativel_com_busca("Coordenador", "Assistente Fiscal"))

    def test_aceita_lideranca_em_ingles(self) -> None:
        self.assertFalse(vaga_compativel_com_busca("Líder de equipe", "Engineering Team Leader"))

    def test_rejeita_aprendiz_para_busca_de_lideranca(self) -> None:
        self.assertFalse(vaga_compativel_com_busca("Líder de equipe", "Jovem Aprendiz Administrativo"))

    def test_busca_exata_aceita_frase_completa(self) -> None:
        self.assertTrue(
            vaga_compativel_com_busca(
                "Analista de PCP",
                "Analista de PCP Pleno",
                modo_correspondencia="exata",
            )
        )

    def test_busca_exata_rejeita_mesma_familia_sem_frase_completa(self) -> None:
        self.assertFalse(
            vaga_compativel_com_busca(
                "Analista de PCP",
                "Analista de Dados Pleno",
                modo_correspondencia="exata",
            )
        )

    def test_busca_generica_de_titulo_especifico_usa_familia_do_cargo(self) -> None:
        self.assertTrue(
            vaga_compativel_com_busca(
                "Analista de PCP",
                "Analista de Suprimentos",
                modo_correspondencia="generica",
            )
        )

    def test_busca_generica_analista_aceita_qualquer_titulo_com_analista(self) -> None:
        self.assertTrue(
            vaga_compativel_com_busca(
                "Analista",
                "Analista de PCP Senior",
                modo_correspondencia="generica",
            )
        )

    def test_busca_generica_analista_rejeita_titulo_sem_analista(self) -> None:
        self.assertFalse(
            vaga_compativel_com_busca(
                "Analista",
                "Coordenador de PCP",
                modo_correspondencia="generica",
            )
        )

    def test_config_linkedin_rejeita_vaga_remota_quando_so_presencial(self) -> None:
        self.assertFalse(
            vaga_aprovada_por_configuracao_linkedin(
                {
                    "permitir_remoto": False,
                    "permitir_hibrido": False,
                    "permitir_presencial": True,
                    "palavras_titulo_bloqueadas": "",
                    "empresas_bloqueadas": "",
                    "localidades_bloqueadas": "",
                },
                "Analista de Dados",
                "Empresa X",
                "Brasil",
                "Vaga 100% remota com home office",
            )
        )

    def test_config_linkedin_aceita_vaga_presencial_quando_presencial_habilitado(self) -> None:
        self.assertTrue(
            vaga_aprovada_por_configuracao_linkedin(
                {
                    "permitir_remoto": False,
                    "permitir_hibrido": False,
                    "permitir_presencial": True,
                    "palavras_titulo_bloqueadas": "",
                    "empresas_bloqueadas": "",
                    "localidades_bloqueadas": "",
                },
                "Analista de PCP",
                "Empresa X",
                "Uberlandia MG",
                "Atuacao presencial na unidade",
            )
        )

    def test_config_linkedin_rejeita_empresa_bloqueada(self) -> None:
        self.assertFalse(
            vaga_aprovada_por_configuracao_linkedin(
                {
                    "permitir_remoto": True,
                    "permitir_hibrido": True,
                    "permitir_presencial": True,
                    "palavras_titulo_bloqueadas": "",
                    "empresas_bloqueadas": "Empresa X",
                    "localidades_bloqueadas": "",
                },
                "Analista de PCP",
                "Empresa X",
                "Uberlandia MG",
                "Atuacao presencial na unidade",
            )
        )


if __name__ == "__main__":
    unittest.main()
