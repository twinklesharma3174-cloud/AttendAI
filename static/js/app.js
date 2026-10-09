(function () {
    const $ = (id) => document.getElementById(id);

    // ---------- Student list search ----------
    const search = $("studentSearch");
    if (search) {
        search.addEventListener("input", () => {
            const query = search.value.trim().toLowerCase();
            let visible = 0;
            document.querySelectorAll(".student-row").forEach((row) => {
                const show = (row.dataset.search || "").includes(query);
                row.classList.toggle("hidden", !show);
                if (show) visible += 1;
            });
            const noResults = $("noSearchResults");
            if (noResults) noResults.classList.toggle("hidden", visible !== 0 || query === "");
        });
    }

    // ---------- Live attendance webcam + face overlay + liveness challenge ----------
    const video = $("camera");
    if (video) {
        const panel = $("cameraPanel");
        const overlay = $("overlayCanvas");
        const startButton = $("startCameraBtn");
        const stopButton = $("stopCameraBtn");
        const fullscreenButton = $("fullscreenCameraBtn");
        const cameraCard = $("cameraCard") || video.closest(".camera-card");
        const statusBadge = $("cameraStatus");
        const placeholder = $("cameraPlaceholder");
        const statusBox = $("recognitionStatus");
        const presentCount = $("presentCount");
        const unknownCount = $("unknownCount");
        const log = $("recognitionLog");
        const captureCanvas = $("captureCanvas");
        const subjectSelect = $("attendanceSubject");

        let stream = null;
        let recognitionTimer = null;
        let requestRunning = false;
        let unknownWasVisible = false;
        let clientSessionId = null;
        const loggedStudents = new Set();
        const recognizedStudents = new Set();
        let unknownEvents = 0;

        function createSessionId() {
            if (window.crypto && typeof window.crypto.randomUUID === "function") {
                return window.crypto.randomUUID();
            }
            return "attendai-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
        }

        function setCameraState(active) {
            statusBadge.textContent = active ? "CAMERA ACTIVE" : "CAMERA OFF";
            statusBadge.className = active ? "pill success" : "pill neutral";
            startButton.disabled = active;
            stopButton.disabled = !active;
            placeholder.classList.toggle("hidden", active);
            video.style.display = active ? "block" : "none";
            overlay.style.display = active ? "block" : "none";
            if (fullscreenButton) fullscreenButton.disabled = !cameraCard;
        }

        async function startCamera() {
            try {
                if (!subjectSelect || !subjectSelect.value) {
                    statusBox.textContent = "Create and select a subject before starting attendance.";
                    subjectSelect?.focus();
                    return;
                }
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    throw new Error("Camera access is unavailable. Open AttendAI at http://127.0.0.1:5000.");
                }
                stream = await navigator.mediaDevices.getUserMedia({
                    video: { width: { ideal: 1920 }, height: { ideal: 1080 }, facingMode: "user" },
                    audio: false
                });
                video.srcObject = stream;
                await video.play();
                clientSessionId = createSessionId();
                // Each camera start creates a fresh challenge and a clean on-screen log.
                loggedStudents.clear();
                recognizedStudents.clear();
                unknownEvents = 0;
                unknownWasVisible = false;
                presentCount.textContent = "0";
                unknownCount.textContent = "0";
                log.innerHTML = '<div class="log-empty">No recognition events yet.</div>';
                if (subjectSelect) subjectSelect.disabled = true;
                await fetch("/api/liveness/reset", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content },
                    body: JSON.stringify({ client_id: clientSessionId })
                });
                setCameraState(true);
                statusBox.textContent = "Camera active. Center your face in the frame; follow the instruction shown on the face box.";
                // Give the camera the largest available source resolution.
                requestAnimationFrame(sizeOverlay);
                recognitionTimer = window.setInterval(captureAndRecognize, 700);
            } catch (error) {
                statusBox.textContent = "Camera access failed: " + error.message;
                statusBadge.textContent = "CAMERA ERROR";
                statusBadge.className = "pill danger";
                console.error("AttendAI camera error:", error);
                if (stream) stream.getTracks().forEach((track) => track.stop());
                stream = null;
                if (subjectSelect) subjectSelect.disabled = false;
            }
        }

        function stopCamera() {
            if (recognitionTimer !== null) {
                window.clearInterval(recognitionTimer);
                recognitionTimer = null;
            }
            if (stream) {
                stream.getTracks().forEach((track) => track.stop());
                stream = null;
            }
            video.srcObject = null;
            if (subjectSelect) subjectSelect.disabled = false;
            const ctx = overlay.getContext("2d");
            ctx.clearRect(0, 0, overlay.width, overlay.height);
            setCameraState(false);
            statusBox.textContent = "Camera stopped. Start again to begin a new head-movement challenge.";
            requestRunning = false;
            unknownWasVisible = false;
            clientSessionId = null;
        }

        function sizeOverlay() {
            const rect = panel.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            overlay.width = Math.max(1, Math.round(rect.width * dpr));
            overlay.height = Math.max(1, Math.round(rect.height * dpr));
            overlay.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
            return { width: rect.width, height: rect.height };
        }

        function clamp(value, min, max) {
            return Math.max(min, Math.min(value, max));
        }

        function wrapCanvasText(ctx, text, maxWidth, maxLines = 2) {
            const words = String(text || "").trim().split(/\s+/).filter(Boolean);
            const lines = [];
            let current = "";
            for (const word of words) {
                const candidate = current ? current + " " + word : word;
                if (current && ctx.measureText(candidate).width > maxWidth) {
                    lines.push(current);
                    current = word;
                } else {
                    current = candidate;
                }
            }
            if (current) lines.push(current);
            if (lines.length > maxLines) {
                const clipped = lines.slice(0, maxLines);
                let last = clipped[maxLines - 1];
                while (last.length && ctx.measureText(last + "…").width > maxWidth) {
                    last = last.slice(0, -1);
                }
                clipped[maxLines - 1] = last + "…";
                return clipped;
            }
            return lines;
        }

        function drawBoxes(results) {
            if (!video.videoWidth || !video.videoHeight) return;
            const dimensions = sizeOverlay();
            const ctx = overlay.getContext("2d");
            ctx.clearRect(0, 0, dimensions.width, dimensions.height);
            const scale = Math.max(dimensions.width / video.videoWidth, dimensions.height / video.videoHeight);
            const offsetX = (dimensions.width - video.videoWidth * scale) / 2;
            const offsetY = (dimensions.height - video.videoHeight * scale) / 2;

            results.forEach((result) => {
                if (!Array.isArray(result.bbox) || result.bbox.length < 4) return;
                const [x, y, w, h] = result.bbox;
                const left = x * scale + offsetX;
                const top = y * scale + offsetY;
                const width = w * scale;
                const height = h * scale;
                const known = result.name !== "Unknown" && Boolean(result.student_id);
                const verified = known && result.liveness === "verified";
                const stroke = !known ? "#ef4444" : (verified ? "#25c878" : "#f7b955");

                // Scanner corners create a more precise, polished face-tracking graphic.
                ctx.save();
                ctx.strokeStyle = stroke;
                ctx.lineWidth = Math.max(2.5, Math.min(4, dimensions.width / 400));
                ctx.shadowColor = stroke;
                ctx.shadowBlur = 8;
                const corner = Math.max(14, Math.min(26, width * 0.2, height * 0.12));
                ctx.beginPath();
                ctx.moveTo(left, top + corner); ctx.lineTo(left, top); ctx.lineTo(left + corner, top);
                ctx.moveTo(left + width - corner, top); ctx.lineTo(left + width, top); ctx.lineTo(left + width, top + corner);
                ctx.moveTo(left, top + height - corner); ctx.lineTo(left, top + height); ctx.lineTo(left + corner, top + height);
                ctx.moveTo(left + width - corner, top + height); ctx.lineTo(left + width, top + height); ctx.lineTo(left + width, top + height - corner);
                ctx.stroke();
                ctx.shadowBlur = 0;

                const title = !known ? "UNKNOWN FACE · NOT MARKED" :
                    (verified ? `${result.name} · ${String(result.status || "PRESENT").toUpperCase()}` : `${result.name} · LIVE CHECK`);
                ctx.font = "700 13px Segoe UI, Arial, sans-serif";
                const titleWidth = Math.min(dimensions.width - 12, Math.max(154, ctx.measureText(title).width + 22));
                const titleX = clamp(left, 6, dimensions.width - titleWidth - 6);
                const titleY = clamp(top - 34, 6, dimensions.height - 30);
                ctx.fillStyle = !known ? "rgba(126, 18, 39, 0.96)" : (verified ? "rgba(14, 91, 56, 0.96)" : "rgba(91, 38, 16, 0.96)");
                ctx.beginPath();
                ctx.roundRect(titleX, titleY, titleWidth, 27, 7);
                ctx.fill();
                ctx.fillStyle = "#ffffff";
                ctx.fillText(title, titleX + 10, titleY + 18, titleWidth - 18);

                // The actual randomized left/center/right instruction is placed ON the face box.
                const instruction = !known ? "Unknown face — attendance blocked" :
                    (verified ? `${result.subject_code || result.subject || "SUBJECT"}  ·  ${result.status === "Already Marked" ? "ALREADY RECORDED" : "ATTENDANCE MARKED"}` :
                    (result.challenge || "Follow the on-screen head movement instruction."));
                ctx.font = "600 12px Segoe UI, Arial, sans-serif";
                const instructionWidth = Math.min(Math.max(190, Math.min(width + 110, 340)), dimensions.width - 16);
                const innerTextWidth = instructionWidth - 20;
                const lines = wrapCanvasText(ctx, instruction, innerTextWidth, 2);
                const lineHeight = 15;
                const instructionHeight = lines.length * lineHeight + 14;
                const instructionX = clamp(left + (width - instructionWidth) / 2, 8, dimensions.width - instructionWidth - 8);
                const instructionY = clamp(top + height - instructionHeight - 5, 8, dimensions.height - instructionHeight - 8);
                ctx.fillStyle = !known ? "rgba(91, 12, 29, 0.94)" : (verified ? "rgba(10, 78, 47, 0.94)" : "rgba(62, 22, 34, 0.94)");
                ctx.beginPath();
                ctx.roundRect(instructionX, instructionY, instructionWidth, instructionHeight, 8);
                ctx.fill();
                ctx.strokeStyle = stroke;
                ctx.lineWidth = 1;
                ctx.stroke();
                ctx.fillStyle = "#ffffff";
                lines.forEach((line, index) => {
                    ctx.fillText(line, instructionX + 10, instructionY + 17 + index * lineHeight, innerTextWidth);
                });
                ctx.restore();
            });
        }

        function addLogEntry(result) {
            const empty = log.querySelector(".log-empty");
            if (empty) empty.remove();
            const entry = document.createElement("div");
            entry.className = "log-entry";
            const left = document.createElement("div");
            const name = document.createElement("strong");
            name.textContent = result.name;
            const details = document.createElement("small");
            details.textContent = `${result.subject || "Subject"} · ` + (result.newly_marked ? "Head-movement check passed · Attendance marked" : "Head-movement check passed · Already recorded for this subject today");
            left.append(name, details);
            const score = document.createElement("span");
            score.className = "log-score";
            score.textContent = "Match " + result.score;
            entry.append(left, score);
            log.prepend(entry);
            while (log.children.length > 6) log.lastElementChild.remove();
        }

        async function captureAndRecognize() {
            if (!stream || requestRunning || video.readyState < 2 || !clientSessionId) return;
            requestRunning = true;
            try {
                captureCanvas.width = video.videoWidth;
                captureCanvas.height = video.videoHeight;
                captureCanvas.getContext("2d").drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
                const image = captureCanvas.toDataURL("image/jpeg", 0.78);
                const response = await fetch("/api/recognize", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content },
                    body: JSON.stringify({ image, client_id: clientSessionId, subject_id: subjectSelect ? subjectSelect.value : null })
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    statusBox.textContent = data.message || "Recognition request failed.";
                    overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);
                    return;
                }

                const results = data.results || [];
                drawBoxes(results);
                const unknownNow = results.some((result) => result.name === "Unknown");
                if (unknownNow && !unknownWasVisible) {
                    unknownEvents += 1;
                    unknownCount.textContent = String(unknownEvents);
                }
                unknownWasVisible = unknownNow;

                const verifiedResults = results.filter((result) => result.student_id && result.liveness === "verified");
                verifiedResults.forEach((result) => {
                    recognizedStudents.add(result.student_id);
                    if (!loggedStudents.has(result.student_id)) {
                        loggedStudents.add(result.student_id);
                        addLogEntry(result);
                    }
                });
                presentCount.textContent = String(recognizedStudents.size);

                if (results.length === 0) {
                    statusBox.textContent = "No face detected. Center one face in the frame.";
                    unknownWasVisible = false;
                } else {
                    statusBox.textContent = results.map((result) => {
                        if (!result.student_id) return "Unknown face detected. Attendance was not marked.";
                        if (result.liveness !== "verified") {
                            return `${result.name} · ${result.challenge || result.status} · Head-movement check required · Attendance not marked`;
                        }
                        return `${result.name} · ${result.subject || "Subject"} · ID ${result.student_id} · Head-movement check passed · ${result.status}`;
                    }).join("\n");
                }
            } catch (error) {
                console.error("AttendAI recognition request failed:", error);
                statusBox.textContent = "Could not contact the recognition service. Check that the Flask server is running.";
            } finally {
                requestRunning = false;
            }
        }

        async function toggleFullscreen() {
            if (!cameraCard || !document.fullscreenEnabled) {
                statusBox.textContent = "Fullscreen is unavailable in this browser. You can still use the large camera view.";
                return;
            }
            try {
                if (document.fullscreenElement === cameraCard) {
                    await document.exitFullscreen();
                } else {
                    await cameraCard.requestFullscreen();
                }
            } catch (error) {
                statusBox.textContent = "Could not enter fullscreen: " + error.message;
            }
        }

        if (fullscreenButton) {
            fullscreenButton.addEventListener("click", toggleFullscreen);
            document.addEventListener("fullscreenchange", () => {
                const isFullscreen = document.fullscreenElement === cameraCard;
                fullscreenButton.textContent = isFullscreen ? "⤢ Exit full screen" : "⛶ Full screen";
                window.requestAnimationFrame(sizeOverlay);
            });
        }

        startButton.addEventListener("click", startCamera);
        stopButton.addEventListener("click", stopCamera);
        window.addEventListener("resize", () => { if (stream) sizeOverlay(); });
        window.addEventListener("beforeunload", stopCamera);
        video.addEventListener("loadedmetadata", () => { if (stream) sizeOverlay(); });
        setCameraState(false);
    }

    // ---------- Browser-based student face enrollment ----------
    const enrollVideo = $("enrollVideo");
    if (enrollVideo) {
        const startButton = $("startEnrollCameraBtn");
        const stopButton = $("stopEnrollCameraBtn");
        const submitButton = $("captureEnrollBtn");
        const form = $("studentRegistrationForm");
        const idInput = $("studentId");
        const nameInput = $("studentName");
        const emailInput = $("studentEmail");
        const canvas = $("enrollCanvas");
        const placeholder = $("enrollPlaceholder");
        const status = $("enrollCameraStatus");
        const message = $("enrollmentMessage");
        let stream = null;
        let submitting = false;

        function stopEnrollCamera() {
            if (stream) stream.getTracks().forEach((track) => track.stop());
            stream = null;
            enrollVideo.srcObject = null;
            enrollVideo.classList.add("hidden");
            placeholder.classList.remove("hidden");
            status.textContent = "CAMERA OFF";
            status.className = "pill neutral";
            startButton.disabled = false;
            stopButton.disabled = true;
            submitButton.disabled = true;
        }

        startButton.addEventListener("click", async () => {
            try {
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    throw new Error("Open this app at http://127.0.0.1:5000 to enable the local camera.");
                }
                stream = await navigator.mediaDevices.getUserMedia({
                    video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
                    audio: false
                });
                enrollVideo.srcObject = stream;
                enrollVideo.classList.remove("hidden");
                placeholder.classList.add("hidden");
                await enrollVideo.play();
                status.textContent = "CAMERA ACTIVE";
                status.className = "pill success";
                startButton.disabled = true;
                stopButton.disabled = false;
                submitButton.disabled = false;
                message.textContent = "Camera is ready. Center one face, then capture and enroll.";
                message.className = "inline-message info";
            } catch (error) {
                message.textContent = "Camera access failed: " + error.message;
                message.className = "inline-message error";
            }
        });

        stopButton.addEventListener("click", stopEnrollCamera);

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (submitting) return;
            const studentId = idInput.value.trim();
            const name = nameInput.value.trim();
            if (!studentId || !name) {
                message.textContent = "Enter both Student ID and name.";
                message.className = "inline-message error";
                return;
            }
            if (!stream || enrollVideo.readyState < 2) {
                message.textContent = "Open the camera before capturing a face.";
                message.className = "inline-message error";
                return;
            }
            submitting = true;
            submitButton.disabled = true;
            submitButton.textContent = "Processing face…";
            message.textContent = "Checking the captured frame and saving the face template…";
            message.className = "inline-message info";
            try {
                canvas.width = enrollVideo.videoWidth;
                canvas.height = enrollVideo.videoHeight;
                canvas.getContext("2d").drawImage(enrollVideo, 0, 0, canvas.width, canvas.height);
                const response = await fetch("/api/register_student", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content },
                    body: JSON.stringify({ student_id: studentId, name, email: emailInput ? emailInput.value.trim() : "", image: canvas.toDataURL("image/jpeg", 0.9) })
                });
                const data = await response.json();
                if (!response.ok || !data.success) throw new Error(data.message || "Student enrollment failed.");
                message.textContent = data.message + " Opening the student directory…";
                message.className = "inline-message success";
                stopEnrollCamera();
                window.location.assign("/students");
            } catch (error) {
                message.textContent = error.message;
                message.className = "inline-message error";
            } finally {
                submitting = false;
                submitButton.textContent = "Capture and enroll";
                if (stream) submitButton.disabled = false;
            }
        });

        window.addEventListener("beforeunload", stopEnrollCamera);
    }
})();
