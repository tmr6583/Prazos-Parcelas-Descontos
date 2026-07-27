# Prazos-Parcelas-Descontos
Aplicação web leve para monitorar pedidos do Olist ERP e alertar quando estiverem fora da política comercial.

Nome operacional da aplicação: `cagoete`.

# Regras de Negócio
Para pedidos com valor até R$ 150,00, o pagamento deve ser a vista e o desconto máximo de 5%. 
Para pedidos com valor de R$ 150,00 a R$ 400,00 , o prazo máximo é de 7 dias e o desconto máximo de 5%. 
Para pedidos com valor de R$ 400,00 a R$ 1.000,00, o prazo máximo é de 21 dias e o desconto máximo de 8%.
Para pedidos com valor acima de R$ 1.000,00 o prazo máximo é de 28 dias e o desconto máximo de 12%. 
Os parcelamentos não podem ultrapassar os prazos máximos. 

## Stack
- Python 3.12
- FastAPI
- SQLAlchemy 2.0
- SQLite
- APScheduler
- Jinja2
- httpx

## Como executar
1. Instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

2. Crie o arquivo `.env` a partir do `.env.example` e preencha as credenciais necessárias.

3. Suba a aplicação:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 3600 --reload
```

4. Acesse:

```text
http://127.0.0.1:3600
```

## Credenciais iniciais
- Usuário mestre: `admin@empresa.com`
- Senha inicial padrão: `Betin@01012023`

Altere a senha logo após o primeiro acesso.

## Como usar
1. Faça login.
2. Revise as `Configurações gerais`.
3. Ajuste as `Políticas comerciais` se precisar alterar as faixas, prazos, descontos e exigência de pagamento à vista.
4. Cadastre os `Destinatários` que receberão os alertas.
5. Clique em `Conectar Olist` após preencher as variáveis OAuth no `.env`.
6. Execute `Executar agora` para rodar a verificação manualmente.
7. Acompanhe os blocos `Histórico de execuções` e `Alertas enviados`.

## Variáveis importantes no .env
- `APP_SESSION_SECRET`
- `OLIST_CLIENT_ID`
- `OLIST_CLIENT_SECRET`
- `OLIST_AUTH_URL`
- `OLIST_TOKEN_URL`
- `OLIST_ORDERS_PATH`
- `RESEND_API_KEY`
- `RESEND_FROM_EMAIL`

## Testes
Para executar a suíte automatizada:

```powershell
python -m pytest
```

