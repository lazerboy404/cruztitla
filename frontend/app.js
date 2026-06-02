const DEFAULT_DATE = "2026-05-29";

const MONTHS = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];

const state = {
  sessionId: null,
  processing: false,
  selectedDate: parseIsoDate(DEFAULT_DATE),
  calendarMonth: parseIsoDate(DEFAULT_DATE),
};

const els = {
  fileInput: document.querySelector("#fileInput"),
  fileName: document.querySelector("#fileName"),
  dropzone: document.querySelector("#dropzone"),
  warpedPreview: document.querySelector("#warpedPreview"),
  facePreview: document.querySelector("#facePreview"),
  credentialPreview: document.querySelector("#credentialPreview"),
  credentialForm: document.querySelector("#credentialForm"),
  generateButton: document.querySelector("#generateButton"),
  downloadLink: document.querySelector("#downloadLink"),
  formatDownloadLink: document.querySelector("#formatDownloadLink"),
  warnings: document.querySelector("#warnings"),
  serverDate: document.querySelector("#serverDate"),
  resultState: document.querySelector("#resultState"),
  nombreCompleto: document.querySelector("#nombreCompleto"),
  fechaNacimiento: document.querySelector("#fechaNacimiento"),
  equipo: document.querySelector("#equipo"),
  categoria: document.querySelector("#categoria"),
  numeroJugador: document.querySelector("#numeroJugador"),
  temporadaSuffix: document.querySelector("#temporadaSuffix"),
  lugarFecha: document.querySelector("#lugarFecha"),
  calendarButton: document.querySelector("#calendarButton"),
  calendarPopover: document.querySelector("#calendarPopover"),
  calendarTitle: document.querySelector("#calendarTitle"),
  calendarGrid: document.querySelector("#calendarGrid"),
  prevMonth: document.querySelector("#prevMonth"),
  nextMonth: document.querySelector("#nextMonth"),
  loadingOverlay: document.querySelector("#loadingOverlay"),
  loadingTitle: document.querySelector("#loadingTitle"),
  loadingText: document.querySelector("#loadingText"),
};

init();

async function init() {
  await loadOptions();
  bindEvents();
  renderCalendar();
}

async function loadOptions() {
  const response = await fetch("/api/options");
  const options = await response.json();
  fillSelect(els.equipo, options.teams);
  fillSelect(els.categoria, options.categories);
  fillSelect(els.temporadaSuffix, options.season_suffixes || ["26"]);
  els.temporadaSuffix.value = options.default_temporada_suffix || "26";

  state.selectedDate = parseIsoDate(options.credential_date_iso || DEFAULT_DATE);
  state.calendarMonth = new Date(state.selectedDate.getFullYear(), state.selectedDate.getMonth(), 1);
  updatePlaceDate();
  els.serverDate.textContent = formatPlaceDate(state.selectedDate);
}

function fillSelect(select, values) {
  select.innerHTML = "";
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
}

function bindEvents() {
  els.fileInput.addEventListener("change", () => {
    const file = els.fileInput.files?.[0];
    if (file) processFile(file);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    els.dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.dropzone.classList.add("is-dragging");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    els.dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.dropzone.classList.remove("is-dragging");
    });
  });

  els.dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files?.[0];
    if (file) processFile(file);
  });

  els.calendarButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleCalendar();
  });

  els.prevMonth.addEventListener("click", () => {
    state.calendarMonth = new Date(
      state.calendarMonth.getFullYear(),
      state.calendarMonth.getMonth() - 1,
      1,
    );
    renderCalendar();
  });

  els.nextMonth.addEventListener("click", () => {
    state.calendarMonth = new Date(
      state.calendarMonth.getFullYear(),
      state.calendarMonth.getMonth() + 1,
      1,
    );
    renderCalendar();
  });

  document.addEventListener("click", (event) => {
    if (!els.calendarPopover.hidden && !event.target.closest(".date-field")) {
      closeCalendar();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeCalendar();
  });

  els.credentialForm.addEventListener("submit", generateCredential);
}

async function processFile(file) {
  if (state.processing) return;
  state.processing = true;
  state.sessionId = null;
  els.fileName.textContent = file.name;
  els.generateButton.disabled = true;
  resetDownloads();
  els.resultState.textContent = "Procesando identificación";
  clearWarnings();
  showLoading("Procesando...", "Enderezando documento y leyendo datos");

  const body = new FormData();
  body.append("file", file);

  try {
    const response = await fetch("/api/process-id", { method: "POST", body });
    const payload = await readJsonResponse(response);

    state.sessionId = payload.session_id;
    els.nombreCompleto.value = payload.extracted.nombre_completo || "";
    els.fechaNacimiento.value = payload.extracted.fecha_nacimiento || "";
    els.warpedPreview.src = withCache(payload.images.warped);
    els.facePreview.src = withCache(payload.images.face);
    els.generateButton.disabled = false;
    els.resultState.textContent = "Datos listos para validar";
    showWarnings(payload.warnings || []);
  } catch (error) {
    showWarnings([error.message]);
    els.resultState.textContent = "No se pudo procesar";
  } finally {
    state.processing = false;
    hideLoading();
  }
}

async function generateCredential(event) {
  event.preventDefault();
  if (!state.sessionId) return;

  els.generateButton.disabled = true;
  els.resultState.textContent = "Generando imagen final";
  showLoading("Generando credencial...", "Componiendo foto, texto y temporada");

  const payload = {
    session_id: state.sessionId,
    nombre_completo: els.nombreCompleto.value,
    equipo: els.equipo.value,
    categoria: els.categoria.value,
    numero_jugador: els.numeroJugador.value.trim(),
    fecha_nacimiento: els.fechaNacimiento.value,
    lugar_fecha: formatPlaceDate(state.selectedDate),
    temporada_suffix: els.temporadaSuffix.value,
  };

  try {
    const response = await fetch("/api/generate-credential", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await readJsonResponse(response);
    els.credentialPreview.src = withCache(result.credential_url);
    els.downloadLink.href = result.download_url;
    els.downloadLink.classList.remove("is-disabled");
    els.formatDownloadLink.href = result.format_download_url;
    els.formatDownloadLink.classList.remove("is-disabled");
    els.resultState.textContent = "Credencial lista";
  } catch (error) {
    if (isMissingSessionError(error)) {
      state.sessionId = null;
      resetDownloads();
      showWarnings(["La sesion de procesamiento ya expiro o se perdio en Render. Sube la identificacion de nuevo."]);
    } else {
      showWarnings([error.message]);
    }
    els.resultState.textContent = "No se pudo generar";
  } finally {
    els.generateButton.disabled = !state.sessionId;
    hideLoading();
  }
}

function toggleCalendar() {
  const isOpening = els.calendarPopover.hidden;
  els.calendarPopover.hidden = !isOpening;
  els.calendarButton.classList.toggle("is-active", isOpening);
  if (isOpening) renderCalendar();
}

function closeCalendar() {
  els.calendarPopover.hidden = true;
  els.calendarButton.classList.remove("is-active");
}

function renderCalendar() {
  const year = state.calendarMonth.getFullYear();
  const month = state.calendarMonth.getMonth();
  els.calendarTitle.textContent = `${MONTHS[month]} de ${year}`;
  els.calendarGrid.innerHTML = "";

  const firstDay = new Date(year, month, 1);
  const mondayOffset = (firstDay.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - mondayOffset);

  for (let index = 0; index < 42; index += 1) {
    const day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "calendar-day";
    button.textContent = String(day.getDate());
    button.setAttribute("aria-label", formatDateOnly(day));

    if (day.getMonth() !== month) button.classList.add("is-muted");
    if (isSameDate(day, state.selectedDate)) button.classList.add("is-selected");

    button.addEventListener("click", () => {
      state.selectedDate = day;
      state.calendarMonth = new Date(day.getFullYear(), day.getMonth(), 1);
      updatePlaceDate();
      renderCalendar();
      closeCalendar();
    });

    els.calendarGrid.append(button);
  }
}

function updatePlaceDate() {
  els.lugarFecha.value = formatDateOnly(state.selectedDate);
  els.serverDate.textContent = formatPlaceDate(state.selectedDate);
}

function parseIsoDate(value) {
  const [year, month, day] = String(value || DEFAULT_DATE).split("-").map(Number);
  return new Date(year || 2026, (month || 5) - 1, day || 29);
}

function formatPlaceDate(date) {
  return `Tultitlán, Méx. ${formatDateOnly(date)}`;
}

function formatDateOnly(date) {
  return `${String(date.getDate()).padStart(2, "0")} de ${MONTHS[date.getMonth()]} de ${date.getFullYear()}`;
}

function isSameDate(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function showLoading(title, text) {
  els.loadingTitle.textContent = title;
  els.loadingText.textContent = text;
  els.loadingOverlay.hidden = false;
}

function hideLoading() {
  els.loadingOverlay.hidden = true;
}

function showWarnings(warnings) {
  const filtered = warnings.filter(Boolean);
  if (!filtered.length) {
    clearWarnings();
    return;
  }
  els.warnings.hidden = false;
  els.warnings.innerHTML = filtered.map((warning) => `<div>${escapeHtml(warning)}</div>`).join("");
}

function clearWarnings() {
  els.warnings.hidden = true;
  els.warnings.textContent = "";
}

async function readJsonResponse(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.detail || "Solicitud fallida");
    error.status = response.status;
    error.detail = payload.detail || "";
    throw error;
  }
  return payload;
}

function isMissingSessionError(error) {
  return error?.status === 404 && /sesi[oó]n/i.test(error.message || "");
}

function withCache(url) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}t=${Date.now()}`;
}

function resetDownloads() {
  els.downloadLink.href = "#";
  els.downloadLink.classList.add("is-disabled");
  els.formatDownloadLink.href = "#";
  els.formatDownloadLink.classList.add("is-disabled");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const map = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return map[char];
  });
}
