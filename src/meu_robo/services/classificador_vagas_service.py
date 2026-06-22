import argparse
import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from meu_robo.config import (
    get_agente_rh_path,
    get_cv_path,
    get_openai_api_key,
    get_openai_model,
)
from meu_robo.repositories.vagas_repository import (
    atualizar_avaliacao_ia,
    listar_vagas_para_avaliacao,
    registrar_erro_avaliacao_ia,
)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_DESCRICAO_CHARS = 14000

AVALIACAO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "nota": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
        },
        "recomendacao": {
            "type": "string",
            "enum": ["alta", "media", "baixa", "descartar"],
        },
        "justificativa": {
            "type": "string",
        },
        "pontos_positivos": {
            "type": "array",
            "items": {"type": "string"},
        },
        "pontos_alerta": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tecnologias_identificadas": {
            "type": "array",
            "items": {"type": "string"},
        },
        "senioridade_estimada": {
            "type": "string",
        },
    },
    "required": [
        "nota",
        "recomendacao",
        "justificativa",
        "pontos_positivos",
        "pontos_alerta",
        "tecnologias_identificadas",
        "senioridade_estimada",
    ],
}


@dataclass
class ResultadoAvaliacao:
    avaliadas: int = 0
    erros: int = 0
    ignoradas: int = 0


def _read_context_file(path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de contexto não encontrado: {path}")

    return path.read_text(encoding="utf-8").strip()


def _join_list(values: list[str]) -> str | None:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return "\n".join(f"- {value}" for value in cleaned) if cleaned else None


def _extract_output_text(response_data: dict) -> str:
    if response_data.get("output_text"):
        return str(response_data["output_text"])

    texts = []
    for item in response_data.get("output", []):
        for content in item.get("content", []):
            if content.get("text"):
                texts.append(str(content["text"]))

    return "\n".join(texts).strip()


def _post_openai_response(payload: dict) -> dict:
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {get_openai_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro da API OpenAI ({exc.code}): {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Falha de conexão com a API OpenAI: {exc.reason}") from exc


def _build_prompt(orientacao_agente: str, curriculo: str, vaga: dict) -> str:
    descricao = str(vaga.get("descricao_vaga") or "")[:MAX_DESCRICAO_CHARS]
    return f"""
Você vai avaliar a aderência de uma vaga ao perfil profissional do candidato.

Use a orientação do agente como critério principal. Se a orientação pedir para retornar
apenas um número, respeite a escala, mas retorne o JSON estruturado solicitado pela aplicação.

ORIENTAÇÃO DO AGENTE:
{orientacao_agente}

CURRÍCULO DO CANDIDATO:
{curriculo}

VAGA:
ID: {vaga.get("id")}
URL: {vaga.get("url")}
Plataforma: {vaga.get("plataforma")}
Título pesquisado: {vaga.get("titulo_busca") or ""}
Localidade pesquisada: {vaga.get("localidade_busca") or ""}
Título extraído: {vaga.get("titulo_vaga") or ""}
Empresa: {vaga.get("empresa") or ""}
Localidade extraída: {vaga.get("localidade_extraida") or ""}
Descrição:
{descricao}

Retorne uma avaliação objetiva. A nota deve ser um inteiro de 1 a 10.
""".strip()


def _parse_avaliacao(response_data: dict) -> dict:
    text = _extract_output_text(response_data)
    if not text:
        raise ValueError("Resposta da IA veio vazia.")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        cleaned = text.strip()
        if cleaned.isdigit():
            data = {
                "nota": int(cleaned),
                "recomendacao": "media",
                "justificativa": "A IA retornou somente a nota, conforme orientação do agente.",
                "pontos_positivos": [],
                "pontos_alerta": [],
                "tecnologias_identificadas": [],
                "senioridade_estimada": "",
            }
        else:
            raise

    nota = int(data["nota"])
    if nota < 1 or nota > 10:
        raise ValueError(f"Nota fora da escala esperada: {nota}")

    return data


def avaliar_vaga(vaga: dict, orientacao_agente: str, curriculo: str) -> None:
    payload = {
        "model": get_openai_model(),
        "input": [
            {
                "role": "developer",
                "content": (
                    "Retorne somente JSON válido no formato solicitado. "
                    "A nota deve ser um inteiro de 1 a 10."
                ),
            },
            {
                "role": "user",
                "content": _build_prompt(orientacao_agente, curriculo, vaga),
            },
        ],
        "max_output_tokens": 1200,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "avaliacao_vaga",
                "schema": AVALIACAO_SCHEMA,
                "strict": True,
            }
        },
    }
    data = _parse_avaliacao(_post_openai_response(payload))
    atualizar_avaliacao_ia(
        vaga_id=int(vaga["id"]),
        nota_aderencia=int(data["nota"]),
        recomendacao_ia=data.get("recomendacao"),
        justificativa_ia=data.get("justificativa"),
        pontos_positivos_ia=_join_list(data.get("pontos_positivos", [])),
        pontos_alerta_ia=_join_list(data.get("pontos_alerta", [])),
        tecnologias_ia=_join_list(data.get("tecnologias_identificadas", [])),
        senioridade_ia=data.get("senioridade_estimada"),
    )


def avaliar_vagas_pendentes(limit: int = 20, reavaliar: bool = False) -> ResultadoAvaliacao:
    orientacao_agente = _read_context_file(get_agente_rh_path())
    curriculo = _read_context_file(get_cv_path())
    vagas = listar_vagas_para_avaliacao(limit=limit, reavaliar=reavaliar)
    resultado = ResultadoAvaliacao()

    for vaga in vagas:
        try:
            avaliar_vaga(vaga, orientacao_agente, curriculo)
            resultado.avaliadas += 1
        except Exception as exc:
            resultado.erros += 1
            registrar_erro_avaliacao_ia(int(vaga["id"]), str(exc))

    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description="Avalia vagas coletadas com IA.")
    parser.add_argument("--limit", type=int, default=20, help="Quantidade máxima de vagas.")
    parser.add_argument("--reavaliar", action="store_true", help="Reavalia vagas já analisadas.")
    args = parser.parse_args()

    resultado = avaliar_vagas_pendentes(limit=args.limit, reavaliar=args.reavaliar)
    print(
        "Avaliação concluída: "
        f"{resultado.avaliadas} avaliadas, {resultado.erros} com erro."
    )


if __name__ == "__main__":
    main()
