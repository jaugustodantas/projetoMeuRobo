import argparse
import ast
import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from meu_robo.config import (
    get_agente_rh_path,
    get_ai_provider,
    get_cv_path,
    get_ollama_model,
    get_ollama_num_ctx,
    get_ollama_url,
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


def _post_ollama_chat(payload: dict) -> dict:
    url = f"{get_ollama_url()}/api/chat"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro do Ollama ({exc.code}): {body}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Falha de conexão com o Ollama em {url}: {exc.reason}"
        ) from exc


def _build_prompt(curriculo: str, vaga: dict) -> str:
    descricao = str(vaga.get("descricao_vaga") or "")[:MAX_DESCRICAO_CHARS]
    return f"""
Compare a vaga com o currículo abaixo.

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

Antes de definir a nota, verifique internamente:

1. Quais são os requisitos obrigatórios?
2. Quais deles estão comprovados no currículo?
3. Quais requisitos importantes estão ausentes?
4. As responsabilidades e a senioridade são compatíveis?
5. A experiência do candidato é direta ou apenas transferível?

Retorne somente o JSON solicitado.
""".strip()


def _parse_avaliacao(response_data: dict) -> dict:
    text = _extract_output_text(response_data)
    if not text:
        raise ValueError("Resposta da IA veio vazia.")

    cleaned = text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as json_error:
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
            try:
                data = ast.literal_eval(cleaned)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f"Resposta da IA não contém JSON válido: {text}") from json_error

    if not isinstance(data, dict):
        raise ValueError("Resposta da IA deve ser um objeto JSON.")

    nota = int(data["nota"])
    if nota < 1 or nota > 10:
        raise ValueError(f"Nota fora da escala esperada: {nota}")

    return data


def avaliar_vaga(vaga: dict, orientacao_agente: str, curriculo: str) -> None:
    prompt = _build_prompt(curriculo, vaga)
    provider = get_ai_provider()

    if provider == "ollama":
        payload = {
            "model": get_ollama_model(),
            "messages": [
                {"role": "system", "content": orientacao_agente},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": AVALIACAO_SCHEMA,
            "options": {
                "temperature": 0,
                "num_ctx": get_ollama_num_ctx(),
                "num_predict": 800,
            },
            "keep_alive": "10m",
        }
        response_data = _post_ollama_chat(payload)
        if response_data.get("done_reason") == "length":
            raise RuntimeError(
                "O Ollama interrompeu a resposta por limite de contexto. "
                "Aumente OLLAMA_NUM_CTX."
            )
        content = response_data.get("message", {}).get("content", "")
        data = _parse_avaliacao({"output_text": content})
    else:
        payload = {
            "model": get_openai_model(),
            "input": [
                {
                    "role": "developer",
                    "content": orientacao_agente,
                },
                {
                    "role": "user",
                    "content": prompt,
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


def avaliar_vagas_pendentes(limit: int | None = None, reavaliar: bool = False) -> ResultadoAvaliacao:
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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Quantidade máxima de vagas. Por padrão, avalia todas as pendentes.",
    )
    parser.add_argument("--reavaliar", action="store_true", help="Reavalia vagas já analisadas.")
    args = parser.parse_args()

    resultado = avaliar_vagas_pendentes(limit=args.limit, reavaliar=args.reavaliar)
    print(
        "Avaliação concluída: "
        f"{resultado.avaliadas} avaliadas, {resultado.erros} com erro."
    )


if __name__ == "__main__":
    main()
