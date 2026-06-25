# Projeto Meu Robo

Ferramenta local para coletar URLs de vagas, salvar no PostgreSQL e acompanhar candidaturas por status e nota.
O robô também abre cada vaga no Chromium logado e salva o conteúdo principal para análise posterior por IA.

## Rodar a interface

```bash
cd /mnt/arquivos/projetoMeuRobo
source .venv/bin/activate
meu-robo-web
```

Ao iniciar, o sistema tenta abrir automaticamente no Google Chrome:

```text
http://127.0.0.1:8000
```

## Coletas

1. Cadastre títulos e localidades na tela inicial.
2. Clique em `Iniciar coleta LinkedIn` ou `Iniciar coleta Indeed`.
3. O robô abre um Chromium separado e navega para a plataforma escolhida.
4. Se `LINKEDIN_EMAIL` e `LINKEDIN_PASSWORD` estiverem configurados no `.env`, o robô tenta fazer o login.
5. Se o Chromium abrir pedindo login, 2FA ou verificação, resolva manualmente.
6. O robô aguarda até 10 minutos e salva a sessão em `browser_session/`.
7. Para cada vaga encontrada, o robô tenta salvar título, empresa, localidade e descrição no banco.

Também é possível rodar uma coleta diretamente pelo terminal:

```bash
meu-robo-linkedin
meu-robo-indeed
```

Observação: a coleta do Indeed é experimental. Ela usa `patchright` quando disponível e
faz fallback para Playwright, porque o Indeed pode bloquear navegadores automatizados.
O checkpoint anterior a essa tentativa está marcado na tag Git:

```bash
checkpoint-before-patchright-indeed
```

## Banco

Configure a conexão no arquivo `.env`:

```text
DATABASE_URL=postgresql://usuario:senha@localhost:5432/projeto_meu_robo
LINKEDIN_EMAIL=seu_email_linkedin
LINKEDIN_PASSWORD=sua_senha_linkedin
OPENAI_API_KEY=sua_chave_openai
OPENAI_MODEL=gpt-5.5
AI_PROVIDER=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_NUM_CTX=16384
```

O schema inicial está em:

```text
database/001_create_initial_schema.sql
```

Migrations incrementais:

```text
database/002_add_job_extracted_content.sql
database/003_add_job_ai_evaluation.sql
```

## Avaliação de vagas com IA

Por padrão, a avaliação usa o Ollama local com o modelo `gemma3:4b`. O Ollama deve
estar ativo em `http://127.0.0.1:11434`. Para usar a API da OpenAI, configure
`AI_PROVIDER=openai` e informe `OPENAI_API_KEY`.

Os arquivos privados de orientação e currículo ficam em:

```text
private/agent_context/agenteRh.md
private/agent_context/cv.md
```

Essa pasta é ignorada pelo Git. Na tela `Vagas`, clique em `Avaliar vagas pendentes`
para classificar vagas que já tenham descrição coletada.

Também é possível rodar pelo terminal:

```bash
meu-robo-avaliar-vagas
```

Por padrão, o comando avalia todas as vagas pendentes. Use `--limit 20` se quiser
processar apenas um lote menor.

## Exportação

Na tela `Vagas`, use os filtros e clique em `Exportar Excel`. Os arquivos também ficam em `exports/`.
