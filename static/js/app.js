/**
 * TubeAgent Dashboard JavaScript Application
 * Manages WebSocket real-time updates, video rendering, modals, and user actions.
 */

document.addEventListener("DOMContentLoaded", () => {
    // State
    let videos = [];
    let currentFilter = "all";
    let ws = null;
    let wsReconnectTimeout = null;

    // DOM Elements
    const videoListContainer = document.getElementById("videoListContainer");
    const emptyState = document.getElementById("emptyState");
    const terminalLogs = document.getElementById("terminalLogs");
    const btnClearLogs = document.getElementById("btnClearLogs");

    // Status cards
    const badgeYouTubeAuth = document.getElementById("badgeYouTubeAuth");
    const channelAvatar = document.getElementById("channelAvatar");
    const channelName = document.getElementById("channelName");
    const channelStats = document.getElementById("channelStats");
    const btnConnectYouTube = document.getElementById("btnConnectYouTube");

    const badgeWatcherStatus = document.getElementById("badgeWatcherStatus");
    const watchFolderPath = document.getElementById("watchFolderPath");
    const statPending = document.getElementById("statPending");
    const statUploaded = document.getElementById("statUploaded");
    const statTotal = document.getElementById("statTotal");

    const badgeGeminiStatus = document.getElementById("badgeGeminiStatus");
    const geminiModelName = document.getElementById("geminiModelName");
    const defaultPrivacyBadge = document.getElementById("defaultPrivacyBadge");
    const agentModeText = document.getElementById("agentModeText");

    // Top action buttons
    const btnScanFolder = document.getElementById("btnScanFolder");
    const btnOpenSettings = document.getElementById("btnOpenSettings");

    // Dropzone
    const fileDropzone = document.getElementById("fileDropzone");
    const fileInput = document.getElementById("fileInput");
    const dropzoneProgress = document.getElementById("dropzoneProgress");
    const dropzoneProgressBar = document.getElementById("dropzoneProgressBar");
    const dropzoneProgressText = document.getElementById("dropzoneProgressText");

    // Modals
    const metadataModal = document.getElementById("metadataModal");
    const btnCloseMetadataModal = document.getElementById("btnCloseMetadataModal");
    const btnCancelEdit = document.getElementById("btnCancelEdit");
    const btnSaveMetadata = document.getElementById("btnSaveMetadata");
    const btnApproveAndUpload = document.getElementById("btnApproveAndUpload");
    const editVideoId = document.getElementById("editVideoId");
    const editVideoTitle = document.getElementById("editVideoTitle");
    const editVideoDescription = document.getElementById("editVideoDescription");
    const editVideoCategory = document.getElementById("editVideoCategory");
    const editVideoPrivacy = document.getElementById("editVideoPrivacy");
    const editVideoTags = document.getElementById("editVideoTags");
    const modalVideoFilename = document.getElementById("modalVideoFilename");
    const titleCharCount = document.getElementById("titleCharCount");

    // Auth Modal
    const authModal = document.getElementById("authModal");
    const btnCloseAuthModal = document.getElementById("btnCloseAuthModal");
    const btnCloseAuthModalBottom = document.getElementById("btnCloseAuthModalBottom");
    const secretDropzone = document.getElementById("secretDropzone");
    const secretFileInput = document.getElementById("secretFileInput");
    const rawSecretJson = document.getElementById("rawSecretJson");
    const btnSaveClientSecret = document.getElementById("btnSaveClientSecret");
    const btnTriggerOAuth = document.getElementById("btnTriggerOAuth");
    const authStatusAlert = document.getElementById("authStatusAlert");

    // Settings Modal
    const settingsModal = document.getElementById("settingsModal");
    const btnCloseSettingsModal = document.getElementById("btnCloseSettingsModal");
    const btnCancelSettings = document.getElementById("btnCancelSettings");
    const btnSaveSettings = document.getElementById("btnSaveSettings");
    const settingWatchFolder = document.getElementById("settingWatchFolder");
    const settingProcessedFolder = document.getElementById("settingProcessedFolder");
    const settingGeminiApiKey = document.getElementById("settingGeminiApiKey");
    const settingGeminiModel = document.getElementById("settingGeminiModel");
    const settingDefaultPrivacy = document.getElementById("settingDefaultPrivacy");
    const settingAutoUpload = document.getElementById("settingAutoUpload");

    // Filter Buttons
    const filterButtons = document.querySelectorAll(".filter-btn");

    // --- Toast Notifications ---
    function showToast(message, type = "info") {
        const container = document.getElementById("toastContainer");
        const toast = document.createElement("div");
        toast.className = "toast";
        
        let icon = "ℹ️";
        if (type === "success") icon = "✅";
        if (type === "warning") icon = "⚠️";
        if (type === "error") icon = "❌";

        toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateY(10px)";
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // --- Initial Load & Polling ---
    async function loadStatus() {
        try {
            const res = await fetch("/api/status");
            const data = await res.json();

            // Watcher
            watchFolderPath.textContent = data.watch_folder;
            watchFolderPath.setAttribute("title", `Click to copy: ${data.watch_folder}`);
            watchFolderPath.onclick = () => {
                navigator.clipboard.writeText(data.watch_folder);
                showToast("Folder path copied to clipboard", "success");
            };

            statPending.textContent = data.stats.pending;
            statUploaded.textContent = data.stats.uploaded;
            statTotal.textContent = data.stats.total;

            // Mode
            if (data.auto_upload) {
                agentModeText.textContent = "Autopilot Mode";
            } else {
                agentModeText.textContent = "Review Mode";
            }

            // Gemini
            if (data.has_gemini_key) {
                badgeGeminiStatus.className = "badge badge-success";
                badgeGeminiStatus.textContent = "Online";
            } else {
                badgeGeminiStatus.className = "badge badge-warning";
                badgeGeminiStatus.textContent = "Needs API Key";
            }
            geminiModelName.textContent = data.gemini_model;
            defaultPrivacyBadge.textContent = `Privacy: ${data.default_privacy.toUpperCase()}`;

            // YouTube Channel
            renderChannelProfile(data.channel);
        } catch (err) {
            console.error("Error loading system status:", err);
        }
    }

    function renderChannelProfile(channel) {
        if (channel && channel.authenticated) {
            badgeYouTubeAuth.className = "badge badge-success";
            badgeYouTubeAuth.textContent = "Connected";
            channelName.textContent = channel.title || "YouTube Channel";
            channelStats.textContent = `${channel.subscribers || 0} subscribers • ${channel.videos || 0} videos`;
            if (channel.avatar_url) {
                channelAvatar.src = channel.avatar_url;
            }
            btnConnectYouTube.textContent = "Switch Channel";
        } else {
            badgeYouTubeAuth.className = "badge badge-warning";
            badgeYouTubeAuth.textContent = "Not Connected";
            channelName.textContent = "Not Connected";
            channelStats.textContent = channel?.has_client_secrets 
                ? "Click below to sign in with Google" 
                : "Needs client_secrets.json setup";
            channelAvatar.src = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=120&q=80";
            btnConnectYouTube.textContent = "Connect Channel";
        }
    }

    async function loadVideos() {
        try {
            const res = await fetch("/api/videos");
            videos = await res.json();
            renderVideos();
        } catch (err) {
            console.error("Error loading videos:", err);
        }
    }

    async function loadLogs() {
        try {
            const res = await fetch("/api/logs?limit=40");
            const logs = await res.json();
            terminalLogs.innerHTML = "";
            logs.reverse().forEach(appendLogEntry);
            scrollTerminalBottom();
        } catch (err) {
            console.error("Error loading logs:", err);
        }
    }

    function appendLogEntry(log) {
        const line = document.createElement("div");
        line.className = `log-line log-${log.level || "INFO"}`;
        const ts = (log.timestamp || "").split(" ")[1] || log.timestamp || "--:--:--";
        line.innerHTML = `
            <span class="log-ts">${ts}</span>
            <span class="log-src">[${log.source || "Agent"}]</span>
            <span class="log-msg">${escapeHtml(log.message || "")}</span>
        `;
        terminalLogs.appendChild(line);
    }

    function scrollTerminalBottom() {
        terminalLogs.scrollTop = terminalLogs.scrollHeight;
    }

    // --- Render Videos ---
    function renderVideos() {
        const filtered = videos.filter(v => {
            if (currentFilter === "all") return true;
            if (currentFilter === "review_ready") return v.status === "review_ready";
            if (currentFilter === "uploading") return v.status === "uploading";
            if (currentFilter === "uploaded") return v.status === "uploaded";
            return true;
        });

        if (filtered.length === 0) {
            videoListContainer.innerHTML = "";
            videoListContainer.appendChild(emptyState);
            emptyState.style.display = "block";
            return;
        }

        emptyState.style.display = "none";
        videoListContainer.innerHTML = "";

        filtered.forEach(video => {
            const card = document.createElement("div");
            card.className = "video-card";
            card.id = `videoCard-${video.id}`;

            // Status badge color and label
            let statusBadge = `<span class="badge badge-info">Detected</span>`;
            if (video.status === "analyzing") {
                statusBadge = `<span class="badge badge-warning">✨ AI Analyzing</span>`;
            } else if (video.status === "review_ready") {
                statusBadge = `<span class="badge badge-warning">⏳ Needs Review</span>`;
            } else if (video.status === "uploading") {
                statusBadge = `<span class="badge badge-info">⬆ Uploading (${video.upload_progress || 0}%)</span>`;
            } else if (video.status === "uploaded") {
                statusBadge = `<span class="badge badge-success">✓ Published (${video.privacy_status})</span>`;
            } else if (video.status === "failed") {
                statusBadge = `<span class="badge badge-danger">✕ Error</span>`;
            }

            const sizeMb = (video.filesize / (1024 * 1024)).toFixed(1);
            const titleDisplay = video.title || video.filename;

            // Action buttons based on status
            let actionButtons = "";
            if (video.status === "review_ready") {
                actionButtons = `
                    <button class="btn btn-sm btn-outline-primary btn-regenerate" data-id="${video.id}" title="Re-run AI for rich description & 10+ tags">✨ AI Polish</button>
                    <button class="btn btn-sm btn-secondary btn-edit" data-id="${video.id}">Edit Details</button>
                    <button class="btn btn-sm btn-success btn-approve" data-id="${video.id}">Approve & Upload</button>
                `;
            } else if (video.status === "uploaded") {
                actionButtons = `
                    <a href="${video.youtube_url}" target="_blank" class="btn btn-sm btn-primary">Watch on YouTube ↗</a>
                    <button class="btn btn-sm btn-outline-primary btn-regenerate" data-id="${video.id}" title="Re-generate and sync rich metadata to YouTube">✨ AI Polish</button>
                    <button class="btn btn-sm btn-secondary btn-edit" data-id="${video.id}">View Metadata</button>
                `;
            } else if (video.status === "failed") {
                actionButtons = `
                    <button class="btn btn-sm btn-warning btn-retry" data-id="${video.id}">Retry</button>
                    <button class="btn btn-sm btn-outline-primary btn-regenerate" data-id="${video.id}">✨ AI Polish</button>
                    <button class="btn btn-sm btn-secondary btn-edit" data-id="${video.id}">Edit</button>
                `;
            } else if (video.status === "uploading") {
                actionButtons = `<span class="badge badge-info">Uploading in progress...</span>`;
            }

            actionButtons += `
                <button class="btn btn-sm btn-ghost btn-delete" data-id="${video.id}" title="Delete record">&times;</button>
            `;

            // Tag bubbles (show up to 15 tags)
            let tagBubbles = "";
            if (video.tags) {
                const tagsList = video.tags.split(",").slice(0, 15);
                tagBubbles = tagsList.map(t => `<span class="tag-bubble">#${escapeHtml(t.trim())}</span>`).join(" ");
            }

            card.innerHTML = `
                <div class="video-card-top">
                    <div class="video-main-info">
                        <div class="video-icon-badge">
                            <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
                                <path d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8 12.5v-9l6 4.5-6 4.5z"/>
                            </svg>
                        </div>
                        <div class="video-text-content">
                            <div class="video-display-title">${escapeHtml(titleDisplay)}</div>
                            <div class="video-original-file">${escapeHtml(video.filename)} &bull; ${sizeMb} MB</div>
                            <div class="video-meta-tags">
                                ${statusBadge}
                                <span class="meta-chip">Privacy: ${video.privacy_status || "private"}</span>
                                <span class="meta-chip">Cat ID: ${video.category_id || "28"}</span>
                            </div>
                        </div>
                    </div>
                    <div class="video-actions">
                        ${actionButtons}
                    </div>
                </div>

                ${video.status === "uploading" ? `
                    <div class="video-upload-bar-wrap">
                        <div class="video-upload-bar" style="width: ${video.upload_progress || 0}%;"></div>
                    </div>
                ` : ""}

                ${video.description ? `
                    <div class="video-details-accordion">
                        <div class="video-desc-preview">${escapeHtml(video.description)}</div>
                        ${tagBubbles ? `<div class="tags-cloud">${tagBubbles}</div>` : ""}
                    </div>
                ` : ""}
            `;

            videoListContainer.appendChild(card);
        });

        attachCardActionHandlers();
    }

    function attachCardActionHandlers() {
        document.querySelectorAll(".btn-regenerate").forEach(btn => {
            btn.onclick = () => triggerRegenerate(parseInt(btn.dataset.id));
        });
        document.querySelectorAll(".btn-edit").forEach(btn => {
            btn.onclick = () => openEditModal(parseInt(btn.dataset.id));
        });
        document.querySelectorAll(".btn-approve").forEach(btn => {
            btn.onclick = () => triggerApprove(parseInt(btn.dataset.id));
        });
        document.querySelectorAll(".btn-retry").forEach(btn => {
            btn.onclick = () => triggerRetry(parseInt(btn.dataset.id));
        });
        document.querySelectorAll(".btn-delete").forEach(btn => {
            btn.onclick = () => triggerDelete(parseInt(btn.dataset.id));
        });
    }

    async function triggerRegenerate(videoId) {
        try {
            showToast(`Generating rich AI description & 10+ keywords for video #${videoId}...`, "info");
            const res = await fetch(`/api/videos/${videoId}/regenerate`, { method: "POST" });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Regeneration failed");
            showToast("✨ AI generated rich description & 10+ keywords!", "success");
            loadVideos();
        } catch (err) {
            showToast(err.message, "error");
        }
    }

    // --- Action Handlers ---
    async function triggerApprove(videoId) {
        try {
            showToast(`Approving upload for video #${videoId}...`, "info");
            const res = await fetch(`/api/videos/${videoId}/approve`, { method: "POST" });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Approval failed");
            showToast("Upload initiated successfully!", "success");
            loadVideos();
            loadStatus();
        } catch (err) {
            showToast(err.message, "error");
        }
    }

    async function triggerRetry(videoId) {
        try {
            showToast(`Retrying video #${videoId}...`, "info");
            const res = await fetch(`/api/videos/${videoId}/retry`, { method: "POST" });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Retry failed");
            showToast("Pipeline re-triggered", "success");
            loadVideos();
        } catch (err) {
            showToast(err.message, "error");
        }
    }

    async function triggerDelete(videoId) {
        if (!confirm("Are you sure you want to remove this video from the queue?")) return;
        try {
            await fetch(`/api/videos/${videoId}`, { method: "DELETE" });
            showToast(`Video #${videoId} removed`, "info");
            videos = videos.filter(v => v.id !== videoId);
            renderVideos();
            loadStatus();
        } catch (err) {
            showToast(err.message, "error");
        }
    }

    function openEditModal(videoId) {
        const video = videos.find(v => v.id === videoId);
        if (!video) return;

        editVideoId.value = video.id;
        modalVideoFilename.textContent = `Edit Metadata: ${video.filename}`;
        editVideoTitle.value = video.title || "";
        editVideoDescription.value = video.description || "";
        editVideoTags.value = video.tags || "";
        editVideoCategory.value = video.category_id || "28";
        editVideoPrivacy.value = video.privacy_status || "private";

        updateCharCount();
        metadataModal.style.display = "flex";
    }

    function updateCharCount() {
        titleCharCount.textContent = editVideoTitle.value.length;
    }
    editVideoTitle.addEventListener("input", updateCharCount);

    btnCloseMetadataModal.onclick = () => metadataModal.style.display = "none";
    btnCancelEdit.onclick = () => metadataModal.style.display = "none";

    const btnModalRegenerate = document.getElementById("btnModalRegenerate");
    if (btnModalRegenerate) {
        btnModalRegenerate.onclick = async () => {
            const videoId = parseInt(editVideoId.value);
            if (!videoId) return;
            try {
                btnModalRegenerate.disabled = true;
                btnModalRegenerate.textContent = "⏳ Generating...";
                showToast("Generating rich AI description & 10+ tags...", "info");
                const res = await fetch(`/api/videos/${videoId}/regenerate`, { method: "POST" });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Regeneration failed");
                const updated = data.video;
                editVideoTitle.value = updated.title || "";
                editVideoDescription.value = updated.description || "";
                editVideoTags.value = updated.tags || "";
                editVideoCategory.value = updated.category_id || "28";
                updateCharCount();
                showToast("✨ Generated rich description and 10+ tags!", "success");
                loadVideos();
            } catch (err) {
                showToast(err.message, "error");
            } finally {
                btnModalRegenerate.disabled = false;
                btnModalRegenerate.textContent = "✨ Regenerate AI";
            }
        };
    }

    btnSaveMetadata.onclick = async () => {
        const videoId = parseInt(editVideoId.value);
        const payload = {
            title: editVideoTitle.value,
            description: editVideoDescription.value,
            tags: editVideoTags.value,
            category_id: editVideoCategory.value,
            privacy_status: editVideoPrivacy.value
        };

        try {
            const res = await fetch(`/api/videos/${videoId}/update`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error("Failed to save changes");
            showToast("Metadata saved successfully!", "success");
            metadataModal.style.display = "none";
            loadVideos();
        } catch (err) {
            showToast(err.message, "error");
        }
    };

    btnApproveAndUpload.onclick = async () => {
        const videoId = parseInt(editVideoId.value);
        // First save metadata
        const payload = {
            title: editVideoTitle.value,
            description: editVideoDescription.value,
            tags: editVideoTags.value,
            category_id: editVideoCategory.value,
            privacy_status: editVideoPrivacy.value
        };

        try {
            await fetch(`/api/videos/${videoId}/update`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            metadataModal.style.display = "none";
            await triggerApprove(videoId);
        } catch (err) {
            showToast(err.message, "error");
        }
    };

    // --- Dropzone Handling ---
    fileDropzone.onclick = () => fileInput.click();
    fileInput.onchange = (e) => {
        if (e.target.files.length > 0) {
            uploadDirectFile(e.target.files[0]);
        }
    };

    fileDropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        fileDropzone.classList.add("dragover");
    });
    fileDropzone.addEventListener("dragleave", () => {
        fileDropzone.classList.remove("dragover");
    });
    fileDropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        fileDropzone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            uploadDirectFile(e.dataTransfer.files[0]);
        }
    });

    function uploadDirectFile(file) {
        const formData = new FormData();
        formData.append("file", file);

        dropzoneProgress.style.display = "block";
        dropzoneProgressBar.style.width = "0%";
        dropzoneProgressText.textContent = `Uploading ${file.name}...`;

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/upload", true);

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                dropzoneProgressBar.style.width = `${percent}%`;
                dropzoneProgressText.textContent = `Uploading ${percent}%...`;
            }
        };

        xhr.onload = () => {
            dropzoneProgress.style.display = "none";
            if (xhr.status === 200) {
                showToast(`'${file.name}' added to watch folder! Agent will process it shortly.`, "success");
                loadVideos();
                loadStatus();
            } else {
                showToast(`Upload failed: ${xhr.responseText}`, "error");
            }
        };

        xhr.onerror = () => {
            dropzoneProgress.style.display = "none";
            showToast("Network error during file upload", "error");
        };

        xhr.send(formData);
    }

    // --- Filter Controls ---
    filterButtons.forEach(btn => {
        btn.onclick = () => {
            filterButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentFilter = btn.dataset.filter;
            renderVideos();
        };
    });

    // --- Scan Button ---
    btnScanFolder.onclick = async () => {
        try {
            btnScanFolder.classList.add("loading");
            const res = await fetch("/api/scan", { method: "POST" });
            const data = await res.json();
            showToast("Scanning folder for new video files...", "info");
            setTimeout(loadVideos, 1500);
        } catch (err) {
            showToast("Error triggering scan", "error");
        } finally {
            btnScanFolder.classList.remove("loading");
        }
    };

    // --- Auth Modal & OAuth ---
    btnConnectYouTube.onclick = () => {
        authModal.style.display = "flex";
        authStatusAlert.style.display = "none";
    };
    btnCloseAuthModal.onclick = () => authModal.style.display = "none";
    btnCloseAuthModalBottom.onclick = () => authModal.style.display = "none";

    secretDropzone.onclick = () => secretFileInput.click();
    secretFileInput.onchange = async (e) => {
        if (e.target.files.length > 0) {
            const file = e.target.files[0];
            const formData = new FormData();
            formData.append("file", file);
            try {
                const res = await fetch("/api/auth/client-secrets", { method: "POST", body: formData });
                if (!res.ok) throw new Error("Failed to save file");
                showToast("client_secrets.json saved successfully!", "success");
                loadStatus();
            } catch (err) {
                showToast(err.message, "error");
            }
        }
    };

    btnSaveClientSecret.onclick = async () => {
        const jsonText = rawSecretJson.value.trim();
        if (!jsonText) return showToast("Please paste valid JSON", "warning");

        const formData = new FormData();
        formData.append("raw_json", jsonText);
        try {
            const res = await fetch("/api/auth/client-secrets", { method: "POST", body: formData });
            if (!res.ok) throw new Error("Invalid client secrets JSON");
            showToast("client_secrets.json saved successfully!", "success");
            rawSecretJson.value = "";
            loadStatus();
        } catch (err) {
            showToast(err.message, "error");
        }
    };

    btnTriggerOAuth.onclick = async () => {
        try {
            authStatusAlert.style.display = "block";
            authStatusAlert.className = "auth-alert";
            authStatusAlert.innerHTML = "⏳ Opening browser authorization window... Please sign in with your Google Account and allow YouTube Upload permission.";

            const res = await fetch("/api/auth/start", { method: "POST" });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to start OAuth");
            showToast("Google sign-in window launched", "info");
        } catch (err) {
            authStatusAlert.style.display = "block";
            authStatusAlert.className = "auth-alert badge-danger";
            authStatusAlert.textContent = `Error: ${err.message}`;
            showToast(err.message, "error");
        }
    };

    // --- Settings Modal ---
    btnOpenSettings.onclick = async () => {
        try {
            const res = await fetch("/api/settings");
            const data = await res.json();
            settingWatchFolder.value = data.watch_folder;
            settingProcessedFolder.value = data.processed_folder;
            settingDefaultPrivacy.value = data.default_privacy;
            settingGeminiApiKey.value = data.gemini_api_key;
            settingGeminiModel.value = data.gemini_model;
            settingAutoUpload.checked = data.auto_upload;
            settingsModal.style.display = "flex";
        } catch (err) {
            showToast("Failed to load settings", "error");
        }
    };

    btnCloseSettingsModal.onclick = () => settingsModal.style.display = "none";
    btnCancelSettings.onclick = () => settingsModal.style.display = "none";

    btnSaveSettings.onclick = async () => {
        const payload = {
            watch_folder: settingWatchFolder.value.trim(),
            processed_folder: settingProcessedFolder.value.trim(),
            default_privacy: settingDefaultPrivacy.value,
            gemini_api_key: settingGeminiApiKey.value.trim(),
            gemini_model: settingGeminiModel.value,
            auto_upload: settingAutoUpload.checked
        };

        try {
            const res = await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error("Failed to save settings");
            showToast("Settings updated successfully!", "success");
            settingsModal.style.display = "none";
            loadStatus();
        } catch (err) {
            showToast(err.message, "error");
        }
    };

    btnClearLogs.onclick = () => {
        terminalLogs.innerHTML = "";
    };

    // --- WebSocket Connection ---
    function connectWebSocket() {
        if (wsReconnectTimeout) clearTimeout(wsReconnectTimeout);

        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log("WebSocket connected");
            // Keepalive ping every 25s
            setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send("ping");
                }
            }, 25000);
        };

        ws.onmessage = (event) => {
            if (event.data === "pong") return;

            try {
                const message = JSON.parse(event.data);
                handleWsEvent(message);
            } catch (err) {
                console.error("Failed to parse WS message:", err);
            }
        };

        ws.onclose = () => {
            console.warn("WebSocket disconnected. Reconnecting in 3s...");
            wsReconnectTimeout = setTimeout(connectWebSocket, 3000);
        };

        ws.onerror = (err) => {
            console.error("WebSocket error:", err);
            ws.close();
        };
    }

    function handleWsEvent(msg) {
        const eventType = msg.event;
        const data = msg.data;

        if (eventType === "video_created") {
            videos.unshift(data);
            renderVideos();
            loadStatus();
            showToast(`New video discovered: ${data.filename}`, "info");
        } else if (eventType === "video_updated") {
            const idx = videos.findIndex(v => v.id === data.id);
            if (idx !== -1) {
                videos[idx] = data;
            } else {
                videos.unshift(data);
            }
            renderVideos();
            loadStatus();
        } else if (eventType === "upload_progress") {
            const video = videos.find(v => v.id === data.id);
            if (video) {
                video.upload_progress = data.progress;
                const card = document.getElementById(`videoCard-${data.id}`);
                if (card) {
                    const bar = card.querySelector(".video-upload-bar");
                    if (bar) bar.style.width = `${data.progress}%`;
                }
            }
        } else if (eventType === "video_deleted") {
            videos = videos.filter(v => v.id !== data.id);
            renderVideos();
            loadStatus();
        } else if (eventType === "auth_success") {
            showToast(`YouTube channel connected: ${data.title}!`, "success");
            renderChannelProfile(data);
            authModal.style.display = "none";
        } else if (eventType === "auth_error") {
            showToast(`YouTube auth failed: ${data.error}`, "error");
        }

        // Live log events
        if (msg.level && msg.message) {
            appendLogEntry(msg);
            scrollTerminalBottom();
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Bootstrap
    loadStatus();
    loadVideos();
    loadLogs();
    connectWebSocket();

    // Periodic safety poll
    setInterval(() => {
        loadStatus();
        loadVideos();
    }, 10000);
});
