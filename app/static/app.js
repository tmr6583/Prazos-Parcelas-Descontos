(function () {
  const policyTableBody = document.getElementById("policy-rules-body");
  const addRowButton = document.getElementById("add-policy-row");
  const rowTemplate = document.getElementById("policy-row-template");

  if (!policyTableBody || !addRowButton || !rowTemplate) {
    return;
  }

  const editFormatter = new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const currencyFormatter = new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
  let rowCounter = policyTableBody.querySelectorAll(".policy-row").length;

  function parseLocalizedNumber(rawValue) {
    const normalized = String(rawValue ?? "")
      .replace(/[^\d,.-]/g, "")
      .trim();

    if (!normalized) {
      return null;
    }

    if (normalized.includes(",")) {
      return Number(normalized.replace(/\./g, "").replace(",", "."));
    }

    const dotCount = (normalized.match(/\./g) || []).length;
    if (dotCount > 1) {
      const parts = normalized.split(".");
      return Number(parts.slice(0, -1).join("") + "." + parts.at(-1));
    }

    return Number(normalized);
  }

  function setEditValue(input) {
    const numericValue = parseLocalizedNumber(input.value);
    input.value = numericValue === null || Number.isNaN(numericValue) ? "" : editFormatter.format(numericValue);
  }

  function formatCurrency(input) {
    const numericValue = parseLocalizedNumber(input.value);
    input.value = numericValue === null || Number.isNaN(numericValue) ? "" : currencyFormatter.format(numericValue);
  }

  function formatPercent(input) {
    const numericValue = parseLocalizedNumber(input.value);
    input.value = numericValue === null || Number.isNaN(numericValue) ? "" : `${editFormatter.format(numericValue)}%`;
  }

  function bindMaskedInput(input, formatter) {
    if (!input || input.dataset.maskBound === "true") {
      return;
    }

    input.dataset.maskBound = "true";
    input.addEventListener("focus", () => setEditValue(input));
    input.addEventListener("blur", () => formatter(input));
    formatter(input);
  }

  function bindRow(row) {
    row.querySelectorAll(".currency-input").forEach((input) => bindMaskedInput(input, formatCurrency));
    row.querySelectorAll(".percent-input").forEach((input) => bindMaskedInput(input, formatPercent));
  }

  function createRow() {
    rowCounter += 1;
    const rowId = `row-new-${rowCounter}`;
    const html = rowTemplate.innerHTML.replaceAll("__ROW_ID__", rowId);
    policyTableBody.insertAdjacentHTML("beforeend", html);
    const row = policyTableBody.lastElementChild;
    if (row) {
      bindRow(row);
      const firstInput = row.querySelector("input[name='rule_name']");
      if (firstInput instanceof HTMLElement) {
        firstInput.focus();
      }
    }
  }

  policyTableBody.querySelectorAll(".policy-row").forEach(bindRow);

  addRowButton.addEventListener("click", createRow);

  policyTableBody.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest(".remove-policy-row") : null;
    if (!button) {
      return;
    }

    const row = button.closest(".policy-row");
    if (row) {
      row.remove();
    }
  });
})();
