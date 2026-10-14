(() => {
  for (const button of document.querySelectorAll("[data-copy-target]")) {
    const originalLabel = button.textContent;
    let resetTimer;
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      const target = document.getElementById(button.dataset.copyTarget);
      const status = document.getElementById(button.dataset.copyStatus);
      if (!target) return;
      const text = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement
        ? target.value
        : target.textContent || "";
      button.disabled = true;
      clearTimeout(resetTimer);
      let copied = false;
      try {
        await navigator.clipboard.writeText(text);
        copied = true;
      } catch {
        const fallback = document.createElement("textarea");
        fallback.value = text;
        fallback.setAttribute("readonly", "");
        fallback.className = "copy-fallback";
        document.body.append(fallback);
        try {
          fallback.select();
          copied = document.execCommand("copy");
        } catch {
          copied = false;
        } finally {
          fallback.remove();
          button.focus({ preventScroll: true });
        }
      } finally {
        button.disabled = false;
      }
      if (!copied) {
        button.textContent = originalLabel;
        if (status) status.textContent = "Select and copy the text manually.";
        const details = target.closest("details");
        if (details) details.open = true;
        return;
      }
      button.textContent = "Copied";
      if (status) status.textContent = "Copied to clipboard.";
      resetTimer = window.setTimeout(() => { button.textContent = originalLabel; }, 1600);
    });
  }
})();
