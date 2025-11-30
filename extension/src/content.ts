type FieldInfo = {
  field_id: string;
  name: string | null;
  id: string | null;
  labels: string[];
  placeholder: string | null;
  type: string;
  options?: string[];
  multiple?: boolean;
  semantic: string;
  element: HTMLElement;
};

type Assignment = { field_id: string; value: string };

const seenElements = new WeakSet<HTMLElement>();

function collectFields(): FieldInfo[] {
  const fields: FieldInfo[] = [];
  traverseNodes(document.body, (el) => {
    if (!(el instanceof HTMLElement)) return;
    if (seenElements.has(el)) return;
    if (!isVisible(el)) return;

    const tag = el.tagName.toLowerCase();
    const typeAttr = (el.getAttribute("type") || "").toLowerCase();
    const isContentEditable = el.getAttribute("contenteditable") === "true";

    if (el instanceof HTMLInputElement) {
      if (el.disabled || el.readOnly) return;
      if (["hidden", "file", "button", "submit"].includes(typeAttr)) return;
    }

    if (tag === "input" || tag === "textarea" || tag === "select" || isContentEditable) {
      const baseType =
        tag === "select"
          ? "select"
          : isContentEditable
            ? "richtext"
            : typeAttr || "text";

      if (
        ![
          "text",
          "email",
          "tel",
          "number",
          "radio",
          "checkbox",
          "password",
          "url",
          "select",
          "richtext",
        ].includes(baseType)
      ) {
        return;
      }

      const labels = collectLabels(el);
      const field_id = domPath(el);

      const field: FieldInfo = {
        field_id,
        name: (el as HTMLInputElement).name || null,
        id: el.id || null,
        labels,
        placeholder: (el as HTMLInputElement).placeholder || null,
        type: baseType,
        semantic: classifyField((el as HTMLInputElement).name, el.id, (el as HTMLInputElement).placeholder, labels),
        element: el,
      };

      if (el instanceof HTMLSelectElement) {
        field.options = Array.from(el.options).map((opt) => opt.text || opt.value || "");
        field.multiple = el.multiple;
      }

      fields.push(field);
      seenElements.add(el);
    }
  });

  // Group radios/checkboxes by name into single logical field
  const grouped: FieldInfo[] = [];
  const radioGroups = new Map<string, FieldInfo>();

  fields.forEach((f) => {
    if (f.type === "radio" || f.type === "checkbox") {
      const name = f.name || f.id || f.field_id;
      const key = `${f.type}::${name}`;
      const existing = radioGroups.get(key);
      const optionLabel = f.labels[0] || "";
      if (existing) {
        const opts = new Set(existing.options || []);
        opts.add(optionLabel);
        existing.options = Array.from(opts);
      } else {
        radioGroups.set(key, {
          ...f,
          field_id: key,
          options: f.options && f.options.length ? f.options : optionLabel ? [optionLabel] : [],
          labels: f.labels,
        });
      }
    } else {
      grouped.push(f);
    }
  });

  grouped.push(...radioGroups.values());
  return grouped;
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
    console.warn("No API base configured");
    return null;
  }

  try {
    const payload = {
      url,
      fields: fields.map(({ name, id, labels, placeholder, type, field_id, options, multiple, semantic }) => ({
        name,
        id,
        field_id,
        labels,
        placeholder,
        type,
        options,
        multiple,
        semantic,
      })),
    };
    const resp = await fetch(`${baseUrl}/extension/autofill`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      console.warn("Autofill: server error");
      return null;
    }
    const data = await resp.json();
    if (data.skip) {
      console.info("Autofill skipped for this domain");
      return null;
    }
    return data.assignments || [];
  } catch (err) {
    console.error("Autofill request failed", err);
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
      if (field.type === "radio" || field.type === "checkbox") {
        const groupName = field.name || field.id || field.field_id;
        const group = document.querySelectorAll<HTMLInputElement>(
          `input[type="${field.type}"][name="${groupName}"]`
        );
        group.forEach((r) => {
          const target = value.toLowerCase();
          const radioVal = (r.value || "").toLowerCase();
          const radioLabel = (r.closest("label")?.textContent || "").toLowerCase();
          if (target === radioVal || target === radioLabel) {
            r.checked = true;
            r.dispatchEvent(new Event("input", { bubbles: true }));
            r.dispatchEvent(new Event("change", { bubbles: true }));
            filled += 1;
          }
        });
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
  console.info(`Autofilled ${filled} fields`);
}

async function getApiBase(): Promise<string | null> {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["apiBase"], (result) => {
      resolve(result.apiBase || "http://localhost:8000");
    });
  });
}

function sanitizeLabel(label: string | null): string | null {
  if (!label) return label;
  return label.replace(/\s+/g, " ").replace(/[✱*]+/g, "").trim();
}

function collectLabels(el: HTMLElement): string[] {
  const labels = new Set<string>();
  const cleaned = (txt: string | null) => sanitizeLabel(txt)?.trim();
  const fromAttr = cleaned(el.getAttribute("aria-label"));
  if (fromAttr) labels.add(fromAttr);

  const ariaIds = (el.getAttribute("aria-labelledby") || "")
    .split(/\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  ariaIds.forEach((id) => {
    const node = document.getElementById(id);
    if (node?.textContent) {
      const txt = cleaned(node.textContent);
      if (txt) labels.add(txt);
    }
  });

  const id = (el as HTMLInputElement).id;
  if (id) {
    const label = document.querySelector(`label[for='${id}']`);
    if (label && label.textContent) {
      const txt = cleaned(label.textContent);
      if (txt) labels.add(txt);
    }
  }
  const parentLabel = el.closest("label");
  if (parentLabel?.textContent) {
    const txt = cleaned(parentLabel.textContent);
    if (txt) labels.add(txt);
  }
  return Array.from(labels);
}

function domPath(el: HTMLElement): string {
  const segments: string[] = [];
  let node: HTMLElement | null = el;
  while (node && node.nodeType === Node.ELEMENT_NODE && node.tagName.toLowerCase() !== "body") {
    const parent = node.parentElement;
    if (!parent) break;
    const siblings = Array.from(parent.children).filter(
      (sibling) => sibling.tagName === node!.tagName
    );
    const index = siblings.indexOf(node);
    segments.push(`${node.tagName.toLowerCase()}:${index}`);
    node = parent;
  }
  segments.reverse();
  return `/${segments.join("/")}`;
}

function classifyField(
  name: string | null,
  id: string | null,
  placeholder: string | null,
  labels: string[]
): string {
  const text = [name, id, placeholder, ...labels]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ");
  const has = (pattern: RegExp) => pattern.test(text);
  if (has(/\bemail\b/)) return "email";
  if (has(/\b(phone|mobile|tel)\b/)) return "phone";
  if (has(/\bpassword\b/)) return "password";
  if (has(/\b(first|given)\s*name\b/)) return "first_name";
  if (has(/\b(last|family)\s*name\b/)) return "last_name";
  if (has(/\b(address|street)\b/)) return "address";
  if (has(/\bcity\b/)) return "city";
  if (has(/\bstate\b/)) return "state";
  if (has(/\bzip|postal\b/)) return "zip";
  return "unknown";
}

function isVisible(el: HTMLElement): boolean {
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) === 0) {
    return false;
  }
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return false;
  return true;
}

function traverseNodes(root: HTMLElement | ShadowRoot, cb: (el: HTMLElement) => void) {
  const walk = (node: HTMLElement | ShadowRoot) => {
    node.childNodes.forEach((child) => {
      if (child instanceof HTMLElement) {
        cb(child);
        if (child.shadowRoot) {
          walk(child.shadowRoot);
        }
        walk(child);
      }
    });
  };
  walk(root);
}

(async () => {
  if ((window as any).__jobAssistantContentLoaded) {
    return;
  }
  (window as any).__jobAssistantContentLoaded = true;

  const run = async () => {
    const fields = collectFields();
    if (!fields.length) return;
    const url = window.location.href;
    const assignments = await requestAssignments(url, fields);
    if (assignments && assignments.length) {
      applyAssignments(fields, assignments);
    }
    await uploadResumeIfNeeded(url);
  };

  await run();

  const observer = new MutationObserver(() => {
    run();
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();

async function uploadResumeIfNeeded(pageUrl: string) {
  const fileInputs = collectFileInputs();
  if (!fileInputs.length) return;
  const baseUrl = await getApiBase();
  if (!baseUrl) return;
  try {
    const resp = await fetch(`${baseUrl}/extension/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: pageUrl, fields: [] }),
    });
    if (!resp.ok) {
      console.warn("Resume fetch failed");
      return;
    }
    const blob = await resp.blob();
    const file = new File([blob], "resume.pdf", { type: "application/pdf" });
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInputs.forEach((input) => {
      input.files = dt.files;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    console.info("Resume attached to file inputs");
  } catch (err) {
    console.error("Resume upload failed", err);
  }
}

function collectFileInputs(): HTMLInputElement[] {
  const inputs: HTMLInputElement[] = [];
  traverseNodes(document.body, (el) => {
    if (!(el instanceof HTMLInputElement)) return;
    if (el.type !== "file") return;
    if (el.disabled || el.readOnly) return;
    inputs.push(el);
  });
  return inputs;
}
