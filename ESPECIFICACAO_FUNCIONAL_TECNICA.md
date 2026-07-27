# Especificação Funcional e Técnica
## Sistema de Alertas ERP - Olist ERP

## 1. Objetivo
Desenvolver uma aplicação web leve para consultar pedidos no Olist ERP, validar regras de negócio de prazo, desconto e parcelamento, e disparar alertas por email quando houver irregularidades.

A aplicação deve:
- Rodar localmente em Windows durante o desenvolvimento
- Ser preparada para deploy futuro em Linux na AWS EC2
- Operar na porta `3600`
- Consumir o mínimo possível de recursos
- Não usar Docker
- Utilizar autenticação local para a área administrativa
- Permitir configuração operacional pela interface

## 2. Escopo
### 2.1 Escopo incluído
- Login administrativo com email e senha
- Usuário mestre inicial
- Cadastro e exclusão de usuários
- Cadastro e exclusão de destinatários de email
- Configuração da frequência de execução
- Configuração de quantos dias para trás buscar pedidos pela data de emissão
- Configuração das regras de negócio pela interface administrativa
- Execução manual da rotina
- Integração OAuth2 com Olist ERP
- Consulta de pedidos no Olist ERP
- Avaliação das regras de negócio
- Envio de alertas por email via Resend
- Persistência local em SQLite
- Logs estruturados em JSON
- Testes unitários para cada regra de política

### 2.2 Fora do escopo inicial
- Perfis de acesso diferentes de administrador
- Aprovação manual de alertas
- Integração com SMS, WhatsApp ou filas
- Multiempresa
- Banco externo
- Docker e orquestração

## 3. Dados já definidos
### 3.1 Integração Olist
- ERP: `Olist ERP`
- URL base informada: `https://erp.olist.com/`
- URL de redirecionamento: `http://localhost:3600/olist/callback`

### 3.2 Email
- Provider: `Resend`
- Remetente: `financeiro@betinalimpeza.com.br`
- Destinatário inicial: `thiago@betinalimpeza.com.br`

### 3.3 Aplicação
- Porta: `3600`
- Frequência inicial: `30 minutos`
- Timezone: `America/Sao_Paulo`
- Execução manual: obrigatória
- Campo configurável: `dias_retroativos_emissao`
- Logo institucional para abas do navegador: `c:\GitHubLocal\Prazos-Parcelas-Descontos\files\Logo_Azul.webp`

### 3.4 Autenticação local
- Todos os usuários são administradores
- Usuário mestre inicial:
  - Email: `admin@empresa.com`
  - Senha inicial: `Betin@01012023`

## 4. Requisitos funcionais
- `RF-01`: a aplicação deve subir na porta `3600`
- `RF-02`: a aplicação deve exigir autenticação para acesso à área administrativa
- `RF-03`: a aplicação deve criar o usuário mestre no primeiro start
- `RF-04`: a aplicação deve permitir incluir usuários
- `RF-05`: a aplicação deve permitir excluir usuários
- `RF-06`: a aplicação deve permitir incluir destinatários
- `RF-07`: a aplicação deve permitir excluir destinatários
- `RF-08`: a aplicação deve permitir alterar a frequência de execução
- `RF-09`: a aplicação deve permitir configurar `dias_retroativos_emissao`
- `RF-10`: a aplicação deve permitir executar a rotina manualmente
- `RF-11`: a aplicação deve iniciar o fluxo OAuth2 com o Olist ERP
- `RF-12`: a aplicação deve receber callback OAuth2 em `/olist/callback`
- `RF-13`: a aplicação deve armazenar `access_token` e `refresh_token`
- `RF-14`: a aplicação deve renovar o token automaticamente quando necessário
- `RF-15`: a aplicação deve consultar pedidos pela data de emissão dentro da janela configurada
- `RF-16`: a aplicação deve avaliar os pedidos conforme as regras de negócio
- `RF-17`: a aplicação deve enviar alertas por email quando houver irregularidades
- `RF-18`: a aplicação deve registrar histórico de execuções
- `RF-19`: a aplicação deve registrar histórico de alertas enviados
- `RF-20`: a aplicação deve evitar alertas duplicados na mesma janela lógica
- `RF-21`: a aplicação deve exibir o resultado da última execução
- `RF-22`: a aplicação deve permitir alterar faixas de valor, prazo máximo, desconto máximo e exigência de pagamento à vista pela interface
- `RF-23`: a aplicação deve validar que as faixas configuradas não tenham sobreposição nem lacunas inválidas
- `RF-24`: a aplicação deve manter histórico lógico das regras para rastreabilidade das execuções
- `RF-25`: a aplicação deve usar o logo institucional como ícone das abas do navegador

## 5. Regras de negócio
Baseadas em [README.md](file:///c:/GitHubLocal/Prazos-Parcelas-Descontos/README.md#L4-L9).

As regras abaixo representam a configuração inicial do sistema e deverão ser carregadas como políticas padrão no primeiro start. Depois disso, o usuário administrador poderá alterá-las pela interface.

### 5.1 Faixas de valor
- Faixa 1: `valor_pedido <= 150.00`
- Faixa 2: `150.00 < valor_pedido <= 400.00`
- Faixa 3: `400.00 < valor_pedido <= 1000.00`
- Faixa 4: `valor_pedido > 1000.00`

### 5.2 Políticas
- Para pedidos com valor até `R$ 150,00`, o pagamento deve ser à vista e o desconto máximo é `5%`
- Para pedidos com valor acima de `R$ 150,00` até `R$ 400,00`, o prazo máximo é `7 dias` e o desconto máximo é `5%`
- Para pedidos com valor acima de `R$ 400,00` até `R$ 1.000,00`, o prazo máximo é `21 dias` e o desconto máximo é `8%`
- Para pedidos com valor acima de `R$ 1.000,00`, o prazo máximo é `28 dias` e o desconto máximo é `12%`
- Parcelamentos não podem ultrapassar os prazos máximos da faixa aplicável

### 5.3 Interpretações operacionais
- `À vista`: considerar `1 parcela` e `prazo_total_dias = 0`, salvo se a API do Olist oferecer um campo mais apropriado
- `Prazo total`: considerar o maior vencimento financeiro relacionado ao pedido
- `Desconto percentual`: calcular com base no valor bruto e no desconto do pedido quando não vier pronto na API

### 5.4 Administração das políticas
- As políticas devem ser persistidas em banco e não ficar exclusivamente fixas em código
- O sistema deve criar uma carga inicial com as quatro faixas atualmente definidas
- O administrador deve poder alterar:
  - valor inicial da faixa
  - valor final da faixa
  - prazo máximo em dias
  - desconto máximo percentual
  - exigência de pagamento à vista
  - status ativo da regra
- O sistema deve validar antes de salvar:
  - faixas sem sobreposição
  - sequência lógica de valores
  - desconto máximo maior ou igual a `0`
  - prazo máximo maior ou igual a `0`
  - ao menos uma regra ativa
- Alterações de política devem valer para novas execuções após o salvamento
- O sistema deve preservar referência da configuração vigente usada em cada execução para auditoria

## 6. Regras booleanas
As expressões abaixo representam a configuração padrão inicial e devem passar a ser avaliadas de forma dinâmica a partir das regras persistidas no banco.

- `faixa_1 = valor_pedido <= 150.00`
- `faixa_2 = 150.00 < valor_pedido <= 400.00`
- `faixa_3 = 400.00 < valor_pedido <= 1000.00`
- `faixa_4 = valor_pedido > 1000.00`

- `violacao_faixa_1 = faixa_1 and (quantidade_parcelas > 1 or prazo_total_dias > 0 or desconto_percentual > 5.00)`
- `violacao_faixa_2 = faixa_2 and (prazo_total_dias > 7 or desconto_percentual > 5.00)`
- `violacao_faixa_3 = faixa_3 and (prazo_total_dias > 21 or desconto_percentual > 8.00)`
- `violacao_faixa_4 = faixa_4 and (prazo_total_dias > 28 or desconto_percentual > 12.00)`
- `violacao_parcelamento = quantidade_parcelas > 1 and prazo_total_dias > prazo_maximo_da_faixa`
- `pedido_irregular = violacao_faixa_1 or violacao_faixa_2 or violacao_faixa_3 or violacao_faixa_4 or violacao_parcelamento`
- `enviar_alerta = pedido_irregular and destinatarios_ativos > 0 and not alerta_duplicado`

## 7. Requisito adicional de busca
A aplicação deve ter um campo onde o usuário define quantos dias para trás será feita a busca da data de emissão do pedido.

### 7.1 Regra operacional
- `dias_retroativos_emissao` deve ser inteiro maior que `0`
- valor inicial recomendado: `7`
- valor padrão do projeto pode ser ajustado depois
- a mesma regra vale para execução automática e manual

### 7.2 Regra de consulta
- `data_inicio = agora_no_timezone - dias_retroativos_emissao`
- buscar apenas pedidos com `data_emissao >= data_inicio`

## 8. Arquitetura
### 8.1 Visão geral
Aplicação monolítica leve com processo único.

### 8.2 Componentes
- `Web UI/Admin`: tela administrativa
- `Auth Local`: login, sessão, usuários
- `Scheduler`: rotina automática
- `Cliente Olist`: OAuth2, refresh token e consulta REST
- `Normalizador`: converte payload do Olist para modelo interno
- `Motor de Políticas`: aplica regras de negócio
- `Notificador`: monta e envia emails via Resend
- `Persistência`: SQLite
- `Observabilidade`: logs JSON e healthcheck

### 8.3 Desenho em texto
```text
[Usuário]
   |
   v
[FastAPI :3600]
   |
   +--> [Auth Local]
   |
   +--> [UI Admin]
   |       |
   |       +--> Usuários
   |       +--> Destinatários
   |       +--> Configurações
   |       +--> Execução Manual
   |
   +--> [Scheduler]
   |       |
   |       v
   |  [Serviço de Verificação]
   |       |
   |       +--> [Cliente Olist OAuth2 + REST]
   |       +--> [Normalizador]
   |       +--> [Motor de Políticas]
   |       +--> [Histórico SQLite]
   |       +--> [Cliente Resend]
   |
   +--> [/health]
```

## 9. Fluxo funcional
### 9.1 Fluxo de autenticação local
- Usuário acessa a aplicação
- Informa email e senha
- Sistema valida a credencial
- Sistema cria sessão autenticada

### 9.2 Fluxo de conexão Olist
- Usuário acessa a tela de integração
- Clica em `Conectar Olist`
- Sistema redireciona para autorização OAuth2
- Olist retorna para `/olist/callback`
- Sistema troca o `code` por tokens
- Tokens são persistidos

### 9.3 Fluxo de execução
- Scheduler ou botão manual inicia a rotina
- Sistema carrega `dias_retroativos_emissao`
- Sistema calcula a data inicial de busca
- Sistema consulta pedidos no Olist
- Sistema normaliza os dados
- Sistema avalia as regras
- Sistema registra histórico
- Sistema envia alertas quando necessário

## 10. Interface administrativa
### 10.1 Tela de login
Campos:
- email
- senha

Ações:
- entrar

### 10.2 Dashboard
Informações:
- status da integração Olist
- frequência configurada
- dias retroativos configurados
- resumo das políticas vigentes
- total de destinatários ativos
- última execução
- resumo da última execução

Ações:
- executar agora

Branding:
- utilizar o arquivo `files/Logo_Azul.webp` como ícone das abas do navegador

### 10.3 Configurações gerais
Campos:
- frequência de execução em minutos
- dias retroativos de emissão
- email remetente
- timezone

Validações:
- frequência maior que zero
- dias retroativos maior que zero
- email válido

### 10.4 Políticas comerciais
Informações:
- lista de faixas vigentes
- prazo máximo por faixa
- desconto máximo por faixa
- indicação de exigência de pagamento à vista
- data/hora da última alteração

Ações:
- adicionar faixa
- editar faixa
- ativar
- desativar
- restaurar configuração padrão inicial

Validações:
- não permitir sobreposição de faixas
- não permitir faixa com limite final menor que o inicial
- não permitir lacuna operacional não intencional entre faixas ativas
- exigir pelo menos uma política ativa
- destacar impacto da alteração antes do salvamento
### 10.5 Integração Olist
Informações:
- conectado ou desconectado
- expiração do token
- último erro de autenticação, se existir

Ações:
- conectar
- reconectar

### 10.6 Destinatários
Campos:
- email
- ativo

Ações:
- adicionar
- excluir
- ativar
- desativar

### 10.7 Usuários
Campos:
- email
- senha

Ações:
- adicionar
- excluir
- redefinir senha

Regras:
- usuário mestre não pode ser excluído
- email deve ser único

### 10.8 Histórico
- execuções
- alertas enviados
- falhas de envio
- versão lógica das políticas usadas em cada execução

## 11. Stack técnica
- `Python 3.12`: tipagem forte, boa performance e portabilidade
- `FastAPI`: API e interface administrativa leve
- `Uvicorn`: servidor ASGI simples e econômico
- `httpx`: cliente HTTP assíncrono para Olist e Resend
- `Pydantic v2`: validação e tipagem de modelos
- `SQLAlchemy 2.0`: persistência organizada
- `SQLite`: banco local leve e suficiente
- `APScheduler`: agendamento interno configurável
- `Jinja2`: renderização de páginas sem SPA
- `passlib` com `bcrypt` ou `argon2`: hash de senha
- `itsdangerous`: sessão segura leve
- `tenacity`: retry para integrações externas
- `structlog` ou logging JSON: logs estruturados
- `pytest`: testes unitários
- `pytest-asyncio`: testes de componentes assíncronos

## 12. Estrutura recomendada
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
```

## 13. Modelo de dados
### 13.1 users
- `id`
- `email`
- `password_hash`
- `is_master`
- `is_active`
- `created_at`
- `updated_at`

### 13.2 recipients
- `id`
- `email`
- `is_active`
- `created_at`
- `updated_at`

### 13.3 settings
- `id`
- `frequency_minutes`
- `dias_retroativos_emissao`
- `timezone`
- `resend_from_email`
- `created_at`
- `updated_at`

### 13.4 policy_rules
- `id`
- `rule_name`
- `value_min`
- `value_max`
- `max_term_days`
- `max_discount_percent`
- `requires_cash_payment`
- `is_active`
- `sort_order`
- `version_group`
- `created_at`
- `updated_at`

### 13.5 oauth_tokens
- `id`
- `provider`
- `access_token`
- `refresh_token`
- `expires_at`
- `scope`
- `created_at`
- `updated_at`

### 13.6 job_runs
- `id`
- `trigger_type`
- `started_at`
- `finished_at`
- `status`
- `query_start_date`
- `policy_version_group`
- `orders_evaluated`
- `orders_irregular`
- `error_message`

### 13.7 alerts_sent
- `id`
- `job_run_id`
- `order_id`
- `order_number`
- `policy_code`
- `dedupe_key`
- `email_to`
- `sent_at`
- `status`
- `provider_message_id`

## 14. Modelo interno de pedido
- `order_id: str`
- `order_number: str`
- `customer_name: str | None`
- `issue_date: datetime`
- `gross_amount: Decimal`
- `discount_amount: Decimal`
- `discount_percent: Decimal`
- `installments_count: int`
- `max_installment_due_date: date | None`
- `prazo_total_dias: int`
- `payment_terms_description: str | None`
- `raw_payload: dict`

## 15. Serviços principais
### 15.1 AuthService
- autenticar usuário
- criar usuário
- excluir usuário
- redefinir senha
- criar sessão
- validar sessão

### 15.2 SettingsService
- obter configuração atual
- atualizar frequência
- atualizar dias retroativos
- atualizar remetente

### 15.3 PolicyRuleService
- carregar políticas ativas
- validar consistência das faixas
- criar política
- editar política
- ativar e desativar política
- restaurar regras padrão
- fornecer versão lógica vigente para auditoria

### 15.4 OlistOAuthService
- iniciar autorização
- trocar `code` por tokens
- renovar token
- obter token válido

### 15.5 OlistOrderService
- consultar pedidos por período
- paginar resultados
- normalizar payload

### 15.6 PolicyEngine
- avaliar pedido
- retornar lista de violações
- aplicar regras dinamicamente a partir das políticas ativas persistidas
- usar snapshot lógico das regras da execução atual

### 15.7 AlertService
- montar assunto e corpo
- resolver destinatários ativos
- deduplicar envio
- enviar email
- persistir histórico

### 15.8 SchedulerService
- agendar rotina
- reconfigurar frequência
- disparar execução manual
- executar verificação

## 16. Endpoints planejados
- `GET /login`
- `POST /login`
- `POST /logout`
- `GET /`
- `GET /settings`
- `POST /settings`
- `GET /policy-rules`
- `POST /policy-rules`
- `POST /policy-rules/{id}/update`
- `POST /policy-rules/{id}/toggle`
- `POST /policy-rules/restore-defaults`
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

## 17. Configuração
### 17.1 Arquivos
- `app.toml`
- `.env`
- `.env.example`

### 17.2 app.toml
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

### 17.3 Variáveis em .env.example
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

## 18. Deduplicação
- Chave lógica sugerida:
  - `policy_code + order_id + data_execucao_logica`
- Não reenviar alerta já enviado com sucesso para a mesma chave
- Pode evoluir depois para considerar alteração material no pedido

## 19. Formato do alerta
### 19.1 Assunto
`Alerta ERP - Pedido fora da política - {numero_pedido}`

### 19.2 Corpo
- número do pedido
- cliente
- data de emissão
- valor do pedido
- desconto aplicado
- quantidade de parcelas
- prazo total
- regras violadas
- data e hora da execução

## 20. Logs estruturados
Formato `JSON` com campos mínimos:
- `timestamp`
- `level`
- `event`
- `job_run_id`
- `order_id`
- `policy_code`
- `http_status`
- `error_type`
- `message`

## 21. Tratamento de erros
- Erro de autenticação Olist:
  - registrar erro
  - marcar integração como inválida
  - exigir reconexão ou refresh

- Erro de rate limit:
  - retry com backoff

- Erro de envio de email:
  - retry até o limite
  - persistir falha

- Erro inesperado:
  - marcar execução como falha
  - registrar detalhes no log

## 22. Requisitos não funcionais
- `RNF-01`: código totalmente tipado
- `RNF-02`: consumo mínimo de recursos
- `RNF-03`: logs estruturados em JSON
- `RNF-04`: compatível com Windows no desenvolvimento
- `RNF-05`: compatível com Linux na EC2
- `RNF-06`: configuração aderente a 12-factor app
- `RNF-07`: sem Docker
- `RNF-08`: execução em processo único
- `RNF-09`: persistência local suficiente para reinício
- `RNF-10`: interface leve e objetiva
- `RNF-11`: identidade visual deve usar o logo institucional fornecido, incluindo o ícone das abas do navegador

## 23. Testes obrigatórios
- um teste para cada faixa de valor
- um teste para cada limite de desconto
- um teste para cada limite de prazo
- teste de parcelamento acima do prazo máximo
- teste de pedido regular por faixa
- teste de alteração das regras pela interface/serviço
- teste de validação de sobreposição de faixas
- teste de restauração da configuração padrão
- teste de uso da versão correta das políticas em uma execução
- teste de deduplicação
- teste de cálculo de `dias_retroativos_emissao`
- teste de autenticação local
- teste de renovação de token OAuth2
- teste de retry no envio de email

## 24. Casos mínimos de teste
- pedido de `150.00` com `2 parcelas` deve falhar
- pedido de `150.00` com desconto `5%` e à vista deve passar
- pedido de `400.00` com prazo `8 dias` deve falhar
- pedido de `1000.00` com desconto `8%` e prazo `21 dias` deve passar
- pedido de `1000.01` com prazo `29 dias` deve falhar
- pedido parcelado acima do prazo da faixa deve falhar
- cálculo da data inicial com `dias_retroativos_emissao = 7` deve considerar exatamente a janela configurada

## 25. Critérios de aceite
- login funciona corretamente
- usuário mestre existe no primeiro start
- cadastro e exclusão de usuários funciona
- cadastro e exclusão de destinatários funciona
- configuração de frequência funciona
- configuração de dias retroativos funciona
- configuração das regras de negócio funciona pela interface
- alterações inválidas de faixa são bloqueadas com mensagem clara
- execução passa a usar as políticas salvas pelo usuário
- histórico da execução registra qual versão lógica das regras foi aplicada
- integração OAuth2 com Olist funciona
- execução manual funciona
- rotina automática respeita a frequência
- consulta respeita `dias_retroativos_emissao`
- políticas são avaliadas corretamente
- email é enviado quando houver irregularidade
- deduplicação evita reenvio indevido
- histórico e logs são persistidos

## 26. Deploy futuro em EC2
### 26.1 Estratégia
- usar `venv`
- instalar dependências diretamente no Linux
- rodar aplicação com `uvicorn`
- gerenciar serviço com `systemd`

### 26.2 Itens previstos
- arquivo de serviço `systemd`
- diretório da aplicação
- `.env`
- banco SQLite local
- logs em journald
- Nginx opcional para proxy e TLS

## 27. Riscos e pendências técnicas
- confirmar endpoints exatos do Olist para autorização, token e pedidos
- confirmar campos reais da API para desconto, parcelas e vencimentos
- validar remetente `financeiro@betinalimpeza.com.br` no Resend
- rotacionar credenciais compartilhadas antes do uso real
- decidir se execução manual poderá sobrescrever temporariamente os dias retroativos
- decidir se alterações de política exigirão confirmação dupla ou publicação imediata
- preferir exclusão lógica para usuários e destinatários

## 28. Recomendações finais
- não armazenar secrets no repositório
- manter senha mestre apenas como bootstrap inicial
- tornar o usuário mestre não excluível
- usar SQLite nesta primeira fase
- manter a UI simples e server-rendered
- evoluir para banco externo apenas se houver necessidade real
