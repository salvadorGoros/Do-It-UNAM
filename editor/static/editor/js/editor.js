(() => {
    const $ = id => document.getElementById(id);
    const form = $("project-form");
    const stage = $("stage");
    if (!form || !stage) return;

    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    const MIN_OBJECT_POSITION = -8000;
    const MAX_OBJECT_POSITION = 8000;
    const MAX_OBJECT_WIDTH = 8000;
    const MAX_OBJECT_HEIGHT = 4500;
    const MIN_OBJECT_WIDTH = 60;
    const MIN_OBJECT_HEIGHT = 30;
    const rotationGuide = document.createElement("div");
    rotationGuide.className = "rotation-guide";
    rotationGuide.hidden = true;
    const rotationGuideLine = document.createElement("span");
    rotationGuideLine.className = "rotation-guide-line";
    const rotationAngleLabel = document.createElement("span");
    rotationAngleLabel.className = "rotation-angle-label";
    rotationGuide.append(rotationGuideLine, rotationAngleLabel);
    document.body.append(rotationGuide);
    let slides = JSON.parse(form.elements.diapositivas.value || "[]");
    if (!slides.length) {
        slides = [{
            id: "slide-1",
            objetos: JSON.parse($("scene-data").textContent),
            fondo: form.elements.fondo.value,
            color_fondo: "#ffffff",
            duracion_frames: Number(form.elements.duracion_frames.value) || 300,
        }];
    }
    slides.forEach(slide => { slide.color_fondo ||= "#ffffff"; });
    let activeSlideIndex = Number(form.elements.diapositiva_activa.value) || 0;
    activeSlideIndex = clamp(activeSlideIndex, 0, slides.length - 1);
    let objects = slides[activeSlideIndex].objetos;
    const assetBase = stage.dataset.assetBase;
    const uploadedImageBase = stage.dataset.uploadedImageBase;
    const imageUrl = path => {
        if (!path.startsWith("uploads/")) return `${assetBase}${encodeURI(path)}`;
        const [, ownerId, filename] = path.split("/");
        return `${uploadedImageBase}${ownerId}/${encodeURIComponent(filename)}/`;
    };
    let activeBackground = slides[activeSlideIndex].fondo;
    let activeSlideColor = slides[activeSlideIndex].color_fondo;
    let savedName = form.elements.nombre.value;
    let savedScene = JSON.stringify(objects);
    let savedBackground = activeBackground;
    let savedSlides = JSON.stringify(slides);
    let selected = null;
    let editing = null;
    let scale = 1;
    let gesture = null;
    let rotationGuideTimer = null;
    let saveTimer = null;
    let saving = false;
    let saveAgain = false;
    let submitting = false;
    let playing = false;
    let previewAnimations = [];
    let objectClipboard = null;
    let slideClipboard = null;
    let playbackTimer = null;
    let saveWaiters = [];
    let historyTimer = null;
    let historyEntries = [];
    let historyIndex = -1;
    let historyReady = false;
    let historyPending = false;
    let restoringHistory = false;
    let hasErrors = Boolean(document.querySelector(".errorlist"));
    let saveErrorVisible = !$("save-status").hidden;
    const current = () => objects.find(obj => obj.id === selected);
    const node = id => [...stage.children].find(el => el.dataset.id === id);
    const objectRotation = obj => obj.fotogramas?.find(frame => frame.frame === 0)?.giro || 0;
    const displayRotation = angle => {
        const normalized = ((angle % 360) + 360) % 360;
        const signed = normalized > 180 ? normalized - 360 : normalized;
        const rounded = Math.round(signed * 10) / 10;
        return Object.is(rounded, -0) ? 0 : rounded;
    };
    const rotationSnapTargets = [-360, -270, -180, -90, 0, 90, 180, 270, 360];

    function updateRotationGuide(obj, angle, x, y) {
        clearTimeout(rotationGuideTimer);
        const closestTarget = rotationSnapTargets.reduce((closest, target) =>
            Math.abs(target - angle) < Math.abs(closest - angle) ? target : closest
        );
        const snapped = Math.abs(closestTarget - angle) <= 3;
        const shownAngle = snapped ? closestTarget : angle;
        const bounds = node(obj.id).getBoundingClientRect();
        rotationGuide.hidden = false;
        rotationGuide.classList.toggle("is-aligned", snapped);
        rotationGuideLine.style.left = `${bounds.left + bounds.width / 2}px`;
        rotationGuideLine.style.top = `${bounds.top + bounds.height / 2}px`;
        rotationGuideLine.style.transform = `translate(-50%, -50%) rotate(${shownAngle}deg)`;
        rotationAngleLabel.textContent = `${displayRotation(shownAngle)}°`;
        rotationAngleLabel.style.left = `${Math.min(x + 12, window.innerWidth - 62)}px`;
        rotationAngleLabel.style.top = `${Math.min(y + 12, window.innerHeight - 34)}px`;
        rotationAngleLabel.classList.toggle("is-aligned", snapped);
    }

    function hideRotationGuide() {
        clearTimeout(rotationGuideTimer);
        rotationGuideTimer = null;
        rotationGuide.hidden = true;
        rotationGuide.classList.remove("is-aligned");
    }
    const objectLabel = obj => obj.tipo === "imagen"
        ? obj.imagen.split("/").at(-1)
        : obj.texto.slice(0, 60) || "Texto vacío";
    const dirty = () => hasErrors
        || form.elements.nombre.value !== savedName
        || form.elements.fondo.value !== savedBackground
        || JSON.stringify(objects) !== savedScene
        || JSON.stringify(slides) !== savedSlides;

    function sync() {
        const slide = slides[activeSlideIndex];
        slide.objetos = objects;
        slide.fondo = activeBackground;
        slide.color_fondo = activeSlideColor;
        slide.duracion_frames = Number($("slide-duration").value) * 30;
        form.elements.objetos.value = JSON.stringify(objects);
        form.elements.fondo.value = activeBackground;
        form.elements.duracion_frames.value = slide.duracion_frames;
        form.elements.diapositivas.value = JSON.stringify(slides);
        form.elements.diapositiva_activa.value = String(activeSlideIndex);
        $("object-count").textContent = `${objects.length} objetos`;
        if (!saveErrorVisible) {
            $("save-status").textContent = saving
                ? "Guardando automáticamente…"
                : dirty() ? "Cambios sin guardar" : "Guardado automáticamente";
        }
        $("save-status").hidden = !saveErrorVisible;
        $("text-tool").disabled = objects.length >= 100;
        $("elements-tool").disabled = objects.length >= 100;
        $("animation-tool").disabled = !slides.some(slide => slide.objetos.length > 0);
        $("copy-object").disabled = !current();
        $("paste-object").disabled = !objectClipboard || objects.length >= 100;
        $("duplicate-slide").disabled = slides.length >= 100;
        $("delete-slide").disabled = slides.length <= 1;
        if (historyReady && !restoringHistory && !gesture) scheduleHistory();
        if (dirty() && !submitting) scheduleSave();
        else if (!dirty() && saveTimer) {
            clearTimeout(saveTimer);
            saveTimer = null;
        }
    }

    function captureHistory() {
        storeCurrentSlide();
        return JSON.stringify({slides, selected});
    }

    function updateHistoryButtons() {
        $("undo-action").disabled = historyIndex <= 0 && !historyPending;
        $("redo-action").disabled = historyPending || historyIndex < 0 || historyIndex >= historyEntries.length - 1;
    }

    function commitHistory() {
        clearTimeout(historyTimer);
        historyTimer = null;
        if (!historyReady || restoringHistory) return;
        const snapshot = captureHistory();
        const currentSlides = JSON.stringify(JSON.parse(snapshot).slides);
        const previousSlides = historyIndex >= 0
            ? JSON.stringify(JSON.parse(historyEntries[historyIndex]).slides)
            : "";
        historyPending = false;
        if (currentSlides === previousSlides) {
            updateHistoryButtons();
            return;
        }
        historyEntries.splice(historyIndex + 1);
        historyEntries.push(snapshot);
        if (historyEntries.length > 100) historyEntries.shift();
        historyIndex = historyEntries.length - 1;
        updateHistoryButtons();
    }

    function scheduleHistory() {
        clearTimeout(historyTimer);
        historyPending = true;
        updateHistoryButtons();
        historyTimer = setTimeout(commitHistory, 500);
    }

    function restoreHistory(index) {
        if (index < 0 || index >= historyEntries.length) return;
        clearTimeout(historyTimer);
        historyTimer = null;
        const snapshot = JSON.parse(historyEntries[index]);
        const currentSlideId = slides[activeSlideIndex]?.id;
        const currentSlideIndex = activeSlideIndex;
        restoringHistory = true;
        historyIndex = index;
        slides = snapshot.slides;
        const preservedSlideIndex = slides.findIndex(slide => slide.id === currentSlideId);
        activeSlideIndex = preservedSlideIndex >= 0
            ? preservedSlideIndex
            : clamp(currentSlideIndex, 0, slides.length - 1);
        objects = slides[activeSlideIndex].objetos;
        activeBackground = slides[activeSlideIndex].fondo;
        activeSlideColor = slides[activeSlideIndex].color_fondo || "#ffffff";
        selected = null;
        editing = null;
        stage.replaceChildren();
        $("slide-duration").value = String(Math.round(slides[activeSlideIndex].duracion_frames / 30));
        stage.style.backgroundImage = activeBackground
            ? `url("${assetBase}${encodeURI(activeBackground)}")`
            : "none";
        stage.style.backgroundColor = activeSlideColor;
        updateSlideColorPicker();
        objects.forEach(mount);
        select(snapshot.selected && objects.some(obj => obj.id === snapshot.selected) ? snapshot.selected : null);
        renderSlideList();
        sync();
        restoringHistory = false;
        historyPending = false;
        updateHistoryButtons();
    }

    function undo() {
        commitHistory();
        if (historyIndex > 0) restoreHistory(historyIndex - 1);
    }

    function redo() {
        commitHistory();
        if (historyIndex < historyEntries.length - 1) restoreHistory(historyIndex + 1);
    }

    function scheduleSave() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => save(), 900);
    }

    function showSaveError(message) {
        const status = $("save-status");
        saveErrorVisible = true;
        status.textContent = message;
        status.hidden = false;
    }

    async function save() {
        clearTimeout(saveTimer);
        saveTimer = null;
        if (saving) {
            saveAgain = true;
            return new Promise(resolve => saveWaiters.push(resolve));
        }
        if (!dirty()) return true;

        saving = true;
        let succeeded = false;
        sync();
        commitHistory();
        const data = new FormData(form);
        const snapshot = {
            name: data.get("nombre"),
            scene: data.get("objetos"),
            background: data.get("fondo"),
            slides: data.get("diapositivas"),
        };
        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: data,
                headers: {"X-Requested-With": "XMLHttpRequest"},
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok) {
                const messages = Object.values(result.errors || {}).flat().map(error => error.message);
                throw new Error(messages.join(" ") || "No se pudieron guardar los cambios.");
            }
            savedName = snapshot.name;
            savedScene = snapshot.scene;
            savedBackground = snapshot.background;
            savedSlides = snapshot.slides;
            hasErrors = false;
            saveErrorVisible = false;
            $("save-status").hidden = true;
            succeeded = true;
        } catch (error) {
            showSaveError(`No se pudieron guardar los cambios: ${error.message}`);
        } finally {
            saving = false;
            const changedDuringSave = dirty();
            sync();
            commitHistory();
            if ((saveAgain || changedDuringSave) && !submitting) {
                saveAgain = false;
                scheduleSave();
            } else {
                const waiters = saveWaiters;
                saveWaiters = [];
                waiters.forEach(resolve => resolve(succeeded && !dirty()));
            }
        }
        return succeeded && !dirty();
    }

    function stopEditing() {
        if (!editing) return;
        const el = node(editing);
        el.classList.remove("editing");
        el.querySelector("textarea").readOnly = true;
        editing = null;
    }

    function setBackground(path) {
        activeBackground = path;
        stage.style.backgroundImage = path ? `url("${assetBase}${encodeURI(path)}")` : "none";
        sync();
    }

    function setSlideColor(color) {
        activeSlideColor = color;
        slides[activeSlideIndex].color_fondo = color;
        activeBackground = "";
        stage.style.backgroundImage = "none";
        stage.style.backgroundColor = color;
        $("slide-custom-color").value = color;
        updateSlideColorPicker();
        sync();
        renderSlideList();
    }

    function updateSlideColorPicker() {
        $("slide-custom-color").value = activeSlideColor;
        for (const swatch of document.querySelectorAll("[data-slide-color]")) {
            swatch.setAttribute("aria-pressed", String(swatch.dataset.slideColor === activeSlideColor));
        }
    }

    function updateAnimationPanel() {
        const obj = current();
        const scope = $("animation-scope").value;
        const canApply = scope === "objeto"
            ? Boolean(obj)
            : scope === "presentacion"
                ? slides.some(slide => slide.objetos.length > 0)
                : objects.length > 0;
        $("animation-selection").textContent = obj
            ? `Animación para: ${objectLabel(obj)}`
            : scope === "objeto"
                ? "Selecciona un texto o elemento para aplicarle una animación."
                : "Se aplicará a los objetos del alcance seleccionado.";
        for (const button of document.querySelectorAll(".animation-choice")) {
            button.setAttribute("aria-pressed", String(Boolean(obj) && (obj.animacion || "ninguna") === button.dataset.animation));
            button.disabled = !canApply;
        }
        $("preview-animation").disabled = !objects.some(obj => (obj.animacion || "ninguna") !== "ninguna");
    }

    function select(id) {
        if (selected !== id) stopEditing();
        selected = id;
        for (const el of stage.children) {
            el.classList.toggle("selected", el.dataset.id === id);
        }
        const obj = current();
        const textSelected = obj && obj.tipo !== "imagen";
        $("text-toolbar").hidden = !textSelected;
        $("slide-color-toolbar").hidden = Boolean(obj);
        $("copy-object").disabled = !obj;
        $("object-tools").disabled = !textSelected;
        for (const id of ["font-family", "font-size", "font-color", "bold", "italic", "underline", "text-align", "edit-text"]) {
            $(id).disabled = !textSelected;
        }
        $("delete-text").disabled = !obj;
        if (textSelected) {
            $("font-family").value = obj.fuente;
            $("font-size").value = obj.tamano;
            $("font-color").value = obj.color;
            $("text-align").value = obj.alineacion;
            for (const [id, key] of [["bold", "negrita"], ["italic", "cursiva"], ["underline", "subrayado"]]) {
                $(id).setAttribute("aria-pressed", String(obj[key]));
            }
        }
        updateAnimationPanel();
    }

    function setObjectRotation(obj, rotation) {
        const firstFrame = obj.fotogramas.find(frame => frame.frame === 0);
        if (firstFrame) {
            firstFrame.giro = rotation;
        } else {
            obj.fotogramas.push({
                frame: 0,
                x: obj.x,
                y: obj.y,
                giro: rotation,
                opacidad: 1,
                interpolacion: "lineal",
            });
            obj.fotogramas.sort((left, right) => left.frame - right.frame);
        }
        node(obj.id).style.transform = `rotate(${rotation}deg)`;
        const rotateHandle = node(obj.id).querySelector(".rotate-handle");
        rotateHandle.title = `Girar objeto (${displayRotation(rotation)}°)`;
        rotateHandle.setAttribute("aria-label", `Girar objeto, ${displayRotation(rotation)} grados`);
        sync();
        historyPending = true;
        updateHistoryButtons();
    }

    function edit() {
        const obj = current();
        if (!obj || obj.tipo === "imagen") return;
        editing = obj.id;
        const el = node(obj.id);
        el.classList.add("editing");
        const input = el.querySelector("textarea");
        input.readOnly = false;
        input.focus();
    }

    function mount(obj) {
        const el = document.createElement("div");
        const isImage = obj.tipo === "imagen";
        el.className = isImage ? "text-object image-object" : "text-object";
        el.dataset.id = obj.id;
        el.tabIndex = 0;
        el.setAttribute("role", "group");
        el.setAttribute("aria-label", isImage
            ? `Elemento ${objectLabel(obj)}; selecciónalo para moverlo`
            : "Cuadro de texto; Enter para editar, flechas para mover");

        let content;
        if (isImage) {
            content = document.createElement("img");
            content.className = "element-image";
            content.src = imageUrl(obj.imagen);
            content.alt = "";
            content.draggable = false;
        } else {
            content = document.createElement("textarea");
            content.className = "object-content";
            content.value = obj.texto;
            content.maxLength = 5000;
            content.readOnly = true;
            content.tabIndex = -1;
            content.setAttribute("aria-label", "Contenido del cuadro de texto");
            content.addEventListener("input", () => {
                obj.texto = content.value;
                updateAnimationPanel();
                sync();
                historyPending = true;
                updateHistoryButtons();
            });
            content.addEventListener("blur", () => {
                if (editing === obj.id) stopEditing();
            });
        }

        const rotateHandle = document.createElement("button");
        rotateHandle.type = "button";
        rotateHandle.className = "rotate-handle";
        rotateHandle.setAttribute("aria-label", "Girar objeto");
        rotateHandle.title = "Girar objeto";
        rotateHandle.textContent = "↻";
        rotateHandle.title = `Girar objeto (${displayRotation(objectRotation(obj))}°)`;
        rotateHandle.setAttribute("aria-label", `Girar objeto, ${displayRotation(objectRotation(obj))} grados`);
        rotateHandle.addEventListener("keydown", event => {
            if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
            event.preventDefault();
            event.stopPropagation();
            const rotation = clamp(
                objectRotation(obj) + (event.key === "ArrowRight" ? 15 : -15),
                -360,
                360,
            );
            setObjectRotation(obj, rotation);
            const bounds = rotateHandle.getBoundingClientRect();
            updateRotationGuide(obj, rotation, bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
            rotationGuideTimer = setTimeout(hideRotationGuide, 900);
            commitHistory();
        });
        const handles = ["n", "ne", "e", "se", "s", "sw", "w", "nw"].map(direction => {
            const handle = document.createElement("span");
            handle.className = `resize-handle resize-${direction}`;
            handle.dataset.handle = direction;
            handle.setAttribute("aria-hidden", "true");
            return handle;
        });
        el.append(content, rotateHandle, ...handles);
        el.addEventListener("focus", () => select(obj.id));
        el.addEventListener("dblclick", () => {
            select(obj.id);
            edit();
        });
        el.addEventListener("pointerdown", event => {
            if (event.button !== 0) return;
            select(obj.id);
            if (editing === obj.id && event.target === content) return;
            event.preventDefault();
            el.focus();
            gesture = {
                id: obj.id,
                pointer: event.pointerId,
                rotate: event.target === rotateHandle,
                resize: event.target instanceof Element && event.target.matches(".resize-handle"),
                handle: event.target instanceof Element ? event.target.dataset.handle : null,
                sx: event.clientX,
                sy: event.clientY,
                rotation: objectRotation(obj),
                startAngle: event.target === rotateHandle
                    ? Math.atan2(
                        event.clientY - (el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2),
                        event.clientX - (el.getBoundingClientRect().left + el.getBoundingClientRect().width / 2),
                    ) * 180 / Math.PI
                    : 0,
                x: obj.x,
                y: obj.y,
                width: obj.ancho,
                height: obj.alto,
            };
            el.setPointerCapture(event.pointerId);
        });
        el.addEventListener("pointermove", event => {
            if (!gesture || gesture.id !== obj.id || gesture.pointer !== event.pointerId) return;
            const dx = (event.clientX - gesture.sx) / scale;
            const dy = (event.clientY - gesture.sy) / scale;
            if (gesture.rotate) {
                const bounds = el.getBoundingClientRect();
                const angle = Math.atan2(
                    event.clientY - (bounds.top + bounds.height / 2),
                    event.clientX - (bounds.left + bounds.width / 2),
                ) * 180 / Math.PI;
                let delta = angle - gesture.startAngle;
                if (delta > 180) delta -= 360;
                if (delta < -180) delta += 360;
                const rotation = clamp(gesture.rotation + delta, -360, 360);
                const closestTarget = rotationSnapTargets.reduce((closest, target) =>
                    Math.abs(target - rotation) < Math.abs(closest - rotation) ? target : closest
                );
                const snappedRotation = Math.abs(closestTarget - rotation) <= 3
                    ? closestTarget
                    : rotation;
                setObjectRotation(obj, snappedRotation);
                updateRotationGuide(obj, snappedRotation, event.clientX, event.clientY);
            } else if (gesture.resize) {
                const west = gesture.handle.includes("w");
                const east = gesture.handle.includes("e");
                const north = gesture.handle.includes("n");
                const south = gesture.handle.includes("s");
                obj.ancho = clamp(
                    gesture.width + (east ? dx : west ? -dx : 0),
                    MIN_OBJECT_WIDTH,
                    MAX_OBJECT_WIDTH,
                );
                obj.alto = clamp(
                    gesture.height + (south ? dy : north ? -dy : 0),
                    MIN_OBJECT_HEIGHT,
                    MAX_OBJECT_HEIGHT,
                );
                obj.x = west ? gesture.x + gesture.width - obj.ancho : gesture.x;
                obj.y = north ? gesture.y + gesture.height - obj.alto : gesture.y;
                obj.x = clamp(obj.x, MIN_OBJECT_POSITION, MAX_OBJECT_POSITION);
                obj.y = clamp(obj.y, MIN_OBJECT_POSITION, MAX_OBJECT_POSITION);
            } else {
                obj.x = clamp(gesture.x + dx, MIN_OBJECT_POSITION, MAX_OBJECT_POSITION);
                obj.y = clamp(gesture.y + dy, MIN_OBJECT_POSITION, MAX_OBJECT_POSITION);
            }
            el.style.left = `${obj.x}px`;
            el.style.top = `${obj.y}px`;
            el.style.width = `${obj.ancho}px`;
            el.style.height = `${obj.alto}px`;
            el.style.transform = `rotate(${objectRotation(obj)}deg)`;
            for (const key of ["x", "y"]) {
                const firstFrame = obj.fotogramas?.[0];
                if (firstFrame?.frame === 0) firstFrame[key] = obj[key];
            }
            sync();
            historyPending = true;
            updateHistoryButtons();
        });
        for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
            el.addEventListener(eventName, () => {
                if (gesture?.id === obj.id && gesture.rotate) hideRotationGuide();
                gesture = null;
                commitHistory();
            });
        }
        stage.append(el);
        el.style.left = `${obj.x}px`;
        el.style.top = `${obj.y}px`;
        el.style.width = `${obj.ancho}px`;
        el.style.height = `${obj.alto}px`;
        if (!isImage) {
            Object.assign(content.style, {
                fontFamily: `${obj.fuente}, sans-serif`,
                fontSize: `${obj.tamano}px`,
                color: obj.color,
                fontWeight: obj.negrita ? "700" : "400",
                fontStyle: obj.cursiva ? "italic" : "normal",
                textDecoration: obj.subrayado ? "underline" : "none",
                textAlign: obj.alineacion,
            });
        }
    }

    function addText() {
        if (objects.length >= 100) return;
        stopEditing();
        const offset = (objects.length % 8) * 16;
        const obj = {
            id: crypto.randomUUID(),
            texto: "Escribe tu texto",
            x: 200 + offset,
            y: 140 + offset,
            ancho: 360,
            alto: 110,
            fuente: "Poppins",
            tamano: 36,
            color: "#ffffff",
            negrita: false,
            cursiva: false,
            subrayado: false,
            alineacion: "center",
            animacion: "ninguna",
            fotogramas: [{frame: 0, x: 200 + offset, y: 140 + offset, giro: 0, opacidad: 1, interpolacion: "lineal"}],
        };
        objects.push(obj);
        mount(obj);
        select(obj.id);
        edit();
        node(obj.id).querySelector("textarea").select();
        sync();
        commitHistory();
    }

    function addElement(path) {
        if (objects.length >= 100) return;
        stopEditing();
        const offset = (objects.length % 8) * 16;
        const obj = {
            id: crypto.randomUUID(),
            tipo: "imagen",
            imagen: path,
            texto: "",
            x: 300 + offset,
            y: 150 + offset,
            ancho: 200,
            alto: 150,
            fuente: "Poppins",
            tamano: 36,
            color: "#ffffff",
            negrita: false,
            cursiva: false,
            subrayado: false,
            alineacion: "center",
            animacion: "ninguna",
            fotogramas: [{frame: 0, x: 300 + offset, y: 150 + offset, giro: 0, opacidad: 1, interpolacion: "lineal"}],
        };
        objects.push(obj);
        mount(obj);
        select(obj.id);
        sync();
        commitHistory();
    }

    function remove() {
        const obj = current();
        if (!obj) return;
        stopEditing();
        node(obj.id).remove();
        objects.splice(objects.findIndex(item => item.id === obj.id), 1);
        select(null);
        sync();
        commitHistory();
        stage.focus();
    }

    function storeCurrentSlide() {
        slides[activeSlideIndex].objetos = objects;
        slides[activeSlideIndex].fondo = activeBackground;
        slides[activeSlideIndex].color_fondo = activeSlideColor;
        slides[activeSlideIndex].duracion_frames = Number($("slide-duration").value) * 30;
    }

    function renderSlideList() {
        const list = $("slide-list");
        list.replaceChildren();
        for (let index = 0; index <= slides.length; index++) {
            const insert = document.createElement("button");
            insert.type = "button";
            insert.className = "slide-insert";
            insert.dataset.insertIndex = String(index);
            insert.setAttribute("aria-label", `Agregar diapositiva en la posición ${index + 1}`);
            insert.title = "Agregar diapositiva aquí";
            insert.disabled = slides.length >= 100;
            insert.innerHTML = '<span aria-hidden="true">+</span>';
            insert.addEventListener("click", () => addSlideAt(index));
            insert.addEventListener("dragover", event => event.preventDefault());
            insert.addEventListener("drop", event => {
                event.preventDefault();
                const dragIndex = event.dataTransfer.getData("application/x-slide-index");
                if (dragIndex === "") return;
                const from = Number(dragIndex);
                reorderSlide(from, index);
            });
            list.append(insert);
            if (index === slides.length) break;

            const slide = slides[index];
            const button = document.createElement("button");
            button.type = "button";
            button.className = "slide-thumb";
            button.draggable = true;
            button.dataset.slideIndex = String(index);
            button.setAttribute("aria-current", String(index === activeSlideIndex));
            button.setAttribute("aria-label", `Abrir diapositiva ${index + 1}`);
            const preview = document.createElement("span");
            preview.className = "slide-thumb-preview";
            preview.style.backgroundColor = slide.color_fondo || "#ffffff";
            if (slide.fondo) preview.style.backgroundImage = `url("${assetBase}${encodeURI(slide.fondo)}")`;
            const sample = slide.objetos.find(obj => obj.tipo !== "imagen" && obj.texto)
                || slide.objetos[0];
            preview.textContent = sample
                ? sample.tipo === "imagen" ? "▧" : sample.texto.slice(0, 28)
                : "En blanco";
            button.append(preview);
            const title = document.createElement("span");
            title.textContent = `Diapositiva ${index + 1}`;
            const details = document.createElement("small");
            details.textContent = `${slide.objetos.length} objetos · ${Math.round(slide.duracion_frames / 30)} s`;
            button.append(title, details);
            button.addEventListener("click", () => showSlide(index));
            button.addEventListener("contextmenu", event => {
                event.preventDefault();
                showSlide(index);
                openSlideContextMenu(event.clientX, event.clientY);
            });
            button.addEventListener("dragstart", event => {
                event.dataTransfer.setData("application/x-slide-index", String(index));
                event.dataTransfer.effectAllowed = "move";
                button.classList.add("dragging");
            });
            button.addEventListener("dragend", () => button.classList.remove("dragging"));
            button.addEventListener("dragover", event => event.preventDefault());
            button.addEventListener("drop", event => {
                event.preventDefault();
                const dragIndex = event.dataTransfer.getData("application/x-slide-index");
                if (dragIndex === "") return;
                const from = Number(dragIndex);
                const bounds = button.getBoundingClientRect();
                const insertionIndex = event.clientX < bounds.left + bounds.width / 2 ? index : index + 1;
                reorderSlide(from, insertionIndex);
            });
            list.append(button);
        }
        $("presentation-count").textContent = `${activeSlideIndex + 1} / ${slides.length}`;
        sync();
    }

    function showSlide(index, storeCurrent = true) {
        if (index < 0 || index >= slides.length) return;
        if (storeCurrent) storeCurrentSlide();
        stopEditing();
        activeSlideIndex = index;
        objects = slides[index].objetos;
        activeBackground = slides[index].fondo;
        activeSlideColor = slides[index].color_fondo || "#ffffff";
        $("slide-duration").value = String(Math.round(slides[index].duracion_frames / 30));
        form.elements.diapositiva_activa.value = String(index);
        stage.replaceChildren();
        stage.style.backgroundImage = activeBackground
            ? `url("${assetBase}${encodeURI(activeBackground)}")`
            : "none";
        stage.style.backgroundColor = activeSlideColor;
        updateSlideColorPicker();
        objects.forEach(mount);
        select(null);
        renderSlideList();
        sync();
    }

    function cloneSlide(slide) {
        const duplicate = JSON.parse(JSON.stringify(slide));
        duplicate.id = crypto.randomUUID();
        duplicate.objetos.forEach(obj => { obj.id = crypto.randomUUID(); });
        return duplicate;
    }

    function addSlideAt(index, data = null) {
        if (slides.length >= 100) return;
        storeCurrentSlide();
        slides.splice(index, 0, data ? cloneSlide(data) : {
            id: crypto.randomUUID(),
            objetos: [],
            fondo: "",
            color_fondo: "#ffffff",
            duracion_frames: 300,
        });
        showSlide(index, false);
    }

    function reorderSlide(from, insertionIndex) {
        if (!Number.isInteger(from) || from < 0 || from >= slides.length) return;
        const boundedIndex = clamp(insertionIndex, 0, slides.length);
        if (boundedIndex === from || boundedIndex === from + 1) return;
        const activeId = slides[activeSlideIndex].id;
        const [slide] = slides.splice(from, 1);
        slides.splice(boundedIndex > from ? boundedIndex - 1 : boundedIndex, 0, slide);
        activeSlideIndex = slides.findIndex(item => item.id === activeId);
        renderSlideList();
        sync();
    }

    function deleteSlide() {
        if (slides.length <= 1) return;
        slides.splice(activeSlideIndex, 1);
        showSlide(Math.min(activeSlideIndex, slides.length - 1), false);
        closeSlideContextMenu();
    }

    function copySlide() {
        storeCurrentSlide();
        slideClipboard = JSON.parse(JSON.stringify(slides[activeSlideIndex]));
        sync();
    }

    function pasteSlide() {
        if (!slideClipboard || slides.length >= 100) return;
        addSlideAt(activeSlideIndex + 1, slideClipboard);
    }

    function openSlideContextMenu(x, y) {
        const menu = $("slide-context-menu");
        menu.hidden = false;
        $("duplicate-slide").disabled = slides.length >= 100;
        $("delete-slide").disabled = slides.length <= 1;
        const bounds = menu.getBoundingClientRect();
        menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - bounds.width - 8))}px`;
        menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - bounds.height - 8))}px`;
        $("duplicate-slide").focus();
    }

    function closeSlideContextMenu() {
        $("slide-context-menu").hidden = true;
    }

    function copyObject() {
        const obj = current();
        if (obj) objectClipboard = JSON.parse(JSON.stringify(obj));
        sync();
    }

    function pasteObject() {
        if (!objectClipboard || objects.length >= 100) return;
        const obj = JSON.parse(JSON.stringify(objectClipboard));
        obj.id = crypto.randomUUID();
        obj.x = clamp(obj.x + 16, MIN_OBJECT_POSITION, MAX_OBJECT_POSITION);
        obj.y = clamp(obj.y + 16, MIN_OBJECT_POSITION, MAX_OBJECT_POSITION);
        if (obj.fotogramas?.[0]?.frame === 0) {
            obj.fotogramas[0].x = obj.x;
            obj.fotogramas[0].y = obj.y;
        }
        objects.push(obj);
        mount(obj);
        select(obj.id);
        sync();
        commitHistory();
    }

    function showGallery(section, button) {
        const panel = $("asset-panel");
        const isOpen = !panel.hidden && panel.dataset.section === section;
        panel.hidden = isOpen;
        panel.dataset.section = isOpen ? "" : section;
        if (!isOpen && section === "elementos") {
            $("element-category-list").hidden = false;
            $("element-category-content").hidden = true;
        }
        for (const gallery of document.querySelectorAll(".asset-gallery")) {
            gallery.hidden = isOpen || gallery.dataset.gallery !== section;
        }
        $("asset-panel-title").textContent = {
            elementos: "Elementos",
            imagenes: "Subir",
            fondos: "Fondos",
            animaciones: "Animar",
        }[section];
        for (const tool of [$("images-tool"), $("elements-tool"), $("background-tool"), $("animation-tool")]) {
            tool.setAttribute("aria-expanded", String(!isOpen && tool === button));
            tool.classList.toggle("tool-active", !isOpen && tool === button);
        }
        if (!isOpen && section === "imagenes") loadUploadedImages();
    }

    function renderUploadedImages(images) {
        const grid = $("uploaded-image-grid");
        grid.replaceChildren();
        for (const image of images) {
            const choice = document.createElement("button");
            choice.type = "button";
            choice.className = "asset-choice";
            choice.dataset.assetPath = image.path;
            choice.setAttribute("aria-label", `Agregar ${image.name}`);
            const preview = document.createElement("img");
            preview.src = image.url;
            preview.alt = "";
            preview.loading = "lazy";
            const label = document.createElement("span");
            label.textContent = image.name;
            choice.append(preview, label);
            choice.addEventListener("click", () => addElement(image.path));
            grid.append(choice);
        }
        $("uploaded-image-empty").hidden = images.length > 0;
    }

    let uploadedImagesRequest = 0;
    let uploadedImagesCache = [];
    function mergeUploadedImages(images) {
        const merged = new Map();
        for (const image of [...images, ...uploadedImagesCache]) merged.set(image.path, image);
        uploadedImagesCache = [...merged.values()];
        return uploadedImagesCache;
    }

    async function loadUploadedImages() {
        const gallery = document.querySelector('[data-gallery="imagenes"]');
        const status = $("image-upload-status");
        const requestId = ++uploadedImagesRequest;
        try {
            const response = await fetch(gallery.dataset.imagesUrl, {
                credentials: "same-origin",
                cache: "no-store",
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "No se pudieron cargar tus imágenes.");
            if (requestId !== uploadedImagesRequest) return null;
            renderUploadedImages(mergeUploadedImages(result.images));
            status.textContent = "";
            return true;
        } catch (error) {
            if (requestId !== uploadedImagesRequest) return null;
            status.textContent = error.message || "No se pudieron cargar tus imágenes.";
            return false;
        }
    }

    async function uploadImages(files) {
        if (!files.length) return;
        const gallery = document.querySelector('[data-gallery="imagenes"]');
        const status = $("image-upload-status");
        const data = new FormData();
        for (const file of files) data.append("images", file);
        data.append("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
        status.textContent = "Subiendo imágenes...";
        try {
            const response = await fetch(gallery.dataset.uploadUrl, {
                method: "POST",
                body: data,
                headers: {"X-Requested-With": "XMLHttpRequest"},
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "No se pudieron subir las imágenes.");
            renderUploadedImages(mergeUploadedImages(result.images));
            status.textContent = `${result.images.length} imagen${result.images.length === 1 ? "" : "es"} guardada${result.images.length === 1 ? "" : "s"}.`;
        } catch (error) {
            status.textContent = error.message || "No se pudieron subir las imágenes.";
        }
    }

    $("upload-image-trigger").addEventListener("click", () => $("image-file-input").click());
    $("image-drop-zone").addEventListener("click", () => $("image-file-input").click());
    $("image-file-input").addEventListener("change", event => {
        uploadImages([...event.target.files]);
        event.target.value = "";
    });
    const dropZone = $("image-drop-zone");
    for (const eventName of ["dragenter", "dragover"]) {
        dropZone.addEventListener(eventName, event => {
            event.preventDefault();
            dropZone.classList.add("is-dragging");
        });
    }
    for (const eventName of ["dragleave", "drop"]) {
        dropZone.addEventListener(eventName, event => {
            event.preventDefault();
            dropZone.classList.remove("is-dragging");
            if (eventName === "drop") uploadImages([...event.dataTransfer.files]);
        });
    }

    document.querySelectorAll(".asset-category-choice").forEach(button => {
        button.addEventListener("click", () => {
            $("element-category-list").hidden = true;
            $("element-category-content").hidden = false;
            $("selected-element-category").textContent = button.dataset.categoryChoice;
            document.querySelectorAll(".asset-category[data-category]").forEach(category => {
                category.hidden = category.dataset.category !== button.dataset.categoryChoice;
            });
        });
    });
    $("back-to-element-categories").addEventListener("click", () => {
        $("element-category-content").hidden = true;
        $("element-category-list").hidden = false;
    });

    $("duplicate-slide").addEventListener("click", () => {
        if (slides.length < 100) addSlideAt(activeSlideIndex + 1, slides[activeSlideIndex]);
        closeSlideContextMenu();
    });
    $("copy-slide").addEventListener("click", () => {
        copySlide();
        closeSlideContextMenu();
    });
    $("delete-slide").addEventListener("click", deleteSlide);
    document.querySelectorAll("[data-slide-color]").forEach(button => {
        button.addEventListener("click", () => setSlideColor(button.dataset.slideColor));
    });
    $("slide-custom-color").addEventListener("input", event => setSlideColor(event.target.value));
    document.addEventListener("pointerdown", event => {
        if (!(event.target instanceof Element) || !event.target.closest("#slide-context-menu")) {
            closeSlideContextMenu();
        }
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") closeSlideContextMenu();
    });
    $("copy-object").addEventListener("click", copyObject);
    $("paste-object").addEventListener("click", pasteObject);
    $("undo-action").addEventListener("click", undo);
    $("redo-action").addEventListener("click", redo);
    $("slide-duration").addEventListener("change", () => {
        $("slide-duration").value = String(clamp(Number($("slide-duration").value) || 10, 1, 120));
        slides[activeSlideIndex].duracion_frames = Number($("slide-duration").value) * 30;
        renderSlideList();
        sync();
    });

    function playAnimations(targetObjects = objects) {
        previewAnimations.forEach(animation => animation.cancel());
        previewAnimations = [];
        const effects = {
            aparecer: [{opacity: 0}, {opacity: 1}],
            subir: [{opacity: 0, transform: "translateY(28px)"}, {opacity: 1, transform: "translateY(0)"}],
            zoom: [{opacity: 0, transform: "scale(.65)"}, {opacity: 1, transform: "scale(1)"}],
            girar: [{opacity: 0, transform: "rotate(-18deg) scale(.75)"}, {opacity: 1, transform: "rotate(0) scale(1)"}],
            rebote: [{opacity: 0, transform: "translateY(-24px) scale(.8)"}, {opacity: 1, transform: "translateY(0) scale(1)"}],
        };
        targetObjects.forEach((obj, index) => {
            const frames = effects[obj.animacion];
            const element = node(obj.id);
            if (!frames || !element) return;
            const animation = element.animate(frames, {
                duration: obj.animacion === "rebote" ? 900 : 650,
                delay: index * 90,
                easing: obj.animacion === "rebote" ? "cubic-bezier(.34,1.56,.64,1)" : "ease-out",
                fill: "both",
            });
            animation.onfinish = () => animation.cancel();
            previewAnimations.push(animation);
        });
        return previewAnimations.length;
    }

    function preview() {
        $("animation-status").textContent = playAnimations()
            ? "Reproduciendo la vista previa de la escena."
            : "Elige un efecto para al menos un objeto.";
    }

    function animateForScope(preset) {
        const scope = $("animation-scope").value;
        let affected;
        if (scope === "objeto") {
            const obj = current();
            if (!obj) {
                $("animation-status").textContent = "Selecciona un objeto o cambia el alcance a diapositiva.";
                return;
            }
            affected = [obj];
        } else if (scope === "diapositiva") {
            affected = objects;
        } else {
            affected = slides.flatMap(slide => slide.objetos);
        }
        affected.forEach(obj => { obj.animacion = preset; });
        updateAnimationPanel();
        $("animation-status").textContent = preset === "ninguna"
            ? "Se quitó la animación del alcance seleccionado."
            : `Animación aplicada a ${affected.length} objetos.`;
        renderSlideList();
        sync();
    }

    function enterPresentation(index = activeSlideIndex) {
        if (playing) return;
        playing = true;
        document.body.classList.add("presenting");
        $("presentation-controls").hidden = false;
        showPresentationSlide(index);
    }

    function showPresentationSlide(index) {
        if (index < 0 || index >= slides.length) {
            exitPresentation();
            return;
        }
        clearTimeout(playbackTimer);
        showSlide(index);
        $("presentation-count").textContent = `${index + 1} / ${slides.length}`;
        playAnimations();
        playbackTimer = setTimeout(
            () => showPresentationSlide(index + 1),
            slides[index].duracion_frames / 30 * 1000,
        );
    }

    function exitPresentation() {
        clearTimeout(playbackTimer);
        playing = false;
        document.body.classList.remove("presenting");
        $("presentation-controls").hidden = true;
    }

    function setTextColor(color) {
        const obj = current();
        if (!obj || obj.tipo === "imagen") return;
        obj.color = color;
        $("font-color").value = color;
        mountStyle(obj);
        sync();
    }

    $("text-tool").addEventListener("click", addText);
    $("delete-text").addEventListener("click", remove);
    $("edit-text").addEventListener("click", edit);
    $("images-tool").addEventListener("click", event => showGallery("imagenes", event.currentTarget));
    $("elements-tool").addEventListener("click", event => showGallery("elementos", event.currentTarget));
    $("background-tool").addEventListener("click", event => showGallery("fondos", event.currentTarget));
    $("animation-tool").addEventListener("click", event => showGallery("animaciones", event.currentTarget));
    $("close-asset-panel").addEventListener("click", () => {
        $("asset-panel").hidden = true;
        for (const tool of [$("images-tool"), $("elements-tool"), $("background-tool"), $("animation-tool")]) {
            tool.setAttribute("aria-expanded", "false");
            tool.classList.remove("tool-active");
        }
    });
    document.querySelectorAll(".asset-choice").forEach(button => {
        button.addEventListener("click", () => {
            const path = button.dataset.assetPath;
            if (button.closest(".asset-gallery").dataset.gallery === "fondos") {
                setBackground(path);
            } else {
                addElement(path);
            }
        });
    });
    $("clear-background").addEventListener("click", () => setBackground(""));
    document.querySelectorAll(".animation-choice").forEach(button => {
        button.addEventListener("click", () => {
            animateForScope(button.dataset.animation);
        });
    });
    $("preview-animation").addEventListener("click", preview);
    $("animation-scope").addEventListener("change", updateAnimationPanel);
    document.querySelectorAll("[data-text-color]").forEach(button => {
        button.addEventListener("click", () => setTextColor(button.dataset.textColor));
    });
    $("font-color").addEventListener("input", event => setTextColor(event.target.value));
    $("present-button").addEventListener("click", () => enterPresentation());
    $("exit-presentation").addEventListener("click", exitPresentation);
    $("previous-slide").addEventListener("click", () => showPresentationSlide(activeSlideIndex - 1));
    $("next-slide").addEventListener("click", () => showPresentationSlide(activeSlideIndex + 1));
    window.addEventListener("keydown", event => {
        if (playing) {
            if (event.key === "Escape") {
                event.preventDefault();
                exitPresentation();
            } else if (event.key === "ArrowRight") {
                event.preventDefault();
                showPresentationSlide(activeSlideIndex + 1);
            } else if (event.key === "ArrowLeft") {
                event.preventDefault();
                showPresentationSlide(activeSlideIndex - 1);
            }
            return;
        }
        const key = event.key.toLowerCase();
        const nativeTextEditing = event.target instanceof HTMLElement
            && !event.target.matches(".object-content")
            && (
                event.target.matches("input:not([type='color']):not([type='range']), textarea")
                || event.target.isContentEditable
            );
        if ((event.ctrlKey || event.metaKey) && key === "z") {
            if (nativeTextEditing) return;
            event.preventDefault();
            if (event.shiftKey) redo();
            else undo();
            return;
        }
        if ((event.ctrlKey || event.metaKey) && key === "y") {
            if (nativeTextEditing) return;
            event.preventDefault();
            redo();
            return;
        }
        const typing = event.target instanceof HTMLElement
            && (event.target.matches("input, textarea, select") || event.target.isContentEditable);
        if (
            event.key === "Delete"
            && !event.defaultPrevented
            && !typing
            && !event.ctrlKey
            && !event.metaKey
            && !current()
        ) {
            event.preventDefault();
            deleteSlide();
            return;
        }
        if (typing || !(event.ctrlKey || event.metaKey)) return;
        if (key === "c" || key === "v") {
            const slideIsFocused = event.target instanceof Element && event.target.closest(".slide-thumb");
            const useSlideClipboard = event.shiftKey || slideIsFocused || !current();
            event.preventDefault();
            if (key === "c") {
                if (useSlideClipboard) copySlide();
                else copyObject();
            } else if (useSlideClipboard) {
                pasteSlide();
            } else {
                pasteObject();
            }
        }
    });
    stage.addEventListener("pointerdown", event => {
        if (event.target === stage) select(null);
    });
    stage.addEventListener("keydown", event => {
        const obj = current();
        if (!obj) return;
        if (editing) {
            if (event.key === "Escape") {
                event.preventDefault();
                stopEditing();
                node(selected).focus();
            }
            return;
        }
        if (event.key === "Enter" && obj.tipo !== "imagen") {
            event.preventDefault();
            edit();
        }
        if (["Delete", "Backspace"].includes(event.key)) {
            event.preventDefault();
            remove();
        }
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
            event.preventDefault();
            const step = event.shiftKey ? 10 : 1;
            obj.x = clamp(
                obj.x + (event.key === "ArrowRight" ? step : event.key === "ArrowLeft" ? -step : 0),
                MIN_OBJECT_POSITION,
                MAX_OBJECT_POSITION,
            );
            obj.y = clamp(
                obj.y + (event.key === "ArrowDown" ? step : event.key === "ArrowUp" ? -step : 0),
                MIN_OBJECT_POSITION,
                MAX_OBJECT_POSITION,
            );
            node(obj.id).style.left = `${obj.x}px`;
            node(obj.id).style.top = `${obj.y}px`;
            if (obj.fotogramas?.[0]?.frame === 0) {
                obj.fotogramas[0].x = obj.x;
                obj.fotogramas[0].y = obj.y;
            }
            sync();
        }
    });

    for (const [id, key] of [["font-family", "fuente"], ["font-size", "tamano"], ["font-color", "color"], ["text-align", "alineacion"]]) {
        $(id).addEventListener("input", () => {
            const obj = current();
            const input = $(id);
            if (!obj || obj.tipo === "imagen" || !input.checkValidity() || input.value === "") return;
            obj[key] = key === "tamano" ? Number(input.value) : input.value;
            mountStyle(obj);
            sync();
        });
    }

    function mountStyle(obj) {
        const input = node(obj.id).querySelector("textarea");
        if (!input) return;
        Object.assign(input.style, {
            fontFamily: `${obj.fuente}, sans-serif`,
            fontSize: `${obj.tamano}px`,
            color: obj.color,
            fontWeight: obj.negrita ? "700" : "400",
            fontStyle: obj.cursiva ? "italic" : "normal",
            textDecoration: obj.subrayado ? "underline" : "none",
            textAlign: obj.alineacion,
        });
    }

    for (const [id, key] of [["bold", "negrita"], ["italic", "cursiva"], ["underline", "subrayado"]]) {
        $(id).addEventListener("click", () => {
            const obj = current();
            if (!obj || obj.tipo === "imagen") return;
            obj[key] = !obj[key];
            $(id).setAttribute("aria-pressed", String(obj[key]));
            mountStyle(obj);
            sync();
        });
    }

    form.elements.nombre.addEventListener("input", sync);
    for (const link of document.querySelectorAll(".share-menu a")) {
        link.addEventListener("click", async event => {
            event.preventDefault();
            const saved = await save();
            if (saved && !dirty()) window.location.assign(link.href);
            else showSaveError("Guarda los cambios antes de exportar.");
        });
    }
    form.addEventListener("submit", event => {
        event.preventDefault();
        submitting = true;
        save();
        submitting = false;
    });
    window.addEventListener("beforeunload", event => {
        if (dirty() || saving) {
            event.preventDefault();
            event.returnValue = "";
        }
    });
    window.addEventListener("pageshow", () => {
        submitting = false;
    });

    const area = stage.parentElement.parentElement;
    new ResizeObserver(() => {
        const compact = window.matchMedia("(max-width: 600px)").matches;
        scale = Math.min(
            Math.max(100, area.clientWidth - (compact ? 16 : 48)) / 800,
            Math.max(100, area.clientHeight - (compact ? 60 : 100)) / 450
        );
        $("stage-viewport").style.width = `${800 * scale}px`;
        $("stage-viewport").style.height = `${450 * scale}px`;
        stage.style.transform = `scale(${scale})`;
    }).observe(area);

    $("slide-duration").value = String(Math.round(slides[activeSlideIndex].duracion_frames / 30));
    stage.style.backgroundImage = activeBackground
        ? `url("${assetBase}${encodeURI(activeBackground)}")`
        : "none";
    stage.style.backgroundColor = activeSlideColor;
    updateSlideColorPicker();
    objects.forEach(mount);
    select(null);
    updateAnimationPanel();
    renderSlideList();
    sync();
    historyEntries = [captureHistory()];
    historyIndex = 0;
    historyReady = true;
    updateHistoryButtons();
})();
