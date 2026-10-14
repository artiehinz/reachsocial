(() => {
  for (const button of document.querySelectorAll("[data-copy-target]")) {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      const status = document.getElementById(button.dataset.copyStatus);
      if (!target) return;
      const text = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement
        ? target.value
        : target.textContent || "";

      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const fallback = document.createElement("textarea");
        fallback.value = text;
        fallback.setAttribute("readonly", "");
        fallback.className = "copy-fallback";
        document.body.append(fallback);
        fallback.select();
        if (!document.execCommand("copy")) {
          if (status) status.textContent = "Select and copy the text manually.";
          fallback.remove();
          return;
        }
        fallback.remove();
      }

      const originalLabel = button.textContent;
      button.textContent = "Copied";
      if (status) status.textContent = "Copied to clipboard.";
      window.setTimeout(() => {
        button.textContent = originalLabel;
      }, 1600);
    });
  }
})();
