import asyncio
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from meu_robo.repositories import execucoes_repository, localidades_repository, titulos_repository
from meu_robo.repositories.vagas_repository import (
    STATUS_VAGAS,
    atualizar_nota,
    atualizar_status,
    contar_vagas_por_status,
    excluir_vaga,
    listar_vagas,
)
from meu_robo.robo.indeed_collector import executar_coleta_indeed
from meu_robo.robo.linkedin_collector import executar_coleta_linkedin
from meu_robo.services.export_service import exportar_vagas_excel

BASE_DIR = Path(__file__).resolve().parent
APP_HOST = "127.0.0.1"
APP_PORT = 8000
APP_URL = f"http://{APP_HOST}:{APP_PORT}"

app = FastAPI(title="Projeto Meu Robo")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _run_linkedin_collection_background() -> None:
    asyncio.run(executar_coleta_linkedin())


def _run_indeed_collection_background() -> None:
    asyncio.run(executar_coleta_indeed())


def _open_app_in_browser() -> None:
    chrome_path = shutil.which("google-chrome-stable") or shutil.which("google-chrome")

    if chrome_path:
        subprocess.Popen([chrome_path, APP_URL])
        return

    webbrowser.open(APP_URL)


def _schedule_open_app_in_browser() -> None:
    timer = threading.Timer(1.5, _open_app_in_browser)
    timer.daemon = True
    timer.start()


def _bool_form_value(value: str | None) -> bool:
    return value in {"true", "on", "1", "sim"}


def _vagas_filtros(
    status: str | None = None,
    plataforma: str | None = None,
    titulo_busca_id: str | None = None,
    localidade_busca_id: str | None = None,
    nota_minima: str | None = None,
    texto: str | None = None,
) -> dict:
    return {
        "status": status or "",
        "plataforma": plataforma or "",
        "titulo_busca_id": titulo_busca_id or "",
        "localidade_busca_id": localidade_busca_id or "",
        "nota_minima": nota_minima or "",
        "texto": texto or "",
    }


@app.get("/")
async def index(request: Request):
    ultima = execucoes_repository.ultima_execucao()
    erros = execucoes_repository.listar_erros(ultima["id"]) if ultima else []
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "titulos": titulos_repository.listar_titulos(),
            "localidades": localidades_repository.listar_localidades(),
            "ultima_execucao": ultima,
            "erros": erros,
            "totais_status": contar_vagas_por_status(),
        },
    )


@app.post("/titulos")
async def criar_titulo(request: Request):
    form = await request.form()
    titulo = str(form.get("titulo", "")).strip()
    if titulo:
        titulos_repository.criar_titulo(titulo)
    return RedirectResponse("/", status_code=303)


@app.post("/titulos/{titulo_id}/ativo")
async def alterar_titulo_ativo(titulo_id: int, request: Request):
    form = await request.form()
    titulos_repository.alterar_ativo(titulo_id, _bool_form_value(str(form.get("ativo"))))
    return RedirectResponse("/", status_code=303)


@app.post("/titulos/{titulo_id}/excluir")
async def excluir_titulo(titulo_id: int):
    titulos_repository.excluir_titulo(titulo_id)
    return RedirectResponse("/", status_code=303)


@app.post("/localidades")
async def criar_localidade(request: Request):
    form = await request.form()
    localidade = str(form.get("localidade", "")).strip()
    if localidade:
        localidades_repository.criar_localidade(localidade)
    return RedirectResponse("/", status_code=303)


@app.post("/localidades/{localidade_id}/ativo")
async def alterar_localidade_ativo(localidade_id: int, request: Request):
    form = await request.form()
    localidades_repository.alterar_ativo(localidade_id, _bool_form_value(str(form.get("ativo"))))
    return RedirectResponse("/", status_code=303)


@app.post("/localidades/{localidade_id}/excluir")
async def excluir_localidade(localidade_id: int):
    localidades_repository.excluir_localidade(localidade_id)
    return RedirectResponse("/", status_code=303)


@app.post("/coletas/linkedin")
async def iniciar_coleta_linkedin(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_linkedin_collection_background)
    return RedirectResponse("/", status_code=303)


@app.post("/coletas/indeed")
async def iniciar_coleta_indeed(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_indeed_collection_background)
    return RedirectResponse("/", status_code=303)


@app.get("/vagas")
async def vagas(
    request: Request,
    status: str | None = Query(default=""),
    plataforma: str | None = Query(default=""),
    titulo_busca_id: str | None = Query(default=""),
    localidade_busca_id: str | None = Query(default=""),
    nota_minima: str | None = Query(default=""),
    texto: str | None = Query(default=""),
):
    filtros = _vagas_filtros(
        status=status,
        plataforma=plataforma,
        titulo_busca_id=titulo_busca_id,
        localidade_busca_id=localidade_busca_id,
        nota_minima=nota_minima,
        texto=texto,
    )
    return templates.TemplateResponse(
        request,
        "vagas.html",
        {
            "request": request,
            "vagas": listar_vagas(filtros),
            "status_vagas": STATUS_VAGAS,
            "filtros": filtros,
            "titulos": titulos_repository.listar_titulos(),
            "localidades": localidades_repository.listar_localidades(),
            "totais_status": contar_vagas_por_status(),
        },
    )


@app.post("/vagas/{vaga_id}/status")
async def alterar_status_vaga(vaga_id: int, request: Request):
    form = await request.form()
    status = str(form.get("status", "")).strip()
    atualizar_status(vaga_id, status)
    return RedirectResponse("/vagas", status_code=303)


@app.post("/vagas/{vaga_id}/nota")
async def alterar_nota_vaga(vaga_id: int, request: Request):
    form = await request.form()
    nota_raw = str(form.get("nota_aderencia", "")).strip()
    nota = int(nota_raw) if nota_raw else None
    atualizar_nota(vaga_id, nota)
    return RedirectResponse("/vagas", status_code=303)


@app.post("/vagas/{vaga_id}/excluir")
async def excluir_registro_vaga(vaga_id: int):
    excluir_vaga(vaga_id)
    return RedirectResponse("/vagas", status_code=303)


@app.get("/vagas/exportar")
async def exportar_vagas(
    status: str | None = Query(default=""),
    plataforma: str | None = Query(default=""),
    titulo_busca_id: str | None = Query(default=""),
    localidade_busca_id: str | None = Query(default=""),
    nota_minima: str | None = Query(default=""),
    texto: str | None = Query(default=""),
):
    filtros = _vagas_filtros(
        status=status,
        plataforma=plataforma,
        titulo_busca_id=titulo_busca_id,
        localidade_busca_id=localidade_busca_id,
        nota_minima=nota_minima,
        texto=texto,
    )
    path = exportar_vagas_excel(filtros)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(path).name,
    )


def main() -> None:
    _schedule_open_app_in_browser()
    uvicorn.run("meu_robo.web.app:app", host=APP_HOST, port=APP_PORT, reload=False)


if __name__ == "__main__":
    main()
