(() => {
  const recipe = document.getElementById("recipe");
  const prompt = document.getElementById("prompt");
  if (recipe && prompt) {
    recipe.addEventListener("change", () => {
      if (recipe.value) prompt.value = recipe.value;
    });
  }

  const grid = document.getElementById("image-grid");
  const densityButtons = [...document.querySelectorAll("[data-density]")];
  const layoutButtons = [...document.querySelectorAll("[data-layout]")];
  const preference = (key, fallback) => {
    try { return localStorage.getItem(key) || fallback; } catch (_) { return fallback; }
  };
  const applyChoice = (buttons, value, dataKey, classes) => {
    if (!grid) return;
    classes.forEach(name => grid.classList.remove(name));
    grid.classList.add(value);
    buttons.forEach(button => {
      const selected = button.dataset[dataKey] === value;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  };
  if (grid) {
    applyChoice(densityButtons, preference("mac-image-lab-density", "medium"), "density", ["large", "medium", "compact"]);
    applyChoice(layoutButtons, preference("mac-image-lab-layout", "natural"), "layout", ["natural", "cropped"]);
    densityButtons.forEach(button => button.addEventListener("click", () => {
      const value = button.dataset.density;
      applyChoice(densityButtons, value, "density", ["large", "medium", "compact"]);
      try { localStorage.setItem("mac-image-lab-density", value); } catch (_) {}
    }));
    layoutButtons.forEach(button => button.addEventListener("click", () => {
      const value = button.dataset.layout;
      applyChoice(layoutButtons, value, "layout", ["natural", "cropped"]);
      try { localStorage.setItem("mac-image-lab-layout", value); } catch (_) {}
    }));
  }
  const filterToggle = document.getElementById("filter-toggle");
  const filterPanel = document.getElementById("filter-panel");
  if (filterToggle && filterPanel) {
    filterToggle.addEventListener("click", () => {
      const opening = filterPanel.hidden;
      filterPanel.hidden = !opening;
      filterToggle.setAttribute("aria-expanded", String(opening));
      if (opening) filterPanel.querySelector("input, select")?.focus();
    });
  }

  const list = document.getElementById("queue-list");
  const connection = document.getElementById("queue-connection");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  if (!list || !connection) return;

  let delay = 2000;
  const terminal = new Set(["succeeded", "failed", "cancelled"]);

  function text(tag, value, className) {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  }

  async function mutate(job, action) {
    const response = await fetch(`/api/jobs/${job.id}/${action}`, {
      method: "POST",
      headers: {"Accept": "application/json", "X-CSRF-Token": csrf}
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Queue action failed");
    return payload;
  }

  function render(jobs) {
    list.replaceChildren();
    if (!jobs.length) {
      list.append(text("p", "No generation jobs yet.", "empty"));
      return;
    }
    for (const job of jobs) {
      const article = document.createElement("article");
      article.className = "queue-job";
      const heading = text("h2", `${job.kind.replaceAll("_", " ")} · ${job.state}`);
      const link = document.createElement("a");
      link.href = `/runs/${job.run_id}`;
      link.textContent = `Open run ${job.run_id.slice(0, 8)}`;
      const timing = text("p", job.heartbeat_at ? `Last worker contact ${job.heartbeat_at}` : `Queued ${job.created_at}`);
      article.append(heading, link, timing);
      if (job.status_detail) article.append(text("p", job.status_detail, "notice"));
      const actions = document.createElement("div");
      actions.className = "actions";
      if (["queued", "running"].includes(job.state)) {
        const cancel = text("button", "Cancel safely", "secondary");
        cancel.type = "button";
        cancel.addEventListener("click", async () => {
          cancel.disabled = true;
          try { await mutate(job, "cancel"); await poll(); }
          catch (error) { connection.textContent = error.message; cancel.disabled = false; }
        });
        actions.append(cancel);
      }
      if (["failed", "cancelled", "needs_attention"].includes(job.state)) {
        const retry = text("button", "Create linked retry", "secondary");
        retry.type = "button";
        retry.addEventListener("click", async () => {
          retry.disabled = true;
          try { const next = await mutate(job, "retry"); location.href = `/runs/${next.run_id}`; }
          catch (error) { connection.textContent = error.message; retry.disabled = false; }
        });
        actions.append(retry);
      }
      if (actions.childNodes.length) article.append(actions);
      list.append(article);
    }
  }

  async function poll() {
    try {
      const response = await fetch("/api/jobs", {headers: {"Accept": "application/json"}, cache: "no-store"});
      if (!response.ok) throw new Error(`Queue returned ${response.status}`);
      const payload = await response.json();
      render(payload.jobs);
      connection.textContent = payload.jobs.some(job => !terminal.has(job.state)) ? "Queue connected · active work updates automatically" : "Queue connected";
      delay = Math.max(1000, (payload.poll_after_seconds || 2) * 1000);
    } catch (error) {
      connection.textContent = "Queue connection lost. Retrying without resubmitting work…";
      delay = Math.min(delay * 2, 30000);
    } finally {
      window.setTimeout(poll, delay);
    }
  }

  poll();
})();
