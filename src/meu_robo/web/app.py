import asyncio
import os
import socket
import shutil
import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from meu_robo.repositories import (
    execucoes_repository,
    linkedin_config_repository,
    localidades_repository,
    titulos_repository,
)
from meu_robo.repositories.vagas_repository import (
    STATUS_VAGAS,
    atualizar_nota,
    atualizar_status,
    contar_vagas_por_status,
    excluir_vaga,
    excluir_vagas,
    listar_vagas,
)
from meu_robo.robo.linkedin_collector import executar_coleta_linkedin
from meu_robo.services.classificador_vagas_service import avaliar_vagas_pendentes
from meu_robo.services.export_service import exportar_vagas_excel

BASE_DIR = Path(__file__).resolve().parent
APP_HOST = "127.0.0.1"
DEFAULT_APP_PORT = 8000
FALLBACK_APP_PORT = 8765

app = FastAPI(title="Projeto Meu Robo")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

_operations_lock = threading.Lock()
_operations = {
    "linkedin": {
        "label": "Coleta do LinkedIn",
        "status": "idle",
        "message": "",
        "updated_at": None,
        "searched_count": 0,
        "saved_count": 0,
        "stop_requested": False,
    },
    "avaliacao": {
        "label": "Avaliação de vagas",
        "status": "idle",
        "message": "",
        "updated_at": None,
        "searched_count": 0,
        "saved_count": 0,
        "stop_requested": False,
    },
}


def _operation_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _start_operation(name: str, message: str) -> bool:
    with _operations_lock:
        operation = _operations[name]
        if operation["status"] == "running":
            return False

        operation.update(
            status="running",
            message=message,
            updated_at=_operation_timestamp(),
            searched_count=0,
            saved_count=0,
            stop_requested=False,
        )
        return True


def _finish_operation(
    name: str,
    message: str,
    failed: bool = False,
    searched_count: int | None = None,
    saved_count: int | None = None,
) -> None:
    with _operations_lock:
        payload = dict(
            status="failed" if failed else "completed",
            message=message,
            updated_at=_operation_timestamp(),
            stop_requested=False,
        )
        if searched_count is not None:
            payload["searched_count"] = searched_count
        if saved_count is not None:
            payload["saved_count"] = saved_count
        _operations[name].update(payload)


def _update_operation_progress(
    name: str,
    searched_count: int,
    saved_count: int,
    message: str | None = None,
) -> None:
    with _operations_lock:
        payload = {
            "searched_count": searched_count,
            "saved_count": saved_count,
            "updated_at": _operation_timestamp(),
        }
        if message is not None:
            payload["message"] = message
        _operations[name].update(payload)


def _request_stop_operation(name: str) -> bool:
    with _operations_lock:
        operation = _operations[name]
        if operation["status"] != "running":
            return False
        operation.update(
            stop_requested=True,
            message=f"{operation['label']}: parada solicitada. Encerrando o lote atual...",
            updated_at=_operation_timestamp(),
        )
        return True


def _should_stop_operation(name: str) -> bool:
    with _operations_lock:
        return bool(_operations[name]["stop_requested"])


def _operations_snapshot() -> dict:
    with _operations_lock:
        return {name: dict(operation) for name, operation in _operations.items()}


def _run_linkedin_collection_background() -> None:
    try:
        result = asyncio.run(
            executar_coleta_linkedin(
                progress_callback=lambda searched_count, saved_count: _update_operation_progress(
                    "linkedin",
                    searched_count,
                    saved_count,
                    message=(
                        "Coleta do LinkedIn em andamento... "
                        f"Pesquisadas: {searched_count}. Salvas: {saved_count}."
                    ),
                ),
                should_stop=lambda: _should_stop_operation("linkedin"),
            )
        )
        _finish_operation(
            "linkedin",
            (
                "Coleta do LinkedIn interrompida: "
                if result.get("interrompida")
                else "Coleta do LinkedIn concluída: "
            )
            + f"{result['vagas_encontradas']} pesquisadas e "
            + f"{result['vagas_novas']} salvas.",
            searched_count=result["vagas_encontradas"],
            saved_count=result["vagas_novas"],
        )
    except Exception as exc:
        _finish_operation("linkedin", f"Coleta do LinkedIn falhou: {exc}", failed=True)


def _run_job_evaluation_background() -> None:
    try:
        result = avaliar_vagas_pendentes()
        _finish_operation(
            "avaliacao",
            "Avaliação concluída: "
            f"{result.avaliadas} vagas avaliadas e {result.erros} com erro. "
            "Atualize a página para ver as notas.",
            failed=result.erros > 0 and result.avaliadas == 0,
        )
    except Exception as exc:
        _finish_operation("avaliacao", f"Avaliação falhou: {exc}", failed=True)


def _find_available_port(host: str, preferred_port: int, max_attempts: int = 20) -> int:
    forced_port = os.getenv("MEU_ROBO_WEB_PORT", "").strip()
    if forced_port:
        return int(forced_port)

    for port in range(preferred_port, preferred_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex((host, port)) != 0:
                return port

    raise RuntimeError(
        f"Nenhuma porta livre encontrada entre {preferred_port} e {preferred_port + max_attempts - 1}."
    )


def _open_app_in_browser(app_url: str) -> None:
    chrome_path = shutil.which("google-chrome-stable") or shutil.which("google-chrome")

    if chrome_path:
        subprocess.Popen([chrome_path, app_url])
        return

    webbrowser.open(app_url)


def _schedule_open_app_in_browser(app_url: str) -> None:
    timer = threading.Timer(1.5, _open_app_in_browser, args=(app_url,))
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


def _redirect_vagas_url(next_url: str) -> str:
    if next_url == "/vagas" or next_url.startswith("/vagas?"):
        return next_url

    return "/vagas"


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
            "linkedin_config": linkedin_config_repository.obter_configuracao(),
            "ultima_execucao": ultima,
            "erros": erros,
            "totais_status": contar_vagas_por_status(),
        },
    )


@app.get("/api/operacoes")
async def estado_operacoes():
    return _operations_snapshot()


@app.post("/titulos")
async def criar_titulo(request: Request):
    form = await request.form()
    titulo = str(form.get("titulo", "")).strip()
    modo_correspondencia = str(form.get("modo_correspondencia", "generica")).strip().lower()
    if titulo:
        titulos_repository.criar_titulo(titulo, modo_correspondencia=modo_correspondencia)
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


@app.post("/linkedin/config")
async def atualizar_configuracao_linkedin(request: Request):
    form = await request.form()
    linkedin_config_repository.atualizar_configuracao(
        permitir_remoto=_bool_form_value(str(form.get("permitir_remoto"))),
        permitir_hibrido=_bool_form_value(str(form.get("permitir_hibrido"))),
        permitir_presencial=_bool_form_value(str(form.get("permitir_presencial"))),
        palavras_titulo_bloqueadas=str(form.get("palavras_titulo_bloqueadas", "")),
        empresas_bloqueadas=str(form.get("empresas_bloqueadas", "")),
        localidades_bloqueadas=str(form.get("localidades_bloqueadas", "")),
    )
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
    if _start_operation("linkedin", "Coleta do LinkedIn em andamento..."):
        background_tasks.add_task(_run_linkedin_collection_background)
    return RedirectResponse("/", status_code=303)


@app.post("/coletas/linkedin/parar")
async def parar_coleta_linkedin():
    _request_stop_operation("linkedin")
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


@app.get("/vagas/excluir")
async def redirecionar_exclusao_vagas():
    return RedirectResponse("/vagas", status_code=303)


@app.post("/vagas/excluir")
async def excluir_registros_vagas(request: Request):
    form = await request.form()
    vaga_ids = []
    for raw_id in form.getlist("vaga_ids"):
        value = str(raw_id).strip()
        if value.isdigit():
            vaga_ids.append(int(value))

    excluir_vagas(vaga_ids)
    next_url = str(form.get("next", "")).strip()
    return RedirectResponse(_redirect_vagas_url(next_url), status_code=303)


@app.post("/vagas/avaliar")
async def avaliar_registros_vagas(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    if _start_operation(
        "avaliacao",
        "Avaliação de todas as vagas pendentes com Gemma em andamento...",
    ):
        background_tasks.add_task(_run_job_evaluation_background)
    next_url = str(form.get("next", "")).strip()
    return RedirectResponse(_redirect_vagas_url(next_url), status_code=303)


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
    try:
        app_port = _find_available_port(APP_HOST, DEFAULT_APP_PORT)
    except PermissionError:
        app_port = int(os.getenv("MEU_ROBO_WEB_PORT", str(FALLBACK_APP_PORT)))
        print(
            "Nao foi possivel inspecionar portas automaticamente neste ambiente. "
            f"Usando {app_port}."
        )
    app_url = f"http://{APP_HOST}:{app_port}"
    print(f"Interface web disponível em {app_url}")
    _schedule_open_app_in_browser(app_url)
    uvicorn.run("meu_robo.web.app:app", host=APP_HOST, port=app_port, reload=False)


if __name__ == "__main__":
    main()
