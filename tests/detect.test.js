const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const catalog = JSON.parse(fs.readFileSync(path.join(root, "extension", "networks.json"), "utf8"));
const cases = JSON.parse(fs.readFileSync(path.join(root, "tests", "cases.json"), "utf8"));
eval(fs.readFileSync(path.join(root, "extension", "detect.js"), "utf8"));

const detect = globalThis.MDE;
let failed = 0;

function check(actual, expected, label) {
  if (actual !== expected) {
    console.error(`${label}: esperado ${JSON.stringify(expected)}, veio ${JSON.stringify(actual)}`);
    failed += 1;
  }
}

for (const item of cases.urls) {
  const found = detect.detectNetwork(item.url, catalog);
  check(found ? found.id : null, item.id, item.url);
  if (item.label) {
    check(found && found.label, item.label, `${item.url} label`);
  }
}

for (const item of cases.filenames) {
  const [year, month, day, hour, minute, second] = item.parts;
  const date = new Date(year, month - 1, day, hour, minute, second);
  check(detect.autoFilename(item.id, date), item.expected, item.expected);
}

for (const item of cases.sanitize) {
  check(detect.sanitizeFilename(item.value), item.expected, item.value);
}

for (const item of cases.extensions) {
  check(detect.outputExtension(item.quality, item.compress), item.expected, item.quality);
}

for (const item of cases.times) {
  const label = `tempo ${JSON.stringify(item.value)}`;
  try {
    const actual = detect.parseTime(item.value);
    if (item.error) {
      console.error(`${label}: deveria falhar`);
      failed += 1;
    } else {
      check(actual, item.seconds, label);
    }
  } catch (error) {
    if (!item.error) {
      console.error(`${label}: ${error.message}`);
      failed += 1;
    } else {
      check(error.message, item.error, label);
    }
  }
}

for (const item of cases.clocks) {
  check(detect.formatTime(item.seconds), item.text, `formato ${item.seconds}`);
  check(detect.parseTime(item.text), item.seconds, `volta ${item.text}`);
}

for (const item of cases.youtubeStarts) {
  check(detect.youtubeStart(item.url), item.seconds, item.url);
}

if (failed) {
  process.exit(1);
}
console.log(`detect.js ok (${cases.urls.length} links)`);
