# Prompt Fechado Para Codificação

Implemente integralmente o projeto `Prazos-Parcelas-Descontos` conforme as instruções abaixo.

## Papel
Você é um desenvolvedor sênior full-stack Python, com foco em aplicações leves, seguras, tipadas e prontas para produção em Linux/EC2.

## Objetivo
Construir uma aplicação web administrativa que:
- conecta ao `Olist ERP` via `OAuth2`
- consulta pedidos por janela retroativa de data de emissão
- valida regras de desconto, prazo e parcelamento
- envia alertas por email via `Resend`
- permite administração de usuários, destinatários, frequência e execução manual

## Restrições Obrigatórias
- Use `Python 3.12`
- Use `FastAPI`
- Use `httpx`
- Use `Pydantic v2`
- Use `SQLite`
- Use `SQLAlchemy 2.0`
- Use `APScheduler`
- Use tipagem completa com `type hints`
- Use logs estruturados em `JSON`
- Não use Docker
- A aplicação deve rodar na porta `3600`
- A aplicação deve consumir o mínimo de recursos possível
- Use UI simples e server-rendered, sem SPA pesada
- Implemente testes unitários para cada regra de política
- Mantenha o projeto preparado para futura execução em Linux/EC2
- Não exponha secrets no código
- Use `.env` para segredos
- Faça exclusão lógica de usuários e destinatários
- O usuário mestre não pode ser excluído

## Decisões Fechadas
Considere estas decisões como definitivas:
- todos os usuários são administradores
- autenticação local por email e senha
- execução manual usa o valor salvo de `dias_retroativos_emissao`
- alertar todos os pedidos irregulares encontrados dentro da janela configurada
- deduplicação por `pedido + regra + janela`
- timezone: `America/Sao_Paulo`
- frequência inicial: `30 minutos`
- destinatário inicial: `thiago@betinalimpeza.com.br`
- remetente Resend: `financeiro@betinalimpeza.com.br`
- URL base informada do Olist: `https://erp.olist.com/`
- callback OAuth2: `http://localhost:3600/olist/callback`

## Usuário Mestre Inicial
Criar no bootstrap:
- email: `admin@empresa.com`
- senha inicial: via variável de ambiente
- `is_master = true`

Não hardcode a senha no código-fonte.
Use variável de ambiente para a senha inicial.

## Regras de Negócio
Implemente exatamente estas regras:

### Faixas
- `faixa_1 = valor_pedido <= 150.00`
- `faixa_2 = 150.00 < valor_pedido <= 400.00`
- `faixa_3 = 400.00 < valor_pedido <= 1000.00`
- `faixa_4 = valor_pedido > 1000.00`

### Políticas
- Para pedidos até `R$ 150,00`, o pagamento deve ser à vista e o desconto máximo é `5%`
- Para pedidos acima de `R$ 150,00` até `R$ 400,00`, o prazo máximo é `7 dias` e o desconto máximo é `5%`
- Para pedidos acima de `R$ 400,00` até `R$ 1.000,00`, o prazo máximo é `21 dias` e o desconto máximo é `8%`
- Para pedidos acima de `R$ 1.000,00`, o prazo máximo é `28 dias` e o desconto máximo é `12%`
- Parcelamentos não podem ultrapassar os prazos máximos da faixa

### Regras Booleanas
Implemente funções puras para avaliar:
- `violacao_faixa_1 = faixa_1 and (quantidade_parcelas > 1 or prazo_total_dias > 0 or desconto_percentual > 5.00)`
- `violacao_faixa_2 = faixa_2 and (prazo_total_dias > 7 or desconto_percentual > 5.00)`
- `violacao_faixa_3 = faixa_3 and (prazo_total_dias > 21 or desconto_percentual > 8.00)`
- `violacao_faixa_4 = faixa_4 and (prazo_total_dias > 28 or desconto_percentual > 12.00)`
- `violacao_parcelamento = quantidade_parcelas > 1 and prazo_total_dias > prazo_maximo_da_faixa`

## Regra De Busca
A aplicação deve ter configuração persistida chamada `dias_retroativos_emissao`.

Requisitos:
- inteiro maior que zero
- valor padrão inicial: `7`
- deve ser editável na interface
- deve ser usado na execução automática e manual
- deve filtrar pedidos por data de emissão

Regra:
- `data_inicio = agora_no_timezone - dias_retroativos_emissao`
- consultar pedidos com `data_emissao >= data_inicio`

## Funcionalidades Obrigatórias
Implemente:

### Autenticação e usuários
- login por email e senha
- logout
- sessão autenticada por cookie seguro
- criação de usuários
- redefinição de senha
- exclusão lógica de usuários
- usuário mestre não excluível

### Destinatários
- cadastro de destinatário
- ativação/desativação
- exclusão lógica
- listagem

### Configurações
- frequência em minutos
- dias retroativos de emissão
- email remetente
- status da integração Olist

### Integração Olist
- iniciar OAuth2
- receber callback
- trocar `code` por tokens
- persistir tokens
- renovar `access_token` com `refresh_token`
- consultar pedidos com base na janela configurada

### Execução
- scheduler automático
- execução manual por botão
- histórico de execuções
- histórico de alertas enviados

### Alertas
- montar email com dados do pedido e violações
- enviar via Resend
- aplicar retry com backoff
- registrar sucesso/falha
- deduplicar envio

## Interface Administrativa
Crie uma interface web simples, densa e leve, sem frontend complexo.

Telas mínimas:
- login
- dashboard
- configurações
- integração Olist
- usuários
- destinatários
- histórico de execuções
- histórico de alertas

O dashboard deve mostrar:
- status da integração Olist
- frequência configurada
- dias retroativos configurados
- última execução
- quantidade de destinatários ativos
- botão `Executar agora`

## Modelo De Dados
Implemente tabelas equivalentes a:

### users
- id
- email
- password_hash
- is_master
- is_active
- created_at
- updated_at
- deleted_at nullable

### recipients
- id
- email
- is_active
- created_at
- updated_at
- deleted_at nullable

### settings
- id
- frequency_minutes
- dias_retroativos_emissao
- timezone
- resend_from_email
- created_at
- updated_at

### oauth_tokens
- id
- provider
- access_token
- refresh_token
- expires_at
- scope
- created_at
- updated_at

### job_runs
- id
- trigger_type
- started_at
- finished_at
- status
- query_start_date
- orders_evaluated
- orders_irregular
- error_message

### alerts_sent
- id
- job_run_id
- order_id
- order_number
- policy_code
- dedupe_key
- email_to
- sent_at
- status
- provider_message_id

## Estrutura Do Projeto
Siga preferencialmente esta estrutura:

```text
app/
  main.py
  config.py
  db.py
  auth/
  clients/
  domain/
  models/
  repositories/
  services/
  templates/
  static/
  web/
tests/
  unit/
  integration/
scripts/
requirements.txt
app.toml
.env.example
README.md
```

## Contratos Internos
Implemente serviços equivalentes a:

- `AuthService`
- `SettingsService`
- `OlistOAuthService`
- `OlistOrderService`
- `PolicyEngine`
- `AlertService`
- `SchedulerService`

## Requisitos Técnicos
- Use funções puras para regras de política
- Separe integração Olist da normalização do payload
- Mantenha URLs OAuth2 e endpoints Olist configuráveis
- Não assuma campos rígidos da API do Olist fora de uma camada de mapeamento
- Use timeout em integrações externas
- Use retry com backoff para chamadas transitórias
- Faça validação de configuração no startup
- Estruture logs em JSON
- Evite dependências desnecessárias
- Prefira código claro a abstrações excessivas

## Endpoints Esperados
Implemente endpoints equivalentes a:
- `GET /login`
- `POST /login`
- `POST /logout`
- `GET /`
- `GET /settings`
- `POST /settings`
- `GET /users`
- `POST /users`
- `POST /users/{id}/delete`
- `POST /users/{id}/reset-password`
- `GET /recipients`
- `POST /recipients`
- `POST /recipients/{id}/delete`
- `POST /recipients/{id}/toggle`
- `GET /olist/connect`
- `GET /olist/callback`
- `POST /runs/execute`
- `GET /runs`
- `GET /alerts`
- `GET /health`

## Configuração
Crie:
- `app.toml`
- `.env.example`

Inclua ao menos:

### app.toml
```toml
[app]
port = 3600
timezone = "America/Sao_Paulo"

[scheduler]
frequency_minutes = 30
default_dias_retroativos_emissao = 7

[alerts]
retry_attempts = 3
retry_backoff_seconds = 2

[logging]
level = "INFO"
```

### .env.example
```env
APP_SESSION_SECRET=
OLIST_CLIENT_ID=
OLIST_CLIENT_SECRET=
OLIST_REDIRECT_URI=http://localhost:3600/olist/callback
OLIST_BASE_URL=https://erp.olist.com/
OLIST_AUTH_URL=
OLIST_TOKEN_URL=
RESEND_API_KEY=
RESEND_FROM_EMAIL=financeiro@betinalimpeza.com.br
MASTER_USER_EMAIL=admin@empresa.com
MASTER_USER_PASSWORD=
```

## Testes Obrigatórios
Implemente testes unitários para:
- cada faixa de valor
- cada limite de desconto
- cada limite de prazo
- parcelamento acima do prazo máximo
- caso válido por faixa
- deduplicação
- cálculo de `dias_retroativos_emissao`
- autenticação local
- refresh de token OAuth2
- retry de envio de email

Casos mínimos:
- pedido `150.00` com `2 parcelas` falha
- pedido `150.00` à vista com `5%` passa
- pedido `400.00` com prazo `8 dias` falha
- pedido `1000.00` com prazo `21 dias` e `8%` passa
- pedido `1000.01` com prazo `29 dias` falha

## Critérios De Aceite
Considere concluído somente se:
- a aplicação sobe localmente na porta `3600`
- login funciona
- usuário mestre é criado
- usuários podem ser geridos
- destinatários podem ser geridos
- frequência pode ser configurada
- dias retroativos podem ser configurados
- OAuth2 do Olist está estruturado
- execução manual funciona
- scheduler automático funciona
- as políticas estão corretas
- alertas são enviados
- deduplicação evita reenvio indevido
- histórico é persistido
- testes passam

## Observações Importantes
- Se houver incerteza sobre campos reais da API do Olist, isole isso na camada de cliente/normalização e mantenha configurável
- Se algum endpoint do Olist precisar ser ajustado, isso deve exigir mudança mínima no restante do código
- Não use Docker
- Não substitua a arquitetura por uma solução mais pesada
- Mantenha a UI simples e funcional
- Documente no `README.md` como executar localmente no Windows e como preparar para Linux/EC2

## Entrega Esperada
Entregue o projeto codificado com:
- código fonte
- configuração base
- testes
- README de execução
- interface administrativa funcional
- scheduler funcional
- integração Resend pronta
- integração Olist estruturada e configurável
