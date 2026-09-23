(() => {
  const connectionBanner = document.getElementById("connection-banner");
  const setConnectionState = online => {
    if (!connectionBanner) return;
    connectionBanner.hidden = online;
  };
  const checkConnection = async () => {
    if (!navigator.onLine) return setConnectionState(false);
    try {
      const response = await fetch("/healthz", {headers: {"Accept": "application/json"}, cache: "no-store"});
      setConnectionState(response.ok);
    } catch (_) {
      setConnectionState(false);
    }
  };
  window.addEventListener("online", checkConnection);
  window.addEventListener("offline", () => setConnectionState(false));
  window.setTimeout(checkConnection, 2000);
  if ("serviceWorker" in navigator && window.isSecureContext && location.protocol === "https:") {
    window.addEventListener("load", () => {
      window.setTimeout(() => navigator.serviceWorker.register("/service-worker.js", {scope: "/"}).catch(() => {}), 1500);
    });
  }

  const draftFields = ["prompt", "model_id", "profile", "aspect", "library_folder", "width", "height", "steps", "seed"];
  const draftForm = document.getElementById("generation-form");
  const draftKey = `mac-image-lab-draft:${location.pathname}`;
  if (draftForm) {
    let draft = {};
    try { draft = JSON.parse(localStorage.getItem(draftKey) || "{}"); } catch (_) {}
    for (const name of draftFields) {
      const field = draftForm.elements.namedItem(name);
      if (field && typeof draft[name] === "string") field.value = draft[name];
    }
    const saveDraft = () => {
      const values = {};
      for (const name of draftFields) {
        const field = draftForm.elements.namedItem(name);
        if (field) values[name] = field.value;
      }
      try { localStorage.setItem(draftKey, JSON.stringify(values)); } catch (_) {}
    };
    draftForm.addEventListener("input", saveDraft);
    draftForm.addEventListener("change", saveDraft);
  }

  const recipe = document.getElementById("recipe");
  const prompt = document.getElementById("prompt");
  const applyRecipe = document.getElementById("apply-recipe");
  const recipeStatus = document.getElementById("recipe-status");
  const generationForm = document.getElementById("generation-form");
  const profile = document.getElementById("profile");
  const aspect = document.getElementById("aspect");
  const model = document.getElementById("model-id");
  const collection = document.getElementById("library-folder");
  const widthInput = generationForm?.querySelector("input[name='width']");
  const heightInput = generationForm?.querySelector("input[name='height']");
  const estimate = document.getElementById("queue-estimate");
  const overrideIndicator = document.getElementById("override-indicator");
  let promptDirty = false;
  let pendingRecipe = "";

  const updateDimensions = () => {
    if (!profile || !aspect || !widthInput || !heightInput || aspect.value === "custom") return;
    const option = profile.selectedOptions[0];
    const shape = aspect.value;
    widthInput.value = option.dataset[`${shape}Width`] || "";
    heightInput.value = option.dataset[`${shape}Height`] || "";
    if (overrideIndicator) overrideIndicator.textContent = "";
  };
  const updateEstimate = () => {
    if (!estimate || !profile) return;
    const active = Number(estimate.dataset.activeJobs || 0);
    estimate.textContent = `Estimated ${profile.selectedOptions[0].dataset.expected}. ${active ? `${active} active job${active === 1 ? "" : "s"} ahead or running.` : "Queue is currently clear."}`;
  };
  const applySelectedRecipe = () => {
    const option = recipe?.selectedOptions[0];
    if (!option || !prompt) return;
    prompt.value = option.dataset.prompt || "";
    if (profile && option.dataset.profile) profile.value = option.dataset.profile;
    if (aspect && option.dataset.aspect) aspect.value = option.dataset.aspect;
    if (model && option.dataset.model && [...model.options].some(item => item.value === option.dataset.model)) model.value = option.dataset.model;
    if (collection && option.dataset.collection && [...collection.options].some(item => item.value === option.dataset.collection)) collection.value = option.dataset.collection;
    promptDirty = false;
    pendingRecipe = "";
    updateDimensions(); updateEstimate();
    model?.dispatchEvent(new Event("change"));
    recipeStatus.textContent = "Recipe applied. Review the controls, then submit explicitly.";
  };
  if (prompt) prompt.addEventListener("input", () => { promptDirty = true; pendingRecipe = ""; });
  if (recipe && applyRecipe) {
    recipe.addEventListener("change", () => { pendingRecipe = ""; });
    applyRecipe.addEventListener("click", () => {
      if (promptDirty && pendingRecipe !== recipe.value) {
        pendingRecipe = recipe.value;
        recipeStatus.textContent = "This will replace your edited prompt. Press Use recipe again to confirm.";
        return;
      }
      applySelectedRecipe();
    });
  }
  profile?.addEventListener("change", () => { updateDimensions(); updateEstimate(); });
  aspect?.addEventListener("change", updateDimensions);
  [widthInput, heightInput].forEach(input => input?.addEventListener("input", () => {
    if (aspect) aspect.value = "custom";
    if (overrideIndicator) overrideIndicator.textContent = "· custom size";
  }));
  model?.addEventListener("change", () => {
    document.querySelectorAll("[data-model-guide]").forEach(guide => { guide.hidden = guide.dataset.modelGuide !== model.value; });
  });
  updateDimensions(); updateEstimate();

  const upload = document.getElementById("reference");
  const uploadPreview = document.getElementById("upload-preview");
  const uploadImage = uploadPreview?.querySelector("img");
  const uploadMetadata = document.getElementById("upload-metadata");
  const removeUpload = document.getElementById("remove-upload");
  const dropzone = document.getElementById("upload-dropzone");
  let previewUrl = "";

  // ── Prompt Wizard ──────────────────────────────────────────────
  const wizFields = ["subject", "style", "background", "composition", "lighting", "mood", "materials", "imagetext"];
  const wizChecks = ["no-text", "no-logo", "no-watermark"];
  let wizActive = false;
  let wizTimer = 0;

  let _wizWriting = false;

  const wizGet = (id) => document.getElementById(`wiz-${id}`);
  const composePrompt = () => {
    const parts = [];
    const style = wizGet("style")?.value || "";
    const subject = (wizGet("subject")?.value || "").trim();
    const composition = wizGet("composition")?.value || "";
    const background = (wizGet("background")?.value || "").trim();
    const lighting = wizGet("lighting")?.value || "";
    const mood = (wizGet("mood")?.value || "").trim();
    const materials = (wizGet("materials")?.value || "").trim();
    const imagetext = (wizGet("imagetext")?.value || "").trim();
    const exclusions = wizChecks
      .map((id) => wizGet(id))
      .filter((el) => el?.checked)
      .map((el) => {
        if (el.id === "wiz-no-text") return "no readable text";
        if (el.id === "wiz-no-logo") return "no logo";
        if (el.id === "wiz-no-watermark") return "no watermark";
        return "";
      })
      .filter(Boolean);

    let opener = "";
    if (style || subject) {
      const medium = style || "image";
      const article = /^[aeiou]/i.test(medium) ? "An" : "A";
      opener = `${article} ${medium}`;
      if (subject) opener += ` of ${subject}`;
      if (composition) opener += `, ${composition}`;
      opener += ".";
    }

    if (opener) parts.push(opener);
    if (background) parts.push(`The setting is ${background}.`);
    if (lighting) parts.push(`${lighting.charAt(0).toUpperCase() + lighting.slice(1)}.`);
    if (materials) parts.push(`Visible textures include ${materials}.`);
    if (mood) parts.push(`The composition is ${mood}.`);
    if (imagetext) parts.push(`The image contains the text "${imagetext}".`);
    if (exclusions.length) parts.push(exclusions.join(", ") + ".");

    const result = parts.join(" ");
    if (result && prompt) {
      _wizWriting = true;
      prompt.value = result;
      promptDirty = false;
      _wizWriting = false;
    }
  };

  const wizInputHandler = () => {
    if (!wizActive) return;
    clearTimeout(wizTimer);
    wizTimer = setTimeout(composePrompt, 120);
  };

  if (prompt && wizGet("subject")) {
    // Attach listeners to all wizard fields
    wizFields.forEach((id) => {
      const el = wizGet(id);
      if (el) el.addEventListener("input", wizInputHandler);
    });
    wizChecks.forEach((id) => {
      const el = wizGet(id);
      if (el) el.addEventListener("change", wizInputHandler);
    });

    // Track whether wizard is open
    const wizardDetails = document.getElementById("prompt-wizard");
    if (wizardDetails) {
      wizardDetails.addEventListener("toggle", () => {
        wizActive = wizardDetails.open;
        if (wizActive) composePrompt();
      });
    }

    // If the user types directly in the prompt box, stop wizard sync
    prompt.addEventListener("input", () => {
      if (_wizWriting) return;
      promptDirty = true;
      pendingRecipe = "";
      wizActive = false;
    });
    // Re-enable wizard when any wizard field changes after manual edit
    const reenableWizard = () => {
      if (promptDirty) {
        wizActive = true;
        promptDirty = false;
      }
    };
    wizFields.forEach((id) => {
      const el = wizGet(id);
      if (el) el.addEventListener("focus", reenableWizard);
    });
    wizChecks.forEach((id) => {
      const el = wizGet(id);
      if (el) el.addEventListener("focus", reenableWizard);
    });
  }
  // ── End Prompt Wizard ──────────────────────────────────────────

  // ── Quality Bar ────────────────────────────────────────────────
  const pqBar = document.getElementById("pq-fill");
  const pqLabel = document.getElementById("pq-label");
  const charCount = document.getElementById("prompt-char-count");
  const updateQualityBar = () => {
    const len = prompt?.value?.length || 0;
    if (charCount) charCount.textContent = `${len} chars`;
    const pct = Math.min(len / 400, 1);
    if (pqBar) pqBar.style.width = `${pct * 100}%`;
    if (pqLabel) {
      if (len < 100) pqLabel.textContent = "Short — add more detail for best results";
      else if (len < 300) pqLabel.textContent = "Good — enough detail for a solid result";
      else pqLabel.textContent = "Excellent — detailed prompt, model has plenty to work with";
    }
    const bar = document.getElementById("prompt-quality-bar");
    if (bar) bar.className = `prompt-quality ${len < 100 ? "pq-short" : len < 300 ? "pq-good" : "pq-great"}`;
  };
  if (prompt) {
    prompt.addEventListener("input", updateQualityBar);
    updateQualityBar();
  }

  // ── Copy Button ────────────────────────────────────────────────
  const copyBtn = document.getElementById("copy-prompt-btn");
  if (copyBtn && prompt) {
    prompt.addEventListener("input", () => { copyBtn.hidden = !(prompt.value?.length > 0); });
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(prompt.value);
        copyBtn.textContent = "✅ Copied";
        setTimeout(() => { copyBtn.textContent = "📋 Copy"; }, 2000);
      } catch (_) {
        prompt.select();
        document.execCommand("copy");
        copyBtn.textContent = "✅ Copied";
        setTimeout(() => { copyBtn.textContent = "📋 Copy"; }, 2000);
      }
    });
    // Initialize visibility
    copyBtn.hidden = !(prompt.value?.length > 0);
  }

  // ── Templates ─────────────────────────────────────────────────
  let allTemplates = { bundled: [], user: [] };

  const loadTemplates = async () => {
    try {
      const r = await fetch("/api/templates", { headers: { "Accept": "application/json" } });
      if (r.ok) allTemplates = await r.json();
    } catch (_) {}
    renderUserTemplates();
  };

  const renderUserTemplates = () => {
    const quick = document.getElementById("user-template-quick");
    if (!quick) return;
    quick.innerHTML = allTemplates.user.map(t =>
      `<button type="button" class="secondary sm" data-template-id="${t.id}">🔖 ${t.name}</button>`
    ).join("");
    // Rebind clicks
    quick.querySelectorAll("button").forEach(btn =>
      btn.addEventListener("click", () => applyTemplate(btn.dataset.templateId))
    );
  };

  const findTemplate = (id) => {
    return allTemplates.bundled.find(t => t.id === id) ||
           allTemplates.user.find(t => t.id === id);
  };

  const applyTemplate = (id) => {
    const t = findTemplate(id);
    if (!t) return;
    const { fields = {}, exclusions = {}, profile, aspect } = t;
    for (const [key, value] of Object.entries(fields)) {
      const el = wizGet(key);
      if (!el) continue;
      if (el.tagName === "SELECT") el.value = el.querySelector(`option[value="${CSS.escape(value)}"]`) ? value : "";
      else el.value = value;
    }
    for (const [key, checked] of Object.entries(exclusions)) {
      const el = wizGet(key);
      if (el) el.checked = checked;
    }
    if (profile) document.getElementById("profile")?.value in (document.getElementById("profile")?.options || []) && (document.getElementById("profile").value = profile);
    if (aspect) document.getElementById("aspect").value = aspect;
    if (wizActive !== undefined) { wizActive = true; composePrompt?.(); }
    // Open the wizard
    const wizard = document.getElementById("prompt-wizard");
    if (wizard) wizard.open = true;
  };

  // Quick template buttons
  document.querySelectorAll("[data-template-id]").forEach(btn =>
    btn.addEventListener("click", () => applyTemplate(btn.dataset.templateId))
  );

  // Load template dropdown
  const loadBtn = document.getElementById("template-load-btn");
  if (loadBtn) {
    loadBtn.addEventListener("click", () => {
      const all = [...allTemplates.bundled, ...allTemplates.user];
      if (!all.length) { alert("No templates available."); return; }
      const names = all.map((t, i) => `${i + 1}. ${t.icon} ${t.name} — ${t.description}`).join("\n");
      const pick = prompt(`Choose a template (1-${all.length}):\n\n${names}`);
      const idx = parseInt(pick) - 1;
      if (idx >= 0 && idx < all.length) applyTemplate(all[idx].id);
    });
  }
  loadTemplates();

  // Save as template
  const saveTemplateBtn = document.getElementById("wiz-save-template");
  saveTemplateBtn?.addEventListener("click", async () => {
    const name = prompt("Template name:");
    if (!name) return;
    const fields = {};
    wizFields.forEach(id => {
      const el = wizGet(id);
      if (el) fields[id] = el.value || "";
    });
    const exclusions = {};
    wizChecks.forEach(id => {
      const el = wizGet(id);
      if (el) exclusions[id] = el.checked;
    });
    const body = {
      name,
      description: "",
      fields,
      exclusions,
      profile: document.getElementById("profile")?.value || "standard",
      aspect: document.getElementById("aspect")?.value || "square",
    };
    try {
      const r = await fetch("/api/user-templates", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) { await loadTemplates(); alert(`Template "${name}" saved.`); }
      else throw new Error((await r.json()).error);
    } catch (e) { alert(`Failed to save: ${e.message}`); }
  });

  // ── Snippets ──────────────────────────────────────────────────
  let snippets = {};

  const loadSnippets = async () => {
    try {
      const r = await fetch("/api/snippets", { headers: { "Accept": "application/json" } });
      if (r.ok) snippets = await r.json();
    } catch (_) {}
    renderSnippetPills();
  };

  const saveSnippets = async (data) => {
    try {
      await fetch("/api/snippets", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(data),
      });
      snippets = data;
    } catch (_) {}
  };

  const renderSnippetPills = () => {
    document.querySelectorAll(".snippet-pills[data-field]").forEach(container => {
      const field = container.dataset.field;
      const items = snippets[field] || [];
      container.innerHTML = items.map((s, i) =>
        `<button type="button" class="snippet-pill" data-field="${field}" data-index="${i}" title="Click to insert: ${s}">${s.length > 30 ? s.slice(0, 28) + "…" : s}</button>`
      ).join("");
    });
    // Bind clicks
    document.querySelectorAll(".snippet-pill").forEach(pill => {
      pill.addEventListener("click", () => {
        const field = pill.dataset.field;
        const idx = parseInt(pill.dataset.index);
        const el = wizGet(field);
        if (!el) return;
        const snippet = (snippets[field] || [])[idx];
        if (!snippet) return;
        if (el.tagName === "SELECT") {
          el.value = el.querySelector(`option[value="${CSS.escape(snippet)}"]`) ? snippet : el.value;
        } else {
          el.value = snippet;
        }
        // Trigger composition
        wizActive = true;
        composePrompt?.();
      });
    });
  };

  // Save all as snippets
  document.getElementById("wiz-save-snippets")?.addEventListener("click", async () => {
    const newSnippets = { ...snippets };
    wizFields.forEach(id => {
      const el = wizGet(id);
      const val = el?.value?.trim?.();
      if (val && val !== "") {
        const arr = newSnippets[id] || [];
        if (!arr.includes(val)) arr.push(val);
        newSnippets[id] = arr;
      }
    });
    await saveSnippets(newSnippets);
    renderSnippetPills();
    alert("Snippets saved for all non-empty fields.");
  });

  // Manage snippets link
  document.getElementById("wiz-manage-snippets")?.addEventListener("click", (e) => {
    e.preventDefault();
    let msg = "Manage snippets — type a field name to edit (or leave blank to cancel):\n\n";
    const fields = Object.keys(snippets);
    if (!fields.length) { alert("No snippets saved yet."); return; }
    msg += fields.map((f, i) => `${i + 1}. ${f} (${snippets[f]?.length || 0} items)`).join("\n");
    msg += `\n\nEnter number to manage (1-${fields.length}):`;
    const pick = prompt(msg);
    const idx = parseInt(pick) - 1;
    if (idx < 0 || idx >= fields.length) return;
    const field = fields[idx];
    const items = snippets[field] || [];
    const action = prompt(`${field} snippets:\n${items.map((s, i) => `${i + 1}. ${s}`).join("\n")}\n\nEnter number to delete (1-${items.length}), or type a new snippet to add:`);
    if (!action) return;
    const delIdx = parseInt(action) - 1;
    if (delIdx >= 0 && delIdx < items.length) {
      items.splice(delIdx, 1);
    } else {
      items.push(action);
    }
    snippets[field] = items;
    saveSnippets(snippets).then(renderSnippetPills);
  });

  loadSnippets();

  // ── Examples ───────────────────────────────────────────────────
  let examples = [];
  const loadExamples = async () => {
    try {
      const r = await fetch("/api/examples", { headers: { "Accept": "application/json" } });
      if (r.ok) examples = await r.json();
    } catch (_) {}
  };
  loadExamples();

  document.getElementById("wiz-load-example")?.addEventListener("click", () => {
    if (!examples.length) { alert("No examples available."); return; }
    const pick = prompt(`Choose an example (1-${examples.length}):\n\n${examples.map((e, i) => `${i + 1}. ${e.name}`).join("\n")}`);
    const idx = parseInt(pick) - 1;
    if (idx < 0 || idx >= examples.length) return;
    const ex = examples[idx];
    const { fields = {}, exclusions = {}, profile, aspect } = ex;
    for (const [key, value] of Object.entries(fields)) {
      const el = wizGet(key);
      if (!el) continue;
      if (el.tagName === "SELECT") el.value = el.querySelector(`option[value="${CSS.escape(value)}"]`) ? value : "";
      else el.value = value;
    }
    for (const [key, checked] of Object.entries(exclusions)) {
      const el = wizGet(key);
      if (el) el.checked = checked;
    }
    if (profile) { const sel = document.getElementById("profile"); if (sel) sel.value = profile; }
    if (aspect) document.getElementById("aspect").value = aspect;
    wizActive = true;
    composePrompt?.();
    const wizard = document.getElementById("prompt-wizard");
    if (wizard) wizard.open = true;
  });

  // ── Clear wizard ───────────────────────────────────────────────
  document.getElementById("wiz-clear")?.addEventListener("click", () => {
    wizFields.forEach(id => {
      const el = wizGet(id);
      if (!el) return;
      if (el.tagName === "SELECT") el.value = "";
      else el.value = "";
    });
    wizChecks.forEach(id => {
      const el = wizGet(id);
      if (el) el.checked = true;
    });
    wizActive = false;
    if (prompt) { prompt.value = ""; promptDirty = false; }
    updateQualityBar();
  });

  // ── Aspect presets ────────────────────────────────────────────
  document.querySelectorAll(".mini-preset[data-preset]").forEach(btn => {
    btn.addEventListener("click", () => {
      const preset = btn.dataset.preset;
      const aspect = document.getElementById("aspect");
      if (!aspect) return;
      if (preset === "instagram-story") { aspect.value = "portrait"; }
      else if (preset === "youtube-thumb") { aspect.value = "landscape"; }
      else if (preset === "square-post") { aspect.value = "square"; }
      aspect.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  // Wire quality bar updates to composePrompt paths
  const origCompose = composePrompt;
  if (origCompose) {
    composePrompt = function() {
      origCompose.apply(this, arguments);
      updateQualityBar();
    };
  }
  // ── End Feature Set ────────────────────────────────────────────
  const showUpload = () => {
    const file = upload?.files?.[0];
    if (!file || !uploadImage || !uploadPreview) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    uploadImage.onload = () => {
      uploadMetadata.textContent = `${uploadImage.naturalWidth}×${uploadImage.naturalHeight} · ${(file.size / 1024 / 1024).toFixed(2)} MiB · ${file.type || "unknown type"}`;
    };
    uploadImage.src = previewUrl;
    uploadPreview.hidden = false;
  };
  upload?.addEventListener("change", showUpload);
  removeUpload?.addEventListener("click", () => {
    upload.value = "";
    uploadPreview.hidden = true;
    uploadImage.removeAttribute("src");
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = "";
    upload.focus();
  });
  if (dropzone && upload) {
    ["dragenter", "dragover"].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.add("dragging"); }));
    ["dragleave", "drop"].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.remove("dragging"); }));
    dropzone.addEventListener("drop", event => {
      if (!event.dataTransfer?.files?.length) return;
      upload.files = event.dataTransfer.files;
      showUpload();
    });
  }

  generationForm?.addEventListener("submit", () => {
    const submit = document.getElementById("generation-submit");
    if (submit) { submit.disabled = true; submit.textContent = "Submitting one job…"; }
  });
  const saveRecipeForm = document.getElementById("save-recipe-form");
  saveRecipeForm?.addEventListener("submit", () => {
    for (const name of ["model_id", "prompt", "profile", "aspect", "library_folder"]) {
      const source = generationForm.elements.namedItem(name);
      const destination = saveRecipeForm.elements.namedItem(name);
      if (source && destination) destination.value = source.value;
    }
  });

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
