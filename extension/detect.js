// Mesmas regras de host/naming.py. Os testes em tests/cases.json cobrem os dois.
(function () {
  function hostMatches(hostname, pattern) {
    const host = String(hostname || "").toLowerCase().replace(/^www\./, "");
    const expected = String(pattern || "").toLowerCase().replace(/^www\./, "");
    return host === expected || host.endsWith(`.${expected}`);
  }

  function detectNetwork(url, catalog) {
    let parsed;
    try {
      parsed = new URL(String(url || "").trim());
    } catch {
      return null;
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    if (!parsed.hostname) {
      return null;
    }
    const hostname = parsed.hostname.toLowerCase().replace(/^www\./, "");
    for (const network of catalog.networks) {
      if (network.hosts.some((pattern) => hostMatches(hostname, pattern))) {
        return { id: network.id, label: network.label };
      }
    }
    return { id: "outra", label: "Outra rede" };
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function autoFilename(networkId, date) {
    const slug = networkId || "midia";
    const stamp = [
      date.getFullYear(),
      pad(date.getMonth() + 1),
      pad(date.getDate()),
    ].join("-");
    const clock = [pad(date.getHours()), pad(date.getMinutes()), pad(date.getSeconds())].join("-");
    return `${slug}_${stamp}_${clock}`;
  }

  function sanitizeFilename(name) {
    let cleaned = String(name || "").trim();
    cleaned = cleaned.replace(/[\\/]/g, " ");
    cleaned = cleaned.replace(/[\u0000-\u001f:*?"<>|]+/g, "");
    cleaned = cleaned.replace(/\s+/g, " ").replace(/^[ .]+|[ .]+$/g, "");
    for (let index = 0; index < 3; index += 1) {
      const next = cleaned.replace(/\.(mp4|mp3|zip|webm|mkv|m4a)$/i, "");
      if (next === cleaned) {
        break;
      }
      cleaned = next.replace(/[ .]+$/g, "");
    }
    cleaned = cleaned.slice(0, 80).replace(/[ .]+$/g, "");
    return cleaned || "midia";
  }

  function outputExtension(quality, compress) {
    if (compress) {
      return ".zip";
    }
    return quality === "audio" ? ".mp3" : ".mp4";
  }

  const TIME_INVALID = "Tempo inválido. Use 1:30 ou 90,5.";
  const TIME_NEGATIVE = "O tempo não pode ser negativo.";
  const TIME_TOO_LONG = "O tempo fica acima de 48 horas.";
  const MAX_MILLIS = 48 * 60 * 60 * 1000;

  function asSeconds(value) {
    const millis = Math.round(Number(value) * 1000);
    if (!Number.isFinite(millis)) {
      throw new Error(TIME_INVALID);
    }
    if (millis < 0) {
      throw new Error(TIME_NEGATIVE);
    }
    if (millis > MAX_MILLIS) {
      throw new Error(TIME_TOO_LONG);
    }
    return millis / 1000;
  }

  function parseTime(value) {
    if (value === null || value === undefined) {
      return null;
    }
    if (typeof value === "boolean") {
      throw new Error(TIME_INVALID);
    }
    if (typeof value === "number") {
      if (!Number.isFinite(value)) {
        throw new Error(TIME_INVALID);
      }
      return asSeconds(value);
    }
    if (typeof value !== "string") {
      throw new Error(TIME_INVALID);
    }
    const text = value.trim().replace(",", ".");
    if (!text) {
      return null;
    }
    if (text.startsWith("-")) {
      throw new Error(TIME_NEGATIVE);
    }
    const clock = text.match(/^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$/);
    if (clock) {
      const hours = clock[1] ? Number(clock[1]) : 0;
      const minutes = Number(clock[2]);
      const seconds = Number(clock[3]);
      if (clock[1] && minutes >= 60) {
        throw new Error(TIME_INVALID);
      }
      if (seconds >= 60) {
        throw new Error(TIME_INVALID);
      }
      return asSeconds(hours * 3600 + minutes * 60 + seconds);
    }
    if (/^\d+(?:\.\d+)?$/.test(text)) {
      return asSeconds(Number(text));
    }
    throw new Error(TIME_INVALID);
  }

  function formatTime(seconds) {
    const millis = Math.max(0, Math.round(Number(seconds) * 1000));
    const hours = Math.floor(millis / 3600000);
    const minutes = Math.floor((millis % 3600000) / 60000);
    const secs = Math.floor((millis % 60000) / 1000);
    const fraction = millis % 1000;
    const frac = fraction % 10 ? String(fraction).padStart(3, "0") : String(Math.floor(fraction / 10)).padStart(2, "0");
    const body = `${pad(secs)}.${frac}`;
    if (hours) {
      return `${hours}:${pad(minutes)}:${body}`;
    }
    return `${minutes}:${body}`;
  }

  function youtubeHost(hostname) {
    const host = String(hostname || "").toLowerCase().replace(/^www\./, "");
    return host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com")
      || host === "youtube-nocookie.com" || host.endsWith(".youtube-nocookie.com");
  }

  function youtubeClock(text) {
    const cleaned = String(text || "").trim().replace(",", ".");
    if (/^\d+(?:\.\d+)?s?$/.test(cleaned)) {
      return parseTime(cleaned.endsWith("s") ? cleaned.slice(0, -1) : cleaned);
    }
    const clock = cleaned.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?$/);
    if (!clock || (!clock[1] && !clock[2] && !clock[3])) {
      return null;
    }
    const hours = Number(clock[1] || 0);
    const minutes = Number(clock[2] || 0);
    const seconds = Number(clock[3] || 0);
    return asSeconds(hours * 3600 + minutes * 60 + seconds);
  }

  function youtubeStart(url) {
    let parsed;
    try {
      parsed = new URL(String(url || "").trim());
    } catch {
      return null;
    }
    if ((parsed.protocol !== "http:" && parsed.protocol !== "https:") || !youtubeHost(parsed.hostname)) {
      return null;
    }
    const raw = parsed.searchParams.get("t") || parsed.searchParams.get("start")
      || new URLSearchParams(parsed.hash.replace(/^#/, "")).get("t");
    if (!raw) {
      return null;
    }
    try {
      return youtubeClock(raw);
    } catch {
      return null;
    }
  }

  globalThis.MDE = {
    hostMatches,
    detectNetwork,
    autoFilename,
    sanitizeFilename,
    outputExtension,
    parseTime,
    formatTime,
    youtubeStart,
  };
})();
