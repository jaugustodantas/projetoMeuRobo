import asyncio
import random
from urllib.parse import quote_plus

from playwright.async_api import BrowserContext, Page, async_playwright

from meu_robo.config import get_browser_session_path
from meu_robo.repositories import (
    execucoes_repository,
    linkedin_config_repository,
    localidades_repository,
    titulos_repository,
)
from meu_robo.robo.filtros_vagas import (
    vaga_aprovada_por_configuracao_linkedin,
    vaga_compativel_com_busca,
)
from meu_robo.repositories.vagas_repository import (
    atualizar_dados_extraidos,
    normalizar_url,
    salvar_vaga,
)

LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs/search/"
MAX_PAGES_PER_COMBINATION = 2
RESULTS_PER_PAGE = 25
MANUAL_WAIT_SECONDS = 600
HUMAN_READING_WPM_RANGE = (175, 300)
SEARCH_PAGE_BASE_DELAY_RANGE_SECONDS = (8.0, 16.0)
SEARCH_PAGE_EXTRA_DELAY_RANGE_SECONDS = (3.0, 8.0)
JOB_DETAILS_BASE_DELAY_RANGE_SECONDS = (6.0, 12.0)
POST_SCROLL_DELAY_RANGE_SECONDS = (1.2, 2.4)
COMBINATION_BREAK_DELAY_RANGE_SECONDS = (45.0, 90.0)
PER_JOB_BREAK_FREQUENCY = 5
PER_JOB_BREAK_DELAY_RANGE_SECONDS = (30.0, 60.0)
LONG_BREAK_EVERY_COMBINATIONS = 2
LONG_BREAK_DELAY_RANGE_SECONDS = (150.0, 240.0)
MAX_COMBINATIONS_PER_EXECUTION = 3
MAX_JOBS_PER_COMBINATION = 10
TAB_BATCH_SIZE = 3
GOOGLE_CHROME_EXECUTABLE_PATH = "/usr/bin/google-chrome-stable"


def _build_workplace_type_values(config_linkedin: dict) -> list[str]:
    valores = []
    if config_linkedin.get("permitir_presencial"):
        valores.append("1")
    if config_linkedin.get("permitir_remoto"):
        valores.append("2")
    if config_linkedin.get("permitir_hibrido"):
        valores.append("3")
    return valores


def _build_search_url(
    titulo: str,
    localidade: str,
    page_index: int,
    config_linkedin: dict | None = None,
) -> str:
    start = page_index * RESULTS_PER_PAGE
    base_url = (
        f"{LINKEDIN_SEARCH_URL}?keywords={quote_plus(titulo)}"
        f"&location={quote_plus(localidade)}"
        f"&start={start}"
    )

    if not config_linkedin:
        return base_url

    workplace_types = _build_workplace_type_values(config_linkedin)
    if not workplace_types:
        return base_url

    return f"{base_url}&f_WT={quote_plus(','.join(workplace_types))}"


def _clean_text(text: str | None) -> str | None:
    if not text:
        return None

    cleaned = " ".join(text.split())
    return cleaned or None


async def _sleep_random(delay_range: tuple[float, float]) -> None:
    inicio, fim = delay_range
    await asyncio.sleep(random.uniform(inicio, fim))


async def _goto_with_log(page: Page, url: str) -> None:
    print(f"Acessando: {url}")
    await page.goto(url, wait_until="domcontentloaded")


async def _simulate_human_browsing(page: Page) -> None:
    try:
        await page.mouse.move(
            random.randint(200, 900),
            random.randint(120, 700),
            steps=random.randint(10, 25),
        )
        await _sleep_random((0.2, 0.7))
        await page.mouse.wheel(0, random.randint(250, 900))
        await _sleep_random((0.4, 1.0))
        await page.mouse.wheel(0, -random.randint(80, 260))
    except Exception:
        return


def _count_words(*parts: str | None) -> int:
    return sum(len((part or "").split()) for part in parts)


def _estimate_reading_delay_seconds(word_count: int, *, skim_ratio_range: tuple[float, float]) -> float:
    words_considered = max(word_count, 1) * random.uniform(*skim_ratio_range)
    reading_wpm = random.randint(*HUMAN_READING_WPM_RANGE)
    reading_seconds = (words_considered / reading_wpm) * 60
    return reading_seconds


def _estimate_search_page_delay_seconds() -> float:
    base_delay = random.uniform(*SEARCH_PAGE_BASE_DELAY_RANGE_SECONDS)
    extra_scan_delay = random.uniform(*SEARCH_PAGE_EXTRA_DELAY_RANGE_SECONDS)
    return base_delay + extra_scan_delay


def _estimate_job_details_delay_seconds(
    titulo_vaga: str | None,
    empresa: str | None,
    localidade: str | None,
    descricao_vaga: str | None,
) -> float:
    header_words = _count_words(titulo_vaga, empresa, localidade)
    descricao_words = _count_words(descricao_vaga)

    header_seconds = _estimate_reading_delay_seconds(
        header_words,
        skim_ratio_range=(0.9, 1.2),
    )
    descricao_seconds = _estimate_reading_delay_seconds(
        min(descricao_words, 900),
        skim_ratio_range=(0.35, 0.65),
    )
    decision_overhead = random.uniform(*JOB_DETAILS_BASE_DELAY_RANGE_SECONDS)

    return min(max(header_seconds + descricao_seconds + decision_overhead, 12.0), 75.0)


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
    await _goto_with_log(page, "https://www.linkedin.com/feed/")
    await _sleep_random((2.0, 4.0))
    if not await _is_login_or_challenge_page(page):
        return

    await _goto_with_log(page, "https://www.linkedin.com/login")
    await _sleep_random((1.5, 3.0))

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


async def _abrir_area_vagas_por_navegacao(page: Page) -> bool:
    seletores = (
        "a[aria-label^='Vagas']",
        "a[href='https://www.linkedin.com/jobs/']",
        "a[href='https://www.linkedin.com/jobs']",
    )

    for seletor in seletores:
        try:
            link = page.locator(seletor).first
            if await link.count() == 0:
                continue
            await link.click(timeout=4000)
            await page.wait_for_load_state("domcontentloaded")
            await _sleep_random((2.0, 4.0))
            return True
        except Exception:
            continue

    return False


async def _aplicar_filtro_modalidade(page: Page, config_linkedin: dict) -> bool:
    try:
        gatilho = page.locator("button#searchFilter_workplaceType").first
        if await gatilho.count() == 0:
            print("Filtro de modalidade nao encontrado na interface; usando parametro da URL.")
            return False

        await gatilho.click(timeout=4000)
        await _sleep_random((1.0, 2.0))

        opcoes = (
            ("input#workplaceType-1", bool(config_linkedin.get("permitir_presencial"))),
            ("input#workplaceType-2", bool(config_linkedin.get("permitir_remoto"))),
            ("input#workplaceType-3", bool(config_linkedin.get("permitir_hibrido"))),
        )

        for seletor, marcado in opcoes:
            campo = page.locator(seletor).first
            if await campo.count() == 0:
                continue
            await campo.set_checked(marcado)
            await _sleep_random((0.2, 0.6))

        aplicar = page.locator(
            "button[aria-label='Aplicar filtro atual para exibir resultados']"
        ).first
        if await aplicar.count() > 0:
            await aplicar.click(timeout=4000)
            await page.wait_for_load_state("domcontentloaded")
            await _sleep_random((2.0, 4.0))
            print("Filtro de modalidade aplicado pela interface do LinkedIn.")
            return True
    except Exception:
        print("Falha ao aplicar filtro de modalidade pela interface; mantendo filtro pela URL.")
        return False

    return False


async def _collect_urls_from_current_page(page: Page) -> list[str]:
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(_estimate_search_page_delay_seconds())
    await _simulate_human_browsing(page)

    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await _sleep_random(POST_SCROLL_DELAY_RANGE_SECONDS)
        await page.evaluate("window.scrollTo(0, 0)")
        await _sleep_random((0.6, 1.4))
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


async def _wait_for_any_selector(page: Page, selectors: list[str], timeout_ms: int = 8000) -> None:
    for selector in selectors:
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            return
        except Exception:
            continue


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
            await _sleep_random((0.8, 1.6))
            return
        except Exception:
            continue


async def _extract_job_details(page: Page, url: str) -> dict:
    title_selectors = [
        ".job-details-jobs-unified-top-card__job-title",
        ".job-details-jobs-unified-top-card__job-title h1",
        ".job-details-jobs-unified-top-card__job-title p",
        ".t-24.job-details-jobs-unified-top-card__job-title",
        ".jobs-unified-top-card__job-title",
        ".jobs-unified-top-card__job-title p",
        ".jobs-unified-top-card h1",
        ".jobs-unified-top-card p",
        ".top-card-layout__title",
        ".job-view-layout.jobs-details h1",
        "main h1",
        "h1",
    ]
    empresa_selectors = [
        ".job-details-jobs-unified-top-card__company-name a",
        ".job-details-jobs-unified-top-card__company-name",
        ".jobs-unified-top-card__company-name a",
        ".jobs-unified-top-card__company-name",
        ".topcard__org-name-link",
        ".topcard__flavor",
    ]
    localidade_selectors = [
        ".job-details-jobs-unified-top-card__primary-description-container",
        ".job-details-jobs-unified-top-card__bullet",
        ".jobs-unified-top-card__primary-description-container",
        ".jobs-unified-top-card__bullet",
        ".topcard__flavor--bullet",
    ]
    descricao_selectors = [
        "[data-testid='expandable-text-box']",
        ".jobs-description__content",
        ".jobs-box__html-content",
        "#job-details",
        ".show-more-less-html__markup",
        ".description__text",
    ]

    if normalizar_url(page.url) != normalizar_url(url):
        await _goto_with_log(page, url)
    await _wait_for_manual_challenge_if_needed(page)
    await _sleep_random((4.0, 7.0))
    await _wait_for_any_selector(page, title_selectors + descricao_selectors, timeout_ms=10000)
    await _simulate_human_browsing(page)
    await _click_show_more_if_available(page)

    titulo = await _first_text(page, title_selectors)
    empresa = await _first_text(page, empresa_selectors)
    localidade = await _first_text(page, localidade_selectors)
    descricao = await _first_text(page, descricao_selectors)

    if not titulo:
        try:
            document_title = _clean_text(await page.title())
            if document_title:
                titulo_documento = document_title.split("|")[0].split(" - ")[0].strip()
                if titulo_documento and titulo_documento.lower() != "linkedin":
                    titulo = titulo_documento
        except Exception:
            pass

    if not empresa:
        try:
            empresa_meta = await page.locator("meta[property='og:description']").get_attribute("content")
            empresa = _clean_text(empresa_meta)
        except Exception:
            pass

    if not descricao:
        dados = {
            "titulo_vaga": titulo,
            "empresa": empresa,
            "localidade_extraida": localidade,
            "descricao_vaga": None,
            "url_acessivel": False,
            "erro_extracao": "Conteudo principal da vaga nao encontrado.",
        }
        await asyncio.sleep(
            _estimate_job_details_delay_seconds(
                titulo,
                empresa,
                localidade,
                None,
            )
        )
        return dados

    dados = {
        "titulo_vaga": titulo,
        "empresa": empresa,
        "localidade_extraida": localidade,
        "descricao_vaga": descricao,
        "url_acessivel": True,
        "erro_extracao": None,
    }
    await asyncio.sleep(
        _estimate_job_details_delay_seconds(
            titulo,
            empresa,
            localidade,
            descricao,
        )
    )
    return dados


async def _abrir_vagas_em_abas(
    context: BrowserContext,
    urls: list[str],
) -> list[tuple[str, Page]]:
    abas: list[tuple[str, Page]] = []

    for url in urls:
        aba = await context.new_page()
        try:
            await _goto_with_log(aba, url)
            await _sleep_random((1.5, 3.0))
            abas.append((url, aba))
        except Exception:
            await aba.close()
            raise

    return abas


async def _coletar_vagas_em_abas(
    context: BrowserContext,
    urls: list[str],
    titulo: dict,
    localidade: dict,
    execucao_id: int,
    config_linkedin: dict,
    filtro_modalidade_aplicado: bool,
    progress_callback=None,
    should_stop=None,
) -> tuple[int, int, int, bool]:
    vagas_encontradas = 0
    vagas_novas = 0
    vagas_duplicadas = 0
    houve_erro = False

    for inicio_lote in range(0, len(urls), TAB_BATCH_SIZE):
        if should_stop and should_stop():
            break

        lote_urls = urls[inicio_lote : inicio_lote + TAB_BATCH_SIZE]

        try:
            abas = await _abrir_vagas_em_abas(context, lote_urls)
        except Exception as exc:
            houve_erro = True
            execucoes_repository.registrar_erro(
                execucao_id=execucao_id,
                titulo_busca_id=titulo["id"],
                localidade_busca_id=localidade["id"],
                mensagem_erro=f"Falha ao abrir abas de vagas: {exc}",
            )
            continue

        for indice_lote, (url, aba) in enumerate(abas, start=1):
            if should_stop and should_stop():
                await aba.close()
                continue

            try:
                vagas_encontradas += 1
                if progress_callback is not None:
                    progress_callback(vagas_encontradas, vagas_novas)

                dados_extraidos = await _extract_job_details(aba, url)
                titulo_extraido = dados_extraidos.get("titulo_vaga")
                empresa_extraida = dados_extraidos.get("empresa")

                if not titulo_extraido:
                    print(f"Descartada sem titulo extraido: {url}")
                    continue

                if not vaga_compativel_com_busca(
                    titulo["titulo"],
                    titulo_extraido,
                    titulo.get("modo_correspondencia", "generica"),
                ):
                    print(
                        "Descartada por filtro de titulo: "
                        f"busca='{titulo['titulo']}' vaga='{titulo_extraido}'"
                    )
                    continue

                if not filtro_modalidade_aplicado and not vaga_aprovada_por_configuracao_linkedin(
                    config_linkedin,
                    titulo_extraido,
                    empresa_extraida,
                    dados_extraidos.get("localidade_extraida"),
                    dados_extraidos.get("descricao_vaga"),
                ):
                    print(
                        "Descartada por configuracao LinkedIn: "
                        f"titulo='{titulo_extraido}' empresa='{empresa_extraida or '-'}'"
                    )
                    continue

                vaga_id, created = salvar_vaga(
                    url=url,
                    plataforma="linkedin",
                    titulo_busca_id=titulo["id"],
                    localidade_busca_id=localidade["id"],
                    execucao_robo_id=execucao_id,
                    titulo_vaga=titulo_extraido,
                )
                atualizar_dados_extraidos(vaga_id, **dados_extraidos)

                if created:
                    vagas_novas += 1
                    print(f"Salva no banco: id={vaga_id} titulo='{titulo_extraido}'")
                else:
                    vagas_duplicadas += 1
                    print(f"Duplicada no banco: id={vaga_id} titulo='{titulo_extraido}'")
            except Exception as exc:
                houve_erro = True
                execucoes_repository.registrar_erro(
                    execucao_id=execucao_id,
                    titulo_busca_id=titulo["id"],
                    localidade_busca_id=localidade["id"],
                    mensagem_erro=f"Falha ao extrair vaga {url}: {exc}",
                )
            finally:
                if not aba.is_closed():
                    await aba.close()

            if progress_callback is not None:
                progress_callback(vagas_encontradas, vagas_novas)

            if indice_lote % PER_JOB_BREAK_FREQUENCY == 0:
                await _sleep_random(PER_JOB_BREAK_DELAY_RANGE_SECONDS)
            else:
                await _sleep_random((4.0, 9.0))

        await _sleep_random((8.0, 15.0))

    return vagas_encontradas, vagas_novas, vagas_duplicadas, houve_erro


async def executar_coleta_linkedin(progress_callback=None, should_stop=None) -> dict[str, int | bool]:
    titulos = titulos_repository.listar_titulos_ativos()
    localidades = localidades_repository.listar_localidades_ativas()
    config_linkedin = linkedin_config_repository.obter_configuracao()
    execucao_id = execucoes_repository.iniciar_execucao("linkedin")

    vagas_encontradas = 0
    vagas_novas = 0
    vagas_duplicadas = 0
    houve_erro = False
    interrompida = False

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
    browser = await playwright.chromium.launch(
        headless=False,
        executable_path=GOOGLE_CHROME_EXECUTABLE_PATH,
    )
    context = await browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()

    try:
        await _wait_for_manual_login_if_needed(page)
        await context.storage_state(path=str(storage_state_path))
        entrou_em_vagas = await _abrir_area_vagas_por_navegacao(page)
        if not entrou_em_vagas:
            print("Nao foi possivel entrar em Vagas pelo menu. Mantendo navegacao direta por URL.")

        combinations_processed = 0
        for titulo in titulos:
            for localidade in localidades:
                if combinations_processed >= MAX_COMBINATIONS_PER_EXECUTION:
                    break

                try:
                    combinations_processed += 1

                    for page_index in range(MAX_PAGES_PER_COMBINATION):
                        if should_stop and should_stop():
                            interrompida = True
                            break

                        search_url = _build_search_url(
                            titulo["titulo"],
                            localidade["localidade"],
                            page_index,
                            config_linkedin,
                        )
                        await _goto_with_log(page, search_url)
                        await _wait_for_manual_challenge_if_needed(page)
                        filtro_modalidade_aplicado = await _aplicar_filtro_modalidade(page, config_linkedin)
                        urls = await _collect_urls_from_current_page(page)

                        if not urls and page_index == 0:
                            break

                        (
                            encontradas_lote,
                            novas_lote,
                            duplicadas_lote,
                            houve_erro_lote,
                        ) = await _coletar_vagas_em_abas(
                            context=context,
                            urls=urls[:MAX_JOBS_PER_COMBINATION],
                            titulo=titulo,
                            localidade=localidade,
                            execucao_id=execucao_id,
                            config_linkedin=config_linkedin,
                            filtro_modalidade_aplicado=filtro_modalidade_aplicado,
                            progress_callback=(
                                None
                                if progress_callback is None
                                else lambda searched_count, saved_count: progress_callback(
                                    vagas_encontradas + searched_count,
                                    vagas_novas + saved_count,
                                )
                            ),
                            should_stop=should_stop,
                        )

                        vagas_encontradas += encontradas_lote
                        vagas_novas += novas_lote
                        vagas_duplicadas += duplicadas_lote
                        houve_erro = houve_erro or houve_erro_lote

                        if should_stop and should_stop():
                            interrompida = True
                            break

                        await _sleep_random(COMBINATION_BREAK_DELAY_RANGE_SECONDS)

                    if interrompida:
                        break

                    if combinations_processed % LONG_BREAK_EVERY_COMBINATIONS == 0:
                        await _sleep_random(LONG_BREAK_DELAY_RANGE_SECONDS)

                except Exception as exc:
                    houve_erro = True
                    execucoes_repository.registrar_erro(
                        execucao_id=execucao_id,
                        titulo_busca_id=titulo["id"],
                        localidade_busca_id=localidade["id"],
                        mensagem_erro=str(exc),
                    )
                    continue

            if interrompida:
                break

            if combinations_processed >= MAX_COMBINATIONS_PER_EXECUTION:
                break

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
            "interrompida": interrompida,
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
