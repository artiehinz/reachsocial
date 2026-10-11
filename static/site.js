(() => {
  for (const button of document.querySelectorAll("[data-copy-target]")) {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      const status = document.getElementById(button.dataset.copyStatus);
      if (!(target instanceof HTMLTextAreaElement)) return;

      try {
        await navigator.clipboard.writeText(target.value);
      } catch {
        target.focus();
        target.select();
        if (!document.execCommand("copy")) {
          if (status) status.textContent = "Select and copy the prompt manually.";
          return;
        }
      }

      button.textContent = "Copied";
      if (status) status.textContent = "Prompt copied.";
      window.setTimeout(() => {
        button.textContent = "Copy prompt";
      }, 1600);
    });
  }
})();
