from __future__ import annotations

from pathlib import Path

from playwright.sync_api import expect, sync_playwright


APP_URL = "http://127.0.0.1:3600"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


def normalize_spaces(value: str) -> str:
    return value.replace("\u00a0", " ").strip()


def main() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1200})

        page.goto(f"{APP_URL}/login", wait_until="networkidle")
        expect(page.locator("input[name='email']")).to_be_visible()
        assert page.locator("img.brand-logo-img").count() == 0

        login_text = page.locator("body").inner_text()
        assert "Alertas de Pedidos" in login_text
        assert "Sistema de Alertas ERP" not in login_text
        assert "cagoete" not in login_text.lower()

        page.locator("input[name='email']").fill("admin@empresa.com")
        page.locator("input[name='password']").fill("Betin@01012023")
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("networkidle")

        expect(page.locator("h1")).to_have_text("Painel administrativo")
        dashboard_text = page.locator("body").inner_text()
        assert "cagoete" not in dashboard_text.lower()
        assert "Timezone" not in dashboard_text

        page_width = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--page-width').trim()")
        assert page_width == "1656px"

        app_main = page.locator("main.app-main")
        app_main_box = app_main.bounding_box()
        assert app_main_box is not None and app_main_box["width"] > 1500

        first_currency = page.locator("input[name='value_min']").first
        first_percent = page.locator("input[name='max_discount_percent']").first
        assert normalize_spaces(first_currency.input_value()) == "R$ 0,00"
        expect(first_percent).to_have_value("5,00%")

        rows_before = page.locator("#policy-rules-body tr").count()
        page.locator("#add-policy-row").click()
        rows_after_add = page.locator("#policy-rules-body tr").count()
        assert rows_after_add == rows_before + 1

        last_row = page.locator("#policy-rules-body tr").last
        last_row.locator("input[name='rule_name']").fill("Faixa teste UI")

        value_min_input = last_row.locator("input[name='value_min']")
        value_min_input.click()
        value_min_input.fill("1500,24")
        value_min_input.press("Tab")
        assert normalize_spaces(value_min_input.input_value()) == "R$ 1.500,24"

        value_max_input = last_row.locator("input[name='value_max']")
        value_max_input.click()
        value_max_input.fill("2500,99")
        value_max_input.press("Tab")
        assert normalize_spaces(value_max_input.input_value()) == "R$ 2.500,99"

        discount_input = last_row.locator("input[name='max_discount_percent']")
        discount_input.click()
        discount_input.fill("12,34")
        discount_input.press("Tab")
        expect(discount_input).to_have_value("12,34%")

        last_row.locator("button.remove-policy-row").click()
        rows_after_remove = page.locator("#policy-rules-body tr").count()
        assert rows_after_remove == rows_before

        page.screenshot(path=str(ARTIFACTS_DIR / "policy-ui-smoke.png"), full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
