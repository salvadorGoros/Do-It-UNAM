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
    const MAX_SLIDE_FRAMES = 108000;
    const FPS = 30;
    const animatedProperties = ["x", "y", "ancho", "alto", "giro", "opacidad", "color", "tamano", "texto"];

    function basePose(obj) {
        return {
            x: obj.x, y: obj.y, ancho: obj.ancho, alto: obj.alto,
            giro: 0, opacidad: 1, color: obj.color, tamano: obj.tamano,
            texto: obj.texto, fuente: obj.fuente,
        };
    }

    function normalizeKeyframes(obj) {
        const source = Array.isArray(obj.fotogramas) && obj.fotogramas.length
            ? [...obj.fotogramas].sort((left, right) => left.frame - right.frame)
            : [{frame: 0, x: obj.x, y: obj.y, giro: 0, opacidad: 1, interpolacion: "lineal"}];
        let previous = basePose(obj);
        obj.fotogramas = source.map(key => {
            previous = {...previous, ...key};
            return {
                frame: key.frame,
                x: previous.x,
                y: previous.y,
                ancho: previous.ancho,
                alto: previous.alto,
                giro: previous.giro,
                opacidad: previous.opacidad,
                color: previous.color,
                tamano: previous.tamano,
                texto: previous.texto,
                fuente: previous.fuente,
                interpolacion: key.interpolacion || "lineal",
                texto_modo: key.texto_modo || "instantaneo",
                ...(key.interpolacion === "bezier" ? {bezier: key.bezier || [.25, .1, .25, 1]} : {}),
            };
        });
    }

    function normalizeSlide(slide) {
        slide.color_fondo ||= "#ffffff";
        slide.audio ||= "";
        slide.audios = Array.isArray(slide.audios) ? slide.audios : [];
        if (slide.audio && !slide.audios.some(track => track.path === slide.audio)) {
            slide.audios.unshift({
                id: crypto.randomUUID(), path: slide.audio, inicio_frame: 0,
                recorte_inicio: 0, recorte_fin: null, volumen: 1, silenciado: false,
                fundido_entrada: 0, fundido_salida: 0,
            });
        }
        slide.audios = slide.audios.slice(0, 3);
        slide.marcadores = Array.isArray(slide.marcadores) ? slide.marcadores : [];
        slide.objetos.forEach(normalizeKeyframes);
        const lastFrame = Math.max(
            0,
            ...slide.objetos.flatMap(obj => obj.fotogramas.map(key => key.frame)),
            ...slide.marcadores.map(marker => marker.frame),
            ...slide.audios.map(track => track.recorte_fin === null
                ? track.inicio_frame
                : track.inicio_frame + (track.recorte_fin - track.recorte_inicio) * FPS),
        );
        slide.duracion_frames = clamp(Math.max(slide.duracion_frames || 300, lastFrame), 30, MAX_SLIDE_FRAMES);
    }
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
            audio: "",
            duracion_frames: Number(form.elements.duracion_frames.value) || 300,
        }];
    }
    slides.forEach(normalizeSlide);
    let activeSlideIndex = Number(form.elements.diapositiva_activa.value) || 0;
    activeSlideIndex = clamp(activeSlideIndex, 0, slides.length - 1);
    let objects = slides[activeSlideIndex].objetos;
    const assetBase = stage.dataset.assetBase;
    const uploadedImageBase = stage.dataset.uploadedImageBase;
    const uploadedAudioBase = stage.dataset.uploadedAudioBase;
    const imageUrl = path => {
        if (!path.startsWith("uploads/")) return `${assetBase}${encodeURI(path)}`;
        const [, ownerId, filename] = path.split("/");
        return `${uploadedImageBase}${ownerId}/${encodeURIComponent(filename)}/`;
    };
    const audioUrl = path => {
        if (!path) return "";
        const [, ownerId, filename] = path.split("/");
        return `${uploadedAudioBase}${ownerId}/${encodeURIComponent(filename)}/`;
    };
    let activeBackground = slides[activeSlideIndex].fondo;
    let activeSlideColor = slides[activeSlideIndex].color_fondo;
    let activeAudios = slides[activeSlideIndex].audios;
    let selectedAudioTrackId = activeAudios[0]?.id || null;
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
    let playbackRequest = null;
    let presentationChromeTimer = null;
    let timelineRunning = false;
    let currentFrame = 0;
    let playbackStartedAt = 0;
    let playbackStartFrame = 0;
    let waitingMarker = null;
    let consumedMarkers = new Set();
    let loopEnabled = false;
    let loopStart = 0;
    let loopEnd = slides[activeSlideIndex].duracion_frames;
    let timelinePixelsPerSecond = 100;
    const selectedKeyframes = new Set();
    const expandedObjects = new Set();
    const audioPlayers = new Map();
    const audioBuffers = new Map();
    let saveWaiters = [];
    let historyTimer = null;
    let historyEntries = [];
    let historyIndex = -1;
    let historyReady = false;
    let historyPending = false;
    let restoringHistory = false;
    let hasErrors = Boolean(document.querySelector(".errorlist"));
    let saveErrorVisible = !$("save-status").hidden;
    let aiConfigured = false;
    let aiCanGenerate = false;
    let aiPresentationResult = null;
    let aiTextResult = null;
    let aiImageResult = null;
    let aiDocumentResult = null;
    let activeDocumentJob = null;
    let documentPollTimer = null;
    let aiRequestPending = false;
    let aiLoadingReturnFocus = null;
    const current = () => objects.find(obj => obj.id === selected);
    const node = id => [...stage.children].find(el => el.dataset.id === id);
    const objectRotation = obj => evaluateObject(obj, $("timeline-panel").hidden ? 0 : currentFrame).giro || 0;
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
        slide.audios = activeAudios;
        slide.audio = activeAudios[0]?.path || "";
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
        activeAudios = slides[activeSlideIndex].audios || [];
        selectedAudioTrackId = activeAudios[0]?.id || null;
        selected = null;
        editing = null;
        stage.replaceChildren();
        $("slide-duration").value = String(Math.round(slides[activeSlideIndex].duracion_frames / 30));
        stage.style.backgroundImage = activeBackground
            ? `url("${assetBase}${encodeURI(activeBackground)}")`
            : "none";
        stage.style.backgroundColor = activeSlideColor;
        updateSelectedAudio();
        updateSlideColorPicker();
        updateAINotes();
        objects.forEach(mount);
        select(snapshot.selected && objects.some(obj => obj.id === snapshot.selected) ? snapshot.selected : null);
        currentFrame = 0;
        applyFrame(0);
        if (!$("timeline-panel").hidden) {
            renderTimeline();
            renderAudioMixer();
        }
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

    function cubicBezierValue(x, values) {
        const [x1, y1, x2, y2] = values;
        const sample = (t, a, b) => 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t ** 2 * b + t ** 3;
        let low = 0, high = 1, t = x;
        for (let index = 0; index < 12; index++) {
            const currentX = sample(t, x1, x2);
            if (Math.abs(currentX - x) < .0005) break;
            if (currentX < x) low = t;
            else high = t;
            t = (low + high) / 2;
        }
        return sample(t, y1, y2);
    }

    function easedProgress(t, key) {
        if (key.interpolacion === "instantanea") return t < 1 ? 0 : 1;
        if (key.interpolacion === "suave") return t * t * (3 - 2 * t);
        if (key.interpolacion === "rebote") {
            const n1 = 7.5625, d1 = 2.75;
            if (t < 1 / d1) return n1 * t * t;
            if (t < 2 / d1) return n1 * (t -= 1.5 / d1) * t + .75;
            if (t < 2.5 / d1) return n1 * (t -= 2.25 / d1) * t + .9375;
            return n1 * (t -= 2.625 / d1) * t + .984375;
        }
        if (key.interpolacion === "bezier") return cubicBezierValue(t, key.bezier || [.25, .1, .25, 1]);
        return t;
    }

    function hexToRgb(color) {
        const value = Number.parseInt(color.slice(1), 16);
        return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
    }

    function interpolateColor(left, right, t) {
        const a = hexToRgb(left), b = hexToRgb(right);
        return `#${a.map((value, index) => Math.round(value + (b[index] - value) * t).toString(16).padStart(2, "0")).join("")}`;
    }

    function evaluateObject(obj, frame) {
        const keys = obj.fotogramas;
        if (frame <= keys[0].frame) return {...keys[0], textOpacity: 1};
        const last = keys.at(-1);
        if (frame >= last.frame) return {...last, textOpacity: 1};
        const nextIndex = keys.findIndex(key => key.frame > frame);
        const left = keys[nextIndex - 1], right = keys[nextIndex];
        const raw = (frame - left.frame) / (right.frame - left.frame);
        const t = easedProgress(raw, left);
        const pose = {...left};
        for (const property of ["x", "y", "ancho", "alto", "giro", "opacidad", "tamano"]) {
            pose[property] = left[property] + (right[property] - left[property]) * t;
        }
        pose.color = interpolateColor(left.color, right.color, clamp(t, 0, 1));
        pose.fuente = raw < .5 ? left.fuente : right.fuente;
        const mode = right.texto_modo || "instantaneo";
        if (mode === "escritura") {
            pose.texto = right.texto.slice(0, Math.round(right.texto.length * clamp(t, 0, 1)));
            pose.textOpacity = 1;
        } else if (mode === "transicion") {
            pose.texto = raw < .5 ? left.texto : right.texto;
            pose.textOpacity = Math.abs(raw - .5) * 2;
        } else {
            pose.texto = raw < 1 ? left.texto : right.texto;
            pose.textOpacity = 1;
        }
        return pose;
    }

    function applyFrame(frame) {
        for (const obj of objects) {
            const element = node(obj.id);
            if (!element) continue;
            const pose = evaluateObject(obj, frame);
            element.style.left = `${pose.x}px`;
            element.style.top = `${pose.y}px`;
            element.style.width = `${pose.ancho}px`;
            element.style.height = `${pose.alto}px`;
            element.style.transform = `rotate(${pose.giro}deg)`;
            element.style.opacity = pose.opacidad;
            const content = element.querySelector("textarea");
            if (content) {
                if (editing !== obj.id) content.value = pose.texto;
                content.style.fontFamily = `${pose.fuente}, sans-serif`;
                content.style.fontSize = `${pose.tamano}px`;
                content.style.color = pose.color;
                content.style.opacity = pose.textOpacity;
            }
        }
    }

    function updateTimelinePosition() {
        const duration = slides[activeSlideIndex].duracion_frames;
        const bounded = clamp(currentFrame, 0, duration);
        $("timeline-time").textContent = `${String(Math.floor(bounded / FPS / 60)).padStart(2, "0")}:${String(Math.floor(bounded / FPS) % 60).padStart(2, "0")}.${String(Math.round((bounded % FPS) / FPS * 100)).padStart(2, "0")} · F${Math.round(bounded)}`;
        $("timeline-playhead").style.left = `${150 + bounded / FPS * timelinePixelsPerSecond}px`;
        updatePresentationProgress();
    }

    function setTimelineFrame(frame, seekAudio = true) {
        currentFrame = clamp(Math.round(frame), 0, slides[activeSlideIndex].duracion_frames);
        applyFrame(currentFrame);
        updateTimelinePosition();
        if (seekAudio && !timelineRunning) syncAudioPlayers(currentFrame, false);
    }

    function keyframeSnapshot(obj, frame = currentFrame) {
        const pose = evaluateObject(obj, frame);
        return {
            frame: Math.round(frame), x: pose.x, y: pose.y, ancho: pose.ancho, alto: pose.alto,
            giro: pose.giro, opacidad: pose.opacidad, color: pose.color, tamano: pose.tamano,
            texto: pose.texto, fuente: pose.fuente, interpolacion: "suave",
            texto_modo: "instantaneo",
        };
    }

    function extendDurationTo(frame) {
        const slide = slides[activeSlideIndex];
        if (frame <= slide.duracion_frames) return;
        slide.duracion_frames = clamp(Math.ceil(frame), 30, MAX_SLIDE_FRAMES);
        $("slide-duration").value = String(Math.ceil(slide.duracion_frames / FPS));
        loopEnd = slide.duracion_frames;
        $("loop-end").value = String(loopEnd);
    }

    function addKeyframeForObject(obj, frame = currentFrame, selectKey = true) {
        if (!obj) return null;
        const roundedFrame = clamp(Math.round(frame), 0, MAX_SLIDE_FRAMES);
        extendDurationTo(roundedFrame);
        let key = obj.fotogramas.find(item => item.frame === roundedFrame);
        if (!key) {
            key = keyframeSnapshot(obj, roundedFrame);
            obj.fotogramas.push(key);
            obj.fotogramas.sort((left, right) => left.frame - right.frame);
        }
        if (selectKey) {
            selectedKeyframes.clear();
            selectedKeyframes.add(`${obj.id}:${key.frame}`);
        }
        renderTimeline();
        renderMotionPath();
        sync();
        return key;
    }

    function renderMotionPath() {
        stage.querySelector(".motion-path-overlay")?.remove();
        const obj = current();
        if (!obj || obj.fotogramas.length < 2 || $("timeline-panel").hidden) return;
        const namespace = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(namespace, "svg");
        svg.classList.add("motion-path-overlay");
        const polyline = document.createElementNS(namespace, "polyline");
        polyline.classList.add("motion-path-line");
        polyline.setAttribute("points", obj.fotogramas.map(key => `${key.x + key.ancho / 2},${key.y + key.alto / 2}`).join(" "));
        svg.append(polyline);
        for (const key of obj.fotogramas) {
            const point = document.createElementNS(namespace, "circle");
            point.classList.add("motion-path-point");
            point.setAttribute("cx", key.x + key.ancho / 2);
            point.setAttribute("cy", key.y + key.alto / 2);
            point.setAttribute("r", "6");
            point.addEventListener("pointerdown", event => {
                event.preventDefault();
                const startX = event.clientX, startY = event.clientY;
                const originalX = key.x, originalY = key.y;
                const move = moveEvent => {
                    key.x = clamp(originalX + (moveEvent.clientX - startX) / scale, MIN_OBJECT_POSITION, MAX_OBJECT_POSITION);
                    key.y = clamp(originalY + (moveEvent.clientY - startY) / scale, MIN_OBJECT_POSITION, MAX_OBJECT_POSITION);
                    setTimelineFrame(key.frame, false);
                    renderMotionPath();
                };
                const up = () => {
                    window.removeEventListener("pointermove", move);
                    window.removeEventListener("pointerup", up);
                    sync();
                    commitHistory();
                };
                window.addEventListener("pointermove", move);
                window.addEventListener("pointerup", up, {once: true});
            });
            svg.append(point);
        }
        stage.append(svg);
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
            button.setAttribute("aria-pressed", String(Boolean(obj) && (obj.animacion || "ninguna") === button.dataset.keyframePreset));
            button.disabled = !canApply;
        }
        $("preview-animation").disabled = !objects.some(obj => obj.fotogramas.length > 1);
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
        renderMotionPath();
        if (!$("timeline-panel").hidden) renderTimeline();
    }

    function setObjectRotation(obj, rotation) {
        const editedFrame = $("timeline-panel").hidden ? 0 : currentFrame;
        const keyframe = obj.fotogramas.find(frame => frame.frame === editedFrame)
            || addKeyframeForObject(obj, editedFrame, false);
        if (keyframe) {
            keyframe.giro = rotation;
        } else {
            obj.fotogramas.push({
                frame: editedFrame,
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
                const editedFrame = $("timeline-panel").hidden ? 0 : currentFrame;
                const keyframe = obj.fotogramas.find(frame => frame.frame === editedFrame)
                    || addKeyframeForObject(obj, editedFrame, false);
                if (keyframe) keyframe.texto = obj.texto;
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
            if (playing) {
                if (waitingMarker?.objeto_id === obj.id) {
                    event.preventDefault();
                    resumeAfterMarker();
                }
                return;
            }
            if (!playing && currentFrame !== 0 && $("timeline-panel").hidden) setTimelineFrame(0);
            select(obj.id);
            if (editing === obj.id && event.target === content) return;
            event.preventDefault();
            el.focus();
            const editedKey = $("timeline-panel").hidden ? null : addKeyframeForObject(obj, currentFrame, false);
            const displayedPose = evaluateObject(obj, currentFrame);
            gesture = {
                id: obj.id,
                pointer: event.pointerId,
                rotate: event.target === rotateHandle,
                resize: event.target instanceof Element && event.target.matches(".resize-handle"),
                handle: event.target instanceof Element ? event.target.dataset.handle : null,
                sx: event.clientX,
                sy: event.clientY,
                rotation: displayedPose.giro,
                startAngle: event.target === rotateHandle
                    ? Math.atan2(
                        event.clientY - (el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2),
                        event.clientX - (el.getBoundingClientRect().left + el.getBoundingClientRect().width / 2),
                    ) * 180 / Math.PI
                    : 0,
                x: displayedPose.x,
                y: displayedPose.y,
                width: displayedPose.ancho,
                height: displayedPose.alto,
                keyframe: editedKey,
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
            const editedFrame = gesture.keyframe || obj.fotogramas?.find(frame => frame.frame === 0);
            if (editedFrame) {
                editedFrame.x = obj.x;
                editedFrame.y = obj.y;
                editedFrame.ancho = obj.ancho;
                editedFrame.alto = obj.alto;
            }
            sync();
            historyPending = true;
            updateHistoryButtons();
        });
        for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
            el.addEventListener(eventName, () => {
                if (gesture?.id === obj.id && gesture.rotate) hideRotationGuide();
                gesture = null;
                if (!$("timeline-panel").hidden) {
                    renderTimeline();
                    renderMotionPath();
                }
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
        normalizeKeyframes(obj);
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
        normalizeKeyframes(obj);
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
        slides[activeSlideIndex].audios = activeAudios;
        slides[activeSlideIndex].audio = activeAudios[0]?.path || "";
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
            details.textContent = `${slide.objetos.length} objetos · ${Math.round(slide.duracion_frames / 30)} s${slide.audios?.length ? ` · ${slide.audios.length} audio${slide.audios.length === 1 ? "" : "s"}` : ""}`;
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
                const timelineLayout = document.body.classList.contains("timeline-open");
                const beforeSlide = timelineLayout
                    ? event.clientY < bounds.top + bounds.height / 2
                    : event.clientX < bounds.left + bounds.width / 2;
                const insertionIndex = beforeSlide ? index : index + 1;
                reorderSlide(from, insertionIndex);
            });
            const wrapper = document.createElement("div");
            wrapper.className = "slide-thumb-wrap";
            const options = document.createElement("button");
            options.type = "button";
            options.className = "slide-options-trigger";
            options.innerHTML = '<i class="fa-solid fa-ellipsis" aria-hidden="true"></i>';
            options.setAttribute("aria-label", `Opciones de la diapositiva ${index + 1}`);
            options.addEventListener("click", event => {
                event.stopPropagation();
                const bounds = options.getBoundingClientRect();
                showSlide(index);
                openSlideContextMenu(bounds.right, bounds.top);
            });
            wrapper.append(button, options);
            list.append(wrapper);
        }
        $("presentation-count").textContent = `${activeSlideIndex + 1} / ${slides.length}`;
        sync();
    }

    function showSlide(index, storeCurrent = true) {
        if (index < 0 || index >= slides.length) return;
        if (timelineRunning) pauseTimeline();
        stopAudioPlayers();
        if (storeCurrent) storeCurrentSlide();
        stopEditing();
        activeSlideIndex = index;
        objects = slides[index].objetos;
        activeBackground = slides[index].fondo;
        activeSlideColor = slides[index].color_fondo || "#ffffff";
        activeAudios = slides[index].audios || [];
        selectedAudioTrackId = activeAudios[0]?.id || null;
        currentFrame = 0;
        loopStart = 0;
        loopEnd = slides[index].duracion_frames;
        $("slide-duration").value = String(Math.round(slides[index].duracion_frames / 30));
        form.elements.diapositiva_activa.value = String(index);
        stage.replaceChildren();
        stage.style.backgroundImage = activeBackground
            ? `url("${assetBase}${encodeURI(activeBackground)}")`
            : "none";
        stage.style.backgroundColor = activeSlideColor;
        updateSlideColorPicker();
        updateSelectedAudio();
        updateAINotes();
        objects.forEach(mount);
        select(null);
        applyFrame(0);
        if (!$("timeline-panel").hidden) {
            renderTimeline();
            renderAudioMixer();
        }
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
            audio: "",
            audios: [],
            marcadores: [],
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
            ia: "Asistente con IA",
            fondos: "Fondos",
            audios: "Audio",
            animaciones: "Animar",
        }[section];
        for (const tool of [$("images-tool"), $("ai-tool"), $("elements-tool"), $("background-tool"), $("audio-tool"), $("animation-tool")]) {
            tool.setAttribute("aria-expanded", String(!isOpen && tool === button));
            tool.classList.toggle("tool-active", !isOpen && tool === button);
        }
        if (!isOpen && section === "imagenes") loadUploadedImages();
        if (!isOpen && section === "audios") loadUploadedAudios();
        if (!isOpen && section === "ia") {
            const obj = current();
            if (!$("ai-text-source").value && obj && obj.tipo !== "imagen") {
                $("ai-text-source").value = obj.texto;
            }
            updateAINotes();
            loadAIStatus();
        }
    }

    function closeAssetPanel() {
        $("asset-panel").hidden = true;
        $("asset-panel").dataset.section = "";
        for (const tool of [$("images-tool"), $("ai-tool"), $("elements-tool"), $("background-tool"), $("audio-tool"), $("animation-tool")]) {
            tool.setAttribute("aria-expanded", "false");
            tool.classList.remove("tool-active");
        }
    }

    function closeAssetPanelOnCompactScreen() {
        if (window.matchMedia("(max-width: 760px), (max-height: 600px) and (max-width: 950px)").matches) {
            closeAssetPanel();
        }
    }

    function setAIMessage(message, error = false) {
        $("ai-message").textContent = message;
        $("ai-message").classList.toggle("error", error);
    }

    function updateAINotes() {
        $("ai-slide-notes").value = slides[activeSlideIndex]?.notas || "";
    }

    function setAIGenerationDisabled(disabled) {
        document.querySelectorAll(".ai-primary").forEach(button => {
            const documentIsActive = button.id === "ai-convert-document"
                && ["pendiente", "procesando"].includes(activeDocumentJob?.status);
            button.disabled = disabled || aiRequestPending || documentIsActive;
        });
    }

    function setAILoading(loading, message = "", trigger = null) {
        const screen = $("ai-loading-screen");
        const gallery = document.querySelector('[data-gallery="ia"]');
        aiRequestPending = loading;
        screen.hidden = !loading;
        gallery.setAttribute("aria-busy", String(loading));
        document.body.classList.toggle("ai-request-pending", loading);
        if (loading) {
            aiLoadingReturnFocus = trigger || document.activeElement;
            $("ai-loading-title").textContent = message || "Gemini está preparando tu contenido…";
            setAIGenerationDisabled(true);
            requestAnimationFrame(() => screen.focus({preventScroll: true}));
            return;
        }
        setAIGenerationDisabled(!aiCanGenerate);
        const returnFocus = aiLoadingReturnFocus;
        aiLoadingReturnFocus = null;
        requestAnimationFrame(() => {
            if (returnFocus instanceof HTMLElement && returnFocus.isConnected) {
                returnFocus.focus({preventScroll: true});
            }
        });
    }

    function updateAIState(state) {
        aiConfigured = Boolean(state.configured);
        const connection = $("ai-connection");
        connection.classList.toggle("configured", aiConfigured);
        connection.classList.toggle("not-configured", !aiConfigured);
        $("ai-connection-text").textContent = aiConfigured
            ? `Clave configurada · ${state.text_model}`
            : "Falta GEMINI_API_KEY en el archivo .env";
        const quota = state.quota || {used: 0, limit: 0, remaining: 0};
        const roleName = state.role?.name || "Cuenta";
        $("ai-quota").textContent = `${roleName} · uso de hoy: ${Number(quota.used).toLocaleString("es-MX")} / ${Number(quota.limit).toLocaleString("es-MX")} tokens`;
        const quotaPercent = quota.limit > 0 ? clamp(quota.used / quota.limit * 100, 0, 100) : 0;
        $("ai-quota-percent").textContent = `${Math.round(quotaPercent)}%`;
        $("ai-quota-bar").style.width = `${quotaPercent}%`;
        $("ai-quota-meter").setAttribute("aria-valuenow", String(Math.round(quotaPercent)));
        aiCanGenerate = aiConfigured && quota.remaining > 0;
        setAIGenerationDisabled(!aiCanGenerate);
        if (state.conversion) renderDocumentConversion(state.conversion);
    }

    async function loadAIStatus() {
        const gallery = document.querySelector('[data-gallery="ia"]');
        try {
            const response = await fetch(gallery.dataset.statusUrl, {credentials: "same-origin"});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "No se pudo consultar Gemini.");
            updateAIState(result);
            if (!result.configured) {
                setAIMessage("Pega tu clave en .env y reinicia el servidor para habilitar estas herramientas.");
            } else setAIMessage("");
        } catch (error) {
            aiConfigured = false;
            aiCanGenerate = false;
            setAIGenerationDisabled(true);
            $("ai-connection").classList.add("not-configured");
            $("ai-connection-text").textContent = "No se pudo comprobar Gemini";
            setAIMessage(error.message, true);
        }
    }

    async function requestAI(payload, button, progressMessage) {
        if (aiRequestPending) return null;
        const gallery = document.querySelector('[data-gallery="ia"]');
        button.setAttribute("aria-busy", "true");
        setAILoading(true, progressMessage, button);
        setAIMessage(progressMessage);
        try {
            const response = await fetch(gallery.dataset.generateUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": form.elements.csrfmiddlewaretoken.value,
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify(payload),
            });
            const result = await response.json().catch(() => ({}));
            if (result.state) updateAIState(result.state);
            if (!response.ok) throw new Error(result.error || "Gemini no pudo completar la solicitud.");
            return result;
        } catch (error) {
            setAIMessage(error.message, true);
            return null;
        } finally {
            button.removeAttribute("aria-busy");
            setAILoading(false);
        }
    }

    function makeAITextObject(text, options = {}) {
        const x = options.x ?? 60;
        const y = options.y ?? 50;
        const obj = {
            id: crypto.randomUUID(),
            texto: text,
            x,
            y,
            ancho: options.width ?? 680,
            alto: options.height ?? 100,
            fuente: "Poppins",
            tamano: options.size ?? 28,
            color: options.color ?? "#0f172a",
            negrita: Boolean(options.bold),
            cursiva: false,
            subrayado: false,
            alineacion: options.align || "left",
            animacion: "ninguna",
            fotogramas: [{frame: 0, x, y, giro: 0, opacidad: 1, interpolacion: "lineal"}],
        };
        normalizeKeyframes(obj);
        return obj;
    }

    function makeAISlide(data) {
        const title = makeAITextObject(data.title, {
            x: 55, y: 35, width: 690, height: 70, size: 30,
            color: "#0b3b60", bold: true, align: "center",
        });
        const bullets = makeAITextObject(data.bullets.map(item => `• ${item}`).join("\n"), {
            x: 70, y: 125, width: 660, height: 270,
            size: data.bullets.join(" ").length > 700 ? 17 : 21,
        });
        const slide = {
            id: crypto.randomUUID(),
            objetos: [title, bullets],
            fondo: "",
            color_fondo: "#ffffff",
            audio: "",
            audios: [],
            marcadores: [],
            notas: `${data.speaker_notes}\n\nSugerencia visual: ${data.visual_suggestion}`,
            duracion_frames: 450,
        };
        normalizeSlide(slide);
        return slide;
    }

    async function generateAIPresentation() {
        const button = $("ai-generate-presentation");
        const topic = $("ai-presentation-topic").value.trim();
        if (topic.length < 3) {
            setAIMessage("Describe el tema de la presentación.", true);
            return;
        }
        const result = await requestAI({
            action: "presentation",
            topic,
            slide_count: Number($("ai-slide-count").value),
            audience: $("ai-audience").value,
            style: $("ai-presentation-style").value,
        }, button, "Gemini está preparando la estructura…");
        if (!result) return;
        aiPresentationResult = result.presentation;
        $("ai-presentation-title").textContent = aiPresentationResult.title;
        const preview = $("ai-presentation-preview");
        preview.replaceChildren();
        aiPresentationResult.slides.forEach(slide => {
            const item = document.createElement("li");
            item.textContent = slide.title;
            preview.append(item);
        });
        $("ai-presentation-result").hidden = false;
        setAIMessage(`Estructura lista · ${result.usage.total.toLocaleString("es-MX")} tokens.`);
    }

    function applyAIPresentation() {
        if (!aiPresentationResult) return;
        if (slides.length + aiPresentationResult.slides.length > 100) {
            setAIMessage("La presentación superaría el máximo de 100 diapositivas.", true);
            return;
        }
        storeCurrentSlide();
        const generated = aiPresentationResult.slides.map(makeAISlide);
        const insertionIndex = activeSlideIndex + 1;
        slides.splice(insertionIndex, 0, ...generated);
        showSlide(insertionIndex, false);
        commitHistory();
        setAIMessage(`Se agregaron ${generated.length} diapositivas editables con sus guiones.`);
    }

    function scheduleDocumentPoll(job) {
        clearTimeout(documentPollTimer);
        documentPollTimer = null;
        if (!job || !["pendiente", "procesando"].includes(job.status)) return;
        documentPollTimer = setTimeout(async () => {
            try {
                const response = await fetch(job.status_url, {credentials: "same-origin"});
                const result = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(result.error || "No se pudo consultar la conversión.");
                renderDocumentConversion(result.conversion);
            } catch (error) {
                setAIMessage(error.message, true);
                scheduleDocumentPoll(activeDocumentJob);
            }
        }, 1800);
    }

    function renderDocumentConversion(job) {
        if (!job) return;
        activeDocumentJob = job;
        const container = $("ai-document-job");
        const active = ["pendiente", "procesando"].includes(job.status);
        container.hidden = false;
        container.classList.toggle("is-failed", ["fallido", "cancelado"].includes(job.status));
        container.classList.toggle("is-completed", job.status === "completado");
        $("ai-document-filename").textContent = job.filename;
        $("ai-document-percent").textContent = `${job.progress}%`;
        $("ai-document-progress").value = job.progress;
        $("ai-document-status").textContent = job.error || job.message;
        $("ai-cancel-document").hidden = !active;
        $("ai-retry-document").hidden = !["fallido", "cancelado"].includes(job.status);
        $("ai-convert-document").disabled = active || !aiCanGenerate || aiRequestPending;

        const resultContainer = $("ai-document-result");
        if (job.status === "completado" && job.presentation) {
            aiDocumentResult = job.presentation;
            $("ai-document-title").textContent = aiDocumentResult.title;
            const preview = $("ai-document-preview");
            preview.replaceChildren();
            aiDocumentResult.slides.forEach(slide => {
                const item = document.createElement("li");
                item.textContent = slide.title;
                preview.append(item);
            });
            resultContainer.hidden = false;
            setAIMessage(`Documento convertido en ${aiDocumentResult.slides.length} diapositivas editables.`);
        } else {
            resultContainer.hidden = true;
            aiDocumentResult = null;
        }
        scheduleDocumentPoll(job);
    }

    async function convertAIDocument() {
        if (aiRequestPending) return;
        const input = $("ai-document-file");
        const file = input.files[0];
        if (!file) {
            setAIMessage("Selecciona un archivo PDF o PPTX.", true);
            return;
        }
        if (file.size > 50 * 1024 * 1024) {
            setAIMessage("El documento debe pesar 50 MB o menos.", true);
            return;
        }
        const button = $("ai-convert-document");
        const gallery = document.querySelector('[data-gallery="ia"]');
        const payload = new FormData();
        payload.append("document", file);
        payload.append("slide_count", $("ai-document-slide-count").value);
        payload.append("audience", $("ai-document-audience").value);
        payload.append("style", $("ai-document-style").value);
        button.setAttribute("aria-busy", "true");
        setAILoading(true, "Gemini está preparando tu documento…", button);
        setAIMessage("Subiendo el documento de forma privada…");
        try {
            const response = await fetch(gallery.dataset.documentUploadUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {"X-CSRFToken": form.elements.csrfmiddlewaretoken.value},
                body: payload,
            });
            const result = await response.json().catch(() => ({}));
            if (result.conversion) renderDocumentConversion(result.conversion);
            if (!response.ok) throw new Error(result.error || result.conversion?.error || "No se pudo iniciar la conversión.");
            if (["pendiente", "procesando"].includes(result.conversion?.status)) {
                setAIMessage("Conversión iniciada. Puedes seguir editando mientras se procesa.");
            }
        } catch (error) {
            setAIMessage(error.message, true);
        } finally {
            button.removeAttribute("aria-busy");
            setAILoading(false);
            button.disabled = ["pendiente", "procesando"].includes(activeDocumentJob?.status) || !aiCanGenerate;
        }
    }

    async function requestDocumentAction(url) {
        try {
            const response = await fetch(url, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": form.elements.csrfmiddlewaretoken.value,
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            const result = await response.json().catch(() => ({}));
            if (result.conversion) renderDocumentConversion(result.conversion);
            if (!response.ok) throw new Error(result.error || "No se pudo actualizar la conversión.");
        } catch (error) {
            setAIMessage(error.message, true);
        }
    }

    function applyAIDocument() {
        if (!aiDocumentResult) return;
        aiPresentationResult = aiDocumentResult;
        applyAIPresentation();
    }

    async function generateAIText() {
        const selectedObject = current();
        const source = $("ai-text-source").value.trim()
            || (selectedObject && selectedObject.tipo !== "imagen" ? selectedObject.texto : "");
        if (!source) {
            setAIMessage("Selecciona un objeto de texto o escribe contenido para procesar.", true);
            return;
        }
        const textAction = $("ai-text-action").value;
        const result = await requestAI({
            action: "text",
            text_action: textAction,
            source,
            instruction: $("ai-text-instruction").value,
        }, $("ai-generate-text"), "Gemini está trabajando el texto…");
        if (!result) return;
        aiTextResult = {
            text: result.text,
            action: textAction,
            slideId: slides[activeSlideIndex].id,
            targetId: selectedObject?.tipo !== "imagen" ? selectedObject?.id : null,
        };
        $("ai-text-output").value = result.text;
        $("ai-apply-text").textContent = textAction === "guion"
            ? "Guardar como guion de la diapositiva"
            : selectedObject?.tipo !== "imagen"
                ? "Aplicar al objeto seleccionado"
                : "Agregar como texto a la diapositiva";
        $("ai-text-result").hidden = false;
        setAIMessage(`Texto listo · ${result.usage.total.toLocaleString("es-MX")} tokens.`);
    }

    function applyAIText() {
        if (!aiTextResult) return;
        const slideIndex = slides.findIndex(slide => slide.id === aiTextResult.slideId);
        if (slideIndex < 0) {
            setAIMessage("La diapositiva original ya no existe.", true);
            return;
        }
        if (slideIndex !== activeSlideIndex) showSlide(slideIndex);
        if (aiTextResult.action === "guion") {
            slides[slideIndex].notas = aiTextResult.text;
            updateAINotes();
            sync();
            commitHistory();
            setAIMessage("El guion se guardó en las notas de la diapositiva.");
            return;
        }
        if (aiTextResult.text.length > 5000) {
            setAIMessage("El resultado supera 5000 caracteres; redúcelo antes de colocarlo en el lienzo.", true);
            return;
        }
        let obj = slides[slideIndex].objetos.find(item => item.id === aiTextResult.targetId && item.tipo !== "imagen");
        if (!obj) {
            if (objects.length >= 100) {
                setAIMessage("La diapositiva ya tiene 100 objetos.", true);
                return;
            }
            obj = makeAITextObject(aiTextResult.text, {x: 120, y: 120, width: 560, height: 210, size: 24});
            objects.push(obj);
            mount(obj);
        } else {
            obj.texto = aiTextResult.text;
            const firstFrame = obj.fotogramas.find(frame => frame.frame === 0);
            if (firstFrame) firstFrame.texto = aiTextResult.text;
            node(obj.id).querySelector("textarea").value = aiTextResult.text;
        }
        select(obj.id);
        sync();
        commitHistory();
        setAIMessage("El texto se aplicó y permanece totalmente editable.");
    }

    async function generateAIImage() {
        const prompt = $("ai-image-prompt").value.trim();
        if (prompt.length < 3) {
            setAIMessage("Describe la imagen o diagrama que necesitas.", true);
            return;
        }
        const result = await requestAI({
            action: "image",
            prompt,
            image_type: $("ai-image-type").value,
            aspect_ratio: $("ai-aspect-ratio").value,
        }, $("ai-generate-image"), "Gemini está generando la imagen…");
        if (!result) return;
        aiImageResult = result.image;
        $("ai-image-preview").src = aiImageResult.url;
        $("ai-image-result").hidden = false;
        setAIMessage(`Imagen guardada en tu biblioteca · ${result.usage.total.toLocaleString("es-MX")} tokens.`);
    }

    function applyAIImage() {
        if (!aiImageResult) return;
        if (objects.length >= 100) {
            setAIMessage("La diapositiva ya tiene 100 objetos.", true);
            return;
        }
        addElement(aiImageResult.path);
        setAIMessage("La imagen se agregó a la diapositiva y a tu biblioteca privada.");
    }

    function renderUploadedImages(images) {
        const grid = $("uploaded-image-grid");
        grid.replaceChildren();
        for (const image of images) {
            const card = document.createElement("article");
            card.className = "uploaded-image-card";
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
            choice.addEventListener("click", () => {
                addElement(image.path);
                closeAssetPanelOnCompactScreen();
            });
            const removeBackground = document.createElement("button");
            removeBackground.type = "button";
            removeBackground.className = "remove-background-trigger";
            removeBackground.innerHTML = '<i class="fa-solid fa-scissors" aria-hidden="true"></i><span>Quitar fondo</span>';
            removeBackground.setAttribute("aria-label", `Quitar fondo de ${image.name}`);
            removeBackground.addEventListener("click", () => openRemoveBackgroundDialog(image));
            card.append(choice, removeBackground);
            grid.append(card);
        }
        $("uploaded-image-empty").hidden = images.length > 0;
    }

    let uploadedImagesRequest = 0;
    let uploadedImagesCache = [];
    let imageSelectedForBackgroundRemoval = null;

    function closeRemoveBackgroundDialog() {
        const dialog = $("remove-background-dialog");
        imageSelectedForBackgroundRemoval = null;
        if (dialog.open) dialog.close();
    }

    function openRemoveBackgroundDialog(image) {
        imageSelectedForBackgroundRemoval = image;
        $("remove-background-preview-image").src = image.url;
        $("remove-background-image-name").textContent = image.name;
        $("remove-background-status").textContent = "";
        $("remove-background-tolerance").value = "32";
        $("remove-background-tolerance-value").value = "32";
        const dialog = $("remove-background-dialog");
        if (!dialog.open) dialog.showModal();
    }

    async function removeSelectedImageBackground() {
        if (!imageSelectedForBackgroundRemoval) return;
        const gallery = document.querySelector('[data-gallery="imagenes"]');
        const button = $("confirm-remove-background");
        const status = $("remove-background-status");
        const data = new FormData();
        data.append("path", imageSelectedForBackgroundRemoval.path);
        data.append("tolerance", $("remove-background-tolerance").value);
        data.append("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
        button.disabled = true;
        status.textContent = "Eliminando el fondo y creando tu PNG…";
        try {
            const response = await fetch(gallery.dataset.removeBackgroundUrl, {
                method: "POST",
                body: data,
                headers: {"X-Requested-With": "XMLHttpRequest"},
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "No se pudo quitar el fondo.");
            uploadedImagesCache = [
                result.image,
                ...uploadedImagesCache.filter(image => image.path !== result.image.path),
            ];
            renderUploadedImages(uploadedImagesCache);
            $("image-upload-status").textContent = `PNG sin fondo creado. Se retiró ${result.removed_percentage}% de la imagen.`;
            closeRemoveBackgroundDialog();
        } catch (error) {
            status.textContent = error.message || "No se pudo quitar el fondo.";
        } finally {
            button.disabled = false;
        }
    }

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
        // Evita que una carga inicial pendiente reemplace la galería después de subir.
        uploadedImagesRequest += 1;
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

    let uploadedAudiosRequest = 0;
    let uploadedAudiosCache = [];

    function mergeUploadedAudios(audios) {
        const merged = new Map();
        for (const audio of [...audios, ...uploadedAudiosCache]) merged.set(audio.path, audio);
        uploadedAudiosCache = [...merged.values()];
        return uploadedAudiosCache;
    }

    function updateSelectedAudio() {
        const selectedTrack = activeAudios.find(track => track.id === selectedAudioTrackId);
        const selectedAudio = uploadedAudiosCache.find(audio => audio.path === selectedTrack?.path);
        const preview = $("selected-audio-preview");
        $("selected-audio-name").textContent = selectedTrack
            ? selectedAudio?.name || selectedTrack.path.split("/").at(-1)
            : "Sin pista seleccionada";
        $("clear-audio").disabled = !selectedTrack;
        if (selectedTrack) {
            preview.src = selectedAudio?.url || audioUrl(selectedTrack.path);
            preview.hidden = false;
        } else {
            preview.pause();
            preview.removeAttribute("src");
            preview.load();
            preview.hidden = true;
        }
        document.querySelectorAll("[data-audio-path]").forEach(button => {
            button.setAttribute("aria-pressed", String(activeAudios.some(track => track.path === button.dataset.audioPath)));
        });
        updateAudioScopeControls(selectedTrack);
    }

    function updateAudioScopeControls(selectedTrack = activeAudios.find(track => track.id === selectedAudioTrackId)) {
        const applyButton = $("apply-audio-all");
        const removeButton = $("remove-audio-all");
        const summary = $("audio-scope-summary");
        if (!selectedTrack) {
            applyButton.disabled = true;
            removeButton.disabled = true;
            summary.textContent = "Selecciona una pista para aplicarla a todas las diapositivas.";
            return;
        }
        const assignedSlides = slides.filter(slide =>
            (slide.audios || []).some(track => track.path === selectedTrack.path)
        ).length;
        summary.textContent = assignedSlides === slides.length
            ? `Esta pista está en las ${slides.length} diapositivas.`
            : `Esta pista está en ${assignedSlides} de ${slides.length} diapositivas.`;
        applyButton.disabled = assignedSlides === slides.length;
        removeButton.disabled = assignedSlides === 0;
    }

    function applySelectedAudioToAllSlides() {
        const selectedTrack = activeAudios.find(track => track.id === selectedAudioTrackId);
        if (!selectedTrack) return;
        storeCurrentSlide();
        let added = 0;
        let full = 0;
        for (const slide of slides) {
            slide.audios ||= [];
            if (slide.audios.some(track => track.path === selectedTrack.path)) continue;
            if (slide.audios.length >= 3) {
                full += 1;
                continue;
            }
            const copy = {
                ...selectedTrack,
                id: crypto.randomUUID(),
                inicio_frame: 0,
            };
            slide.audios.push(copy);
            slide.audio = slide.audios[0]?.path || "";
            if (copy.recorte_fin !== null) {
                const endFrame = Math.round(Math.max(0, copy.recorte_fin - copy.recorte_inicio) * FPS);
                slide.duracion_frames = clamp(Math.max(slide.duracion_frames, endFrame), 30, MAX_SLIDE_FRAMES);
            }
            added += 1;
        }
        activeAudios = slides[activeSlideIndex].audios;
        selectedAudioTrackId = activeAudios.find(track => track.path === selectedTrack.path)?.id || null;
        $("slide-duration").value = String(Math.round(slides[activeSlideIndex].duracion_frames / FPS));
        $("audio-scope-message").textContent = full
            ? `Se agregó a ${added} diapositiva${added === 1 ? "" : "s"}; ${full} se omitieron porque ya tienen tres pistas.`
            : added
                ? `Pista aplicada a ${slides.length} diapositiva${slides.length === 1 ? "" : "s"}.`
                : "La pista ya estaba aplicada en todas las diapositivas.";
        $("audio-scope-message").classList.toggle("warning", full > 0);
        updateSelectedAudio();
        renderAudioMixer();
        renderTimeline();
        renderSlideList();
        sync();
        commitHistory();
    }

    function removeSelectedAudioFromAllSlides() {
        const selectedTrack = activeAudios.find(track => track.id === selectedAudioTrackId);
        if (!selectedTrack) return;
        storeCurrentSlide();
        let removed = 0;
        for (const slide of slides) {
            const previousLength = (slide.audios || []).length;
            slide.audios = (slide.audios || []).filter(track => track.path !== selectedTrack.path);
            removed += previousLength - slide.audios.length;
            slide.audio = slide.audios[0]?.path || "";
        }
        stopAudioPlayers();
        activeAudios = slides[activeSlideIndex].audios;
        selectedAudioTrackId = activeAudios[0]?.id || null;
        $("audio-scope-message").textContent = `Pista retirada de ${removed} diapositiva${removed === 1 ? "" : "s"}.`;
        $("audio-scope-message").classList.remove("warning");
        updateSelectedAudio();
        renderAudioMixer();
        renderTimeline();
        renderSlideList();
        sync();
        commitHistory();
    }

    function hydrateAudioTrack(track) {
        const probe = new Audio(audioUrl(track.path));
        probe.preload = "metadata";
        probe.addEventListener("loadedmetadata", () => {
            const duration = clamp(probe.duration || 0, 0, 3600);
            if (track.recorte_fin === null) track.recorte_fin = duration;
            extendDurationTo(track.inicio_frame + Math.max(0, track.recorte_fin - track.recorte_inicio) * FPS);
            renderAudioMixer();
            renderTimeline();
            sync();
        }, {once: true});
    }

    function selectAudio(path) {
        let track = activeAudios.find(item => item.path === path);
        if (!track) {
            if (activeAudios.length >= 3) {
                $("audio-upload-status").textContent = "Cada diapositiva admite un máximo de 3 pistas.";
                return;
            }
            track = {
                id: crypto.randomUUID(), path, inicio_frame: currentFrame,
                recorte_inicio: 0, recorte_fin: null, volumen: 1, silenciado: false,
                fundido_entrada: 0, fundido_salida: 0,
            };
            activeAudios.push(track);
            hydrateAudioTrack(track);
        }
        selectedAudioTrackId = track.id;
        slides[activeSlideIndex].audios = activeAudios;
        slides[activeSlideIndex].audio = activeAudios[0]?.path || "";
        updateSelectedAudio();
        renderAudioMixer();
        renderSlideList();
        sync();
    }

    function removeSelectedAudioTrack() {
        if (!selectedAudioTrackId) return;
        stopAudioPlayers();
        activeAudios = activeAudios.filter(track => track.id !== selectedAudioTrackId);
        selectedAudioTrackId = activeAudios[0]?.id || null;
        slides[activeSlideIndex].audios = activeAudios;
        slides[activeSlideIndex].audio = activeAudios[0]?.path || "";
        updateSelectedAudio();
        renderAudioMixer();
        renderSlideList();
        sync();
    }

    function renderUploadedAudios(audios) {
        const list = $("uploaded-audio-list");
        list.replaceChildren();
        for (const audio of audios) {
            const item = document.createElement("article");
            item.className = "audio-item";
            const name = document.createElement("strong");
            name.textContent = audio.name;
            const player = document.createElement("audio");
            player.controls = true;
            player.preload = "metadata";
            player.src = audio.url;
            player.setAttribute("aria-label", `Escuchar ${audio.name}`);
            player.addEventListener("play", () => {
                document.querySelectorAll(".audio-item audio, #selected-audio-preview").forEach(other => {
                    if (other !== player) other.pause();
                });
            });
            const selectButton = document.createElement("button");
            selectButton.type = "button";
            selectButton.className = "audio-select";
            selectButton.dataset.audioPath = audio.path;
            selectButton.textContent = "Agregar o seleccionar pista";
            selectButton.addEventListener("click", () => selectAudio(audio.path));
            item.append(name, player, selectButton);
            list.append(item);
        }
        $("uploaded-audio-empty").hidden = audios.length > 0;
        updateSelectedAudio();
    }

    async function loadUploadedAudios() {
        const gallery = document.querySelector('[data-gallery="audios"]');
        const status = $("audio-upload-status");
        const requestId = ++uploadedAudiosRequest;
        try {
            const response = await fetch(gallery.dataset.audiosUrl, {
                credentials: "same-origin",
                cache: "no-store",
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "No se pudieron cargar tus audios.");
            if (requestId !== uploadedAudiosRequest) return null;
            renderUploadedAudios(mergeUploadedAudios(result.audios));
            status.textContent = "";
            return true;
        } catch (error) {
            if (requestId !== uploadedAudiosRequest) return null;
            status.textContent = error.message || "No se pudieron cargar tus audios.";
            return false;
        }
    }

    async function uploadAudios(files) {
        if (!files.length) return;
        const gallery = document.querySelector('[data-gallery="audios"]');
        const status = $("audio-upload-status");
        const data = new FormData();
        for (const file of files) data.append("audios", file);
        data.append("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
        status.textContent = "Subiendo audios...";
        try {
            const response = await fetch(gallery.dataset.uploadUrl, {
                method: "POST",
                body: data,
                headers: {"X-Requested-With": "XMLHttpRequest"},
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "No se pudieron subir los audios.");
            renderUploadedAudios(mergeUploadedAudios(result.audios));
            status.textContent = `${result.audios.length} audio${result.audios.length === 1 ? "" : "s"} guardado${result.audios.length === 1 ? "" : "s"}.`;
        } catch (error) {
            status.textContent = error.message || "No se pudieron subir los audios.";
        }
    }

    let audioContext = null;

    async function drawWaveform(canvas, track) {
        try {
            if (!audioBuffers.has(track.path)) {
                const response = await fetch(audioUrl(track.path), {credentials: "same-origin"});
                const bytes = await response.arrayBuffer();
                audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
                audioBuffers.set(track.path, await audioContext.decodeAudioData(bytes.slice(0)));
            }
            const buffer = audioBuffers.get(track.path);
            if (track.recorte_fin === null) {
                track.recorte_fin = Math.min(buffer.duration, 3600);
                extendDurationTo(track.inicio_frame + (track.recorte_fin - track.recorte_inicio) * FPS);
                sync();
            }
            const width = Math.max(1, Math.round(canvas.clientWidth * devicePixelRatio));
            const height = Math.max(1, Math.round(canvas.clientHeight * devicePixelRatio));
            canvas.width = width;
            canvas.height = height;
            const context = canvas.getContext("2d");
            context.clearRect(0, 0, width, height);
            context.strokeStyle = "#2563eb";
            context.lineWidth = Math.max(1, devicePixelRatio);
            context.beginPath();
            const channel = buffer.getChannelData(0);
            const step = Math.max(1, Math.floor(channel.length / width));
            for (let x = 0; x < width; x++) {
                let min = 1, max = -1;
                for (let sample = x * step; sample < Math.min(channel.length, (x + 1) * step); sample++) {
                    min = Math.min(min, channel[sample]);
                    max = Math.max(max, channel[sample]);
                }
                context.moveTo(x, (1 + min) * height / 2);
                context.lineTo(x, (1 + max) * height / 2);
            }
            context.stroke();
        } catch (error) {
            canvas.setAttribute("aria-label", "No se pudo generar la forma de onda");
        }
    }

    function updateAudioTrack(track, field, rawValue) {
        if (field === "silenciado") track[field] = Boolean(rawValue);
        else if (field === "inicio_frame") track[field] = clamp(Math.round(Number(rawValue) * FPS), 0, MAX_SLIDE_FRAMES);
        else if (field === "volumen") track[field] = clamp(Number(rawValue), 0, 1);
        else if (field === "recorte_fin") track[field] = rawValue === "" ? null : clamp(Number(rawValue), track.recorte_inicio + .01, 3600);
        else track[field] = clamp(Number(rawValue), 0, 3600);
        const end = track.inicio_frame + Math.max(0, (track.recorte_fin ?? track.recorte_inicio) - track.recorte_inicio) * FPS;
        extendDurationTo(end);
        renderAudioMixer();
        renderTimeline();
        sync();
    }

    function renderAudioMixer() {
        const container = $("audio-waveform-tracks");
        container.replaceChildren();
        for (const track of activeAudios) {
            const row = document.createElement("article");
            row.className = "audio-wave-track";
            const name = document.createElement("button");
            name.type = "button";
            name.className = "audio-track-name";
            name.textContent = uploadedAudiosCache.find(audio => audio.path === track.path)?.name || track.path.split("/").at(-1);
            name.setAttribute("aria-pressed", String(track.id === selectedAudioTrackId));
            name.addEventListener("click", () => {
                selectedAudioTrackId = track.id;
                updateSelectedAudio();
                renderAudioMixer();
            });
            const canvas = document.createElement("canvas");
            canvas.setAttribute("aria-label", `Forma de onda de ${name.textContent}`);
            const controls = document.createElement("div");
            controls.className = "audio-track-controls";
            const definitions = [
                ["inicio_frame", "Inicio (s)", track.inicio_frame / FPS, "0.1"],
                ["recorte_inicio", "Recorte inicial", track.recorte_inicio, "0.1"],
                ["recorte_fin", "Recorte final", track.recorte_fin ?? "", "0.1"],
                ["volumen", "Volumen", track.volumen, "0.05"],
                ["fundido_entrada", "Fundido entrada", track.fundido_entrada, "0.1"],
                ["fundido_salida", "Fundido salida", track.fundido_salida, "0.1"],
            ];
            for (const [field, labelText, value, step] of definitions) {
                const label = document.createElement("label");
                label.textContent = labelText;
                const input = document.createElement("input");
                input.type = "number";
                input.min = "0";
                input.step = step;
                input.value = value;
                input.addEventListener("change", () => updateAudioTrack(track, field, input.value));
                label.append(input);
                controls.append(label);
            }
            const mute = document.createElement("label");
            mute.textContent = "Silencio";
            const muteInput = document.createElement("input");
            muteInput.type = "checkbox";
            muteInput.checked = track.silenciado;
            muteInput.addEventListener("change", () => updateAudioTrack(track, "silenciado", muteInput.checked));
            mute.append(muteInput);
            controls.append(mute);
            row.append(name, canvas, controls);
            container.append(row);
            drawWaveform(canvas, track);
        }
        if (!activeAudios.length) {
            const empty = document.createElement("p");
            empty.className = "asset-empty";
            empty.textContent = "Agrega pistas desde el apartado Audio.";
            container.append(empty);
        }
    }

    function audioVolumeAt(track, localTime) {
        const duration = Math.max(0, (track.recorte_fin ?? track.recorte_inicio) - track.recorte_inicio);
        let volume = track.silenciado ? 0 : track.volumen;
        if (track.fundido_entrada > 0) volume *= clamp(localTime / track.fundido_entrada, 0, 1);
        if (track.fundido_salida > 0) volume *= clamp((duration - localTime) / track.fundido_salida, 0, 1);
        return clamp(volume, 0, 1);
    }

    function syncAudioPlayers(frame, shouldPlay) {
        const activeIds = new Set(activeAudios.map(track => track.id));
        for (const [id, player] of audioPlayers) {
            if (!activeIds.has(id)) {
                player.pause();
                audioPlayers.delete(id);
            }
        }
        for (const track of activeAudios) {
            let player = audioPlayers.get(track.id);
            if (!player) {
                player = new Audio(audioUrl(track.path));
                player.preload = "auto";
                audioPlayers.set(track.id, player);
            }
            const localTime = frame / FPS - track.inicio_frame / FPS;
            const duration = Math.max(0, (track.recorte_fin ?? Infinity) - track.recorte_inicio);
            if (localTime < 0 || localTime >= duration) {
                player.pause();
                continue;
            }
            const desiredTime = track.recorte_inicio + localTime;
            if (Number.isFinite(player.duration) && Math.abs(player.currentTime - desiredTime) > .3) {
                player.currentTime = clamp(desiredTime, 0, player.duration || desiredTime);
            }
            player.volume = audioVolumeAt(track, localTime);
            if (shouldPlay && player.paused) player.play().catch(() => player.pause());
            if (!shouldPlay && !player.paused) player.pause();
        }
    }

    function stopAudioPlayers() {
        for (const player of audioPlayers.values()) {
            player.pause();
            player.currentTime = 0;
        }
    }

    const keyframeId = (objectId, frame) => `${objectId}:${frame}`;

    function selectedKeyframeData() {
        const selectedData = [];
        for (const obj of objects) {
            for (const key of obj.fotogramas) {
                if (selectedKeyframes.has(keyframeId(obj.id, key.frame))) selectedData.push({obj, key});
            }
        }
        return selectedData;
    }

    function updateKeyframeInspector() {
        const items = selectedKeyframeData();
        const fields = $("keyframe-fields");
        fields.disabled = !items.length;
        $("keyframe-empty").hidden = Boolean(items.length);
        if (!items.length) return;
        $("keyframe-inspector-panel").open = true;
        const key = items[0].key;
        $("keyframe-frame").value = key.frame;
        $("keyframe-x").value = Math.round(key.x * 100) / 100;
        $("keyframe-y").value = Math.round(key.y * 100) / 100;
        $("keyframe-width").value = Math.round(key.ancho * 100) / 100;
        $("keyframe-height").value = Math.round(key.alto * 100) / 100;
        $("keyframe-rotation").value = Math.round(key.giro * 100) / 100;
        $("keyframe-opacity").value = Math.round(key.opacidad * 100) / 100;
        $("keyframe-color").value = key.color;
        $("keyframe-font-size").value = Math.round(key.tamano * 100) / 100;
        $("keyframe-font-family").value = key.fuente;
        $("keyframe-text").value = key.texto;
        $("keyframe-easing").value = key.interpolacion;
        $("keyframe-text-mode").value = key.texto_modo;
        const bezier = key.bezier || [.25, .1, .25, 1];
        ["bezier-x1", "bezier-y1", "bezier-x2", "bezier-y2"].forEach((id, index) => {
            $(id).value = bezier[index];
        });
        $("bezier-fields").hidden = key.interpolacion !== "bezier";
    }

    function timelineLane(labelText, className = "") {
        const row = document.createElement("div");
        row.className = `timeline-track ${className}`.trim();
        const label = document.createElement("div");
        label.className = "timeline-track-label";
        label.title = labelText;
        const labelName = document.createElement("span");
        labelName.className = "timeline-track-name";
        labelName.textContent = labelText;
        label.append(labelName);
        const lane = document.createElement("div");
        lane.className = "timeline-track-lane";
        lane.style.width = `${Math.max(540, slides[activeSlideIndex].duracion_frames / FPS * timelinePixelsPerSecond)}px`;
        lane.addEventListener("pointerdown", event => {
            if (event.target !== lane) return;
            const bounds = lane.getBoundingClientRect();
            setTimelineFrame((event.clientX - bounds.left) / timelinePixelsPerSecond * FPS);
        });
        row.append(label, lane);
        return {row, label, lane};
    }

    function makeKeyframeButton(obj, key, property = "") {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "timeline-keyframe";
        button.style.left = `${key.frame / FPS * timelinePixelsPerSecond}px`;
        button.title = `${property ? `${property}: ` : ""}fotograma ${key.frame}`;
        button.setAttribute("aria-label", button.title);
        const id = keyframeId(obj.id, key.frame);
        button.classList.toggle("selected", selectedKeyframes.has(id));
        button.addEventListener("pointerdown", event => {
            event.preventDefault();
            event.stopPropagation();
            if (event.ctrlKey || event.metaKey || event.shiftKey) {
                if (selectedKeyframes.has(id)) selectedKeyframes.delete(id);
                else selectedKeyframes.add(id);
            } else if (!selectedKeyframes.has(id)) {
                selectedKeyframes.clear();
                selectedKeyframes.add(id);
            }
            setTimelineFrame(key.frame, false);
            const initial = selectedKeyframeData().map(item => ({
                obj: item.obj,
                key: item.key,
                frame: item.key.frame,
                id: keyframeId(item.obj.id, item.key.frame),
            }));
            const startX = event.clientX;
            const move = moveEvent => {
                const requestedDelta = Math.round((moveEvent.clientX - startX) / timelinePixelsPerSecond * FPS);
                const minimum = Math.min(...initial.map(item => item.frame));
                const maximum = Math.max(...initial.map(item => item.frame));
                const delta = clamp(requestedDelta, -minimum, MAX_SLIDE_FRAMES - maximum);
                const movingByObject = new Map();
                initial.forEach(item => {
                    if (!movingByObject.has(item.obj.id)) movingByObject.set(item.obj.id, []);
                    movingByObject.get(item.obj.id).push(item);
                });
                const collision = [...movingByObject.values()].some(group => {
                    const movingKeys = new Set(group.map(item => item.key));
                    const occupied = new Set(group[0].obj.fotogramas.filter(item => !movingKeys.has(item)).map(item => item.frame));
                    return group.some(item => occupied.has(item.frame + delta));
                });
                if (collision) return;
                selectedKeyframes.clear();
                initial.forEach(item => {
                    item.key.frame = item.frame + delta;
                    selectedKeyframes.add(keyframeId(item.obj.id, item.key.frame));
                });
                const target = clamp(key.frame, 0, MAX_SLIDE_FRAMES);
                extendDurationTo(target);
                setTimelineFrame(target, false);
                renderTimeline();
            };
            const up = () => {
                window.removeEventListener("pointermove", move);
                window.removeEventListener("pointerup", up);
                objects.forEach(item => item.fotogramas.sort((left, right) => left.frame - right.frame));
                sync();
                commitHistory();
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", up, {once: true});
            renderTimeline();
        });
        return button;
    }

    function renderTimeline() {
        if ($("timeline-panel").hidden) return;
        const slide = slides[activeSlideIndex];
        const expandedPropertyCount = objects.reduce((total, obj) => total + (
            expandedObjects.has(obj.id)
                ? animatedProperties.filter(property => obj.tipo !== "imagen" || !["color", "tamano", "texto"].includes(property)).length
                : 0
        ), 0);
        const panel = $("timeline-panel");
        panel.style.height = `${Math.min(268, Math.max(190, 158 + Math.min(objects.length + expandedPropertyCount, 4) * 22))}px`;
        panel.style.setProperty("--timeline-second", `${timelinePixelsPerSecond}px`);
        panel.style.setProperty("--timeline-half-second", `${timelinePixelsPerSecond / 2}px`);
        const durationWidth = Math.max(540, slide.duracion_frames / FPS * timelinePixelsPerSecond);
        const ruler = $("timeline-ruler");
        ruler.replaceChildren();
        ruler.style.width = `${150 + durationWidth}px`;
        const corner = document.createElement("span");
        corner.className = "timeline-ruler-corner";
        corner.textContent = "Pistas";
        ruler.append(corner);
        const seconds = Math.ceil(slide.duracion_frames / FPS);
        const tickEvery = timelinePixelsPerSecond < 70 ? 2 : 1;
        for (let second = 0; second <= seconds; second += tickEvery) {
            const tick = document.createElement("span");
            tick.className = "timeline-tick";
            tick.style.left = `${150 + second * timelinePixelsPerSecond}px`;
            tick.textContent = second < 60
                ? `${second}s`
                : `${Math.floor(second / 60)}:${String(second % 60).padStart(2, "0")}`;
            ruler.append(tick);
        }
        ruler.onclick = event => {
            const bounds = ruler.getBoundingClientRect();
            setTimelineFrame((event.clientX - bounds.left - 150) / timelinePixelsPerSecond * FPS);
        };
        const tracks = $("timeline-tracks");
        tracks.replaceChildren();
        const markerRow = timelineLane("Pausas por clic", "marker-track");
        for (const marker of slide.marcadores) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "timeline-marker";
            button.style.left = `${marker.frame / FPS * timelinePixelsPerSecond}px`;
            const target = objects.find(obj => obj.id === marker.objeto_id);
            button.textContent = "C";
            button.title = `Pausa en F${marker.frame}; continúa al pulsar ${target ? objectLabel(target) : "el objeto"}. Doble clic para eliminar.`;
            button.addEventListener("click", event => {
                event.stopPropagation();
                setTimelineFrame(marker.frame);
                select(marker.objeto_id);
            });
            button.addEventListener("dblclick", event => {
                event.stopPropagation();
                slide.marcadores = slide.marcadores.filter(item => item.id !== marker.id);
                renderTimeline();
                sync();
            });
            markerRow.lane.append(button);
        }
        tracks.append(markerRow.row);
        for (const obj of objects) {
            const main = timelineLane(objectLabel(obj));
            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "track-expand";
            toggle.textContent = expandedObjects.has(obj.id) ? "▾" : "▸";
            toggle.setAttribute("aria-label", `${expandedObjects.has(obj.id) ? "Contraer" : "Expandir"} propiedades`);
            toggle.addEventListener("click", () => {
                if (expandedObjects.has(obj.id)) expandedObjects.delete(obj.id);
                else expandedObjects.add(obj.id);
                renderTimeline();
            });
            main.label.prepend(toggle);
            main.label.addEventListener("click", () => select(obj.id));
            obj.fotogramas.forEach(key => main.lane.append(makeKeyframeButton(obj, key)));
            tracks.append(main.row);
            if (expandedObjects.has(obj.id)) {
                for (const property of animatedProperties) {
                    if (obj.tipo === "imagen" && ["color", "tamano", "texto"].includes(property)) continue;
                    const sub = timelineLane(`↳ ${property}`, "property-track");
                    obj.fotogramas.forEach(key => sub.lane.append(makeKeyframeButton(obj, key, property)));
                    tracks.append(sub.row);
                }
            }
        }
        $("loop-start").max = slide.duracion_frames;
        $("loop-end").max = slide.duracion_frames;
        $("loop-start").value = loopStart;
        $("loop-end").value = loopEnd;
        updateKeyframeInspector();
        updateTimelinePosition();
    }

    function updateSelectedKeyframes(field, rawValue) {
        const items = selectedKeyframeData();
        if (!items.length) return;
        if (field === "frame") {
            const firstFrame = items[0].key.frame;
            const desired = clamp(Math.round(Number(rawValue)), 0, MAX_SLIDE_FRAMES);
            const delta = desired - firstFrame;
            const movingKeys = new Set(items.map(item => item.key));
            const collision = items.some(({obj, key}) => obj.fotogramas.some(other =>
                !movingKeys.has(other) && other.frame === key.frame + delta
            ));
            if (collision || items.some(item => item.key.frame + delta < 0 || item.key.frame + delta > MAX_SLIDE_FRAMES)) {
                updateKeyframeInspector();
                return;
            }
            selectedKeyframes.clear();
            items.forEach(({obj, key}) => {
                key.frame += delta;
                selectedKeyframes.add(keyframeId(obj.id, key.frame));
                obj.fotogramas.sort((left, right) => left.frame - right.frame);
            });
            extendDurationTo(Math.max(...items.map(item => item.key.frame)));
            setTimelineFrame(desired, false);
        } else {
            const numericLimits = {
                x: [MIN_OBJECT_POSITION, MAX_OBJECT_POSITION], y: [MIN_OBJECT_POSITION, MAX_OBJECT_POSITION],
                ancho: [MIN_OBJECT_WIDTH, MAX_OBJECT_WIDTH], alto: [MIN_OBJECT_HEIGHT, MAX_OBJECT_HEIGHT],
                giro: [-360, 360], opacidad: [0, 1], tamano: [8, 120],
            };
            items.forEach(({key}) => {
                if (numericLimits[field]) key[field] = clamp(Number(rawValue), ...numericLimits[field]);
                else key[field] = rawValue;
                if (field === "interpolacion") {
                    if (rawValue === "bezier") key.bezier ||= [.25, .1, .25, 1];
                    else delete key.bezier;
                }
            });
        }
        renderTimeline();
        setTimelineFrame(currentFrame, false);
        renderMotionPath();
        sync();
    }

    function updateBezier(index, rawValue) {
        for (const {key} of selectedKeyframeData()) {
            key.interpolacion = "bezier";
            key.bezier ||= [.25, .1, .25, 1];
            key.bezier[index] = clamp(Number(rawValue), index % 2 === 0 ? 0 : -2, index % 2 === 0 ? 1 : 2);
        }
        renderTimeline();
        sync();
    }

    function addClickMarker() {
        const obj = current();
        if (!obj) {
            $("animation-status").textContent = "Selecciona el objeto que reanudará la reproducción.";
            return;
        }
        const slide = slides[activeSlideIndex];
        const existing = slide.marcadores.find(marker => marker.frame === currentFrame && marker.objeto_id === obj.id);
        if (!existing) slide.marcadores.push({id: crypto.randomUUID(), frame: currentFrame, objeto_id: obj.id});
        slide.marcadores.sort((left, right) => left.frame - right.frame);
        renderTimeline();
        sync();
    }

    function pauseTimeline() {
        timelineRunning = false;
        cancelAnimationFrame(playbackRequest);
        playbackRequest = null;
        syncAudioPlayers(currentFrame, false);
        $("timeline-play").innerHTML = '<i class="fa-solid fa-play" aria-hidden="true"></i>';
        $("timeline-play").setAttribute("aria-label", "Reproducir");
        $("timeline-play").title = "Reproducir";
        if (playing) updatePresentationPlaybackUI();
    }

    function playbackTick(now) {
        if (!timelineRunning) return;
        const slide = slides[activeSlideIndex];
        const previousFrame = currentFrame;
        let nextFrame = playbackStartFrame + (now - playbackStartedAt) / 1000 * FPS;
        if (playing) {
            const marker = slide.marcadores.find(item =>
                !consumedMarkers.has(item.id) && item.frame >= previousFrame && item.frame <= nextFrame
            );
            if (marker) {
                consumedMarkers.add(marker.id);
                waitingMarker = marker;
                setTimelineFrame(marker.frame, false);
                pauseTimeline();
                node(marker.objeto_id)?.classList.add("click-wait-target");
                document.body.classList.add("presentation-awaiting-click");
                updatePresentationPlaybackUI();
                revealPresentationChrome(true);
                return;
            }
        }
        const end = loopEnabled && !playing ? loopEnd : slide.duracion_frames;
        if (nextFrame >= end) {
            if (loopEnabled && !playing) {
                nextFrame = loopStart;
                setTimelineFrame(nextFrame, false);
                playbackStartFrame = nextFrame;
                playbackStartedAt = now;
                syncAudioPlayers(nextFrame, true);
                playbackRequest = requestAnimationFrame(playbackTick);
                return;
            }
            setTimelineFrame(end, false);
            pauseTimeline();
            if (playing) showPresentationSlide(activeSlideIndex + 1);
            return;
        }
        setTimelineFrame(nextFrame, false);
        syncAudioPlayers(currentFrame, true);
        playbackRequest = requestAnimationFrame(playbackTick);
    }

    function startTimeline() {
        if (timelineRunning) {
            pauseTimeline();
            return;
        }
        const slide = slides[activeSlideIndex];
        const end = loopEnabled && !playing ? loopEnd : slide.duracion_frames;
        if (currentFrame >= end) setTimelineFrame(loopEnabled && !playing ? loopStart : 0, false);
        waitingMarker = null;
        playbackStartFrame = currentFrame;
        playbackStartedAt = performance.now();
        timelineRunning = true;
        $("timeline-play").innerHTML = '<i class="fa-solid fa-pause" aria-hidden="true"></i>';
        $("timeline-play").setAttribute("aria-label", "Pausar");
        $("timeline-play").title = "Pausar";
        if (playing) updatePresentationPlaybackUI();
        syncAudioPlayers(currentFrame, true);
        playbackRequest = requestAnimationFrame(playbackTick);
    }

    function resumeAfterMarker() {
        if (!waitingMarker) return;
        node(waitingMarker.objeto_id)?.classList.remove("click-wait-target");
        waitingMarker = null;
        document.body.classList.remove("presentation-awaiting-click");
        startTimeline();
        revealPresentationChrome();
    }

    function presetFrames(obj, preset, startFrame) {
        const pose = keyframeSnapshot(obj, startFrame);
        const endFrame = clamp(startFrame + 21, 0, MAX_SLIDE_FRAMES);
        const middleFrame = clamp(startFrame + 10, 0, MAX_SLIDE_FRAMES);
        const clone = (frame, changes = {}, easing = "suave") => ({
            ...pose, frame, ...changes, interpolacion: easing,
        });
        if (preset === "aparecer") return [clone(startFrame, {opacidad: 0}), clone(endFrame, {opacidad: pose.opacidad})];
        if (preset === "subir") return [clone(startFrame, {y: pose.y + 40, opacidad: 0}), clone(endFrame)];
        if (preset === "zoom") return [clone(startFrame, {ancho: Math.max(60, pose.ancho * .65), alto: Math.max(30, pose.alto * .65), opacidad: 0}), clone(endFrame)];
        if (preset === "girar") return [clone(startFrame, {giro: clamp(pose.giro - 90, -360, 360), opacidad: 0}), clone(endFrame)];
        if (preset === "rebote") return [clone(startFrame, {y: pose.y - 50}, "rebote"), clone(endFrame)];
        if (preset === "pulso") return [clone(startFrame), clone(middleFrame, {ancho: pose.ancho * 1.12, alto: pose.alto * 1.12}), clone(endFrame)];
        if (preset === "desaparecer") return [clone(startFrame), clone(endFrame, {opacidad: 0})];
        if (preset === "salir-arriba") return [clone(startFrame), clone(endFrame, {y: pose.y - 80, opacidad: 0})];
        return [];
    }

    function mergePreset(obj, frames, targetSlide = slides[activeSlideIndex]) {
        const incomingFrames = new Set(frames.map(key => key.frame));
        obj.fotogramas = obj.fotogramas.filter(key => !incomingFrames.has(key.frame)).concat(frames);
        obj.fotogramas.sort((left, right) => left.frame - right.frame);
        const lastFrame = obj.fotogramas.at(-1).frame;
        targetSlide.duracion_frames = clamp(Math.max(targetSlide.duracion_frames, lastFrame), 30, MAX_SLIDE_FRAMES);
        if (targetSlide === slides[activeSlideIndex]) extendDurationTo(lastFrame);
    }

    function applyPresetForScope(preset) {
        const scope = $("animation-scope").value;
        let targets = [];
        if (scope === "objeto") {
            if (!current()) {
                $("animation-status").textContent = "Selecciona un objeto o cambia el alcance.";
                return;
            }
            targets = [{slide: slides[activeSlideIndex], obj: current()}];
        } else if (scope === "diapositiva") {
            targets = objects.map(obj => ({slide: slides[activeSlideIndex], obj}));
        } else {
            targets = slides.flatMap(slide => slide.objetos.map(obj => ({slide, obj})));
        }
        for (const target of targets) {
            const frame = target.slide === slides[activeSlideIndex] ? currentFrame : 0;
            const oldObjects = objects;
            if (target.slide !== slides[activeSlideIndex]) objects = target.slide.objetos;
            if (preset === "ninguna") {
                target.obj.fotogramas = [keyframeSnapshot(target.obj, 0)];
            } else {
                mergePreset(target.obj, presetFrames(target.obj, preset, frame), target.slide);
            }
            objects = oldObjects;
            target.obj.animacion = preset;
        }
        $("animation-status").textContent = `Preajuste aplicado a ${targets.length} objeto${targets.length === 1 ? "" : "s"}; sus fotogramas siguen siendo editables.`;
        updateAnimationPanel();
        setTimelineFrame(currentFrame, false);
        renderTimeline();
        renderMotionPath();
        renderSlideList();
        sync();
    }

    let animationTemplates = [];

    function renderAnimationTemplates() {
        const list = $("animation-template-list");
        list.replaceChildren();
        if (!animationTemplates.length) {
            list.textContent = "Todavía no hay plantillas privadas.";
            return;
        }
        for (const template of animationTemplates) {
            const wrapper = document.createElement("span");
            wrapper.className = "template-item";
            const apply = document.createElement("button");
            apply.type = "button";
            apply.textContent = template.name;
            apply.title = "Aplicar al objeto seleccionado";
            apply.addEventListener("click", () => {
                const obj = current();
                if (!obj) {
                    $("animation-template-status").textContent = "Selecciona un objeto antes de aplicar la plantilla.";
                    return;
                }
                const source = template.data.fotogramas;
                const offset = currentFrame - source[0].frame;
                const frames = source.map(key => ({...key, frame: clamp(key.frame + offset, 0, MAX_SLIDE_FRAMES)}));
                mergePreset(obj, frames);
                renderTimeline();
                renderMotionPath();
                sync();
                $("animation-template-status").textContent = `Plantilla “${template.name}” aplicada.`;
            });
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "delete-template";
            remove.textContent = "×";
            remove.setAttribute("aria-label", `Eliminar plantilla ${template.name}`);
            remove.addEventListener("click", () => deleteAnimationTemplate(template));
            wrapper.append(apply, remove);
            list.append(wrapper);
        }
    }

    async function loadAnimationTemplates() {
        try {
            const response = await fetch($("timeline-panel").dataset.templatesUrl, {credentials: "same-origin"});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "No se pudieron cargar las plantillas.");
            animationTemplates = result.templates;
            renderAnimationTemplates();
        } catch (error) {
            $("animation-template-status").textContent = error.message;
        }
    }

    async function saveAnimationTemplate() {
        const obj = current();
        const name = $("animation-template-name").value.trim();
        if (!obj || !name) {
            $("animation-template-status").textContent = "Selecciona un objeto y escribe un nombre.";
            return;
        }
        const chosen = selectedKeyframeData().filter(item => item.obj.id === obj.id).map(item => item.key);
        const source = chosen.length ? chosen.sort((a, b) => a.frame - b.frame) : obj.fotogramas;
        const first = source[0].frame;
        const data = {fotogramas: source.map(key => ({...key, frame: key.frame - first}))};
        const body = new FormData();
        body.append("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
        body.append("nombre", name);
        body.append("datos", JSON.stringify(data));
        try {
            const response = await fetch($("timeline-panel").dataset.saveTemplateUrl, {method: "POST", body, credentials: "same-origin"});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "No se pudo guardar la plantilla.");
            const index = animationTemplates.findIndex(item => item.id === result.template.id);
            if (index >= 0) animationTemplates[index] = result.template;
            else animationTemplates.push(result.template);
            renderAnimationTemplates();
            $("animation-template-status").textContent = "Plantilla privada guardada.";
        } catch (error) {
            $("animation-template-status").textContent = error.message;
        }
    }

    async function deleteAnimationTemplate(template) {
        const body = new FormData();
        body.append("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
        const url = $("timeline-panel").dataset.deleteTemplatePattern.replace("999999", String(template.id));
        try {
            const response = await fetch(url, {method: "POST", body, credentials: "same-origin"});
            if (!response.ok) throw new Error("No se pudo eliminar la plantilla.");
            animationTemplates = animationTemplates.filter(item => item.id !== template.id);
            renderAnimationTemplates();
            $("animation-template-status").textContent = "Plantilla eliminada.";
        } catch (error) {
            $("animation-template-status").textContent = error.message;
        }
    }

    $("upload-image-trigger").addEventListener("click", () => $("image-file-input").click());
    $("image-drop-zone").addEventListener("click", () => $("image-file-input").click());
    $("image-file-input").addEventListener("change", event => {
        uploadImages([...event.target.files]);
        event.target.value = "";
    });
    $("remove-background-tolerance").addEventListener("input", event => {
        $("remove-background-tolerance-value").value = event.target.value;
    });
    $("confirm-remove-background").addEventListener("click", removeSelectedImageBackground);
    $("cancel-remove-background").addEventListener("click", closeRemoveBackgroundDialog);
    $("close-remove-background").addEventListener("click", closeRemoveBackgroundDialog);
    $("remove-background-dialog").addEventListener("click", event => {
        if (event.target === event.currentTarget) closeRemoveBackgroundDialog();
    });
    $("upload-audio-trigger").addEventListener("click", () => $("audio-file-input").click());
    $("audio-file-input").addEventListener("change", event => {
        uploadAudios([...event.target.files]);
        event.target.value = "";
    });
    $("clear-audio").addEventListener("click", removeSelectedAudioTrack);
    $("apply-audio-all").addEventListener("click", applySelectedAudioToAllSlides);
    $("remove-audio-all").addEventListener("click", removeSelectedAudioFromAllSlides);
    $("selected-audio-preview").addEventListener("play", event => {
        document.querySelectorAll(".audio-item audio").forEach(audio => {
            if (audio !== event.currentTarget) audio.pause();
        });
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
        $("slide-duration").value = String(clamp(Number($("slide-duration").value) || 10, 1, 3600));
        slides[activeSlideIndex].duracion_frames = Math.round(Number($("slide-duration").value) * FPS);
        loopEnd = Math.min(loopEnd, slides[activeSlideIndex].duracion_frames);
        currentFrame = Math.min(currentFrame, slides[activeSlideIndex].duracion_frames);
        renderSlideList();
        renderTimeline();
        setTimelineFrame(currentFrame);
        sync();
    });

    function setTimelineVisible(visible) {
        document.body.classList.toggle("timeline-open", visible);
        $("timeline-panel").hidden = !visible;
        $("toggle-timeline").setAttribute("aria-expanded", String(visible));
        $("toggle-timeline").setAttribute("aria-label", visible ? "Cerrar línea de tiempo" : "Abrir línea de tiempo");
        if (visible) {
            renderTimeline();
            renderAudioMixer();
            renderMotionPath();
            loadAnimationTemplates();
        } else {
            renderMotionPath();
        }
    }

    $("toggle-timeline").addEventListener("click", () => setTimelineVisible($("timeline-panel").hidden));
    $("close-timeline").addEventListener("click", () => setTimelineVisible(false));
    $("audio-mixer-panel").addEventListener("toggle", event => {
        if (event.currentTarget.open) renderAudioMixer();
    });
    $("animation-template-panel").addEventListener("toggle", event => {
        if (event.currentTarget.open) loadAnimationTemplates();
    });
    $("timeline-start").addEventListener("click", () => {
        pauseTimeline();
        setTimelineFrame(loopEnabled ? loopStart : 0);
    });
    $("timeline-play").addEventListener("click", startTimeline);
    $("timeline-stop").addEventListener("click", () => {
        pauseTimeline();
        setTimelineFrame(0);
    });
    $("timeline-add-keyframe").addEventListener("click", () => addKeyframeForObject(current()));
    $("timeline-add-marker").addEventListener("click", addClickMarker);
    $("timeline-loop").addEventListener("click", () => {
        loopEnabled = !loopEnabled;
        $("timeline-loop").setAttribute("aria-pressed", String(loopEnabled));
    });
    $("timeline-zoom").addEventListener("input", event => {
        timelinePixelsPerSecond = Number(event.target.value);
        renderTimeline();
    });
    $("loop-start").addEventListener("change", event => {
        loopStart = clamp(Math.round(Number(event.target.value)), 0, Math.max(0, loopEnd - 1));
        renderTimeline();
    });
    $("loop-end").addEventListener("change", event => {
        loopEnd = clamp(Math.round(Number(event.target.value)), loopStart + 1, slides[activeSlideIndex].duracion_frames);
        renderTimeline();
    });
    const keyframeFieldMap = {
        "keyframe-frame": "frame", "keyframe-x": "x", "keyframe-y": "y",
        "keyframe-width": "ancho", "keyframe-height": "alto", "keyframe-rotation": "giro",
        "keyframe-opacity": "opacidad", "keyframe-color": "color", "keyframe-font-size": "tamano",
        "keyframe-font-family": "fuente", "keyframe-text": "texto",
        "keyframe-easing": "interpolacion", "keyframe-text-mode": "texto_modo",
    };
    for (const [id, field] of Object.entries(keyframeFieldMap)) {
        $(id).addEventListener("change", event => updateSelectedKeyframes(field, event.target.value));
    }
    ["bezier-x1", "bezier-y1", "bezier-x2", "bezier-y2"].forEach((id, index) => {
        $(id).addEventListener("change", event => updateBezier(index, event.target.value));
    });
    $("delete-keyframes").addEventListener("click", () => {
        const chosen = selectedKeyframeData();
        const chosenKeys = new Set(chosen.map(item => item.key));
        for (const obj of new Set(chosen.map(item => item.obj))) {
            obj.fotogramas = obj.fotogramas.filter(key => !chosenKeys.has(key));
            if (!obj.fotogramas.length) obj.fotogramas = [keyframeSnapshot(obj, 0)];
        }
        selectedKeyframes.clear();
        renderTimeline();
        renderMotionPath();
        setTimelineFrame(currentFrame, false);
        sync();
    });
    $("save-animation-template").addEventListener("click", saveAnimationTemplate);

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
        setTimelineFrame(0, false);
        startTimeline();
        $("animation-status").textContent = "Reproduciendo la línea de tiempo de la diapositiva.";
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

    function updatePresentationProgress() {
        if (!playing) return;
        const totalFrames = slides.reduce((total, slide) => total + slide.duracion_frames, 0);
        const previousFrames = slides.slice(0, activeSlideIndex)
            .reduce((total, slide) => total + slide.duracion_frames, 0);
        const progress = totalFrames ? clamp((previousFrames + currentFrame) / totalFrames, 0, 1) : 0;
        $("presentation-progress-bar").style.transform = `scaleX(${progress})`;
        $("presentation-progress").setAttribute("aria-valuenow", String(Math.round(progress * 100)));
    }

    function updatePresentationNavigation(index = activeSlideIndex) {
        const previous = $("previous-slide");
        const next = $("next-slide");
        const lastSlide = index === slides.length - 1;
        previous.disabled = index === 0;
        next.setAttribute("aria-label", lastSlide ? "Finalizar presentación" : "Diapositiva siguiente");
        next.querySelector("span").textContent = lastSlide ? "Finalizar" : "Siguiente";
        next.querySelector("i").className = lastSlide ? "fa-solid fa-flag-checkered" : "fa-solid fa-arrow-right";
        $("presentation-count").textContent = `${index + 1} / ${slides.length}`;
    }

    function updatePresentationPlaybackUI() {
        if (!playing) return;
        const toggle = $("toggle-presentation-play");
        const state = $("presentation-playback-state");
        if (waitingMarker) {
            toggle.innerHTML = '<i class="fa-solid fa-hand-pointer" aria-hidden="true"></i>';
            toggle.setAttribute("aria-label", "Esperando interacción con la diapositiva");
            state.innerHTML = '<i class="fa-solid fa-hand-pointer" aria-hidden="true"></i> Interacción';
            $("presentation-hint").textContent = "Haz clic en el elemento resaltado para continuar";
        } else if (timelineRunning) {
            toggle.innerHTML = '<i class="fa-solid fa-pause" aria-hidden="true"></i>';
            toggle.setAttribute("aria-label", "Pausar presentación");
            state.innerHTML = '<i class="fa-solid fa-circle-play" aria-hidden="true"></i> Reproduciendo';
            $("presentation-hint").textContent = "Usa ← y → para navegar · Espacio para pausar · Esc para salir";
        } else {
            toggle.innerHTML = '<i class="fa-solid fa-play" aria-hidden="true"></i>';
            toggle.setAttribute("aria-label", "Reanudar presentación");
            state.innerHTML = '<i class="fa-solid fa-circle-pause" aria-hidden="true"></i> En pausa';
            $("presentation-hint").textContent = "Presentación en pausa · Pulsa espacio para continuar";
        }
    }

    function revealPresentationChrome(keepVisible = false) {
        if (!playing) return;
        clearTimeout(presentationChromeTimer);
        presentationChromeTimer = null;
        document.body.classList.remove("presentation-ui-hidden");
        if (keepVisible || waitingMarker) return;
        presentationChromeTimer = setTimeout(() => {
            if (!playing || waitingMarker) return;
            document.body.classList.add("presentation-ui-hidden");
        }, 2800);
    }

    function togglePresentationPlayback() {
        if (!playing) return;
        if (waitingMarker) {
            node(waitingMarker.objeto_id)?.focus({preventScroll: true});
            revealPresentationChrome(true);
            return;
        }
        if (timelineRunning) pauseTimeline();
        else startTimeline();
        revealPresentationChrome();
    }

    function enterPresentation(index = activeSlideIndex) {
        if (playing) return;
        document.querySelectorAll(".audio-item audio, #selected-audio-preview").forEach(audio => audio.pause());
        playing = true;
        $("presentation-project-name").textContent = form.elements.nombre.value || "Presentación";
        document.body.classList.add("presenting");
        document.body.classList.remove("presentation-ui-hidden", "presentation-awaiting-click");
        $("presentation-chrome").hidden = false;
        showPresentationSlide(index);
        stage.focus({preventScroll: true});
        revealPresentationChrome();
    }

    function showPresentationSlide(index) {
        if (index < 0) return;
        if (index >= slides.length) {
            exitPresentation();
            return;
        }
        pauseTimeline();
        stopAudioPlayers();
        if (waitingMarker) node(waitingMarker.objeto_id)?.classList.remove("click-wait-target");
        document.body.classList.remove("presentation-awaiting-click");
        showSlide(index);
        updatePresentationNavigation(index);
        consumedMarkers = new Set();
        waitingMarker = null;
        setTimelineFrame(0, false);
        startTimeline();
        revealPresentationChrome();
    }

    function exitPresentation() {
        clearTimeout(presentationChromeTimer);
        presentationChromeTimer = null;
        pauseTimeline();
        stopAudioPlayers();
        if (waitingMarker) node(waitingMarker.objeto_id)?.classList.remove("click-wait-target");
        waitingMarker = null;
        playing = false;
        document.body.classList.remove("presenting", "presentation-ui-hidden", "presentation-awaiting-click");
        $("presentation-chrome").hidden = true;
        setTimelineFrame(0, false);
        $("present-button").focus({preventScroll: true});
    }

    function setTextColor(color) {
        const obj = current();
        if (!obj || obj.tipo === "imagen") return;
        obj.color = color;
        const editedFrame = $("timeline-panel").hidden ? 0 : currentFrame;
        const keyframe = obj.fotogramas.find(frame => frame.frame === editedFrame)
            || addKeyframeForObject(obj, editedFrame, false);
        if (keyframe) keyframe.color = color;
        $("font-color").value = color;
        mountStyle(obj);
        sync();
    }

    $("text-tool").addEventListener("click", addText);
    $("delete-text").addEventListener("click", remove);
    $("edit-text").addEventListener("click", edit);
    $("images-tool").addEventListener("click", event => showGallery("imagenes", event.currentTarget));
    $("ai-tool").addEventListener("click", event => showGallery("ia", event.currentTarget));
    document.querySelectorAll("details.ai-card").forEach(card => {
        card.addEventListener("toggle", () => {
            if (!card.open) return;
            document.querySelectorAll("details.ai-card").forEach(other => {
                if (other !== card) other.open = false;
            });
        });
    });
    $("elements-tool").addEventListener("click", event => showGallery("elementos", event.currentTarget));
    $("background-tool").addEventListener("click", event => showGallery("fondos", event.currentTarget));
    $("audio-tool").addEventListener("click", event => showGallery("audios", event.currentTarget));
    $("animation-tool").addEventListener("click", event => showGallery("animaciones", event.currentTarget));
    $("close-asset-panel").addEventListener("click", closeAssetPanel);
    $("ai-generate-presentation").addEventListener("click", generateAIPresentation);
    $("ai-apply-presentation").addEventListener("click", applyAIPresentation);
    $("ai-convert-document").addEventListener("click", convertAIDocument);
    $("ai-cancel-document").addEventListener("click", () => {
        if (activeDocumentJob) requestDocumentAction(activeDocumentJob.cancel_url);
    });
    $("ai-retry-document").addEventListener("click", () => {
        if (activeDocumentJob) requestDocumentAction(activeDocumentJob.retry_url);
    });
    $("ai-apply-document").addEventListener("click", applyAIDocument);
    $("ai-generate-text").addEventListener("click", generateAIText);
    $("ai-apply-text").addEventListener("click", applyAIText);
    $("ai-generate-image").addEventListener("click", generateAIImage);
    $("ai-apply-image").addEventListener("click", applyAIImage);
    $("ai-slide-notes").addEventListener("input", event => {
        slides[activeSlideIndex].notas = event.target.value;
        sync();
    });
    document.querySelectorAll(".asset-choice").forEach(button => {
        button.addEventListener("click", () => {
            const path = button.dataset.assetPath;
            if (button.closest(".asset-gallery").dataset.gallery === "fondos") {
                setBackground(path);
            } else {
                addElement(path);
            }
            closeAssetPanelOnCompactScreen();
        });
    });
    $("clear-background").addEventListener("click", () => {
        setBackground("");
        closeAssetPanelOnCompactScreen();
    });
    document.querySelectorAll(".animation-choice").forEach(button => {
        button.addEventListener("click", () => {
            applyPresetForScope(button.dataset.keyframePreset);
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
    $("previous-slide").addEventListener("click", () => {
        if (activeSlideIndex > 0) showPresentationSlide(activeSlideIndex - 1);
    });
    $("next-slide").addEventListener("click", () => showPresentationSlide(activeSlideIndex + 1));
    $("toggle-presentation-play").addEventListener("click", togglePresentationPlayback);
    $("presentation-chrome").addEventListener("focusin", event => {
        revealPresentationChrome(event.target instanceof HTMLElement && event.target.matches(":focus-visible"));
    });
    $("presentation-chrome").addEventListener("focusout", () => revealPresentationChrome());
    window.addEventListener("pointermove", () => {
        if (playing) revealPresentationChrome();
    });
    window.addEventListener("pointerdown", () => {
        if (playing) revealPresentationChrome();
    });
    window.addEventListener("keydown", event => {
        if (aiRequestPending) {
            event.preventDefault();
            return;
        }
        if (playing) {
            revealPresentationChrome();
            if (event.key === "Escape") {
                event.preventDefault();
                exitPresentation();
            } else if (event.key === "ArrowRight") {
                event.preventDefault();
                showPresentationSlide(activeSlideIndex + 1);
            } else if (event.key === "ArrowLeft") {
                event.preventDefault();
                if (activeSlideIndex > 0) showPresentationSlide(activeSlideIndex - 1);
            } else if (event.key === " " && !(event.target instanceof HTMLButtonElement)) {
                event.preventDefault();
                togglePresentationPlayback();
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
        if (playing) return;
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
            const pose = evaluateObject(obj, $("timeline-panel").hidden ? 0 : currentFrame);
            obj.x = pose.x;
            obj.y = pose.y;
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
            const editedFrame = $("timeline-panel").hidden ? 0 : currentFrame;
            const keyframe = obj.fotogramas.find(frame => frame.frame === editedFrame)
                || addKeyframeForObject(obj, editedFrame, false);
            keyframe.x = obj.x;
            keyframe.y = obj.y;
            sync();
        }
    });

    for (const [id, key] of [["font-family", "fuente"], ["font-size", "tamano"], ["font-color", "color"], ["text-align", "alineacion"]]) {
        $(id).addEventListener("input", () => {
            const obj = current();
            const input = $(id);
            if (!obj || obj.tipo === "imagen" || !input.checkValidity() || input.value === "") return;
            obj[key] = key === "tamano" ? Number(input.value) : input.value;
            const editedFrame = $("timeline-panel").hidden ? 0 : currentFrame;
            const keyframe = obj.fotogramas.find(frame => frame.frame === editedFrame)
                || addKeyframeForObject(obj, editedFrame, false);
            if (keyframe && ["fuente", "tamano", "color"].includes(key)) keyframe[key] = obj[key];
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
            if (saved && !dirty()) {
                const destination = new URL(link.href, window.location.href);
                if (link.classList.contains("animated-export")) {
                    destination.searchParams.set("resolucion", $("export-resolution").value);
                }
                window.location.assign(destination.href);
            }
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
        const compact = window.matchMedia("(max-width: 760px), (max-height: 600px) and (max-width: 950px)").matches;
        const horizontalInset = playing ? (compact ? 16 : 96) : (compact ? 16 : 48);
        const verticalInset = playing ? (compact ? 130 : 180) : (compact ? 60 : 100);
        scale = Math.min(
            Math.max(100, area.clientWidth - horizontalInset) / 800,
            Math.max(100, area.clientHeight - verticalInset) / 450
        );
        $("stage-viewport").style.width = `${800 * scale}px`;
        $("stage-viewport").style.height = `${450 * scale}px`;
        stage.style.transform = `scale(${scale})`;
        stage.style.setProperty("--resize-handle-size", compact ? `${Math.min(58, Math.max(24, 20 / scale))}px` : "10px");
        stage.style.setProperty("--rotate-handle-size", compact ? `${Math.min(64, Math.max(30, 24 / scale))}px` : "20px");
    }).observe(area);

    $("slide-duration").value = String(Math.round(slides[activeSlideIndex].duracion_frames / 30));
    stage.style.backgroundImage = activeBackground
        ? `url("${assetBase}${encodeURI(activeBackground)}")`
        : "none";
    stage.style.backgroundColor = activeSlideColor;
    updateSlideColorPicker();
    updateSelectedAudio();
    updateAINotes();
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
