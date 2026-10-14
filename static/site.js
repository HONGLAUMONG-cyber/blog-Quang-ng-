document.addEventListener("DOMContentLoaded", () => {
  const editor = document.querySelector("[data-rich-editor]");
  const bodyInput = document.querySelector("[data-body-input]");
  const editorForm = document.querySelector("[data-editor-form]");

  if (editor && bodyInput && editorForm) {
    const toolbar = document.querySelector(".rich-toolbar");
    const inlinePicker = document.querySelector("[data-inline-picker]");
    const inlineFilesInput = document.querySelector("[data-inline-media-files]");
    const inlineRefsInput = document.querySelector("[data-inline-media-refs]");
    let savedRange = null;
    const inlineFiles = new Map();

    const saveSelection = () => {
      const selection = window.getSelection();
      if (selection?.rangeCount && editor.contains(selection.anchorNode)) {
        savedRange = selection.getRangeAt(0).cloneRange();
      }
    };

    const restoreSelection = () => {
      if (!savedRange) return;
      editor.focus();
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(savedRange);
    };

    const insertAtSelection = (node) => {
      restoreSelection();
      let range = savedRange;
      if (!range || !editor.contains(range.startContainer)) {
        range = document.createRange();
        range.selectNodeContents(editor);
        range.collapse(false);
      }
      range.deleteContents();
      range.insertNode(node);
      range.setStartAfter(node);
      range.collapse(true);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      savedRange = range.cloneRange();
    };

    const getEmbedUrl = (url) => {
      const host = url.hostname.toLowerCase();
      let videoId = null;
      if (host === "youtu.be") {
        videoId = url.pathname.split("/").filter(Boolean)[0];
      } else if (
        host === "youtube.com" ||
        host === "www.youtube.com" ||
        host === "m.youtube.com" ||
        host === "youtube-nocookie.com" ||
        host === "www.youtube-nocookie.com"
      ) {
        videoId = url.searchParams.get("v")
          || url.pathname.match(/^\/(?:embed|shorts|live)\/([^/]+)/)?.[1];
      }
      if (videoId && /^[\w-]{11}$/.test(videoId)) {
        return new URL(`https://www.youtube-nocookie.com/embed/${videoId}`);
      }
      if (host === "vimeo.com" || host === "www.vimeo.com") {
        const match = url.pathname.match(/^\/(\d+)(?:\/([a-zA-Z0-9]+))?/);
        if (match) {
          const embedUrl = new URL(`https://player.vimeo.com/video/${match[1]}`);
          if (match[2]) embedUrl.searchParams.set("h", match[2]);
          return embedUrl;
        }
      }
      return url;
    };

    toolbar?.addEventListener("mousedown", (event) => {
      if (event.target instanceof Element && event.target.closest("button")) {
        saveSelection();
        event.preventDefault();
      }
    });

    editorForm.addEventListener("submit", () => {
      bodyInput.value = editor.innerHTML;
      const markers = Array.from(editor.querySelectorAll("[data-inline-media-ref]"));
      const transfer = new DataTransfer();
      const refs = [];
      markers.forEach((marker) => {
        const ref = marker.getAttribute("data-inline-media-ref");
        const file = ref ? inlineFiles.get(ref) : null;
        if (ref && file) {
          refs.push(ref);
          transfer.items.add(file);
        }
      });
      if (inlineFilesInput) inlineFilesInput.files = transfer.files;
      if (inlineRefsInput) inlineRefsInput.value = JSON.stringify(refs);
    });

    document.querySelectorAll("[data-command]").forEach((button) => {
      button.addEventListener("click", () => {
        const command = button.dataset.command;
        let value = button.dataset.value || null;
        if (command === "createLink") {
          value = window.prompt("Dán đường dẫn https://");
          if (!value) return;
          if (!/^https?:\/\//i.test(value)) value = `https://${value}`;
        }
        restoreSelection();
        document.execCommand(command, false, value);
        saveSelection();
      });
    });

    document.querySelectorAll("[data-insert-media]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!inlinePicker) return;
        inlinePicker.accept = button.dataset.insertMedia === "video"
          ? "video/mp4,video/webm,video/quicktime"
          : "image/jpeg,image/png,image/webp,image/gif";
        inlinePicker.click();
      });
    });

    document.querySelectorAll("[data-insert-media-link]").forEach((button) => {
      button.addEventListener("click", () => {
        const kind = button.dataset.insertMediaLink;
        const rawUrl = window.prompt(
          kind === "image"
            ? "Dán URL HTTPS trực tiếp của ảnh:"
            : kind === "video"
              ? "Dán URL HTTPS của tệp video hoặc trang nhúng:"
              : "Dán URL HTTPS của trang nhúng:"
        );
        if (!rawUrl) return;

        let url;
        try {
          url = new URL(rawUrl.trim());
        } catch {
          window.alert("Đường dẫn không hợp lệ. Hãy dùng URL đầy đủ bắt đầu bằng https://");
          return;
        }
        if (url.protocol !== "https:" || !url.hostname || url.username || url.password) {
          window.alert("Chỉ chấp nhận URL HTTPS hợp lệ.");
          return;
        }

        let node;
        if (kind === "image") {
          node = document.createElement("img");
          node.src = url.href;
          node.alt = url.hostname;
          node.loading = "lazy";
        } else if (
          kind === "video" &&
          /\.(mp4|webm|mov)$/i.test(url.pathname)
        ) {
          node = document.createElement("video");
          node.src = url.href;
          node.controls = true;
          node.playsInline = true;
          node.preload = "metadata";
        } else {
          node = document.createElement("iframe");
          const embedUrl = kind === "video" ? getEmbedUrl(url) : url;
          node.src = embedUrl.href;
          node.title = "Nội dung nhúng từ " + embedUrl.hostname;
          node.loading = "lazy";
          node.referrerPolicy = "strict-origin-when-cross-origin";
          node.setAttribute("sandbox", "allow-scripts allow-presentation");
          node.allowFullscreen = true;
        }
        insertAtSelection(node);
      });
    });

    inlinePicker?.addEventListener("change", () => {
      const files = Array.from(inlinePicker.files || []);
      if (!files.length) return;
      restoreSelection();
      let range = savedRange;
      if (!range || !editor.contains(range.startContainer)) {
        range = document.createRange();
        range.selectNodeContents(editor);
        range.collapse(false);
      }
      files.forEach((file) => {
        const token = crypto.randomUUID().replaceAll("-", "");
        const marker = document.createElement("span");
        marker.className = "pending-inline-media";
        marker.dataset.inlineMediaRef = token;
        const label = document.createElement("span");
        label.textContent = `${file.type.startsWith("video/") ? "Video" : "Ảnh"} sẽ được chèn: ${file.name}`;
        marker.append(label);
        range.deleteContents();
        range.insertNode(marker);
        inlineFiles.set(token, file);

        range.setStartAfter(marker);
        range.collapse(true);
      });
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      savedRange = range.cloneRange();
      inlinePicker.value = "";
    });
  }

  document.querySelectorAll("[data-confirm]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (!window.confirm(button.dataset.confirm)) event.preventDefault();
    });
  });

  const coverInput = document.querySelector('input[name="cover"]');
  const coverName = document.querySelector("[data-file-name]");
  coverInput?.addEventListener("change", () => {
    if (coverName) coverName.textContent = coverInput.files?.[0]?.name || "";
  });

  const mediaInput = document.querySelector("[data-media-input]");
  const mediaNames = document.querySelector("[data-media-names]");
  mediaInput?.addEventListener("change", () => {
    if (mediaNames) {
      mediaNames.textContent = Array.from(mediaInput.files || [])
        .map((file) => file.name)
        .join(", ");
    }
  });
});
