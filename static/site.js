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
