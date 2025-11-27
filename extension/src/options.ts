const apiInput = document.getElementById("apiBase") as HTMLInputElement;
const saveBtn = document.getElementById("saveBtn") as HTMLButtonElement;
const statusEl = document.getElementById("status") as HTMLSpanElement;

chrome.storage.sync.get(["apiBase"], (result) => {
  apiInput.value = result.apiBase || "http://localhost:8000";
});

saveBtn.addEventListener("click", () => {
  chrome.storage.sync.set({ apiBase: apiInput.value.trim() || null }, () => {
    statusEl.textContent = "Saved";
    setTimeout(() => (statusEl.textContent = ""), 1500);
  });
});
