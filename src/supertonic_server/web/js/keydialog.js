// The API key dialog (a native <dialog>, never window.prompt).

let pending = null;

/**
 * Ask for an API key. Concurrent callers share one dialog.
 * @param {string} [message] optional error to show (e.g. "That key was rejected")
 * @returns {Promise<string|null>} the key, or null when cancelled
 */
export function askForKey(message = "") {
  if (pending) return pending;
  const dialog = document.getElementById("key-dialog");
  const form = dialog.querySelector("form");
  const input = document.getElementById("key-input");
  const error = document.getElementById("key-error");
  const cancel = document.getElementById("key-cancel");

  pending = new Promise((resolve) => {
    error.textContent = message;
    input.value = "";
    const finish = (value) => {
      form.removeEventListener("submit", onSubmit);
      cancel.removeEventListener("click", onCancel);
      dialog.removeEventListener("cancel", onCancel);
      if (dialog.open) dialog.close();
      pending = null;
      resolve(value);
    };
    const onSubmit = (event) => {
      event.preventDefault();
      const key = input.value.trim();
      if (!key) {
        error.textContent = "Enter the key set in SUPERTONIC_API_KEY on the server.";
        input.focus();
        return;
      }
      finish(key);
    };
    const onCancel = (event) => {
      event.preventDefault();
      finish(null);
    };
    form.addEventListener("submit", onSubmit);
    cancel.addEventListener("click", onCancel);
    dialog.addEventListener("cancel", onCancel);
    dialog.showModal();
    input.focus();
  });
  return pending;
}
