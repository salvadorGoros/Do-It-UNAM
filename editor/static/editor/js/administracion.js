(() => {
    const panel = document.querySelector(".create-user-panel");
    const closeButton = document.querySelector(".create-user-close");
    if (!panel || !closeButton) return;

    function closeCreateUserPanel() {
        panel.open = false;
        panel.querySelector("summary")?.focus();
    }

    closeButton.addEventListener("click", closeCreateUserPanel);
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && panel.open) closeCreateUserPanel();
    });
})();
