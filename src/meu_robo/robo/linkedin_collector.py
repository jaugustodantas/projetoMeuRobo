import asyncio
from urllib.parse import quote_plus

from playwright.async_api import Page, async_playwright

from meu_robo.config import get_browser_session_path, get_linkedin_credentials
from meu_robo.repositories import execucoes_repository, localidades_repository, titulos_repository
from meu_robo.repositories.vagas_repository import (
    atualizar_dados_extraidos,
    normalizar_url,
    salvar_vaga,
)

LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs/search/"
MAX_PAGES_PER_COMBINATION = 3
RESULTS_PER_PAGE = 25
MANUAL_WAIT_SECONDS = 600


def _build_search_url(titulo: str, localidade: str, page_index: int) -> str:
    start = page_index * RESULTS_PER_PAGE
    return (
        f"{LINKEDIN_SEARCH_URL}?keywords={quote_plus(titulo)}"
        f"&location={quote_plus(localidade)}"
        f"&start={start}"
    )


def _clean_text(text: str | None) -> str | None:
    if not text:
        return None

    cleaned = " ".join(text.split())
    return cleaned or None


async def _is_login_or_challenge_page(page: Page) -> bool:
    url = page.url.lower()
    if any(part in url for part in ["/login", "/checkpoint", "/challenge", "authwall"]):
        return True

    selectors = [
        "input#username",
        "input#password",
        "form.login__form",
        ".captcha",
        "[data-test='captcha-form']",
    ]
    for selector in selectors:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _wait_for_manual_login_if_needed(page: Page) -> None:
    await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    if not await _is_login_or_challenge_page(page):
        return

    credentials = get_linkedin_credentials()
    if credentials:
        email, password = credentials
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        if await page.locator("input#username").count() > 0:
            await page.locator("input#username").fill(email)
            await page.locator("input#password").fill(password)
            await page.locator("button[type='submit']").click()
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(3)

            if not await _is_login_or_challenge_page(page):
                return

    print("\nLinkedIn precisa de login ou verificação manual.")
    print("Faça login no Chromium aberto. O robô aguardará até 10 minutos.\n")

    for _ in range(MANUAL_WAIT_SECONDS):
        await asyncio.sleep(1)
        if not await _is_login_or_challenge_page(page):
            return

    raise TimeoutError("Tempo máximo de 10 minutos para login/verificação foi excedido.")


async def _wait_for_manual_challenge_if_needed(page: Page) -> None:
    if not await _is_login_or_challenge_page(page):
        return

    print("\nLinkedIn pediu verificação durante a coleta.")
    print("Resolva no Chromium aberto. O robô aguardará até 10 minutos.\n")

    for _ in range(MANUAL_WAIT_SECONDS):
        await asyncio.sleep(1)
        if not await _is_login_or_challenge_page(page):
            return

    raise TimeoutError("Tempo máximo de 10 minutos para verificação foi excedido.")


async def _collect_urls_from_current_page(page: Page) -> list[str]:
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(2)

    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass

    card_urls = await page.locator(
        """
        .scaffold-layout__list [data-view-name='job-card'][data-job-id],
        .scaffold-layout__list .job-card-job-posting-card-wrapper[data-job-id],
        .scaffold-layout__list div[data-job-id],
        .jobs-search-results__list-item,
        .job-card-container,
        .base-card,
        .job-card-list__entity-lockup,
        .scaffold-layout__list-item,
        div[data-job-id]
        """
    ).evaluate_all(
        """
        elements => elements
            .flatMap(element => {
                const ids = [
                    element.getAttribute('data-occludable-job-id'),
                    element.getAttribute('data-job-id')
                ].filter(Boolean);
                const links = Array.from(
                    element.querySelectorAll(
                        "a[href*='currentJobId='], a[href*='/jobs/collections/recommended'], a[href*='/jobs/collections/top-applicant'], a[href*='/jobs/view/'], a[data-control-name='job_card_title'], .job-card-job-posting-card-wrapper__card-link, .base-card__full-link, .job-card-container__link, .jobs-search-results__list-item-action"
                    )
                ).map(link => link.href || link.getAttribute('href')).filter(Boolean);
                return [...ids.map(id => `https://www.linkedin.com/jobs/view/${id}`), ...links];
            })
            .filter(Boolean)
        """
    )

    fallback_urls = await page.locator(
        "a[href*='/jobs/view/'], a[href*='currentJobId='], a[href*='/jobs-guest/jobs/api/jobPosting/']"
    ).evaluate_all(
        """
        elements => elements
            .map(element => element.href)
            .filter(Boolean)
        """
    )

    normalized = []
    seen = set()
    for url in [*card_urls, *fallback_urls]:
        normalized_url = normalizar_url(url)
        if "/jobs/view/" not in normalized_url:
            continue
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        normalized.append(normalized_url)

    return normalized


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


async def _click_show_more_if_available(page: Page) -> None:
    selectors = [
        "button[aria-label*='ver mais']",
        "button[aria-label*='Ver mais']",
        "button[aria-label*='Show more']",
        "button:has-text('ver mais')",
        "button:has-text('Ver mais')",
        "button:has-text('Show more')",
        ".jobs-description__footer-button",
    ]

    for selector in selectors:
        try:
            button = page.locator(selector).first
            if await button.count() == 0:
                continue
            await button.click(timeout=2000)
            await asyncio.sleep(1)
            return
        except Exception:
            continue


async def _extract_job_details(page: Page, url: str) -> dict:
    await page.goto(url, wait_until="domcontentloaded")
    await _wait_for_manual_challenge_if_needed(page)
    await asyncio.sleep(2)
    await _click_show_more_if_available(page)

    titulo = await _first_text(
        page,
        [
            ".job-details-jobs-unified-top-card__job-title",
            ".job-details-jobs-unified-top-card__job-title h1",
            ".top-card-layout__title",
            "h1",
        ],
    )
    empresa = await _first_text(
        page,
        [
            ".job-details-jobs-unified-top-card__company-name a",
            ".job-details-jobs-unified-top-card__company-name",
            ".topcard__org-name-link",
            ".topcard__flavor",
        ],
    )
    localidade = await _first_text(
        page,
        [
            ".job-details-jobs-unified-top-card__primary-description-container",
            ".job-details-jobs-unified-top-card__bullet",
            ".topcard__flavor--bullet",
        ],
    )
    descricao = await _first_text(
        page,
        [
            "[data-testid='expandable-text-box']",
            ".jobs-description__content",
            ".jobs-box__html-content",
            "#job-details",
            ".show-more-less-html__markup",
            ".description__text",
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


async def executar_coleta_linkedin() -> dict[str, int]:
    titulos = titulos_repository.listar_titulos_ativos()
    localidades = localidades_repository.listar_localidades_ativas()
    execucao_id = execucoes_repository.iniciar_execucao("linkedin")

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

    storage_state_path = get_browser_session_path()
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    storage_state = str(storage_state_path) if storage_state_path.exists() else None

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(storage_state=storage_state, viewport={"width": 1440, "height": 900})
    page = await context.new_page()

    try:
        await _wait_for_manual_login_if_needed(page)
        await context.storage_state(path=str(storage_state_path))

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
                        await _wait_for_manual_challenge_if_needed(page)
                        urls = await _collect_urls_from_current_page(page)

                        if not urls and page_index == 0:
                            break

                        for url in urls:
                            vagas_encontradas += 1
                            vaga_id, created = salvar_vaga(
                                url=url,
                                plataforma="linkedin",
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
        try:
            await context.storage_state(path=str(storage_state_path))
        except Exception:
            pass
        await context.close()
        await browser.close()
        await playwright.stop()


def main() -> None:
    asyncio.run(executar_coleta_linkedin())


if __name__ == "__main__":
    main()
