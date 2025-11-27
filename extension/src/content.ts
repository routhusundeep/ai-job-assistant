type FieldInfo = {
  name: string | null;
  id: string | null;
  label: string | null;
  placeholder: string | null;
  type: string | null;
  field_id: string;
  element: HTMLElement;
  optionLabel?: string | null;
  options?: string[];
};

type Assignment = { field_id: string; value: string };

const overlayId = "__job_assistant_overlay";

function collectFields(): FieldInfo[] {
  const fields: FieldInfo[] = [];
  const elements = Array.from(
    document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
      "input, textarea, select"
    )
  );
  elements.forEach((el) => {
    const label = findLabel(el);
    const field_id = el.id || el.name || label || el.placeholder || "";
    let optionLabel: string | null = null;
    let options: string[] | undefined;
    if (el instanceof HTMLInputElement && el.type === "radio") {
      optionLabel = el.closest("label")?.textContent?.trim() || null;
      if (el.name) {
        const groupRadios = Array.from(
          document.querySelectorAll<HTMLInputElement>(`input[type="radio"][name="${el.name}"]`)
        );
        options = Array.from(
          new Set(
            groupRadios
              .map((r) => r.value || r.closest("label")?.textContent?.trim() || "")
              .filter(Boolean)
          )
        );
      }
    }
    fields.push({
      name: el.name || null,
      id: el.id || null,
      label,
      placeholder: el.getAttribute("placeholder"),
      type: el.getAttribute("type"),
      field_id,
      element: el,
      optionLabel,
      options,
    });
  });
  return fields.filter((f) => f.field_id);
}

function findLabel(el: HTMLElement): string | null {
  const id = (el as HTMLInputElement).id;
  if (id) {
    const label = document.querySelector(`label[for='${id}']`);
    if (label && label.textContent) return label.textContent.trim();
  }
  const parentLabel = el.closest("label");
  if (parentLabel && parentLabel.textContent) return parentLabel.textContent.trim();
  return null;
}

async function requestAssignments(url: string, fields: FieldInfo[]): Promise<Assignment[] | null> {
  const baseUrl = await getApiBase();
  if (!baseUrl) {
    showOverlay("No API base configured", true);
    return null;
  }

  try {
    const payload = {
      url,
      fields: fields.map(({ name, id, label, placeholder, type, field_id, options }) => ({
        name,
        field_id,
        label,
        placeholder,
        type,
        options,
      })),
    };
    const resp = await fetch(`${baseUrl}/extension/autofill`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      showOverlay("Autofill: server error", true);
      return null;
    }
    const data = await resp.json();
    if (data.skip) {
      showOverlay("Autofill skipped for this domain", true);
      return null;
    }
    return data.assignments || [];
  } catch (err) {
    console.error("Autofill request failed", err);
    showOverlay("Autofill failed", true);
    return null;
  }
}

function applyAssignments(fields: FieldInfo[], assignments: Assignment[]) {
  const map = new Map(assignments.map((a) => [a.field_id, a.value]));
  let filled = 0;
  fields.forEach((field) => {
    const value = map.get(field.field_id);
    if (value === undefined) return;
    const el = field.element as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
    try {
      if (el instanceof HTMLInputElement && el.type === "radio") {
        const target = value.toLowerCase();
        const radioVal = (el.value || "").toLowerCase();
        const radioLabel = (field.optionLabel || "").toLowerCase();
        if (target === radioVal || target === radioLabel) {
          el.checked = true;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
          filled += 1;
        }
      } else {
        el.focus();
        el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        filled += 1;
      }
    } catch (err) {
      console.warn("Unable to fill field", field.field_id, err);
    }
  });
  showOverlay(`Autofilled ${filled} fields`);
}

function showOverlay(message: string, isError = false) {
  let overlay = document.getElementById(overlayId);
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = overlayId;
    overlay.style.position = "fixed";
    overlay.style.bottom = "16px";
    overlay.style.right = "16px";
    overlay.style.padding = "10px 12px";
    overlay.style.borderRadius = "8px";
    overlay.style.zIndex = "999999";
    overlay.style.fontFamily = "sans-serif";
    overlay.style.fontSize = "14px";
    overlay.style.boxShadow = "0 4px 12px rgba(0,0,0,0.15)";
    document.body.appendChild(overlay);
  }
  overlay.textContent = message;
  overlay.style.background = isError ? "#fee2e2" : "#ecfeff";
  overlay.style.color = isError ? "#991b1b" : "#0f172a";
  setTimeout(() => {
    overlay?.remove();
  }, 4000);
}

async function getApiBase(): Promise<string | null> {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["apiBase"], (result) => {
      resolve(result.apiBase || "http://localhost:8000");
    });
  });
}

(async () => {
  const fields = collectFields();
  if (!fields.length) return;
  const url = window.location.href;
  const assignments = await requestAssignments(url, fields);
  if (assignments && assignments.length) {
    applyAssignments(fields, assignments);
  }
})();
