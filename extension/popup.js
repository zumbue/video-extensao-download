const SERVICE = "http://127.0.0.1:8734";
const CLIENT = "video-extensao-download";

const form = document.querySelector("#form");
const urlInput = document.querySelector("#url");
const filenameInput = document.querySelector("#filename");
const compressInput = document.querySelector("#compress");
const networkNode = document.querySelector("#network");
const qualitiesNode = document.querySelector("#qualities");
const extNode = document.querySelector("#ext");
const serviceNode = document.querySelector("#service");
const bannerNode = document.querySelector("#banner");
const progressWrap = document.querySelector("#progress-wrap");
const barNode = document.querySelector("#bar");
const progressLabel = document.querySelector("#progress-label");
const downloadButton = document.querySelector("#download");
const openFolderButton = document.querySelector("#open-folder");
const useTabButton = document.querySelector("#use-tab");
const renameButton = document.querySelector("#rename");
const hintNode = document.querySelector("#hint");
const trimSection = document.querySelector("#trim");
const startInput = document.querySelector("#trim-start");
const endInput = document.querySelector("#trim-end");
const trimBar = document.querySelector("#trim-bar");
const trimFill = document.querySelector("#trim-fill");
const startHandle = document.querySelector("#trim-start-handle");
const endHandle = document.querySelector("#trim-end-handle");
const trimMeta = document.querySelector("#trim-meta");

const browserApi = globalThis.chrome;
const headers = { "X-Mde-Client": CLIENT };

let catalog = null;
let quality = "best";
let autoName = true;
let stamp = null;
let jobId = null;
let pollTimer = null;
let health = null;
let duration = null;
let probeState = "idle";
let probeTimer = null;
let probeSerial = 0;
let probedId = null;
let videoId = null;
let drag = null;
let savedName = "";
let sessionOpen = false;
let finishedOnce = false;
let healthTimer = null;
let idleMark = null;
let wakeGeneration = 0;
let healthInFlight = null;

function storage() {
  return browserApi?.storage?.session;
}

function networkOf(url) {
  if (!catalog) {
    return null;
  }
  return globalThis.MDE.detectNetwork(url, catalog);
}

function suggestedName(url) {
  const network = networkOf(url);
  if (!network) {
    return "";
  }
  if (!stamp) {
    stamp = new Date().toISOString();
  }
  return globalThis.MDE.autoFilename(network.id, new Date(stamp));
}

function syncName() {
  if (!autoName) {
    return;
  }
  filenameInput.value = suggestedName(urlInput.value.trim());
}

function setBanner(kind, text) {
  if (!text) {
    bannerNode.hidden = true;
    bannerNode.textContent = "";
    bannerNode.className = "banner";
    return;
  }
  bannerNode.hidden = false;
  bannerNode.textContent = text;
  bannerNode.className = `banner ${kind}`;
}

function setProgress(value, failed) {
  const amount = Math.max(0, Math.min(100, Number(value) || 0));
  progressWrap.hidden = false;
  progressWrap.classList.toggle("bad", Boolean(failed));
  barNode.style.width = `${amount}%`;
  progressLabel.textContent = `${Math.round(amount)}%`;
}

function hideProgress() {
  progressWrap.hidden = true;
  barNode.style.width = "0";
  progressLabel.textContent = "0%";
  progressWrap.classList.remove("bad");
}

function youtubeVideoId(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
  if (host === "youtu.be") {
    return parsed.pathname.split("/").filter(Boolean)[0] || null;
  }
  const youtube = host === "youtube.com" || host.endsWith(".youtube.com")
    || host === "youtube-nocookie.com" || host.endsWith(".youtube-nocookie.com");
  if (!youtube) {
    return null;
  }
  if (parsed.searchParams.get("v")) {
    return parsed.searchParams.get("v");
  }
  const parts = parsed.pathname.split("/").filter(Boolean);
  if (["shorts", "embed", "live", "v"].includes(parts[0]) && parts[1]) {
    return parts[1];
  }
  return null;
}

function readTrim() {
  let start = null;
  let end = null;
  let startError = "";
  let endError = "";
  try {
    start = globalThis.MDE.parseTime(startInput.value);
  } catch (error) {
    startError = error.message;
  }
  try {
    end = globalThis.MDE.parseTime(endInput.value);
  } catch (error) {
    endError = error.message;
  }
  let error = startError || endError;
  if (!error && start !== null && end !== null && end <= start) {
    error = "O fim precisa ser depois do início.";
  }
  if (!error && duration && start !== null && start > duration) {
    error = "O início passa da duração do vídeo.";
  }
  if (!error && duration && end !== null && end > duration + 0.001) {
    error = "O fim passa da duração do vídeo.";
  }
  return { start, end, error, startError, endError };
}

function activeTrim() {
  const network = networkOf(urlInput.value.trim());
  if (!network || network.id !== "youtube") {
    return { start: null, end: null, error: "", startError: "", endError: "" };
  }
  return readTrim();
}

function probeMessage() {
  if (probeState === "loading") {
    return "Medindo a duração…";
  }
  if (duration) {
    return `Duração ${globalThis.MDE.formatTime(duration)}. Vazio baixa o vídeo inteiro.`;
  }
  if (probeState === "unknown" || probeState === "offline") {
    return "Digite o início e o fim. Vazio baixa o vídeo inteiro.";
  }
  return "Vazio baixa o vídeo inteiro.";
}

function placeHandles(start, end) {
  const max = duration || 1;
  const startRatio = Math.min(1, Math.max(0, start / max));
  const endRatio = Math.min(1, Math.max(startRatio, end / max));
  startHandle.style.left = `${startRatio * 100}%`;
  endHandle.style.left = `${endRatio * 100}%`;
  trimFill.style.left = `${startRatio * 100}%`;
  trimFill.style.width = `${(endRatio - startRatio) * 100}%`;
  for (const [handle, value] of [[startHandle, start], [endHandle, end]]) {
    handle.setAttribute("aria-valuemin", "0");
    handle.setAttribute("aria-valuemax", String(max));
    handle.setAttribute("aria-valuenow", String(value));
    handle.setAttribute("aria-valuetext", globalThis.MDE.formatTime(value));
  }
}

function renderTrim(network, trim) {
  const youtube = Boolean(network && network.id === "youtube");
  trimSection.hidden = !youtube;
  if (!youtube) {
    return;
  }
  const orderError = Boolean(trim.error && !trim.startError && !trim.endError);
  startInput.classList.toggle("bad", Boolean(trim.startError) || orderError);
  endInput.classList.toggle("bad", Boolean(trim.endError) || orderError);
  startInput.setAttribute("aria-invalid", String(Boolean(trim.startError) || orderError));
  endInput.setAttribute("aria-invalid", String(Boolean(trim.endError) || orderError));
  endInput.placeholder = duration ? globalThis.MDE.formatTime(duration) : "fim";
  const showBar = Boolean(duration) && probeState === "ready";
  trimBar.hidden = !showBar;
  if (showBar && !trim.error) {
    placeHandles(trim.start ?? 0, trim.end ?? duration);
  }
  trimMeta.textContent = trim.error || probeMessage();
  trimMeta.classList.toggle("bad", Boolean(trim.error));
}

function render() {
  const url = urlInput.value.trim();
  const network = networkOf(url);
  extNode.textContent = globalThis.MDE.outputExtension(quality, compressInput.checked);

  if (!url) {
    networkNode.textContent = "Aguardando link";
    networkNode.className = "chip";
  } else if (!network) {
    networkNode.textContent = "Link inválido";
    networkNode.className = "chip bad";
  } else if (network.id === "outra") {
    networkNode.textContent = "Outra rede";
    networkNode.className = "chip other";
  } else {
    networkNode.textContent = network.label;
    networkNode.className = "chip known";
  }

  const trim = activeTrim();
  renderTrim(network, trim);
  const nameReady = globalThis.MDE.sanitizeFilename(filenameInput.value) !== "midia" || filenameInput.value.trim() !== "";
  const blocked = Boolean(health?.ok && !health.resting && (!health.ffmpeg || !health.ytdlp));
  const canDownload = Boolean(network && filenameInput.value.trim() && nameReady && !trim.error && !blocked);
  downloadButton.disabled = jobId ? false : !canDownload;
  downloadButton.textContent = jobId ? "Cancelar" : "Baixar";
  downloadButton.classList.toggle("danger", Boolean(jobId));
  openFolderButton.disabled = !(health?.ok || health?.resting || savedName);

  for (const field of [urlInput, filenameInput, compressInput, useTabButton, renameButton, startInput, endInput, startHandle, endHandle]) {
    field.disabled = Boolean(jobId);
  }
  for (const button of qualitiesNode.querySelectorAll("button")) {
    button.disabled = Boolean(jobId);
  }

  if (health?.resting) {
    serviceNode.textContent = "encerrado";
    serviceNode.className = "service";
    hintNode.textContent = "Serviço encerrado. Cole outro link para baixar de novo.";
  } else if (health?.idle) {
    serviceNode.textContent = "em espera";
    serviceNode.className = "service";
    hintNode.textContent = "Cole um link para iniciar. O serviço encerra depois do download.";
  } else if (!health) {
    serviceNode.textContent = sessionOpen ? "iniciando" : "em espera";
    serviceNode.className = "service";
    hintNode.textContent = sessionOpen ? "Iniciando o serviço local." : "Cole um link para iniciar. O serviço encerra depois do download.";
  } else if (!health.ok) {
    serviceNode.textContent = "offline";
    serviceNode.className = "service off";
    hintNode.textContent = "Serviço desligado. Abra Instalar de novo.";
  } else if (!health.ffmpeg) {
    serviceNode.textContent = "sem ffmpeg";
    serviceNode.className = "service off";
    hintNode.textContent = "Instale o FFmpeg para converter o vídeo.";
  } else if (!health.ytdlp) {
    serviceNode.textContent = "sem yt-dlp";
    serviceNode.className = "service off";
    hintNode.textContent = "Abra Instalar de novo para instalar o yt-dlp.";
  } else {
    serviceNode.textContent = "no ar";
    serviceNode.className = "service on";
    const runtime = health.js_runtime ? `Runtime ${health.js_runtime}.` : "Sem Node ou Deno: o YouTube pode falhar.";
    hintNode.textContent = `Salva em ~/Downloads/Video Extensao Download. ${runtime}`;
  }
}

function selectQuality(next) {
  quality = next;
  for (const button of qualitiesNode.querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.quality === quality));
  }
  render();
  saveDraft();
}

function buildQualities() {
  qualitiesNode.replaceChildren();
  for (const item of catalog.qualities) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "choice";
    button.dataset.quality = item.id;
    button.textContent = item.label;
    button.setAttribute("aria-pressed", String(item.id === quality));
    button.addEventListener("click", () => selectQuality(item.id));
    qualitiesNode.append(button);
  }
}

async function saveDraft() {
  const session = storage();
  if (!session) {
    return;
  }
  await session.set({
    draft: {
      url: urlInput.value,
      quality,
      filename: filenameInput.value,
      compress: compressInput.checked,
      autoName,
      stamp,
      jobId,
      startText: startInput.value,
      endText: endInput.value,
      savedName,
    },
  });
}

async function loadInitialUrl() {
  const session = storage();
  const stored = session ? await session.get(["draft", "pendingUrl"]) : {};
  if (stored.pendingUrl) {
    urlInput.value = stored.pendingUrl;
    stamp = new Date().toISOString();
    autoName = true;
    startInput.value = "";
    endInput.value = "";
    const hinted = globalThis.MDE.youtubeStart(stored.pendingUrl);
    if (hinted) {
      startInput.value = globalThis.MDE.formatTime(hinted);
    }
    if (stored.draft) {
      quality = stored.draft.quality || quality;
      compressInput.checked = Boolean(stored.draft.compress);
      jobId = stored.draft.jobId || null;
      savedName = stored.draft.savedName || "";
    }
    await session.remove("pendingUrl");
    return jobId ? "job" : "pending";
  }
  const draft = stored.draft;
  if (draft) {
    urlInput.value = draft.url || "";
    quality = draft.quality || quality;
    compressInput.checked = Boolean(draft.compress);
    autoName = draft.autoName !== false;
    stamp = draft.stamp || null;
    filenameInput.value = draft.filename || "";
    startInput.value = draft.startText || "";
    endInput.value = draft.endText || "";
    jobId = draft.jobId || null;
    savedName = draft.savedName || "";
    return jobId ? "job" : "draft";
  }
  const params = new URLSearchParams(location.search);
  if (params.get("url")) {
    urlInput.value = params.get("url");
    if (params.get("quality")) {
      quality = params.get("quality");
    }
    compressInput.checked = params.get("compress") === "1";
    if (params.get("start")) {
      startInput.value = params.get("start");
    } else {
      const hinted = globalThis.MDE.youtubeStart(urlInput.value.trim());
      if (hinted) {
        startInput.value = globalThis.MDE.formatTime(hinted);
      }
    }
    if (params.get("end")) {
      endInput.value = params.get("end");
    }
    return "query";
  }
  if (!browserApi?.tabs) {
    return "empty";
  }
  const [tab] = await browserApi.tabs.query({ active: true, currentWindow: true });
  if (tab?.url && /^https?:/i.test(tab.url)) {
    urlInput.value = tab.url;
    return "tab";
  }
  return "empty";
}

function isExtension() {
  return Boolean(browserApi?.runtime?.id);
}

function stopHealthLoop() {
  if (healthTimer) {
    clearInterval(healthTimer);
    healthTimer = null;
  }
}

function armLocalIdle(seconds) {
  clearTimeout(idleMark);
  if (!seconds || jobId) {
    return;
  }
  const generation = wakeGeneration;
  idleMark = setTimeout(() => {
    if (generation !== wakeGeneration || jobId) {
      return;
    }
    stopHealthLoop();
    sessionOpen = false;
    health = finishedOnce
      ? { resting: true, ok: true, ffmpeg: true, ytdlp: true }
      : { idle: true };
    render();
  }, Math.max(1, seconds - 1) * 1000);
}

function wakeService() {
  wakeGeneration += 1;
  sessionOpen = true;
  if (!health?.ok || health.idle || health.resting) {
    health = null;
    serviceNode.textContent = "iniciando";
    serviceNode.className = "service";
    hintNode.textContent = "Iniciando o serviço local.";
  }
  if (!healthInFlight) {
    healthInFlight = checkHealth().finally(() => {
      healthInFlight = null;
      if (health?.ok && !health.idle_exit && !healthTimer) {
        healthTimer = setInterval(checkHealth, 3000);
      }
    });
  }
  return healthInFlight;
}

async function checkHealth() {
  try {
    const response = await fetch(`${SERVICE}/health`, { headers, signal: AbortSignal.timeout(20000) });
    health = response.ok ? await response.json() : { ok: false };
  } catch {
    health = { ok: false };
  }
  if (health?.idle_exit && !jobId) {
    armLocalIdle(health.idle_seconds);
  }
  if (health?.ok && health.ffmpeg && health.ytdlp && probeState === "offline") {
    scheduleProbe();
  }
  render();
}

async function readError(response) {
  try {
    const payload = await response.json();
    return payload.error || "O serviço recusou o pedido.";
  } catch {
    return "O serviço recusou o pedido.";
  }
}

function noteFinished() {
  finishedOnce = true;
  clearTimeout(idleMark);
  if (health?.idle_exit) {
    stopHealthLoop();
    armLocalIdle(health.settled_seconds || 30);
  }
}

function applyJob(job) {
  if (job.state === "done") {
    jobId = null;
    hideProgress();
    savedName = job.name || savedName;
    setBanner("ok", `Salvo: ${job.name}`);
    noteFinished();
    render();
    saveDraft();
    return;
  }
  if (job.state === "error") {
    jobId = null;
    setProgress(job.progress || 0, true);
    setBanner("bad", job.error || "O download falhou.");
    noteFinished();
    render();
    saveDraft();
    return;
  }
  if (job.state === "cancelled") {
    jobId = null;
    hideProgress();
    setBanner("bad", "Download cancelado.");
    noteFinished();
    render();
    saveDraft();
    return;
  }
  clearTimeout(idleMark);
  setBanner("", "");
  const amount = job.progress || (job.state === "running" ? 8 : 0);
  setProgress(amount, false);
  progressLabel.textContent = job.progress ? `${Math.round(job.progress)}%` : "...";
  render();
}

async function poll() {
  if (!jobId) {
    return;
  }
  try {
    const response = await fetch(`${SERVICE}/jobs/${jobId}`, { headers });
    if (response.status === 404) {
      throw new Error("O serviço já encerrou este download. Se o arquivo foi salvo, use Abrir pasta.");
    }
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const job = await response.json();
    applyJob(job);
    if (job.state === "queued" || job.state === "running") {
      pollTimer = setTimeout(poll, 400);
    }
  } catch (error) {
    setBanner("bad", error.message || "Sem resposta do serviço.");
    jobId = null;
    render();
    saveDraft();
  }
}

async function startDownload() {
  setBanner("", "");
  const url = urlInput.value.trim();
  const network = networkOf(url);
  if (!network) {
    setBanner("bad", "Cole um link http ou https.");
    return;
  }
  if (!health?.ok || health.resting || health.idle) {
    serviceNode.textContent = "iniciando";
    serviceNode.className = "service";
    hintNode.textContent = "Iniciando o serviço local.";
    await wakeService();
    if (!health?.ok) {
      setBanner("bad", "O serviço não iniciou. Abra Instalar de novo.");
      render();
      return;
    }
  }
  if (!health.ffmpeg) {
    setBanner("bad", "Instale o FFmpeg para converter o vídeo.");
    render();
    return;
  }
  if (!health.ytdlp) {
    setBanner("bad", "Abra Instalar de novo para instalar o yt-dlp.");
    render();
    return;
  }
  clearTimeout(idleMark);
  const trim = activeTrim();
  if (trim.error) {
    setBanner("bad", trim.error);
    render();
    return;
  }
  const filename = globalThis.MDE.sanitizeFilename(filenameInput.value);
  filenameInput.value = filename;
  downloadButton.disabled = true;
  try {
    const response = await fetch(`${SERVICE}/download`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        quality,
        filename,
        compress: compressInput.checked,
        start_time: network.id === "youtube" ? trim.start : null,
        end_time: network.id === "youtube" ? trim.end : null,
      }),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const job = await response.json();
    jobId = job.id;
    await saveDraft();
    applyJob(job);
    poll();
  } catch (error) {
    setBanner("bad", error.message || "Não foi possível começar o download.");
    render();
  }
}

async function cancelDownload() {
  if (!jobId) {
    return;
  }
  downloadButton.disabled = true;
  try {
    const response = await fetch(`${SERVICE}/jobs/${jobId}/cancel`, { method: "POST", headers });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    applyJob(await response.json());
  } catch (error) {
    setBanner("bad", error.message || "Não foi possível cancelar.");
    render();
  }
}

openFolderButton.addEventListener("click", async () => {
  if (!health?.ok) {
    return;
  }
  openFolderButton.disabled = true;
  try {
    const response = await fetch(`${SERVICE}/folder`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify(savedName ? { name: savedName } : {}),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
  } catch (error) {
    setBanner("bad", error.message || "Não foi possível abrir a pasta.");
  }
  render();
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (jobId) {
    cancelDownload();
    return;
  }
  startDownload();
});

urlInput.addEventListener("input", () => {
  if (!networkOf(urlInput.value.trim())) {
    stamp = null;
  }
  noteUrlChange();
  syncName();
  setBanner("", "");
  if (/^https?:\/\//i.test(urlInput.value.trim())) {
    wakeService();
  }
  scheduleProbe();
  render();
  saveDraft();
});

filenameInput.addEventListener("input", () => {
  autoName = filenameInput.value.trim() === suggestedName(urlInput.value.trim());
  setBanner("", "");
  render();
  saveDraft();
});

compressInput.addEventListener("change", () => {
  render();
  saveDraft();
});

renameButton.addEventListener("click", () => {
  stamp = new Date().toISOString();
  autoName = true;
  syncName();
  render();
  saveDraft();
});

useTabButton.addEventListener("click", async () => {
  if (!browserApi?.tabs) {
    return;
  }
  const [tab] = await browserApi.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/i.test(tab.url)) {
    setBanner("bad", "A aba atual não tem um link http ou https.");
    return;
  }
  urlInput.value = tab.url;
  stamp = new Date().toISOString();
  autoName = true;
  noteUrlChange();
  syncName();
  setBanner("", "");
  wakeService();
  scheduleProbe();
  render();
  saveDraft();
});

if (!browserApi?.tabs) {
  useTabButton.hidden = true;
}

if (!browserApi?.runtime?.id) {
  document.body.classList.add("page");
}

function noteUrlChange() {
  const next = youtubeVideoId(urlInput.value.trim());
  if (!next || next === videoId) {
    if (next) {
      videoId = next;
    }
    return;
  }
  videoId = next;
  startInput.value = "";
  endInput.value = "";
  const hinted = globalThis.MDE.youtubeStart(urlInput.value.trim());
  if (hinted) {
    startInput.value = globalThis.MDE.formatTime(hinted);
  }
}

function scheduleProbe() {
  const url = urlInput.value.trim();
  const network = networkOf(url);
  const id = youtubeVideoId(url);
  if (!network || network.id !== "youtube") {
    clearTimeout(probeTimer);
    probeSerial += 1;
    duration = null;
    probeState = "idle";
    probedId = null;
    return;
  }
  if (id && id === probedId && (probeState === "ready" || probeState === "unknown")) {
    return;
  }
  if (!sessionOpen) {
    clearTimeout(probeTimer);
    probeSerial += 1;
    probeState = "idle";
    return;
  }
  clearTimeout(probeTimer);
  probeState = "loading";
  duration = null;
  const serial = ++probeSerial;
  probeTimer = setTimeout(() => requestProbe(url, id, serial), 500);
}

async function requestProbe(url, id, serial) {
  try {
    const response = await fetch(`${SERVICE}/probe`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (serial !== probeSerial) {
      return;
    }
    if (!response.ok) {
      duration = null;
      probeState = "offline";
    } else {
      const payload = await response.json();
      if (serial !== probeSerial) {
        return;
      }
      duration = typeof payload.duration === "number" && payload.duration > 0 ? payload.duration : null;
      probeState = duration ? "ready" : "unknown";
      probedId = id;
    }
  } catch {
    if (serial !== probeSerial) {
      return;
    }
    duration = null;
    probeState = "offline";
  }
  render();
}

function onTrimBlur(input) {
  try {
    const parsed = globalThis.MDE.parseTime(input.value);
    if (parsed !== null) {
      input.value = globalThis.MDE.formatTime(parsed);
    }
  } catch {
    // O texto inválido fica na tela para ser corrigido.
  }
  render();
  saveDraft();
}

function snapTime(value) {
  return Math.round(value * 100) / 100;
}

function pointerTime(event) {
  const rect = trimBar.getBoundingClientRect();
  const ratio = rect.width ? (event.clientX - rect.left) / rect.width : 0;
  return snapTime(Math.min(1, Math.max(0, ratio)) * duration);
}

function edgeTime(kind) {
  const read = readTrim();
  if (read.error) {
    return kind === "start" ? 0 : duration;
  }
  if (kind === "start") {
    return read.start ?? 0;
  }
  return read.end ?? duration;
}

function moveHandle(which, value) {
  if (!duration || jobId) {
    return;
  }
  const gap = duration > 0.02 ? 0.01 : duration / 2;
  let start = edgeTime("start");
  let end = edgeTime("end");
  if (which === "start") {
    start = Math.min(Math.max(0, value), end - gap);
  } else {
    end = Math.max(Math.min(duration, value), start + gap);
  }
  start = snapTime(Math.max(0, start));
  end = snapTime(Math.min(duration, end));
  if (end < start + gap) {
    if (which === "start") {
      start = snapTime(Math.max(0, end - gap));
    } else {
      end = snapTime(Math.min(duration, start + gap));
    }
  }
  if (which === "start") {
    startInput.value = start <= 0 ? "" : globalThis.MDE.formatTime(start);
  } else {
    endInput.value = end >= duration - 0.001 ? "" : globalThis.MDE.formatTime(end);
  }
  render();
}

function beginDrag(which, event) {
  if (!duration || jobId) {
    return;
  }
  event.preventDefault();
  drag = which;
  startHandle.classList.toggle("active", which === "start");
  endHandle.classList.toggle("active", which === "end");
  (which === "start" ? startHandle : endHandle).focus();
  moveHandle(which, pointerTime(event));
  try {
    trimBar.setPointerCapture(event.pointerId);
  } catch {
    drag = null;
  }
}

function endDrag(event) {
  if (!drag) {
    return;
  }
  if (event?.pointerId !== undefined && trimBar.hasPointerCapture(event.pointerId)) {
    trimBar.releasePointerCapture(event.pointerId);
  }
  drag = null;
  startHandle.classList.remove("active");
  endHandle.classList.remove("active");
  saveDraft();
}

function onHandleKey(which, event) {
  if (!duration || jobId) {
    return;
  }
  const read = readTrim();
  const current = which === "start" ? (read.start ?? 0) : (read.end ?? duration);
  let next = null;
  if (event.key === "Home") {
    next = which === "start" ? 0 : 0.01;
  } else if (event.key === "End") {
    next = which === "start" ? Math.max(0, duration - 0.01) : duration;
  } else if (event.key === "PageDown") {
    next = current - 10;
  } else if (event.key === "PageUp") {
    next = current + 10;
  } else if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
    next = current - (event.shiftKey ? 1 : 0.01);
  } else if (event.key === "ArrowRight" || event.key === "ArrowUp") {
    next = current + (event.shiftKey ? 1 : 0.01);
  } else {
    return;
  }
  event.preventDefault();
  moveHandle(which, next);
  saveDraft();
}

trimBar.addEventListener("pointerdown", (event) => {
  if (!duration || jobId) {
    return;
  }
  let which;
  if (event.target === startHandle) {
    which = "start";
  } else if (event.target === endHandle) {
    which = "end";
  } else {
    const value = pointerTime(event);
    which = Math.abs(value - edgeTime("start")) <= Math.abs(value - edgeTime("end")) ? "start" : "end";
  }
  beginDrag(which, event);
});
trimBar.addEventListener("pointermove", (event) => {
  if (!drag || !trimBar.hasPointerCapture(event.pointerId)) {
    return;
  }
  moveHandle(drag, pointerTime(event));
});
trimBar.addEventListener("pointerup", endDrag);
trimBar.addEventListener("pointercancel", endDrag);
startHandle.addEventListener("keydown", (event) => onHandleKey("start", event));
endHandle.addEventListener("keydown", (event) => onHandleKey("end", event));

function onTrimEdit() {
  setBanner("", "");
  render();
  saveDraft();
}

startInput.addEventListener("input", onTrimEdit);
endInput.addEventListener("input", onTrimEdit);
startInput.addEventListener("blur", () => onTrimBlur(startInput));
endInput.addEventListener("blur", () => onTrimBlur(endInput));

async function boot() {
  const response = await fetch("networks.json");
  catalog = await response.json();
  const source = await loadInitialUrl();
  videoId = youtubeVideoId(urlInput.value.trim());
  buildQualities();
  syncName();
  const extension = isExtension();
  if (!extension || source === "pending" || source === "job" || source === "query") {
    sessionOpen = true;
  }
  scheduleProbe();
  render();
  if (sessionOpen) {
    await wakeService();
  } else {
    health = savedName ? { resting: true, ok: true, ffmpeg: true, ytdlp: true } : { idle: true };
    if (savedName) {
      finishedOnce = true;
    }
    render();
  }
  if (jobId) {
    poll();
  }
}

boot().catch((error) => {
  setBanner("bad", error.message || "A extensão não abriu por completo.");
});
