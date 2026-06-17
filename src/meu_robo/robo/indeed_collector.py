import asyncio
from urllib.parse import quote_plus

from playwright.async_api import Page, async_playwright

from meu_robo.repositories import execucoes_repository, localidades_repository, titulos_repository
from meu_robo.repositories.vagas_repository import (
    atualizar_dados_extraidos,
    normalizar_url,
    salvar_vaga,
)

INDEED_SEARCH_URL = "https://br.indeed.com/jobs"
MAX_PAGES_PER_COMBINATION = 3
RESULTS_PER_PAGE = 10


def _build_search_url(titulo: str, localidade: str, page_index: int) -> str:
    start = page_index * RESULTS_PER_PAGE
    return (
        f"{INDEED_SEARCH_URL}?q={quote_plus(titulo)}"
        f"&l={quote_plus(localidade)}"
        f"&start={start}"
    )


def _clean_text(text: str | None) -> str | None:
    if not text:
        return None

    cleaned = " ".join(text.split())
    return cleaned or None


async def _close_popups_if_available(page: Page) -> None:
    selectors = [
        "button[aria-label*='fechar']",
        "button[aria-label*='Fechar']",
        "button[aria-label*='close']",
        "button[aria-label*='Close']",
        "#onetrust-accept-btn-handler",
        "button:has-text('Aceitar')",
        "button:has-text('Entendi')",
        "button:has-text('Not now')",
        "button:has-text('Agora não')",
    ]

    for selector in selectors:
        try:
            button = page.locator(selector).first
            if await button.count() == 0:
                continue
            await button.click(timeout=1500)
            await asyncio.sleep(0.5)
        except Exception:
            continue


async def _first_text(page: Page, selectors: list[str]) -> str | None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            text = _clean_text(await locator.inner_text(timeout=3000))
            if text:
                return text
        except Exception:
            continue
    return None


async def _collect_urls_from_current_page(page: Page) -> list[str]:
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(2)
    await _close_popups_if_available(page)

    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass

    urls = await page.locator(
        "a[href*='/viewjob?jk='], a[href*='jk='], a[data-jk]"
    ).evaluate_all(
        """
        elements => elements
            .map(element => {
                const href = element.href || element.getAttribute('href');
                const jobKey = element.getAttribute('data-jk');
                return href || (jobKey ? `/viewjob?jk=${jobKey}` : null);
            })
            .filter(Boolean)
        """
    )

    normalized = []
    seen = set()
    for url in urls:
        normalized_url = normalizar_url(url)
        if "indeed.com/viewjob?jk=" not in normalized_url:
            continue
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        normalized.append(normalized_url)

    return normalized


async def _extract_job_details(page: Page, url: str) -> dict:
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(2)
    await _close_popups_if_available(page)

    titulo = await _first_text(
        page,
        [
            "[data-testid='jobsearch-JobInfoHeader-title']",
            "h1.jobsearch-JobInfoHeader-title",
            "h1",
        ],
    )
    empresa = await _first_text(
        page,
        [
            "[data-testid='inlineHeader-companyName']",
            "[data-company-name='true']",
            ".jobsearch-InlineCompanyRating a",
            ".jobsearch-InlineCompanyRating",
        ],
    )
    localidade = await _first_text(
        page,
        [
            "[data-testid='job-location']",
            ".jobsearch-JobInfoHeader-subtitle div",
            "#jobLocationText",
        ],
    )
    descricao = await _first_text(
        page,
        [
            "#jobDescriptionText",
            "[data-testid='jobsearch-jobDescriptionText']",
            ".jobsearch-jobDescriptionText",
        ],
    )

    if not descricao:
        return {
            "titulo_vaga": titulo,
            "empresa": empresa,
            "localidade_extraida": localidade,
            "descricao_vaga": None,
            "url_acessivel": False,
            "erro_extracao": "Conteudo principal da vaga nao encontrado.",
        }

    return {
        "titulo_vaga": titulo,
        "empresa": empresa,
        "localidade_extraida": localidade,
        "descricao_vaga": descricao,
        "url_acessivel": True,
        "erro_extracao": None,
    }


async def executar_coleta_indeed() -> dict[str, int]:
    titulos = titulos_repository.listar_titulos_ativos()
    localidades = localidades_repository.listar_localidades_ativas()
    execucao_id = execucoes_repository.iniciar_execucao("indeed")

    vagas_encontradas = 0
    vagas_novas = 0
    vagas_duplicadas = 0
    houve_erro = False

    if not titulos or not localidades:
        execucoes_repository.finalizar_execucao(
            execucao_id=execucao_id,
            status="finalizada",
            vagas_encontradas=0,
            vagas_novas=0,
            vagas_duplicadas=0,
            mensagem_erro="Cadastre pelo menos um título e uma localidade ativos.",
        )
        return {
            "vagas_encontradas": 0,
            "vagas_novas": 0,
            "vagas_duplicadas": 0,
        }

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="pt-BR",
    )
    page = await context.new_page()

    try:
        for titulo in titulos:
            for localidade in localidades:
                try:
                    for page_index in range(MAX_PAGES_PER_COMBINATION):
                        search_url = _build_search_url(
                            titulo["titulo"],
                            localidade["localidade"],
                            page_index,
                        )
                        await page.goto(search_url, wait_until="domcontentloaded")
                        urls = await _collect_urls_from_current_page(page)

                        if not urls and page_index == 0:
                            break

                        for url in urls:
                            vagas_encontradas += 1
                            vaga_id, created = salvar_vaga(
                                url=url,
                                plataforma="indeed",
                                titulo_busca_id=titulo["id"],
                                localidade_busca_id=localidade["id"],
                                execucao_robo_id=execucao_id,
                            )

                            try:
                                dados_extraidos = await _extract_job_details(page, url)
                                atualizar_dados_extraidos(vaga_id, **dados_extraidos)
                            except Exception as exc:
                                atualizar_dados_extraidos(
                                    vaga_id,
                                    url_acessivel=False,
                                    erro_extracao=str(exc),
                                )

                            if created:
                                vagas_novas += 1
                            else:
                                vagas_duplicadas += 1

                except Exception as exc:
                    houve_erro = True
                    execucoes_repository.registrar_erro(
                        execucao_id=execucao_id,
                        titulo_busca_id=titulo["id"],
                        localidade_busca_id=localidade["id"],
                        mensagem_erro=str(exc),
                    )
                    continue

        status = "finalizada_com_erros" if houve_erro else "finalizada"
        execucoes_repository.finalizar_execucao(
            execucao_id=execucao_id,
            status=status,
            vagas_encontradas=vagas_encontradas,
            vagas_novas=vagas_novas,
            vagas_duplicadas=vagas_duplicadas,
        )
        return {
            "vagas_encontradas": vagas_encontradas,
            "vagas_novas": vagas_novas,
            "vagas_duplicadas": vagas_duplicadas,
        }
    except Exception as exc:
        execucoes_repository.finalizar_execucao(
            execucao_id=execucao_id,
            status="falhou",
            vagas_encontradas=vagas_encontradas,
            vagas_novas=vagas_novas,
            vagas_duplicadas=vagas_duplicadas,
            mensagem_erro=str(exc),
        )
        raise
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()


def main() -> None:
    asyncio.run(executar_coleta_indeed())


if __name__ == "__main__":
    main()
