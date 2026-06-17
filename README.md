# Projeto Meu Robo

Ferramenta local para coletar URLs de vagas, salvar no PostgreSQL e acompanhar candidaturas por status e nota.

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

## Coleta LinkedIn

1. Cadastre títulos e localidades na tela inicial.
2. Clique em `Iniciar coleta LinkedIn`.
3. O robô abre um Chromium separado e navega para o LinkedIn.
4. Se `LINKEDIN_EMAIL` e `LINKEDIN_PASSWORD` estiverem configurados no `.env`, o robô tenta fazer o login.
5. Se o Chromium abrir pedindo login, 2FA ou verificação, resolva manualmente.
6. O robô aguarda até 10 minutos e salva a sessão em `browser_session/`.

## Banco

Configure a conexão no arquivo `.env`:

```text
DATABASE_URL=postgresql://usuario:senha@localhost:5432/projeto_meu_robo
LINKEDIN_EMAIL=seu_email_linkedin
LINKEDIN_PASSWORD=sua_senha_linkedin
```

O schema inicial está em:

```text
database/001_create_initial_schema.sql
```

## Exportação

Na tela `Vagas`, use os filtros e clique em `Exportar Excel`. Os arquivos também ficam em `exports/`.
