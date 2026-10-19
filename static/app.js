// VideoDub Studio AI - Client Frontend JavaScript
document.addEventListener("DOMContentLoaded", () => {
    // State variables
    let selectedVideoPath = null;
    let selectedVideoTitle = null;
    let brandLogoPath = null;
    let currentTaskId = null;
    let currentEventSource = null;

    let targetLang = "vi";
    let mode = "vietsub";
    let blurOldSub = true;
    let sourceText = "ocr";

    // DOM Elements
    const videoUrlInput = document.getElementById("videoUrlInput");
    const btnPasteUrl = document.getElementById("btnPasteUrl");
    const btnDownloadUrl = document.getElementById("btnDownloadUrl");
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");

    const selectedVideoBanner = document.getElementById("selectedVideoBanner");
    const loadedVideoTitle = document.getElementById("loadedVideoTitle");
    const loadedVideoMeta = document.getElementById("loadedVideoMeta");
    const btnClearVideo = document.getElementById("btnClearVideo");

    const targetLangSelector = document.getElementById("targetLangSelector");
    const modeSelector = document.getElementById("modeSelector");
    const sourceTextSelector = document.getElementById("sourceTextSelector");
    const ocrOptionsWrapper = document.getElementById("ocrOptionsWrapper");
    const whisperOptionsWrapper = document.getElementById("whisperOptionsWrapper");
    const whisperModelSelect = document.getElementById("whisperModelSelect");
    const blurOldSubSelector = document.getElementById("blurOldSubSelector");
    const blurModeSelect = document.getElementById("blurModeSelect");
    const blurModeWrapper = document.getElementById("blurModeWrapper");
    const ttsProviderSelect = document.getElementById("ttsProviderSelect");
    const videoContextInput = document.getElementById("videoContextInput");
    const contextChips = document.getElementById("contextChips");

    const chkRemoveLogo = document.getElementById("chkRemoveLogo");
    const removeLogoOptions = document.getElementById("removeLogoOptions");
    const selRemoveLogoPos = document.getElementById("selRemoveLogoPos");

    const chkBrandLogo = document.getElementById("chkBrandLogo");
    const brandLogoOptions = document.getElementById("brandLogoOptions");
    const brandLogoInput = document.getElementById("brandLogoInput");
    const btnChooseBrandLogo = document.getElementById("btnChooseBrandLogo");
    const lblBrandLogoName = document.getElementById("lblBrandLogoName");
    const selBrandLogoCorner = document.getElementById("selBrandLogoCorner");
    const txtBrandLogoWidth = document.getElementById("txtBrandLogoWidth");

    const btnStartExport = document.getElementById("btnStartExport");
    const trackerStatusMsg = document.getElementById("trackerStatusMsg");
    const trackerPercent = document.getElementById("trackerPercent");
    const stepLineProgress = document.getElementById("stepLineProgress");
    const stepNodes = document.querySelectorAll(".step-node");
    const terminalBody = document.getElementById("terminalBody");
    const btnClearLog = document.getElementById("btnClearLog");

    // Modal elements
    const resultModal = document.getElementById("resultModal");
    const resultVideoPlayer = document.getElementById("resultVideoPlayer");
    const modalVideoTitle = document.getElementById("modalVideoTitle");
    const modalVideoMeta = document.getElementById("modalVideoMeta");
    const btnDownloadVideo = document.getElementById("btnDownloadVideo");
    const btnDownloadSrt = document.getElementById("btnDownloadSrt");
    const btnOpenOutputFolder = document.getElementById("btnOpenOutputFolder");
    const btnCloseModal = document.getElementById("btnCloseModal");
    const btnProcessAnother = document.getElementById("btnProcessAnother");
    const videoUnmuteHint = document.getElementById("videoUnmuteHint");

    // Header actions
    const btnPreviewLatest = document.getElementById("btnPreviewLatest");
    const btnOpenFolderHeader = document.getElementById("btnOpenFolderHeader");

    // Key Modal elements
    const keyModal = document.getElementById("keyModal");
    const btnOpenKeyModal = document.getElementById("btnOpenKeyModal");
    const btnCloseKeyModal = document.getElementById("btnCloseKeyModal");
    const btnSaveKeyModal = document.getElementById("btnSaveKeyModal");
    const inputApiKeyModal = document.getElementById("inputApiKeyModal");
    const keyBtnText = document.getElementById("keyBtnText");

    const toast = document.getElementById("toastNotification");

    // 1. Toast Notification Helper
    function showToast(message, isError = false) {
        toast.textContent = message;
        toast.style.borderColor = isError ? "var(--accent-rose)" : "var(--primary-cyan)";
        toast.classList.remove("hidden");
        setTimeout(() => {
            toast.classList.add("hidden");
        }, 3500);
    }

    // 2. Fetch Initial Config & Status
    async function loadInitialConfig() {
        try {
            const res = await fetch("/api/config");
            const data = await res.json();
            if (data.has_api_key) {
                keyBtnText.textContent = `Key: ${data.masked_key}`;
                keyBtnText.style.color = "#34d399";
            } else {
                keyBtnText.textContent = "Chưa có API Key";
                keyBtnText.style.color = "#fb7185";
            }
        } catch (e) {
            console.warn("Không thể tải cấu hình API:", e);
        }
    }
    loadInitialConfig();

    // 3. Tab Switching
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            btn.classList.add("active");
            const tabId = btn.getAttribute("data-tab");
            document.getElementById(tabId).classList.add("active");
        });
    });

    // 4. URL Paste & Download Video
    btnPasteUrl.addEventListener("click", async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text) {
                videoUrlInput.value = text.trim();
                showToast("Đã dán liên kết từ bộ nhớ tạm!");
            }
        } catch (err) {
            showToast("Vui lòng dán trực tiếp bằng phím tắt Ctrl+V", true);
        }
    });

    btnDownloadUrl.addEventListener("click", async () => {
        const url = videoUrlInput.value.trim();
        if (!url) {
            showToast("Vui lòng nhập hoặc dán liên kết video!", true);
            return;
        }

        btnDownloadUrl.disabled = true;
        btnDownloadUrl.innerHTML = `<span class="btn-icon">⏳</span> Đang tải...`;
        appendLog(`[${new Date().toLocaleTimeString()}] Bắt đầu tải video từ link: ${url}`);

        try {
            const res = await fetch("/api/download-url", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Tải video thất bại");

            setLoadedVideo(data.video_path, data.title, `Tải từ link • Thời lượng: ${Math.round(data.duration || 0)}s`);
            showToast("Tải video thành công!");
            appendLog(`[${new Date().toLocaleTimeString()}] Tải thành công: ${data.title}`);
        } catch (e) {
            showToast(e.message, true);
            appendLog(`[${new Date().toLocaleTimeString()}] Lỗi tải link: ${e.message}`);
        } finally {
            btnDownloadUrl.disabled = false;
            btnDownloadUrl.innerHTML = `<span class="btn-icon">⚡</span> Tải & Nạp Video`;
        }
    });

    // 5. Drag & Drop File Upload
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });
    fileInput.addEventListener("change", () => {
        if (fileInput.files && fileInput.files.length > 0) {
            uploadFile(fileInput.files[0]);
        }
    });

    async function uploadFile(file) {
        const formData = new FormData();
        formData.append("file", file);
        appendLog(`[${new Date().toLocaleTimeString()}] Đang tải lên file: ${file.name}...`);

        try {
            const res = await fetch("/api/upload-video", {
                method: "POST",
                body: formData
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Không thể tải file");

            const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
            setLoadedVideo(data.video_path, file.name, `File máy tính • Dung lượng: ${sizeMb} MB`);
            showToast("Nạp video thành công!");
            appendLog(`[${new Date().toLocaleTimeString()}] Nạp video hoàn tất: ${file.name}`);
        } catch (e) {
            showToast(e.message, true);
            appendLog(`[${new Date().toLocaleTimeString()}] Lỗi nạp video: ${e.message}`);
        }
    }

    function setLoadedVideo(path, title, meta) {
        selectedVideoPath = path;
        selectedVideoTitle = title;
        loadedVideoTitle.textContent = title;
        loadedVideoMeta.textContent = meta;
        selectedVideoBanner.classList.remove("hidden");

        // Tự động nạp ngữ cảnh từ tiêu đề video (loại bỏ chuỗi số ID / đuôi file)
        if (videoContextInput && (!videoContextInput.value || videoContextInput.dataset.autofilled === "true")) {
            let cleanTitle = (title || "").replace(/_\d{15,25}$/, "").replace(/\.(mp4|mkv|webm)$/i, "").trim();
            videoContextInput.value = cleanTitle;
            videoContextInput.dataset.autofilled = "true";
        }
    }

    btnClearVideo.addEventListener("click", () => {
        selectedVideoPath = null;
        selectedVideoTitle = null;
        selectedVideoBanner.classList.add("hidden");
        videoUrlInput.value = "";
        fileInput.value = "";
        if (videoContextInput && videoContextInput.dataset.autofilled === "true") {
            videoContextInput.value = "";
        }
    });

    // Xử lý các chip gợi ý chủ đề / ngữ cảnh video
    if (contextChips) {
        contextChips.querySelectorAll(".chip-btn").forEach(chip => {
            chip.addEventListener("click", () => {
                const tag = chip.getAttribute("data-tag");
                if (videoContextInput) {
                    if (videoContextInput.value.includes(tag)) {
                        videoContextInput.value = videoContextInput.value.replace(tag, "").replace(/\s*\|\s*/, " ").trim();
                        chip.classList.remove("active");
                    } else {
                        videoContextInput.value = videoContextInput.value ? `${videoContextInput.value} | ${tag}` : tag;
                        chip.classList.add("active");
                    }
                    videoContextInput.dataset.autofilled = "false";
                }
            });
        });
    }

    // 6. Target Language Selector
    targetLangSelector.querySelectorAll(".pill-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            targetLangSelector.querySelectorAll(".pill-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            targetLang = btn.getAttribute("data-lang");
            appendLog(`[${new Date().toLocaleTimeString()}] Đã chọn ngôn ngữ dịch: ${targetLang === "en" ? "Tiếng Anh (English)" : "Tiếng Việt"}`);
        });
    });

    // 7. Mode Selector (vietsub / dubbing / both)
    modeSelector.querySelectorAll(".radio-card").forEach(card => {
        card.addEventListener("click", () => {
            modeSelector.querySelectorAll(".radio-card").forEach(c => c.classList.remove("active"));
            card.classList.add("active");
            mode = card.getAttribute("data-mode");
            appendLog(`[${new Date().toLocaleTimeString()}] Đã chọn chế độ xuất: ${mode}`);
        });
    });

    // 7b. Source Text Selector (OCR vs Whisper AI)
    if (sourceTextSelector) {
        sourceTextSelector.querySelectorAll(".radio-card").forEach(card => {
            card.addEventListener("click", () => {
                sourceTextSelector.querySelectorAll(".radio-card").forEach(c => c.classList.remove("active"));
                card.classList.add("active");
                sourceText = card.getAttribute("data-source");

                if (sourceText === "asr") {
                    ocrOptionsWrapper.classList.add("hidden");
                    whisperOptionsWrapper.classList.remove("hidden");
                    appendLog(`[${new Date().toLocaleTimeString()}] 🎙️ Đã chọn trích xuất phụ đề bằng: Whisper AI (Nghe giọng nói)`);
                } else {
                    ocrOptionsWrapper.classList.remove("hidden");
                    whisperOptionsWrapper.classList.add("hidden");
                    appendLog(`[${new Date().toLocaleTimeString()}] 👁️ Đã chọn trích xuất phụ đề bằng: Hardsub OCR (Quét chữ màn hình)`);
                }
            });
        });
    }

    // 8. Blur Old Sub Selector (true / false)
    blurOldSubSelector.querySelectorAll(".radio-card").forEach(card => {
        card.addEventListener("click", () => {
            blurOldSubSelector.querySelectorAll(".radio-card").forEach(c => c.classList.remove("active"));
            card.classList.add("active");
            blurOldSub = card.getAttribute("data-blur") === "true";
            if (blurOldSub) {
                blurModeWrapper.style.opacity = "1";
                blurModeWrapper.style.pointerEvents = "auto";
                const padWrap = document.getElementById("blurPaddingWrapper");
                if (padWrap) { padWrap.style.opacity = "1"; padWrap.style.pointerEvents = "auto"; }
                appendLog(`[${new Date().toLocaleTimeString()}] Bật làm mờ sub cũ (sub mới hiển thị trên khung mờ)`);
            } else {
                blurModeWrapper.style.opacity = "0.4";
                blurModeWrapper.style.pointerEvents = "none";
                const padWrap = document.getElementById("blurPaddingWrapper");
                if (padWrap) { padWrap.style.opacity = "0.4"; padWrap.style.pointerEvents = "none"; }
                appendLog(`[${new Date().toLocaleTimeString()}] Giữ nguyên sub gốc (sub mới sẽ hiển thị BÊN DƯỚI sub gốc)`);
            }
        });
    });

    // 9. Logo Removal Checkbox
    chkRemoveLogo.addEventListener("change", () => {
        if (chkRemoveLogo.checked) {
            removeLogoOptions.classList.remove("disabled");
            appendLog(`[${new Date().toLocaleTimeString()}] Bật tính năng che logo video gốc (${selRemoveLogoPos.value})`);
        } else {
            removeLogoOptions.classList.add("disabled");
        }
    });

    // 10. Brand Logo Overlay
    chkBrandLogo.addEventListener("change", () => {
        if (chkBrandLogo.checked) {
            brandLogoOptions.classList.remove("disabled");
        } else {
            brandLogoOptions.classList.add("disabled");
        }
    });

    btnChooseBrandLogo.addEventListener("click", () => brandLogoInput.click());
    brandLogoInput.addEventListener("change", async () => {
        if (brandLogoInput.files && brandLogoInput.files.length > 0) {
            const file = brandLogoInput.files[0];
            const formData = new FormData();
            formData.append("file", file);
            try {
                const res = await fetch("/api/upload-logo", { method: "POST", body: formData });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Không thể tải logo");
                brandLogoPath = data.logo_path;
                lblBrandLogoName.textContent = file.name;
                lblBrandLogoName.style.color = "#34d399";
                showToast("Đã nạp logo thương hiệu!");
                appendLog(`[${new Date().toLocaleTimeString()}] Nạp logo thương hiệu: ${file.name}`);
            } catch (e) {
                showToast(e.message, true);
            }
        }
    });

    // 11. Circular Step Status Updaters
    // Steps: 0: Tải Video, 1: Quét Sub, 2: Dịch AI, 3: Lồng tiếng, 4: Logo & Mờ, 5: Xuất Video
    function updateStepProgress(activeStepIdx, percent = 0) {
        stepNodes.forEach(node => {
            const idx = parseInt(node.getAttribute("data-step"), 10);
            node.classList.remove("step-pending", "step-running", "step-completed");
            if (idx < activeStepIdx) {
                node.classList.add("step-completed");
            } else if (idx === activeStepIdx) {
                node.classList.add("step-running");
            } else {
                node.classList.add("step-pending");
            }
        });

        // Cập nhật thanh line nối giữa các ô tròn
        const totalSteps = stepNodes.length - 1;
        const linePercent = Math.min(100, Math.max(0, (activeStepIdx / totalSteps) * 100));
        stepLineProgress.style.width = `${linePercent}%`;

        // Cập nhật nhãn %
        const pctDisplay = Math.round(percent * 100);
        trackerPercent.textContent = `${pctDisplay}%`;
    }

    function appendLog(line) {
        const p = document.createElement("p");
        p.className = "term-line";
        if (line.includes("LỖI") || line.includes("error")) p.classList.add("error");
        else if (line.includes("HOÀN THÀNH") || line.includes("thành công")) p.classList.add("success");
        p.textContent = line;
        terminalBody.appendChild(p);
        terminalBody.scrollTop = terminalBody.scrollHeight;
    }

    btnClearLog.addEventListener("click", () => {
        terminalBody.innerHTML = `<p class="term-line prompt">> Bảng log đã xóa...</p>`;
    });

    // 12. BẮT ĐẦU XUẤT VIDEO (MAIN PROCESS)
    btnStartExport.addEventListener("click", async () => {
        if (!selectedVideoPath) {
            showToast("Vui lòng tải hoặc nạp video trước khi bắt đầu!", true);
            return;
        }

        // Khóa nút bắt đầu
        btnStartExport.disabled = true;
        btnStartExport.querySelector(".btn-giant-text").textContent = "ĐANG TIẾN HÀNH XỬ LÝ...";

        // Cuộn mượt xuống bảng tiến trình
        document.getElementById("trackerSection").scrollIntoView({ behavior: "smooth" });

        // Reset trạng thái tiến trình
        updateStepProgress(0, 0.05);
        trackerStatusMsg.textContent = "Đang khởi tạo tiến trình xử lý...";
        appendLog(`[${new Date().toLocaleTimeString()}] ================================================`);
        appendLog(`[${new Date().toLocaleTimeString()}] BẮT ĐẦU XUẤT VIDEO: ${selectedVideoTitle}`);

        const payload = {
            video_path: selectedVideoPath,
            target_lang: targetLang,
            mode: mode,
            blur_old_sub: blurOldSub,
            blur_mode: blurModeSelect.value,
            ocr_region_preset: document.getElementById("ocrRegionSelect") ? document.getElementById("ocrRegionSelect").value : "auto",
            ocr_fps: document.getElementById("ocrFpsSelect") ? parseFloat(document.getElementById("ocrFpsSelect").value) : 1.5,
            blur_padding: document.getElementById("blurPaddingSelect") ? parseInt(document.getElementById("blurPaddingSelect").value, 10) : 16,
            tts_provider: ttsProviderSelect.value,
            logo_remove_enabled: chkRemoveLogo.checked,
            logo_remove_pos: selRemoveLogoPos.value,
            brand_logo_enabled: chkBrandLogo.checked,
            brand_logo_path: brandLogoPath,
            brand_logo_corner: selBrandLogoCorner.value,
            brand_logo_width: parseInt(txtBrandLogoWidth.value, 10) || 120,
            source_text: sourceText,
            whisper_model: whisperModelSelect ? whisperModelSelect.value : "small",
            whisper_provider: (whisperModelSelect && whisperModelSelect.value === "openai") ? "openai" : "local",
            context: videoContextInput ? videoContextInput.value.trim() : "",
            title: selectedVideoTitle || ""
        };

        try {
            const res = await fetch("/api/start-process", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Không thể bắt đầu tác vụ");

            currentTaskId = data.task_id;
            listenTaskProgress(currentTaskId);
        } catch (e) {
            showToast(e.message, true);
            appendLog(`[${new Date().toLocaleTimeString()}] ❌ Lỗi: ${e.message}`);
            resetExportButton();
        }
    });

    function listenTaskProgress(taskId) {
        if (currentEventSource) {
            currentEventSource.close();
        }

        currentEventSource = new EventSource(`/api/progress-sse/${taskId}`);

        currentEventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.message) {
                    trackerStatusMsg.textContent = data.message;
                }
                if (data.log) {
                    appendLog(data.log);
                }
                if (data.step_index !== undefined && data.percent !== undefined) {
                    updateStepProgress(data.step_index, data.percent);
                }

                // Khi tác vụ hoàn tất
                if (data.status === "completed") {
                    currentEventSource.close();
                    updateStepProgress(5, 1.0);
                    stepNodes.forEach(n => {
                        n.classList.remove("step-pending", "step-running");
                        n.classList.add("step-completed");
                    });
                    stepLineProgress.style.width = "100%";
                    trackerStatusMsg.textContent = "Hoàn tất xuất video thành công!";
                    resetExportButton();

                    // Mở popup modal kết quả
                    if (data.result) {
                        showCompletionModal(data.result);
                    }
                } else if (data.status === "failed") {
                    currentEventSource.close();
                    trackerStatusMsg.textContent = "Quá trình xử lý gặp lỗi!";
                    showToast(data.message || "Xử lý video thất bại", true);
                    resetExportButton();
                }
            } catch (err) {
                console.error("Lỗi đọc SSE:", err);
            }
        };

        currentEventSource.onerror = (e) => {
            console.warn("SSE kết thúc hoặc mất kết nối:", e);
        };
    }

    function resetExportButton() {
        btnStartExport.disabled = false;
        btnStartExport.querySelector(".btn-giant-text").textContent = "BẮT ĐẦU XUẤT VIDEO NGAY";
    }

    // 13. Completion Popup Modal Display
    function showUnmuteHint() {
        if (videoUnmuteHint) videoUnmuteHint.classList.remove("hidden");
    }

    function hideUnmuteHint() {
        if (videoUnmuteHint) videoUnmuteHint.classList.add("hidden");
    }

    // 13. Completion Popup Modal Display
    function showCompletionModal(result) {
        if (!result) return;

        modalVideoTitle.textContent = result.filename;
        modalVideoTitle.title = result.filename;
        const secs = result.seconds ? `${result.seconds}s` : "Hoàn tất";
        const lang = (result.target_lang || "VI").toUpperCase();
        const modeText = result.mode === "vietsub" ? "Chỉ Vietsub" : (result.mode === "dubbing" ? "Chỉ Lồng Tiếng" : "Cả Hai");
        modalVideoMeta.textContent = `Thời gian xử lý: ${secs} • Ngôn ngữ: ${lang} • Chế độ: ${modeText}`;

        // Nút tải video MP4: dùng download_url (hoặc fallback /api/download-video)
        const downloadHref = result.download_url || `/api/download-video?filename=${encodeURIComponent(result.filename)}`;
        btnDownloadVideo.href = downloadHref;
        btnDownloadVideo.download = result.filename;

        // Nút tải phụ đề SRT
        if (result.srt_url) {
            btnDownloadSrt.href = result.srt_url;
            btnDownloadSrt.download = result.filename.replace(/\.mp4$/i, ".srt");
            btnDownloadSrt.style.display = "flex";
        } else {
            btnDownloadSrt.style.display = "none";
        }

        // Mở popup modal lên màn hình TRƯỚC khi load video để trình duyệt tính toán đúng kích thước player
        resultModal.classList.remove("hidden");
        hideUnmuteHint();

        // Nạp URL video (preview endpoint hỗ trợ inline stream và Range request)
        const videoSrc = result.video_url || `/api/preview-video?filename=${encodeURIComponent(result.filename)}`;
        
        try {
            resultVideoPlayer.pause();
            resultVideoPlayer.currentTime = 0;
        } catch (e) {}

        resultVideoPlayer.src = videoSrc;
        resultVideoPlayer.load();

        // Tự động phát thông minh:
        // 1. Thử phát có tiếng trước
        resultVideoPlayer.muted = false;
        const playPromise = resultVideoPlayer.play();
        if (playPromise !== undefined) {
            playPromise.then(() => {
                hideUnmuteHint();
            }).catch(() => {
                // 2. Nếu Chrome/Edge chặn âm thanh tự động -> tự động phát tắt tiếng để video CHẠY NGAY
                resultVideoPlayer.muted = true;
                resultVideoPlayer.play().then(() => {
                    showUnmuteHint();
                }).catch(err => {
                    console.warn("Autoplay bị chặn hoàn toàn:", err);
                });
            });
        }
    }

    // Bật tiếng khi người dùng tương tác với video hoặc click vào hint
    resultVideoPlayer.addEventListener("volumechange", () => {
        if (!resultVideoPlayer.muted && resultVideoPlayer.volume > 0) {
            hideUnmuteHint();
        }
    });

    if (videoUnmuteHint) {
        videoUnmuteHint.addEventListener("click", () => {
            resultVideoPlayer.muted = false;
            resultVideoPlayer.play();
            hideUnmuteHint();
        });
    }

    function closeModal() {
        resultModal.classList.add("hidden");
        hideUnmuteHint();
        try {
            resultVideoPlayer.pause();
            resultVideoPlayer.removeAttribute("src");
            resultVideoPlayer.load();
        } catch (e) {}
    }

    btnCloseModal.addEventListener("click", closeModal);

    // Đóng khi click ngoài khung modal
    resultModal.addEventListener("click", (e) => {
        if (e.target === resultModal) {
            closeModal();
        }
    });

    // Phím Esc để đóng modal
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !resultModal.classList.contains("hidden")) {
            closeModal();
        }
    });

    // Làm video tiếp theo: Đóng modal, xóa link cũ, cuộn lên đầu trang
    btnProcessAnother.addEventListener("click", () => {
        closeModal();
        urlVideoInput.value = "";
        selectedVideoPath = null;
        selectedVideoTitle = null;
        inputMetaInfo.textContent = "Chưa chọn video";
        inputMetaInfo.style.color = "var(--text-muted)";
        window.scrollTo({ top: 0, behavior: "smooth" });
    });

    btnOpenOutputFolder.addEventListener("click", async () => {
        try {
            await fetch("/api/open-folder", { method: "POST" });
            showToast("Đã mở thư mục output trên máy tính!");
        } catch (e) {
            console.error(e);
        }
    });

    btnOpenFolderHeader.addEventListener("click", async () => {
        try {
            await fetch("/api/open-folder", { method: "POST" });
            showToast("Đã mở thư mục output!");
        } catch (e) {
            console.error(e);
        }
    });

    if (btnPreviewLatest) {
        btnPreviewLatest.addEventListener("click", async () => {
            try {
                const res = await fetch("/api/latest-result");
                const data = await res.json();
                if (!res.ok) {
                    showToast(data.detail || "Chưa có video nào trong thư mục output!", true);
                    return;
                }
                showCompletionModal(data);
            } catch (e) {
                showToast("Không thể tải thông tin video gần nhất", true);
            }
        });
    }

    // 14. API Key Modal Handlers
    btnOpenKeyModal.addEventListener("click", () => keyModal.classList.remove("hidden"));
    btnCloseKeyModal.addEventListener("click", () => keyModal.classList.add("hidden"));

    btnSaveKeyModal.addEventListener("click", async () => {
        const key = inputApiKeyModal.value.trim();
        if (!key) {
            showToast("Vui lòng nhập API Key", true);
            return;
        }

        try {
            const res = await fetch("/api/config/key", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ gemini_api_key: key })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Không thể lưu key");

            showToast("Đã lưu API Key Gemini thành công!");
            keyModal.classList.add("hidden");
            inputApiKeyModal.value = "";
            loadInitialConfig();
        } catch (e) {
            showToast(e.message, true);
        }
    });
});
