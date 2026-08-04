// SPDX-License-Identifier: CPAL-1.0

import {
  ApiError,
  clearSessionToken,
  deleteAsset,
  getAbout,
  getAsset,
  getAssetBlob,
  getSessionToken,
  searchAssets,
  setSessionToken,
  updateAsset,
  uploadAsset,
} from "./api.js";
import {
  createAssetCard,
  formatBytes,
  renderAbout,
  renderMetadataList,
  setButtonBusy,
  setCardImage,
  setCardImageError,
  showToast,
  splitTags,
} from "./ui.js";

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const ALLOWED_FILE_TYPES = new Set(["image/png", "image/jpeg"]);
const THUMBNAIL_CONCURRENCY = 4;

const state = {
  assets: [],
  total: 0,
  offset: 0,
  limit: 20,
  query: "",
  tags: [],
  mimeType: "",
  createdFrom: "",
  createdTo: "",
  selectedAsset: null,
  loading: false,
  tokenState: getSessionToken() ? "available" : "local",
  objectUrls: new Map(),
  detailObjectUrl: "",
  uploadObjectUrl: "",
  uploadFile: null,
  thumbnailQueue: [],
  thumbnailActive: 0,
  thumbnailObserver: null,
  debounceTimer: 0,
};

const dom = {
  assetCount: document.querySelector("#asset-count"),
  connectionButton: document.querySelector("#connection-button"),
  connectionDot: document.querySelector("#connection-dot"),
  connectionLabel: document.querySelector("#connection-label"),
  aboutButton: document.querySelector("#about-button"),
  openUploadButton: document.querySelector("#open-upload-button"),
  emptyUploadButton: document.querySelector("#empty-upload-button"),
  searchInput: document.querySelector("#search-input"),
  toggleFiltersButton: document.querySelector("#toggle-filters-button"),
  filtersPanel: document.querySelector("#filters-panel"),
  filterCount: document.querySelector("#filter-count"),
  tagsFilter: document.querySelector("#tags-filter"),
  mimeFilter: document.querySelector("#mime-filter"),
  createdFrom: document.querySelector("#created-from"),
  createdTo: document.querySelector("#created-to"),
  limitSelect: document.querySelector("#limit-select"),
  clearFiltersButton: document.querySelector("#clear-filters-button"),
  loadingLine: document.querySelector("#loading-line"),
  statusMessage: document.querySelector("#status-message"),
  emptyState: document.querySelector("#empty-state"),
  emptyTitle: document.querySelector("#empty-title"),
  emptyCopy: document.querySelector("#empty-copy"),
  assetGrid: document.querySelector("#asset-grid"),
  previousButton: document.querySelector("#previous-button"),
  nextButton: document.querySelector("#next-button"),
  pageStatus: document.querySelector("#page-status"),
  uploadDialog: document.querySelector("#upload-dialog"),
  uploadForm: document.querySelector("#upload-form"),
  fileInput: document.querySelector("#file-input"),
  dropZone: document.querySelector("#drop-zone"),
  uploadPreview: document.querySelector("#upload-preview"),
  uploadPreviewImage: document.querySelector("#upload-preview-image"),
  uploadFileName: document.querySelector("#upload-file-name"),
  uploadFileType: document.querySelector("#upload-file-type"),
  uploadFileSize: document.querySelector("#upload-file-size"),
  uploadTitle: document.querySelector("#upload-title-input"),
  uploadDescription: document.querySelector("#upload-description"),
  uploadTags: document.querySelector("#upload-tags"),
  uploadError: document.querySelector("#upload-error"),
  uploadSubmit: document.querySelector("#upload-submit"),
  detailDialog: document.querySelector("#detail-dialog"),
  detailImage: document.querySelector("#detail-image"),
  detailImageError: document.querySelector("#detail-image-error"),
  metadataForm: document.querySelector("#metadata-form"),
  detailTitle: document.querySelector("#detail-title-input"),
  detailDescription: document.querySelector("#detail-description"),
  detailTags: document.querySelector("#detail-tags"),
  metadataList: document.querySelector("#metadata-list"),
  detailAssetId: document.querySelector("#detail-asset-id"),
  copyIdButton: document.querySelector("#copy-id-button"),
  metadataError: document.querySelector("#metadata-error"),
  openDeleteButton: document.querySelector("#open-delete-button"),
  saveMetadataButton: document.querySelector("#save-metadata-button"),
  deleteDialog: document.querySelector("#delete-dialog"),
  deleteTarget: document.querySelector("#delete-target"),
  deleteError: document.querySelector("#delete-error"),
  cancelDeleteButton: document.querySelector("#cancel-delete-button"),
  confirmDeleteButton: document.querySelector("#confirm-delete-button"),
  unlockDialog: document.querySelector("#unlock-dialog"),
  unlockForm: document.querySelector("#unlock-form"),
  tokenInput: document.querySelector("#token-input"),
  clearTokenButton: document.querySelector("#clear-token-button"),
  unlockError: document.querySelector("#unlock-error"),
  aboutDialog: document.querySelector("#about-dialog"),
  aboutAttribution: document.querySelector("#about-attribution"),
  aboutList: document.querySelector("#about-list"),
  officialRepositoryLink: document.querySelector("#official-repository-link"),
  toastRegion: document.querySelector("#toast-region"),
};

function errorMessage(error, fallback) {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }
  return fallback;
}

function openDialog(dialog) {
  if (!dialog.open) {
    dialog.showModal();
  }
}

function closeDialog(dialog) {
  if (dialog.open) {
    dialog.close();
  }
}

function setConnectionState(mode) {
  state.tokenState = mode;
  const locked = mode === "locked";
  dom.connectionDot.classList.toggle("locked", locked);
  if (locked) {
    dom.connectionLabel.textContent = "Unlock";
  } else if (getSessionToken()) {
    dom.connectionLabel.textContent = "Unlocked";
  } else {
    dom.connectionLabel.textContent = "Local";
  }
}

function releaseObjectUrl(key) {
  const url = state.objectUrls.get(key);
  if (url) {
    URL.revokeObjectURL(url);
    state.objectUrls.delete(key);
  }
}

function releaseGridObjectUrls() {
  for (const url of state.objectUrls.values()) {
    URL.revokeObjectURL(url);
  }
  state.objectUrls.clear();
}

function releaseDetailObjectUrl() {
  if (state.detailObjectUrl) {
    URL.revokeObjectURL(state.detailObjectUrl);
    state.detailObjectUrl = "";
  }
  dom.detailImage.removeAttribute("src");
}

function releaseUploadObjectUrl() {
  if (state.uploadObjectUrl) {
    URL.revokeObjectURL(state.uploadObjectUrl);
    state.uploadObjectUrl = "";
  }
  dom.uploadPreviewImage.removeAttribute("src");
}

function currentFilters() {
  return {
    query: state.query,
    tags: state.tags,
    mimeType: state.mimeType,
    createdFrom: state.createdFrom,
    createdTo: state.createdTo,
    limit: state.limit,
    offset: state.offset,
  };
}

function updateFilterCount() {
  const count =
    state.tags.length +
    Number(Boolean(state.mimeType)) +
    Number(Boolean(state.createdFrom)) +
    Number(Boolean(state.createdTo)) +
    Number(state.limit !== 20);
  dom.filterCount.hidden = count === 0;
  dom.filterCount.textContent = String(count);
}

function updatePagination() {
  const page = Math.floor(state.offset / state.limit) + 1;
  const pages = Math.max(1, Math.ceil(state.total / state.limit));
  dom.pageStatus.textContent = `Page ${page} of ${pages}`;
  dom.previousButton.disabled = state.loading || state.offset === 0;
  dom.nextButton.disabled =
    state.loading || state.offset + state.limit >= state.total;
}

function updateArchiveCount() {
  const noun = state.total === 1 ? "image" : "images";
  dom.assetCount.textContent = `${state.total} ${noun}`;
}

function setLoading(loading) {
  state.loading = loading;
  dom.loadingLine.hidden = !loading;
  dom.assetGrid.setAttribute("aria-busy", String(loading));
  updatePagination();
}

function clearThumbnailQueue() {
  state.thumbnailQueue = [];
  state.thumbnailActive = 0;
  if (state.thumbnailObserver) {
    state.thumbnailObserver.disconnect();
  }
}

async function loadThumbnail(item) {
  try {
    const blob = await getAssetBlob(item.asset.asset_id);
    if (!item.card.isConnected) {
      return;
    }
    releaseObjectUrl(item.asset.asset_id);
    const objectUrl = URL.createObjectURL(blob);
    state.objectUrls.set(item.asset.asset_id, objectUrl);
    setCardImage(item.parts, objectUrl);
  } catch {
    if (item.card.isConnected) {
      setCardImageError(item.parts);
    }
  }
}

function processThumbnailQueue() {
  while (
    state.thumbnailActive < THUMBNAIL_CONCURRENCY &&
    state.thumbnailQueue.length
  ) {
    const item = state.thumbnailQueue.shift();
    state.thumbnailActive += 1;
    loadThumbnail(item).finally(() => {
      state.thumbnailActive -= 1;
      processThumbnailQueue();
    });
  }
}

function enqueueThumbnail(item) {
  state.thumbnailQueue.push(item);
  processThumbnailQueue();
}

function renderAssets() {
  clearThumbnailQueue();
  releaseGridObjectUrls();
  const cards = [];
  const observed = [];
  for (const asset of state.assets) {
    const parts = createAssetCard(asset, openAssetDetail);
    cards.push(parts.card);
    observed.push({ asset, card: parts.card, parts });
  }
  dom.assetGrid.replaceChildren(...cards);

  state.thumbnailObserver = new IntersectionObserver(
    (entries, observer) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) {
          continue;
        }
        observer.unobserve(entry.target);
        const item = observed.find((candidate) => candidate.card === entry.target);
        if (item) {
          enqueueThumbnail(item);
        }
      }
    },
    { rootMargin: "180px" },
  );
  for (const item of observed) {
    state.thumbnailObserver.observe(item.card);
  }
}

function updateEmptyState() {
  const empty = !state.loading && state.assets.length === 0;
  dom.emptyState.hidden = !empty;
  dom.assetGrid.hidden = empty;
  if (!empty) {
    return;
  }
  const filtered =
    Boolean(state.query) ||
    state.tags.length > 0 ||
    Boolean(state.mimeType) ||
    Boolean(state.createdFrom) ||
    Boolean(state.createdTo);
  dom.emptyTitle.textContent = filtered ? "No matching images." : "No images yet.";
  dom.emptyCopy.textContent = filtered
    ? "Try a different search or clear the filters."
    : "Add your first image.";
}

async function loadAssets(options = {}) {
  if (options.resetOffset) {
    state.offset = 0;
  }
  setLoading(true);
  dom.statusMessage.textContent = "";
  try {
    const result = await searchAssets(currentFilters());
    state.assets = result.results;
    state.total = result.total;
    state.offset = result.offset;
    state.limit = result.limit;
    setConnectionState(getSessionToken() ? "available" : "local");
    renderAssets();
  } catch (error) {
    state.assets = [];
    state.total = 0;
    renderAssets();
    if (error instanceof ApiError && error.status === 401) {
      setConnectionState("locked");
      openDialog(dom.unlockDialog);
      dom.statusMessage.textContent = "Unlock the archive to view images.";
    } else {
      dom.statusMessage.textContent = errorMessage(
        error,
        "The archive is currently unavailable.",
      );
    }
  } finally {
    setLoading(false);
    updateArchiveCount();
    updateEmptyState();
    updatePagination();
  }
}

function fillDetail(asset) {
  state.selectedAsset = asset;
  dom.detailTitle.value = asset.title;
  dom.detailDescription.value = asset.description;
  dom.detailTags.value = asset.tags.join(", ");
  dom.detailAssetId.textContent = asset.asset_id;
  dom.detailImage.alt = asset.title || asset.original_filename;
  dom.detailImageError.hidden = true;
  dom.metadataError.textContent = "";
  renderMetadataList(dom.metadataList, asset);
}

async function openAssetDetail(assetId) {
  releaseDetailObjectUrl();
  dom.detailImageError.hidden = true;
  try {
    const asset = await getAsset(assetId);
    fillDetail(asset);
    openDialog(dom.detailDialog);
    getAssetBlob(assetId)
      .then((blob) => {
        if (!state.selectedAsset || state.selectedAsset.asset_id !== assetId) {
          return;
        }
        releaseDetailObjectUrl();
        state.detailObjectUrl = URL.createObjectURL(blob);
        dom.detailImage.src = state.detailObjectUrl;
      })
      .catch(() => {
        dom.detailImageError.hidden = false;
      });
  } catch (error) {
    showToast(
      dom.toastRegion,
      errorMessage(error, "Image details are unavailable."),
      "error",
    );
  }
}

function changedMetadata() {
  const asset = state.selectedAsset;
  if (!asset) {
    return {};
  }
  const changes = {};
  const tags = splitTags(dom.detailTags.value);
  if (dom.detailTitle.value !== asset.title) {
    changes.title = dom.detailTitle.value;
  }
  if (dom.detailDescription.value !== asset.description) {
    changes.description = dom.detailDescription.value;
  }
  if (JSON.stringify(tags) !== JSON.stringify(asset.tags)) {
    changes.tags = tags;
  }
  return changes;
}

async function saveMetadata(event) {
  event.preventDefault();
  const changes = changedMetadata();
  if (!Object.keys(changes).length || !state.selectedAsset) {
    showToast(dom.toastRegion, "No changes to save.");
    return;
  }
  dom.metadataError.textContent = "";
  setButtonBusy(dom.saveMetadataButton, true, "Saving", "Save changes");
  try {
    const updated = await updateAsset(state.selectedAsset.asset_id, changes);
    fillDetail(updated);
    const index = state.assets.findIndex(
      (asset) => asset.asset_id === updated.asset_id,
    );
    if (index >= 0) {
      state.assets[index] = updated;
      renderAssets();
    }
    showToast(dom.toastRegion, "Image details updated.", "success");
  } catch (error) {
    dom.metadataError.textContent = errorMessage(
      error,
      "The changes could not be saved.",
    );
  } finally {
    setButtonBusy(dom.saveMetadataButton, false, "Saving", "Save changes");
  }
}

function validateUploadFile(file) {
  if (!file || !ALLOWED_FILE_TYPES.has(file.type)) {
    return "Choose a PNG or JPEG image.";
  }
  if (file.size > MAX_FILE_BYTES) {
    return "The image must be 10 MiB or smaller.";
  }
  return "";
}

function selectUploadFile(file) {
  const error = validateUploadFile(file);
  dom.uploadError.textContent = error;
  if (error) {
    state.uploadFile = null;
    dom.fileInput.value = "";
    dom.uploadPreview.hidden = true;
    releaseUploadObjectUrl();
    return;
  }
  state.uploadFile = file;
  releaseUploadObjectUrl();
  state.uploadObjectUrl = URL.createObjectURL(file);
  dom.uploadPreviewImage.src = state.uploadObjectUrl;
  dom.uploadFileName.textContent = file.name;
  dom.uploadFileType.textContent = file.type;
  dom.uploadFileSize.textContent = formatBytes(file.size);
  dom.uploadPreview.hidden = false;
}

function resetUploadForm() {
  dom.uploadForm.reset();
  dom.uploadError.textContent = "";
  dom.uploadPreview.hidden = true;
  state.uploadFile = null;
  releaseUploadObjectUrl();
}

async function submitUpload(event) {
  event.preventDefault();
  const file = state.uploadFile;
  const validation = validateUploadFile(file);
  if (validation) {
    dom.uploadError.textContent = validation;
    return;
  }
  setButtonBusy(dom.uploadSubmit, true, "Uploading", "Upload image");
  dom.uploadError.textContent = "";
  try {
    const result = await uploadAsset(file, {
      title: dom.uploadTitle.value,
      description: dom.uploadDescription.value,
      tags: splitTags(dom.uploadTags.value),
    });
    closeDialog(dom.uploadDialog);
    resetUploadForm();
    await loadAssets({ resetOffset: true });
    showToast(
      dom.toastRegion,
      result.deduplicated
        ? "This image is already in your archive."
        : "Image added to your archive.",
      result.deduplicated ? "warning" : "success",
    );
  } catch (error) {
    dom.uploadError.textContent = errorMessage(
      error,
      "The image could not be uploaded.",
    );
  } finally {
    setButtonBusy(dom.uploadSubmit, false, "Uploading", "Upload image");
  }
}

function openDeleteConfirmation() {
  if (!state.selectedAsset) {
    return;
  }
  dom.deleteError.textContent = "";
  dom.deleteTarget.textContent =
    state.selectedAsset.title || state.selectedAsset.original_filename;
  openDialog(dom.deleteDialog);
}

async function confirmDelete() {
  if (!state.selectedAsset) {
    return;
  }
  dom.deleteError.textContent = "";
  setButtonBusy(dom.confirmDeleteButton, true, "Deleting", "Delete");
  const assetId = state.selectedAsset.asset_id;
  try {
    const result = await deleteAsset(assetId);
    releaseObjectUrl(assetId);
    releaseDetailObjectUrl();
    state.selectedAsset = null;
    closeDialog(dom.deleteDialog);
    closeDialog(dom.detailDialog);
    await loadAssets();
    showToast(
      dom.toastRegion,
      result.cleanup_pending
        ? "The image was removed, but temporary cleanup is still pending."
        : "Image removed from the archive.",
      result.cleanup_pending ? "warning" : "success",
    );
  } catch (error) {
    dom.deleteError.textContent = errorMessage(
      error,
      "The image could not be deleted.",
    );
  } finally {
    setButtonBusy(dom.confirmDeleteButton, false, "Deleting", "Delete");
  }
}

async function submitUnlock(event) {
  event.preventDefault();
  const token = dom.tokenInput.value.trim();
  if (token.length < 32) {
    dom.unlockError.textContent = "Enter a valid Token.";
    return;
  }
  setSessionToken(token);
  dom.tokenInput.value = "";
  dom.unlockError.textContent = "";
  try {
    await searchAssets({ ...currentFilters(), limit: 1, offset: 0 });
    setConnectionState("available");
    closeDialog(dom.unlockDialog);
    await loadAssets({ resetOffset: true });
  } catch (error) {
    clearSessionToken();
    setConnectionState("locked");
    dom.unlockError.textContent = errorMessage(
      error,
      "The archive could not be unlocked.",
    );
  }
}

async function showAbout() {
  openDialog(dom.aboutDialog);
  try {
    const about = await getAbout();
    dom.aboutAttribution.textContent = about.attribution;
    renderAbout(dom.aboutList, about);
    dom.officialRepositoryLink.href = about.official_repository;
  } catch {
    dom.aboutAttribution.textContent = "Project information is unavailable.";
    dom.aboutList.replaceChildren();
    dom.officialRepositoryLink.removeAttribute("href");
  }
}

function clearFilters() {
  state.query = "";
  state.tags = [];
  state.mimeType = "";
  state.createdFrom = "";
  state.createdTo = "";
  state.limit = 20;
  state.offset = 0;
  dom.searchInput.value = "";
  dom.tagsFilter.value = "";
  dom.mimeFilter.value = "";
  dom.createdFrom.value = "";
  dom.createdTo.value = "";
  dom.limitSelect.value = "20";
  updateFilterCount();
  loadAssets();
}

function applyFilters() {
  state.tags = splitTags(dom.tagsFilter.value);
  state.mimeType = dom.mimeFilter.value;
  state.createdFrom = dom.createdFrom.value;
  state.createdTo = dom.createdTo.value;
  state.limit = Number(dom.limitSelect.value) || 20;
  state.offset = 0;
  updateFilterCount();
  loadAssets();
}

function connectEvents() {
  dom.openUploadButton.addEventListener("click", () => openDialog(dom.uploadDialog));
  dom.emptyUploadButton.addEventListener("click", () => openDialog(dom.uploadDialog));
  dom.aboutButton.addEventListener("click", showAbout);
  dom.connectionButton.addEventListener("click", () => openDialog(dom.unlockDialog));
  dom.toggleFiltersButton.addEventListener("click", () => {
    const expanded = dom.toggleFiltersButton.getAttribute("aria-expanded") === "true";
    dom.toggleFiltersButton.setAttribute("aria-expanded", String(!expanded));
    dom.filtersPanel.hidden = expanded;
  });
  dom.clearFiltersButton.addEventListener("click", clearFilters);
  dom.searchInput.addEventListener("input", () => {
    window.clearTimeout(state.debounceTimer);
    state.debounceTimer = window.setTimeout(() => {
      state.query = dom.searchInput.value.trim();
      loadAssets({ resetOffset: true });
    }, 300);
  });
  for (const input of [
    dom.tagsFilter,
    dom.mimeFilter,
    dom.createdFrom,
    dom.createdTo,
    dom.limitSelect,
  ]) {
    input.addEventListener("change", applyFilters);
  }
  dom.previousButton.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    loadAssets();
  });
  dom.nextButton.addEventListener("click", () => {
    state.offset += state.limit;
    loadAssets();
  });
  dom.fileInput.addEventListener("change", () => {
    selectUploadFile(dom.fileInput.files[0]);
  });
  for (const eventName of ["dragenter", "dragover"]) {
    dom.dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dom.dropZone.classList.add("dragging");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    dom.dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dom.dropZone.classList.remove("dragging");
    });
  }
  dom.dropZone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0];
    selectUploadFile(file);
  });
  dom.uploadForm.addEventListener("submit", submitUpload);
  dom.metadataForm.addEventListener("submit", saveMetadata);
  dom.openDeleteButton.addEventListener("click", openDeleteConfirmation);
  dom.cancelDeleteButton.addEventListener("click", () => closeDialog(dom.deleteDialog));
  dom.confirmDeleteButton.addEventListener("click", confirmDelete);
  dom.unlockForm.addEventListener("submit", submitUnlock);
  dom.clearTokenButton.addEventListener("click", () => {
    clearSessionToken();
    dom.tokenInput.value = "";
    setConnectionState("locked");
    closeDialog(dom.unlockDialog);
    loadAssets({ resetOffset: true });
  });
  dom.copyIdButton.addEventListener("click", async () => {
    if (!state.selectedAsset) {
      return;
    }
    try {
      await navigator.clipboard.writeText(state.selectedAsset.asset_id);
      showToast(dom.toastRegion, "Asset ID copied.", "success");
    } catch {
      showToast(dom.toastRegion, "Asset ID could not be copied.", "error");
    }
  });
  for (const button of document.querySelectorAll("[data-close-dialog]")) {
    button.addEventListener("click", () => {
      const dialog = document.getElementById(button.dataset.closeDialog);
      closeDialog(dialog);
    });
  }
  dom.uploadDialog.addEventListener("close", resetUploadForm);
  dom.detailDialog.addEventListener("close", () => {
    releaseDetailObjectUrl();
    state.selectedAsset = null;
  });
  window.addEventListener("remember-me-auth-required", () => {
    setConnectionState("locked");
    openDialog(dom.unlockDialog);
  });
  window.addEventListener("beforeunload", () => {
    releaseGridObjectUrls();
    releaseDetailObjectUrl();
    releaseUploadObjectUrl();
  });
}

async function start() {
  connectEvents();
  setConnectionState(getSessionToken() ? "available" : "local");
  await Promise.allSettled([showAboutDataOnly(), loadAssets()]);
}

async function showAboutDataOnly() {
  try {
    const about = await getAbout();
    document.title = about.project_name;
    dom.aboutAttribution.textContent = about.attribution;
    renderAbout(dom.aboutList, about);
    dom.officialRepositoryLink.href = about.official_repository;
  } catch {
    return;
  }
}

start();
