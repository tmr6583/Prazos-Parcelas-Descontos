---
name: "olist-alerts-erp-coder"
description: "Builds the Olist ERP alerts system end-to-end. Invoke when implementing, extending, or reviewing this project’s code, architecture, rules, scheduler, auth, and integrations."
---

# Olist ERP Alerts ERP Coder

## Purpose

Use this skill to implement and maintain the `Prazos-Parcelas-Descontos` project.

This project is a lightweight Python web application that:
- connects to Olist ERP using OAuth2
- queries orders by issue date window
- evaluates payment term and discount policies
- sends alert emails through Resend
- provides a small admin UI for settings, users, recipients, and manual execution

## When To Invoke

Invoke this skill when:
- creating the initial project structure
- implementing API/UI/auth/scheduler/database code
- wiring Olist OAuth2 or order queries
- implementing policy evaluation
- implementing email alerts with retry and deduplication
- adding tests for the business rules
- refactoring the project while preserving the agreed architecture

Do not invoke this skill for unrelated generic coding tasks outside this repository.

## Fixed Project Decisions

Treat the following as approved requirements unless the user explicitly changes them:

- Language: `Python`
- Runtime: `Python 3.12`
- Web framework: `FastAPI`
- HTTP client: `httpx`
- Validation: `Pydantic v2`
- Persistence: `SQLite`
- ORM/access layer: `SQLAlchemy 2.0`
- Scheduler: `APScheduler`
- Email provider: `Resend`
- Logs: structured JSON
- Deployment target: Linux on AWS EC2 later
- Current environment: local Windows
- App port: `3600`
- No Docker
- Single lightweight process
- Minimal resource usage
- Admin authentication with local email/password
- All users are administrators
- Master user exists at bootstrap and is not deletable
- Logical deletion for users and recipients
- Manual execution uses the saved `dias_retroativos_emissao`
- Alerts apply to all irregular orders inside the configured window
- Deduplication key uses `pedido + regra + janela`

## Business Rules

Use these exact rules:

- If `valor_pedido <= 150.00`, payment must be cash/immediate and discount must be at most `5%`
- If `150.00 < valor_pedido <= 400.00`, max term is `7 days` and discount must be at most `5%`
- If `400.00 < valor_pedido <= 1000.00`, max term is `21 days` and discount must be at most `8%`
- If `valor_pedido > 1000.00`, max term is `28 days` and discount must be at most `12%`
- Installments must never exceed the max term of the applicable range

Boolean interpretation:

- `faixa_1 = valor_pedido <= 150.00`
- `faixa_2 = 150.00 < valor_pedido <= 400.00`
- `faixa_3 = 400.00 < valor_pedido <= 1000.00`
- `faixa_4 = valor_pedido > 1000.00`

- `violacao_faixa_1 = faixa_1 and (quantidade_parcelas > 1 or prazo_total_dias > 0 or desconto_percentual > 5.00)`
- `violacao_faixa_2 = faixa_2 and (prazo_total_dias > 7 or desconto_percentual > 5.00)`
- `violacao_faixa_3 = faixa_3 and (prazo_total_dias > 21 or desconto_percentual > 8.00)`
- `violacao_faixa_4 = faixa_4 and (prazo_total_dias > 28 or desconto_percentual > 12.00)`
- `violacao_parcelamento = quantidade_parcelas > 1 and prazo_total_dias > prazo_maximo_da_faixa`

## Functional Requirements

Always preserve these behaviors:

- app listens on port `3600`
- admin login is required
- app supports user management
- app supports recipient management
- app supports configurable run frequency
- app supports configurable `dias_retroativos_emissao`
- app supports manual execution
- app uses Olist OAuth2 callback at `http://localhost:3600/olist/callback`
- app stores and refreshes OAuth tokens
- app queries orders by issue date window
- app sends alerts via Resend
- app records job history and sent alerts
- app exposes lightweight admin UI and health endpoint

## Technical Requirements

- Use type hints everywhere
- Keep modules small and cohesive
- Prefer async I/O for external calls
- Use low-overhead server-rendered pages instead of a heavy SPA
- Keep dependencies minimal
- Read secrets from `.env`, never hardcode
- Do not expose secrets in logs
- Store passwords hashed only
- Use structured JSON logging
- Add unit tests for each policy
- Add retry for external HTTP failures where appropriate
- Validate configuration at startup
- Prefer logical deletion over physical deletion for users/recipients

## Recommended Project Layout

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

## Olist Integration Guidance

Base information already known:
- base URL informed by user: `https://erp.olist.com/`
- OAuth2 callback: `http://localhost:3600/olist/callback`

During implementation:
- keep auth/token/order endpoints configurable
- avoid assuming undocumented payload fields without encapsulating mapping logic
- isolate normalization inside a dedicated service/client layer
- make pagination and filtering explicit and testable

## Email Guidance

Use Resend through HTTP calls.
Implement:
- timeout
- retry with backoff
- recipient resolution from active recipients
- deduplication before send
- persistence of send result

## Testing Guidance

At minimum, cover:
- one valid and one invalid case for each range
- installment term overflow
- deduplication behavior
- retroactive days filter calculation
- local auth behavior
- OAuth token refresh path
- email retry path

## Implementation Style

- Favor clarity over abstraction
- Avoid premature generalization
- Keep HTML simple and dense
- Keep vertical spacing compact in UI
- Build for maintainability and low resource usage
- If a real API detail is uncertain, make it configurable and isolate the assumption
