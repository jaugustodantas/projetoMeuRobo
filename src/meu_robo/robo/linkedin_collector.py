import asyncio
from urllib.parse import quote_plus

from playwright.async_api import Page, async_playwright

from meu_robo.config import get_browser_session_path, get_linkedin_credentials
from meu_robo.repositories import execucoes_repository, localidades_repository, titulos_repository
from meu_robo.repositories.vagas_repository import normalizar_url, salvar_vaga

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

    urls = await page.locator(
        "a[href*='/jobs/view/'], a[href*='currentJobId=']"
    ).evaluate_all(
        """
        elements => elements
            .map(element => element.href)
            .filter(Boolean)
        """
    )

    normalized = []
    seen = set()
    for url in urls:
        normalized_url = normalizar_url(url)
        if "/jobs/view/" not in normalized_url:
            continue
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        normalized.append(normalized_url)

    return normalized


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
                            _, created = salvar_vaga(
                                url=url,
                                plataforma="linkedin",
                                titulo_busca_id=titulo["id"],
                                localidade_busca_id=localidade["id"],
                                execucao_robo_id=execucao_id,
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
