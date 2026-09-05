// The panel's one script: what used to be inline attributes. Everything else
// is htmx. Behaviour hangs off data attributes so the templates stay HTML.
document.addEventListener("submit", (e) => {
  const form = e.target;
  const stop = () => e.preventDefault();

  // A destructive action names what it destroys; typing it back is the confirmation.
  if (form.dataset.confirmTyped) {
    const typed = prompt(form.dataset.confirm || `Type ${form.dataset.confirmTyped} to continue`);
    if (typed !== form.dataset.confirmTyped) stop();
    return;
  }
  if (form.dataset.confirm && !confirm(form.dataset.confirm)) return stop();

  // Unticking a box that turns something live off.
  const box = form.querySelector("[data-confirm-off]");
  if (box && box.defaultChecked && !box.checked && !confirm(box.dataset.confirmOff)) return stop();

  // Lines added to a list that erases history when saved.
  const list = form.querySelector("[data-confirm-added]");
  if (list) {
    const before = new Set((list.dataset.original || "").split("\n").map((s) => s.trim()).filter(Boolean));
    const added = list.value.split(/[\n,]/).map((s) => s.trim()).filter((s) => s && !before.has(s));
    if (added.length && !confirm(list.dataset.confirmAdded.replace("{ids}", added.join(", ")))) return stop();
  }
});

// A range shows its value next to it.
document.addEventListener("input", (e) => {
  if (!e.target.matches("[data-mirror]")) return;
  const out = e.target.parentElement.querySelector("output");
  if (out) out.value = e.target.value;
});

// A dropdown that fills a text field (the model picker).
document.addEventListener("change", (e) => {
  if (!e.target.matches("[data-fill]")) return;
  const target = document.getElementById(e.target.dataset.fill);
  if (target && e.target.value) {
    target.value = e.target.value;
    target.classList.add("filled");
  }
});
