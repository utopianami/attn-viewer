export function buildDocumentPayload({ metadata, markdown, convertedAt, warnings, assets, analysis }) {
  return {
    id: metadata.id,
    originalName: metadata.originalName,
    size: metadata.size,
    uploadedAt: metadata.uploadedAt,
    convertedAt,
    markdown,
    markdownBytes: Buffer.byteLength(markdown, "utf8"),
    pdfUrl: `/api/documents/${metadata.id}/pdf`,
    assets: assets || { pageCount: null, charts: [], pages: [] },
    analysis,
    warnings: cleanWarningText(warnings),
  };
}

export function buildSharedDocumentPayload(document, token) {
  return {
    ...document,
    pdfUrl: `/api/shares/${token}/pdf`,
    analysisStatus: document.analysis ? "succeeded" : "idle",
    analysisProgress: null,
    activeAnalysisJobId: "",
    assets: {
      ...(document.assets || {}),
      charts: remapSharedAssets(document.assets?.charts || [], token),
      pages: remapSharedAssets(document.assets?.pages || [], token),
    },
  };
}

function remapSharedAssets(assets, token) {
  return assets.map((asset) => ({
    ...asset,
    url: `/api/shares/${token}/assets/${encodeURIComponent(asset.file)}`,
  }));
}

export function isValidDocumentId(id) {
  return /^[a-zA-Z0-9-]+$/.test(id);
}

export function normalizeDocumentTitle(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= 180 ? text : "";
}

export function isValidNoteId(id) {
  return /^[a-zA-Z0-9-]+$/.test(id);
}

export function isValidShareToken(token) {
  return /^[a-zA-Z0-9-]+$/.test(token);
}

export function isValidAssetFile(file) {
  return /^[^/\\]+$/.test(file);
}

export function isValidAnalysisHtmlFile(file) {
  return /^[^/\\]+\.html?$/i.test(file);
}

export function normalizeAssetManifest(id, manifest) {
  return {
    pageCount: manifest.pageCount || null,
    charts: normalizeAssets(id, manifest.charts || []),
    pages: normalizeAssets(id, manifest.pages || []),
    error: manifest.error || "",
  };
}

function normalizeAssets(id, assets) {
  return assets.map((asset) => ({
    ...asset,
    url: `/assets/${id}/${encodeURIComponent(asset.file)}`,
  }));
}

export function cleanWarningText(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.includes("Could not get FontBBox from font descriptor"))
    .join("\n");
}

export function splitSentences(text) {
  return String(text || "")
    .replace(/\s+/g, " ")
    .trim()
    .match(/[^.!?。！？]+[.!?。！？]?/g)
    ?.map((sentence) => sentence.trim())
    .filter(Boolean) || [];
}

