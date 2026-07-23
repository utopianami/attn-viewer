import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDocumentPayload,
  buildSharedDocumentPayload,
  cleanWarningText,
  isValidAnalysisHtmlFile,
  isValidAssetFile,
  isValidDocumentId,
  isValidNoteId,
  isValidShareToken,
  normalizeAssetManifest,
  normalizeDocumentTitle,
  splitSentences,
} from "./document-utils.mjs";

test("path validators preserve accepted ids and reject traversal", () => {
  assert.equal(isValidDocumentId("doc-123"), true);
  assert.equal(isValidNoteId("note-123"), true);
  assert.equal(isValidShareToken("share-123"), true);
  assert.equal(isValidDocumentId("../doc"), false);
  assert.equal(isValidAssetFile("chart 1.png"), true);
  assert.equal(isValidAssetFile("../chart.png"), false);
  assert.equal(isValidAnalysisHtmlFile("report.HTML"), true);
  assert.equal(isValidAnalysisHtmlFile("report.pdf"), false);
});

test("document title and warnings keep current normalization rules", () => {
  assert.equal(normalizeDocumentTitle("  Hello\n world  "), "Hello world");
  assert.equal(normalizeDocumentTitle("x".repeat(181)), "");
  assert.equal(
    cleanWarningText(" keep me \nCould not get FontBBox from font descriptor 123\n\n second "),
    "keep me\nsecond",
  );
});

test("asset manifests generate current authenticated asset URLs", () => {
  assert.deepEqual(
    normalizeAssetManifest("doc-1", {
      pageCount: 2,
      charts: [{ file: "chart one.png", page: 1 }],
      pages: [{ file: "page-1.png" }],
      error: "",
    }),
    {
      pageCount: 2,
      charts: [{ file: "chart one.png", page: 1, url: "/assets/doc-1/chart%20one.png" }],
      pages: [{ file: "page-1.png", url: "/assets/doc-1/page-1.png" }],
      error: "",
    },
  );
});

test("document payloads preserve byte counts and public share URL remapping", () => {
  const document = buildDocumentPayload({
    metadata: {
      id: "doc-1",
      originalName: "Fixture",
      size: 10,
      uploadedAt: "uploaded",
    },
    markdown: "한글",
    convertedAt: "converted",
    warnings: "warning",
    assets: {
      pageCount: 1,
      charts: [{ file: "chart.png", url: "/assets/doc-1/chart.png" }],
      pages: [],
    },
    analysis: null,
  });
  assert.equal(document.markdownBytes, 6);
  assert.equal(document.pdfUrl, "/api/documents/doc-1/pdf");

  const shared = buildSharedDocumentPayload(document, "token-1");
  assert.equal(shared.pdfUrl, "/api/shares/token-1/pdf");
  assert.equal(shared.assets.charts[0].url, "/api/shares/token-1/assets/chart.png");
  assert.equal(shared.analysisStatus, "idle");
  assert.equal(shared.analysisProgress, null);
});

test("sentence splitting keeps punctuation and supports CJK terminators", () => {
  assert.deepEqual(splitSentences(" First. 둘째! 最後。 "), ["First.", "둘째!", "最後。"]);
  assert.deepEqual(splitSentences(""), []);
});

