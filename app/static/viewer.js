(() => {
  const saveToPhotos = document.querySelector("[data-save-to-photos]");
  if (saveToPhotos) {
    const status = document.getElementById("save-to-photos-status");
    saveToPhotos.addEventListener("click", async () => {
      const imageUrl = saveToPhotos.dataset.imageUrl;
      const originalLabel = saveToPhotos.textContent;
      saveToPhotos.disabled = true;
      saveToPhotos.textContent = "Preparing image…";
      try {
        const response = await fetch(imageUrl, {credentials: "same-origin", cache: "no-store"});
        if (!response.ok) throw new Error(`Image request failed (${response.status})`);
        const blob = await response.blob();
        const file = new File([blob], saveToPhotos.dataset.filename || "image.png", {type: blob.type || "image/png"});
        const payload = {files: [file], title: "Mac Image Lab image"};
        if (navigator.share && (!navigator.canShare || navigator.canShare(payload))) {
          await navigator.share(payload);
          if (status) status.textContent = "Share sheet opened. Choose Save Image to add it to Photos.";
          return;
        }
        window.open(imageUrl, "_blank", "noopener");
        if (status) status.textContent = "The image opened in a new tab. Touch and hold it, then choose Save to Photos.";
      } catch (error) {
        if (error && error.name === "AbortError") return;
        window.open(imageUrl, "_blank", "noopener");
        if (status) status.textContent = "Could not open the share sheet. Touch and hold the opened image, then choose Save to Photos.";
      } finally {
        saveToPhotos.disabled = false;
        saveToPhotos.textContent = originalLabel;
      }
    });
  }

  const opener = document.getElementById("viewer-open");
  const dialog = document.getElementById("image-viewer");
  if (!opener || !dialog) return;

  const image = document.getElementById("viewer-image");
  const stage = document.getElementById("viewer-stage");
  const close = document.getElementById("viewer-close");
  const zoomIn = document.getElementById("viewer-zoom-in");
  const zoomOut = document.getElementById("viewer-zoom-out");
  const reset = document.getElementById("viewer-reset");
  const details = document.getElementById("viewer-details");
  const metadata = document.getElementById("viewer-metadata");
  const points = new Map();
  let scale = 1;
  let x = 0;
  let y = 0;
  let dragOrigin = null;
  let pinchDistance = null;

  const render = () => {
    stage.dataset.scale = String(Number(scale.toFixed(2)));
    image.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${scale})`;
    reset.textContent = `${Math.round(scale * 100)}%`;
    zoomOut.disabled = scale <= 1;
    zoomIn.disabled = scale >= 5;
  };

  const setScale = (next) => {
    scale = Math.min(5, Math.max(1, next));
    if (scale === 1) { x = 0; y = 0; }
    render();
  };

  const resetView = () => {
    scale = 1; x = 0; y = 0; render();
  };

  const focusable = () => [...dialog.querySelectorAll("button:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])")]
    .filter(node => !node.hidden && node.getAttribute("aria-hidden") !== "true");

  opener.addEventListener("click", () => {
    if (!image.src) image.src = image.dataset.src;
    dialog.showModal();
    document.body.classList.add("viewer-open");
    close.focus();
  });

  close.addEventListener("click", () => dialog.close());
  zoomIn.addEventListener("click", () => setScale(scale + 0.25));
  zoomOut.addEventListener("click", () => setScale(scale - 0.25));
  reset.addEventListener("click", resetView);
  details.addEventListener("click", () => {
    const opening = metadata.hidden;
    metadata.hidden = !opening;
    metadata.setAttribute("aria-hidden", String(!opening));
    details.setAttribute("aria-expanded", String(opening));
  });

  dialog.addEventListener("close", () => {
    document.body.classList.remove("viewer-open");
    resetView();
    opener.focus();
  });

  dialog.addEventListener("keydown", event => {
    if (event.key === "ArrowRight" && opener.dataset.nextUrl) {
      event.preventDefault();
      window.location.assign(opener.dataset.nextUrl);
    } else if (event.key === "ArrowLeft" && opener.dataset.previousUrl) {
      event.preventDefault();
      window.location.assign(opener.dataset.previousUrl);
    } else if (event.key === "+" || event.key === "=") {
      event.preventDefault(); setScale(scale + 0.25);
    } else if (event.key === "-" || event.key === "_") {
      event.preventDefault(); setScale(scale - 0.25);
    } else if (event.key === "0") {
      event.preventDefault(); resetView();
    } else if (event.key === "Tab") {
      const nodes = focusable();
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }
  });

  stage.addEventListener("wheel", event => {
    event.preventDefault();
    setScale(scale + (event.deltaY < 0 ? 0.2 : -0.2));
  }, {passive: false});

  stage.addEventListener("pointerdown", event => {
    stage.setPointerCapture(event.pointerId);
    points.set(event.pointerId, {x: event.clientX, y: event.clientY});
    if (points.size === 1) dragOrigin = {pointerX: event.clientX, pointerY: event.clientY, x, y};
    if (points.size === 2) {
      const [a, b] = [...points.values()];
      pinchDistance = Math.hypot(a.x - b.x, a.y - b.y);
    }
  });

  stage.addEventListener("pointermove", event => {
    if (!points.has(event.pointerId)) return;
    points.set(event.pointerId, {x: event.clientX, y: event.clientY});
    if (points.size === 2) {
      const [a, b] = [...points.values()];
      const distance = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinchDistance) setScale(scale * distance / pinchDistance);
      pinchDistance = distance;
    } else if (scale > 1 && dragOrigin) {
      x = dragOrigin.x + event.clientX - dragOrigin.pointerX;
      y = dragOrigin.y + event.clientY - dragOrigin.pointerY;
      render();
    }
  });

  const endPointer = event => {
    points.delete(event.pointerId);
    dragOrigin = null;
    pinchDistance = null;
  };
  stage.addEventListener("pointerup", endPointer);
  stage.addEventListener("pointercancel", endPointer);

  render();
})();
