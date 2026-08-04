// SPDX-License-Identifier: CPAL-1.0

function element(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  return node;
}

export function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value || "");
  }
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function splitTags(value) {
  const seen = new Set();
  const tags = [];
  for (const item of String(value || "").split(",")) {
    const display = item.trim().replace(/\s+/g, " ");
    const identity = display.toLocaleLowerCase();
    if (display && !seen.has(identity)) {
      seen.add(identity);
      tags.push(display);
    }
  }
  return tags;
}

export function createAssetCard(asset, onOpen) {
  const card = element("article", "asset-card");
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute(
    "aria-label",
    `Open ${asset.title || asset.original_filename}`,
  );
  card.dataset.assetId = asset.asset_id;

  const imageWrap = element("div", "card-image-wrap");
  const skeleton = element("span", "card-skeleton");
  skeleton.setAttribute("aria-hidden", "true");
  const image = element("img", "card-image");
  image.alt = asset.title || asset.original_filename;
  const imageError = element(
    "span",
    "card-image-error",
    "Preview unavailable",
  );
  imageError.hidden = true;
  imageWrap.append(skeleton, image, imageError);

  const body = element("div", "card-body");
  const title = element(
    "h2",
    "card-title",
    asset.title || asset.original_filename,
  );
  const filename = element(
    "p",
    "card-filename",
    asset.original_filename,
  );
  const tags = element("div", "tag-list");
  tags.setAttribute("aria-label", "Tags");
  for (const tag of asset.tags.slice(0, 4)) {
    tags.append(element("span", "tag", tag));
  }
  if (asset.tags.length > 4) {
    tags.append(element("span", "tag", `+${asset.tags.length - 4}`));
  }
  const meta = element("div", "card-meta");
  meta.append(
    element("span", "", `${asset.width} × ${asset.height}`),
    element("span", "", formatBytes(asset.stored_bytes)),
    element("span", "", formatDate(asset.created_at)),
  );
  body.append(title, filename, tags, meta);
  card.append(imageWrap, body);

  const open = () => onOpen(asset.asset_id);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });

  return { card, image, skeleton, imageError };
}

export function setCardImage(parts, objectUrl) {
  parts.image.classList.remove("loaded");
  parts.skeleton.hidden = false;
  parts.imageError.hidden = true;

  const handleLoad = () => {
    parts.image.removeEventListener("error", handleError);
    parts.image.classList.add("loaded");
    parts.skeleton.hidden = true;
    parts.imageError.hidden = true;
  };
  const handleError = () => {
    parts.image.removeEventListener("load", handleLoad);
    setCardImageError(parts);
  };
  parts.image.addEventListener("load", handleLoad, { once: true });
  parts.image.addEventListener("error", handleError, { once: true });
  parts.image.src = objectUrl;
}

export function setCardImageError(parts) {
  parts.image.classList.remove("loaded");
  parts.skeleton.hidden = true;
  parts.imageError.hidden = false;
}

export function renderMetadataList(container, asset) {
  const values = [
    ["Original file", asset.original_filename],
    ["Format", asset.mime_type],
    ["Dimensions", `${asset.width} × ${asset.height}`],
    ["Uploaded bytes", formatBytes(asset.decoded_bytes)],
    ["Stored bytes", formatBytes(asset.stored_bytes)],
    ["Created", formatDate(asset.created_at)],
    ["Updated", formatDate(asset.updated_at)],
  ];
  const nodes = values.map(([label, value]) => {
    const row = element("div");
    row.append(element("dt", "", label), element("dd", "", value));
    return row;
  });
  container.replaceChildren(...nodes);
}

export function renderAbout(container, about) {
  const values = [
    ["Project version", about.project_version],
    ["Dashboard version", about.dashboard_version],
    ["HTTP API", about.http_api_version],
    ["Data compatibility", about.data_compatibility_version],
    ["Original creator", about.original_creator],
    ["License", about.license],
  ];
  const nodes = values.map(([label, value]) => {
    const row = element("div");
    row.append(element("dt", "", label), element("dd", "", value));
    return row;
  });
  container.replaceChildren(...nodes);
}

export function showToast(region, message, tone = "") {
  const toast = element("div", `toast ${tone}`.trim(), message);
  region.append(toast);
  window.setTimeout(() => {
    toast.remove();
  }, 4200);
}

export function setButtonBusy(button, busy, busyText, idleText) {
  button.disabled = busy;
  button.textContent = busy ? busyText : idleText;
  button.setAttribute("aria-busy", String(busy));
}
