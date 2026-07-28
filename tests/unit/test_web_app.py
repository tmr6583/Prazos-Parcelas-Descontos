from __future__ import annotations
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.models import AlertSent, IdentifiedOrder, JobRun, OAuthToken, OlistConnectionSetting, Recipient, Setting, User
from app.services.admin import AdminService
from app.services.runtime_log import write_runtime_event


def login(client) -> None:
    response = client.post(
        "/login",
        data={"email": "admin@empresa.com", "password": "Betin@01012023"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_login_and_dashboard_render(web_client, monkeypatch) -> None:
    client, _, _ = web_client
    monkeypatch.setattr(
        AdminService,
        "get_online_log_lines",
        lambda self, limit=10: [f"[27/07/2026 17:30:{index:02d}] linha {index}" for index in range(10)],
    )

    response = client.get("/login")
    assert response.status_code == 200
    assert "Sistema de Alertas ERP" in response.text
    assert "cagoete" not in response.text
    assert "Betina Soluções em Limpeza" not in response.text

    login(client)

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Políticas comerciais" in dashboard.text
    assert "Painel administrativo" in dashboard.text
    assert "Operação leve, interface densa e controle administrativo centralizado." not in dashboard.text
    assert "Timezone" not in dashboard.text
    assert "cagoete" not in dashboard.text
    assert "Betina" in dashboard.text
    assert "ID do cliente" in dashboard.text
    assert "URL do token OAuth" in dashboard.text
    assert "Log online" in dashboard.text
    assert "Pedidos Identificados" in dashboard.text
    assert "Últimas 10 linhas do log" in dashboard.text
    assert "[27/07/2026 17:30:09] linha 9" in dashboard.text
    assert "Fluxo OAuth2 com configuração persistida na aplicação, seguindo o padrão do Albertina." not in dashboard.text
    assert "Frequência, janela de busca e remetente para os alertas." not in dashboard.text
    assert "As regras são dados administráveis pelo usuário. Salvar gera uma nova versão lógica." not in dashboard.text
    assert dashboard.text.index("Log online") < dashboard.text.index("Integração Olist")
    assert dashboard.text.index("Integração Olist") < dashboard.text.index("Configurações gerais")


def test_update_settings_and_policy_rules(web_client) -> None:
    client, db_session, scheduler = web_client
    login(client)

    settings_response = client.post(
        "/settings",
        data={
            "frequency_minutes": "45",
            "dias_retroativos_emissao": "10",
            "resend_from_email": "financeiro@betinalimpeza.com.br",
        },
        follow_redirects=False,
    )
    assert settings_response.status_code == 303
    assert scheduler.rescheduled is True

    settings_row = db_session.get(Setting, 1)
    assert settings_row.frequency_minutes == 45
    assert settings_row.dias_retroativos_emissao == 10

    policy_response = client.post(
        "/policy-rules",
        data={
            "row_id": ["1", "2", "3"],
            "rule_name": ["Faixa 1", "Faixa 2", "Faixa VIP"],
            "value_min": ["R$ 0,00", "R$ 100,01", "R$ 250,01"],
            "value_max": ["R$ 100,00", "R$ 250,00", ""],
            "max_term_days": ["0", "12", "30"],
            "max_discount_percent": ["4,00%", "6,50%", "9,25%"],
            "requires_cash_payment": ["1"],
            "is_active": ["1", "2", "3"],
        },
        follow_redirects=False,
    )
    assert policy_response.status_code == 303

    dashboard = client.get("/")
    assert "Faixa VIP" in dashboard.text
    assert "R$ 250,01" in dashboard.text
    assert "9,25%" in dashboard.text
    assert "12" in dashboard.text
    assert "Faixa 4" not in dashboard.text


def test_update_olist_settings_and_connect(web_client) -> None:
    client, db_session, _ = web_client
    login(client)

    response = client.post(
        "/olist/settings",
        data={
            "client_id": "cliente-123",
            "client_secret": "segredo-456",
            "redirect_uri": "http://localhost:3600/olist/callback",
            "auth_url": "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth",
            "token_url": "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token",
            "api_base_url": "https://erp.olist.com/",
            "orders_path": "api/v3/orders",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    config = db_session.get(OlistConnectionSetting, 1)
    assert config is not None
    assert config.client_id == "cliente-123"
    assert config.client_secret == "segredo-456"
    assert config.orders_path == "api/v3/orders"

    connect = client.get("/olist/connect", follow_redirects=False)
    assert connect.status_code == 302
    assert connect.headers["location"].startswith("https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth?")
    db_session.refresh(config)
    assert config.oauth_state is not None
    assert "state=" in connect.headers["location"]


def test_olist_callback_and_renew_token(web_client, monkeypatch) -> None:
    client, db_session, _ = web_client
    login(client)

    config = db_session.get(OlistConnectionSetting, 1)
    assert config is not None
    config.client_id = "cliente-123"
    config.client_secret = "segredo-456"
    config.auth_url = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth"
    config.token_url = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token"
    config.redirect_uri = "http://localhost:3600/olist/callback"
    config.api_base_url = "https://erp.olist.com/"
    config.oauth_state = "estado-valido"
    db_session.commit()

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    payloads = [
        {
            "access_token": "access-123",
            "refresh_token": "refresh-123",
            "expires_in": 3600,
            "scope": "openid",
            "token_type": "Bearer",
        },
        {
            "access_token": "access-456",
            "refresh_token": "refresh-456",
            "expires_in": 7200,
            "scope": "openid",
            "token_type": "Bearer",
        },
    ]

    def fake_post(url, headers, data, timeout):
        assert url == "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token"
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert timeout == 20.0
        return DummyResponse(payloads.pop(0))

    monkeypatch.setattr("app.services.olist.httpx.post", fake_post)

    callback = client.get("/olist/callback?code=abc123&state=estado-valido", follow_redirects=False)
    assert callback.status_code == 303

    token = db_session.query(OAuthToken).filter(OAuthToken.provider == "olist").one()
    assert token.access_token == "access-123"
    assert token.refresh_token == "refresh-123"
    db_session.refresh(config)
    assert config.oauth_state is None
    assert config.last_callback_at is not None

    renew = client.post("/olist/renew-token", follow_redirects=False)
    assert renew.status_code == 303
    db_session.refresh(token)
    assert token.access_token == "access-456"
    assert token.refresh_token == "refresh-456"


def test_online_log_merges_runtime_and_control_entries(db_session, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.services.admin.BASE_DIR", tmp_path)
    monkeypatch.setattr("app.services.runtime_log.RUNTIME_LOG_PATH", tmp_path / "Cagoete.runtime.log")

    (tmp_path / "Cagoete.log").write_text(
        "[27/07/2026 17:14:16] Inicio solicitado.\n",
        encoding="utf-8",
    )
    write_runtime_event(
        "olist_authorized",
        "Olist conectada com sucesso.",
        expires_at="2026-07-27T22:15:00+00:00",
    )

    lines = AdminService(db_session).get_online_log_lines(limit=10)
    assert any("Inicio solicitado." in line for line in lines)
    assert any("Olist conectada com sucesso." in line for line in lines)


def test_dashboard_shows_oauth_events_in_online_log(web_client, monkeypatch, tmp_path) -> None:
    client, db_session, _ = web_client
    monkeypatch.setattr("app.services.admin.BASE_DIR", tmp_path)
    monkeypatch.setattr("app.services.runtime_log.RUNTIME_LOG_PATH", tmp_path / "Cagoete.runtime.log")
    login(client)

    config = db_session.get(OlistConnectionSetting, 1)
    assert config is not None
    config.client_id = "cliente-123"
    config.client_secret = "segredo-456"
    config.auth_url = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth"
    config.token_url = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token"
    config.redirect_uri = "http://localhost:3600/olist/callback"
    config.api_base_url = "https://erp.olist.com/"
    config.oauth_state = "estado-valido"
    db_session.commit()

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    payloads = [
        {
            "access_token": "access-123",
            "refresh_token": "refresh-123",
            "expires_in": 3600,
            "scope": "openid",
            "token_type": "Bearer",
        },
        {
            "access_token": "access-456",
            "refresh_token": "refresh-456",
            "expires_in": 7200,
            "scope": "openid",
            "token_type": "Bearer",
        },
    ]

    def fake_post(url, headers, data, timeout):
        return DummyResponse(payloads.pop(0))

    monkeypatch.setattr("app.services.olist.httpx.post", fake_post)

    callback = client.get("/olist/callback?code=abc123&state=estado-valido", follow_redirects=False)
    assert callback.status_code == 303

    renew = client.post("/olist/renew-token", follow_redirects=False)
    assert renew.status_code == 303

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Olist conectada com sucesso." in dashboard.text
    assert "Token Olist renovado com sucesso." in dashboard.text


def test_dashboard_formats_olist_datetimes_in_sao_paulo(web_client, monkeypatch) -> None:
    client, db_session, _ = web_client
    monkeypatch.setattr(AdminService, "get_online_log_lines", lambda self, limit=10: [])
    login(client)

    config = db_session.get(OlistConnectionSetting, 1)
    assert config is not None
    config.client_id = "cliente-123"
    config.client_secret = "segredo-456"
    config.last_connect_attempt_at = datetime(2026, 7, 27, 21, 31, 23, 595197, tzinfo=UTC)
    config.last_callback_at = datetime(2026, 7, 27, 22, 0, 5, 100000, tzinfo=UTC)

    token = OAuthToken(
        provider="olist",
        access_token="access-123",
        refresh_token="refresh-123",
        expires_at=datetime(2026, 7, 27, 23, 15, 0, tzinfo=UTC),
    )
    db_session.add(token)
    db_session.commit()

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "2026-07-27 18:31:23" in dashboard.text
    assert "2026-07-27 19:00:05" in dashboard.text
    assert "2026-07-27 20:15:00" in dashboard.text
    assert "595197" not in dashboard.text


def test_dashboard_shows_identifed_orders_panel(web_client, monkeypatch) -> None:
    client, db_session, _ = web_client
    monkeypatch.setattr(AdminService, "get_online_log_lines", lambda self, limit=10: [])
    login(client)

    job_run = JobRun(
        trigger_type="manual",
        status="success",
        orders_evaluated=4,
        orders_irregular=1,
        started_at=datetime(2026, 7, 27, 20, 0, 0, tzinfo=UTC),
    )
    db_session.add(job_run)
    db_session.commit()
    db_session.refresh(job_run)

    identified_order = IdentifiedOrder(
        job_run_id=job_run.id,
        order_id="pedido-001",
        order_number="12345",
        policy_code="FAIXA_4",
        violation_description="Faixa 4 permite até 28 dias e desconto máximo de 12.00%.",
        sale_date_display="2026-07-27",
        gross_amount=Decimal("1500.24"),
        discount_amount=Decimal("180.03"),
        discount_percent=Decimal("12.00"),
        seller_name="Juliana",
        customer_name="Cliente Exemplo",
    )
    db_session.add(identified_order)
    db_session.commit()

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Pedidos Identificados" in dashboard.text
    assert "12345" in dashboard.text
    assert "2026-07-27" in dashboard.text
    assert "Cliente Exemplo" in dashboard.text
    assert "R$ 1.500,24" in dashboard.text
    assert "R$ 180,03" in dashboard.text
    assert "12,00%" in dashboard.text
    assert "FAIXA_4" in dashboard.text
    assert "Juliana" in dashboard.text
    assert "1" in dashboard.text


def test_execution_service_writes_runtime_log_events(db_session, monkeypatch) -> None:
    from app.config import Settings
    from app.services.execution import ExecutionService

    recorded_events: list[tuple[str, str, dict]] = []

    def fake_write_runtime_event(event, message, level="INFO", **context):
        recorded_events.append((event, message, {"level": level, **context}))

    monkeypatch.setattr("app.services.execution.write_runtime_event", fake_write_runtime_event)

    service = ExecutionService(db_session, Settings())
    monkeypatch.setattr(
        service.settings_service,
        "get",
        lambda: SimpleNamespace(timezone="America/Sao_Paulo", dias_retroativos_emissao=7),
    )
    monkeypatch.setattr(service.policy_rule_service, "list_current_rules", lambda: [SimpleNamespace()])
    monkeypatch.setattr(service.policy_rule_service, "get_current_version_group", lambda: 1)
    monkeypatch.setattr(
        "app.services.execution.PolicyEngine",
        lambda rules: SimpleNamespace(evaluate=lambda order: []),
    )
    monkeypatch.setattr(
        service.settings_service,
        "calculate_query_start",
        lambda timezone_name, dias_retroativos_emissao: datetime(2026, 7, 27, 0, 0, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(service.admin_service, "list_active_recipients", lambda: [])
    monkeypatch.setattr(service.olist_service, "fetch_orders", lambda query_start: [])

    job_run = service.run(trigger_type="manual")

    assert job_run.status == "success"
    assert [item[0] for item in recorded_events] == [
        "execution_started",
        "execution_olist_summary",
        "execution_finished",
    ]
    assert recorded_events[1][2]["orders_evaluated"] == 0
    assert recorded_events[1][2]["recipients_count"] == 0
    assert recorded_events[2][2]["orders_irregular"] == 0


def test_execution_service_persists_identified_orders_without_recipients(db_session, monkeypatch) -> None:
    from app.config import Settings
    from app.services.execution import ExecutionService

    service = ExecutionService(db_session, Settings())
    monkeypatch.setattr(
        service.settings_service,
        "get",
        lambda: SimpleNamespace(timezone="America/Sao_Paulo", dias_retroativos_emissao=7),
    )
    monkeypatch.setattr(service.policy_rule_service, "list_current_rules", lambda: [SimpleNamespace()])
    monkeypatch.setattr(service.policy_rule_service, "get_current_version_group", lambda: 1)
    monkeypatch.setattr(
        service.settings_service,
        "calculate_query_start",
        lambda timezone_name, dias_retroativos_emissao: datetime(2026, 7, 27, 0, 0, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(service.admin_service, "list_active_recipients", lambda: [])
    monkeypatch.setattr(
        service.olist_service,
        "fetch_orders",
        lambda query_start: [
            SimpleNamespace(
                order_id="pedido-002",
                order_number="2002",
                customer_name="Cliente B",
                seller_name="Fernanda",
                gross_amount=1250.50,
                discount_amount=75.03,
                discount_percent=6.00,
                issue_date_display="2026-07-28",
            ),
        ],
    )
    monkeypatch.setattr(
        "app.services.execution.PolicyEngine",
        lambda rules: SimpleNamespace(
            evaluate=lambda order: [
                SimpleNamespace(
                    policy_code="FAIXA_2",
                    description="Faixa 2 permite até 7 dias e desconto máximo de 5.00%.",
                ),
            ],
        ),
    )
    monkeypatch.setattr("app.services.execution.write_runtime_event", lambda *args, **kwargs: None)

    job_run = service.run(trigger_type="manual")

    identified_orders = db_session.query(IdentifiedOrder).filter(IdentifiedOrder.job_run_id == job_run.id).all()
    assert job_run.orders_irregular == 1
    assert len(identified_orders) == 1
    assert identified_orders[0].order_number == "2002"
    assert identified_orders[0].policy_code == "FAIXA_2"
    assert identified_orders[0].seller_name == "Fernanda"
    assert identified_orders[0].customer_name == "Cliente B"
    assert identified_orders[0].sale_date_display == "2026-07-28"
    assert float(identified_orders[0].gross_amount) == 1250.50
    assert float(identified_orders[0].discount_amount) == 75.03
    assert float(identified_orders[0].discount_percent) == 6.00


def test_execution_service_reuses_failed_alert_record_without_integrity_error(db_session, monkeypatch) -> None:
    from app.config import Settings
    from app.services.execution import ExecutionService

    service = ExecutionService(db_session, Settings())
    monkeypatch.setattr(
        service.settings_service,
        "get",
        lambda: SimpleNamespace(timezone="America/Sao_Paulo", dias_retroativos_emissao=3),
    )
    monkeypatch.setattr(service.policy_rule_service, "list_current_rules", lambda: [SimpleNamespace()])
    monkeypatch.setattr(service.policy_rule_service, "get_current_version_group", lambda: 1)
    monkeypatch.setattr(
        service.settings_service,
        "calculate_query_start",
        lambda timezone_name, dias_retroativos_emissao: datetime(2026, 7, 25, 0, 0, 0, tzinfo=UTC),
    )

    recipient = Recipient(email="thiago@betinalimpeza.com.br", is_active=True, is_deleted=False)
    db_session.add(recipient)
    db_session.commit()

    existing_run = JobRun(
        trigger_type="manual",
        status="failed",
        query_start_date=datetime(2026, 7, 25, 0, 0, 0, tzinfo=UTC),
        policy_version_group=1,
    )
    db_session.add(existing_run)
    db_session.commit()
    db_session.refresh(existing_run)

    existing_alert = AlertSent(
        job_run_id=existing_run.id,
        order_id="940612326",
        order_number="3104",
        policy_code="FAIXA_1",
        dedupe_key="FAIXA_1:940612326:2026-07-25",
        email_to="thiago@betinalimpeza.com.br",
        status="failed",
        error_message="RESEND_API_KEY não configurada.",
    )
    db_session.add(existing_alert)
    db_session.commit()

    monkeypatch.setattr(service.admin_service, "list_active_recipients", lambda: [recipient])
    monkeypatch.setattr(
        service.olist_service,
        "fetch_orders",
        lambda query_start: [
            SimpleNamespace(
                order_id="940612326",
                order_number="3104",
                customer_name="Cliente Teste",
                seller_name="Juliana",
                gross_amount=Decimal("120.00"),
                discount_amount=Decimal("8.00"),
                discount_percent=Decimal("6.67"),
                issue_date_display="2026-07-27",
                installments_count=1,
                prazo_total_dias=0,
            ),
        ],
    )
    monkeypatch.setattr(
        "app.services.execution.PolicyEngine",
        lambda rules: SimpleNamespace(
            evaluate=lambda order: [
                SimpleNamespace(
                    policy_code="FAIXA_1",
                    description="Faixa 1 permite pagamento à vista e desconto máximo de 5.00%.",
                ),
            ],
        ),
    )
    monkeypatch.setattr(service.alert_service, "send", lambda **kwargs: (_ for _ in ()).throw(ValueError("RESEND_API_KEY não configurada.")))
    monkeypatch.setattr("app.services.execution.write_runtime_event", lambda *args, **kwargs: None)

    job_run = service.run(trigger_type="manual")

    alerts = db_session.query(AlertSent).filter(AlertSent.dedupe_key == "FAIXA_1:940612326:2026-07-25").all()
    assert job_run.status == "success"
    assert len(alerts) == 1
    assert alerts[0].job_run_id == job_run.id
    assert alerts[0].status == "failed"
    assert alerts[0].error_message == "RESEND_API_KEY não configurada."


def test_manage_users_and_recipients(web_client) -> None:
    client, db_session, _ = web_client
    login(client)

    create_user = client.post(
        "/users",
        data={"email": "novo@empresa.com", "password": "Senha123"},
        follow_redirects=False,
    )
    assert create_user.status_code == 303
    assert db_session.query(User).filter(User.email == "novo@empresa.com").one_or_none() is not None

    add_recipient = client.post(
        "/recipients",
        data={"email": "alerta@empresa.com"},
        follow_redirects=False,
    )
    assert add_recipient.status_code == 303

    recipient = db_session.query(Recipient).filter(Recipient.email == "alerta@empresa.com").one()
    assert recipient.is_active is True

    toggle_response = client.post(f"/recipients/{recipient.id}/toggle", follow_redirects=False)
    assert toggle_response.status_code == 303
    db_session.refresh(recipient)
    assert recipient.is_active is False


def test_execution_route_and_assets(web_client, monkeypatch) -> None:
    client, _, _ = web_client
    login(client)

    monkeypatch.setattr(
        "app.main.ExecutionService.run",
        lambda self, trigger_type: SimpleNamespace(
            status="success",
            orders_evaluated=3,
            orders_irregular=1,
        ),
    )

    execute = client.post("/runs/execute", follow_redirects=False)
    assert execute.status_code == 303
    assert execute.headers["location"] == "/#online-log"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/webp")
