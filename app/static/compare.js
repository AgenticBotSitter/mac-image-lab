(() => {
  const sideButton = document.getElementById("side-by-side-button");
  const sliderButton = document.getElementById("slider-button");
  const side = document.getElementById("compare-side-by-side");
  const slider = document.getElementById("compare-slider-view");
  if (!sideButton || !sliderButton || !side || !slider) return;

  const sync = document.getElementById("sync-zoom");
  const reset = document.getElementById("compare-reset");
  const position = document.getElementById("compare-position");
  const overlay = document.getElementById("compare-overlay");
  const viewports = [...document.querySelectorAll("[data-compare-viewport]")];
  const states = new Map(viewports.map(viewport => [viewport, {scale: 1, x: 0, y: 0}]));

  const setMode = showSlider => {
    side.hidden = showSlider;
    slider.hidden = !showSlider;
    sideButton.classList.toggle("active", !showSlider);
    sliderButton.classList.toggle("active", showSlider);
    sideButton.setAttribute("aria-pressed", String(!showSlider));
    sliderButton.setAttribute("aria-pressed", String(showSlider));
  };
  sideButton.addEventListener("click", () => setMode(false));
  sliderButton.addEventListener("click", () => setMode(true));
  position?.addEventListener("input", () => overlay.style.setProperty("--position", `${position.value}%`));

  const render = viewport => {
    const state = states.get(viewport);
    viewport.querySelectorAll("img").forEach(image => {
      image.style.transform = `translate3d(${state.x}px, ${state.y}px, 0) scale(${state.scale})`;
    });
  };
  const update = (viewport, next) => {
    const targets = sync?.checked ? viewports : [viewport];
    targets.forEach(target => {
      const state = states.get(target);
      Object.assign(state, next);
      if (state.scale <= 1) { state.scale = 1; state.x = 0; state.y = 0; }
      state.scale = Math.min(5, state.scale);
      render(target);
    });
  };
  reset?.addEventListener("click", () => viewports.forEach(viewport => update(viewport, {scale: 1, x: 0, y: 0})));

  viewports.forEach(viewport => {
    let drag = null;
    viewport.addEventListener("wheel", event => {
      event.preventDefault();
      const state = states.get(viewport);
      update(viewport, {scale: state.scale + (event.deltaY < 0 ? .2 : -.2)});
    }, {passive: false});
    viewport.addEventListener("pointerdown", event => {
      viewport.setPointerCapture(event.pointerId);
      const state = states.get(viewport);
      drag = {clientX: event.clientX, clientY: event.clientY, x: state.x, y: state.y};
    });
    viewport.addEventListener("pointermove", event => {
      const state = states.get(viewport);
      if (!drag || state.scale <= 1) return;
      update(viewport, {x: drag.x + event.clientX - drag.clientX, y: drag.y + event.clientY - drag.clientY});
    });
    ["pointerup", "pointercancel"].forEach(type => viewport.addEventListener(type, () => { drag = null; }));
  });
})();
