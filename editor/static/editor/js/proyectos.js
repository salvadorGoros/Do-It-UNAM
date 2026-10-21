(() => {
    const normalize = value => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-MX");

    function assetUrl(preview, path) {
        if (!path) return "";
        if (!path.startsWith("uploads/")) return `${preview.dataset.assetBase}${encodeURI(path)}`;
        const parts = path.split("/");
        const ownerId = parts[1] || preview.dataset.userId;
        const filename = parts.at(-1);
        return `${preview.dataset.uploadedImageBase}${ownerId}/${encodeURIComponent(filename)}/`;
    }

    function renderPreview(preview) {
        const script = document.getElementById(preview.dataset.previewScript);
        if (!script) return;
        let slide;
        try {
            slide = JSON.parse(script.textContent);
        } catch (error) {
            return;
        }
        const stage = preview.querySelector(".project-preview-stage");
        stage.style.backgroundColor = slide.color_fondo || "#ffffff";
        if (slide.fondo) stage.style.backgroundImage = `url("${assetUrl(preview, slide.fondo)}")`;

        for (const object of (slide.objetos || []).slice(0, 12)) {
            const element = document.createElement(object.tipo === "imagen" ? "img" : "div");
            element.className = object.tipo === "imagen" ? "preview-image" : "preview-text";
            element.style.left = `${object.x || 0}px`;
            element.style.top = `${object.y || 0}px`;
            element.style.width = `${object.ancho || 100}px`;
            element.style.height = `${object.alto || 50}px`;
            element.style.transform = `rotate(${object.giro || 0}deg)`;
            element.style.opacity = object.opacidad ?? 1;
            if (object.tipo === "imagen") {
                element.src = assetUrl(preview, object.imagen || "");
                element.alt = "";
            } else {
                element.textContent = object.texto || "";
                element.style.color = object.color || "#0f172a";
                element.style.fontFamily = `${object.fuente || "Poppins"}, sans-serif`;
                element.style.fontSize = `${object.tamano || 28}px`;
                element.style.fontWeight = object.negrita ? "700" : "400";
                element.style.fontStyle = object.cursiva ? "italic" : "normal";
                element.style.textDecoration = object.subrayado ? "underline" : "none";
                element.style.textAlign = object.alineacion || "left";
            }
            stage.append(element);
        }

        new ResizeObserver(() => {
            const scale = preview.clientWidth / 800;
            stage.style.transform = `scale(${scale})`;
        }).observe(preview);
    }

    document.querySelectorAll(".project-preview").forEach(renderPreview);

    const search = document.getElementById("project-search");
    if (!search) return;
    const cards = [...document.querySelectorAll(".project-card")];
    const empty = document.getElementById("project-search-empty");
    search.addEventListener("input", () => {
        const query = normalize(search.value.trim());
        let visible = 0;
        for (const card of cards) {
            const matches = !query || normalize(card.dataset.projectName).includes(query);
            card.hidden = !matches;
            if (matches) visible += 1;
        }
        empty.hidden = visible > 0;
    });
})();
