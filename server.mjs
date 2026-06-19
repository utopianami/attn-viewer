import express from "express";
import multer from "multer";
import { execFile, spawn } from "node:child_process";
import { randomUUID, timingSafeEqual } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { mkdir, readFile, readdir, rm, stat, unlink, writeFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { promisify } from "node:util";

loadEnvFile(join(process.cwd(), ".env"));

const port = Number(process.env.PORT || 3000);
const publicDir = join(process.cwd(), "public");
const storageDir = join(process.cwd(), "storage");
const sessionsPath = join(storageDir, "sessions.json");
const analysisJobsPath = join(storageDir, "analysis-jobs.json");
const usersDir = join(storageDir, "users");
const schemasDir = join(process.cwd(), "schemas");
const markitdownBin = process.env.MARKITDOWN_BIN || join(process.cwd(), ".venv", "bin", "markitdown");
const pythonBin = process.env.PYTHON_BIN || join(process.cwd(), ".venv", "bin", "python");
const assetExtractorScript = join(process.cwd(), "scripts", "extract_pdf_assets.py");
const codexBin = process.env.CODEX_BIN || "codex";
const codexModel = process.env.CODEX_MODEL || "";
const analysisSchemaPath = join(schemasDir, "translation-analysis.schema.json");
const analysisChunkPages = parsePositiveInteger(process.env.CODEX_ANALYSIS_CHUNK_PAGES, 4);
const analysisConcurrency = parsePositiveInteger(process.env.CODEX_ANALYSIS_CONCURRENCY, 2);
const maxUploadMb = Number(process.env.MAX_UPLOAD_MB || 50);
const execFileAsync = promisify(execFile);
const users = parseAuthUsers(process.env.AUTH_USERS_JSON || "");
const sessions = new Map();
const sessionMaxAgeMs = 1000 * 60 * 60 * 24 * 14;
const analysisJobs = new Map();
const activeAnalysisJobs = new Map();

await mkdir(usersDir, { recursive: true });
await loadSessions();
await loadAnalysisJobs();

const app = express();
app.use(express.json({ limit: "1mb" }));
const diskStorage = multer.diskStorage({
  destination: (req, _file, done) => {
    done(null, req.userDirs.uploads);
  },
  filename: (_req, file, done) => {
    done(null, `${Date.now()}-${randomUUID()}${extname(file.originalname) || ".pdf"}`);
  },
});

const upload = multer({
  storage: diskStorage,
  limits: {
    fileSize: maxUploadMb * 1024 * 1024,
    files: 1,
  },
  fileFilter: (_req, file, done) => {
    const extension = extname(file.originalname).toLowerCase();
    const isPdfMime =
      file.mimetype === "application/pdf" || file.mimetype === "application/octet-stream";

    if (extension === ".pdf" && isPdfMime) {
      done(null, true);
      return;
    }

    done(new Error("PDF 파일만 업로드할 수 있습니다."));
  },
});

app.get("/api/session", async (req, res) => {
  const user = getSessionUser(req);
  if (!user) {
    res.status(401).json({ ok: false, error: "로그인이 필요합니다." });
    return;
  }

  res.json({ ok: true, user: { username: user } });
});

app.post("/api/login", async (req, res) => {
  const username = String(req.body?.username || "").trim();
  const password = String(req.body?.password || "");

  if (users.size === 0) {
    res.status(503).json({ ok: false, error: "로그인 계정 설정이 필요합니다." });
    return;
  }

  if (!isValidLogin(username, password)) {
    res.status(401).json({ ok: false, error: "아이디 또는 비밀번호가 올바르지 않습니다." });
    return;
  }

  await ensureUserDirs(username);
  const token = randomUUID();
  const expiresAt = Date.now() + sessionMaxAgeMs;
  sessions.set(token, { username, expiresAt });
  persistSessions();
  res.setHeader(
    "set-cookie",
    `attn_session=${token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=${sessionMaxAgeMs / 1000}`,
  );
  res.json({ ok: true, user: { username } });
});

app.post("/api/logout", (req, res) => {
  const token = getCookie(req, "attn_session");
  if (token) {
    sessions.delete(token);
    persistSessions();
  }
  res.setHeader("set-cookie", "attn_session=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0");
  res.json({ ok: true });
});

app.use("/api/documents", requireAuth);
app.use("/api/uploads", requireAuth);
app.use("/api/analysis-jobs", requireAuth);
app.use("/assets", requireAuth);

app.get("/api/documents", async (req, res) => {
  try {
    const documents = await listDocuments(req.userDirs, req.user.username);
    res.json({ ok: true, documents });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "글 목록을 불러오지 못했습니다.",
    });
  }
});

app.get("/api/documents/latest", async (req, res) => {
  try {
    const document = attachDocumentAnalysisJob(
      await getLatestDocument(req.userDirs),
      req.user.username,
    );
    res.json({ ok: true, document });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "문서를 불러오지 못했습니다.",
    });
  }
});

app.get("/api/documents/:id", async (req, res) => {
  if (!isValidDocumentId(req.params.id)) {
    res.status(400).json({ ok: false, error: "Bad document id" });
    return;
  }

  try {
    const document = attachDocumentAnalysisJob(
      await getDocument(req.userDirs, req.params.id),
      req.user.username,
    );
    if (!document) {
      res.status(404).json({ ok: false, error: "글을 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true, document });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "글을 불러오지 못했습니다.",
    });
  }
});

app.delete("/api/documents/:id", async (req, res) => {
  if (!isValidDocumentId(req.params.id)) {
    res.status(400).json({ ok: false, error: "Bad document id" });
    return;
  }

  try {
    const deleted = await deleteDocument(req.userDirs, req.user.username, req.params.id);
    if (!deleted) {
      res.status(404).json({ ok: false, error: "글을 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "글 삭제에 실패했습니다.",
    });
  }
});

app.get("/api/documents/:id/pdf", (req, res) => {
  if (!isValidDocumentId(req.params.id)) {
    res.status(400).send("Bad document id");
    return;
  }

  const pdfPath = join(req.userDirs.uploads, `${req.params.id}.pdf`);
  if (!existsSync(pdfPath)) {
    res.status(404).send("PDF not found");
    return;
  }

  res.sendFile(pdfPath, {
    headers: {
      "cache-control": "no-store",
      "content-type": "application/pdf",
      "content-disposition": "inline",
    },
  });
});

app.post("/api/documents/:id/analyze", async (req, res) => {
  if (!isValidDocumentId(req.params.id)) {
    res.status(400).json({ ok: false, error: "Bad document id" });
    return;
  }

  try {
    const maxAnalysisPages = Number(process.env.MAX_ANALYSIS_PAGES || 25);
    const requestedPages = Number(req.body?.pages || req.query.pages || 0);
    const pages =
      requestedPages > 0 ? Math.max(1, Math.min(maxAnalysisPages, requestedPages)) : 0;
    const job = createAnalysisJob(req.user.username, req.userDirs, req.params.id, pages);
    res.status(202).json({ ok: true, job: serializeAnalysisJob(job) });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "번역 작업을 시작하지 못했습니다.",
    });
  }
});

app.get("/api/analysis-jobs/:jobId", (req, res) => {
  if (!isValidDocumentId(req.params.jobId)) {
    res.status(400).json({ ok: false, error: "Bad job id" });
    return;
  }

  const job = analysisJobs.get(req.params.jobId);
  if (!job || job.username !== req.user.username) {
    res.status(404).json({ ok: false, error: "번역 작업을 찾지 못했습니다." });
    return;
  }

  res.json({ ok: true, job: serializeAnalysisJob(job) });
});

app.post("/api/uploads/pdf", (req, res) => {
  upload.single("pdf")(req, res, async (error) => {
    if (error) {
      const status = error instanceof multer.MulterError ? 413 : 400;
      res.status(status).json({
        ok: false,
        error:
          error instanceof multer.MulterError && error.code === "LIMIT_FILE_SIZE"
            ? `PDF는 ${maxUploadMb}MB 이하만 업로드할 수 있습니다.`
            : error.message,
      });
      return;
    }

    if (!req.file) {
      res.status(400).json({ ok: false, error: "업로드할 PDF를 선택하세요." });
      return;
    }

    const metadata = {
      id: req.file.filename.replace(/\.pdf$/i, ""),
      originalName: req.file.originalname,
      size: req.file.size,
      storedName: req.file.filename,
      uploadedAt: new Date().toISOString(),
    };

    try {
      const document = attachDocumentAnalysisJob(
        await convertDocument(req.userDirs, metadata),
        req.user.username,
      );
      res.json({ ok: true, document });
    } catch (conversionError) {
      res.status(500).json({
        ok: false,
        error: conversionError.message || "PDF 변환에 실패했습니다.",
      });
    }
  });
});

app.get("/assets/:id/:file", (req, res) => {
  if (!isValidDocumentId(req.params.id) || !isValidAssetFile(req.params.file)) {
    res.status(400).send("Bad asset path");
    return;
  }

  res.sendFile(join(req.userDirs.assets, req.params.id, req.params.file), {
    headers: {
      "cache-control": "no-store",
    },
  });
});

app.use(
  express.static(publicDir, {
    etag: false,
    lastModified: false,
    setHeaders: (res) => {
      res.setHeader("cache-control", "no-store");
    },
  }),
);

app.listen(port, "127.0.0.1", () => {
  console.log(`attn-viewer listening on http://127.0.0.1:${port}`);
});

async function requireAuth(req, res, next) {
  const username = getSessionUser(req);
  if (!username) {
    res.status(401).json({ ok: false, error: "로그인이 필요합니다." });
    return;
  }

  req.user = { username };
  req.userDirs = await ensureUserDirs(username);
  next();
}

function getSessionUser(req) {
  const token = getCookie(req, "attn_session");
  if (!token) {
    return null;
  }

  const session = sessions.get(token);
  if (!session) {
    return null;
  }

  if (Date.now() > session.expiresAt) {
    sessions.delete(token);
    persistSessions();
    return null;
  }

  return session.username;
}

function getCookie(req, name) {
  const cookies = String(req.headers.cookie || "").split(/;\s*/);
  for (const cookie of cookies) {
    const index = cookie.indexOf("=");
    if (index === -1) {
      continue;
    }
    if (cookie.slice(0, index) === name) {
      return decodeURIComponent(cookie.slice(index + 1));
    }
  }
  return "";
}

function isValidLogin(username, password) {
  const expected = users.get(username);
  return Boolean(expected) && safeEqual(password, expected);
}

function safeEqual(first, second) {
  const firstBuffer = Buffer.from(String(first));
  const secondBuffer = Buffer.from(String(second));
  return firstBuffer.length === secondBuffer.length && timingSafeEqual(firstBuffer, secondBuffer);
}

function parsePositiveInteger(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return fallback;
  }
  return Math.floor(parsed);
}

async function loadSessions() {
  try {
    const raw = await readFile(sessionsPath, "utf8");
    const parsed = JSON.parse(raw);
    const now = Date.now();

    Object.entries(parsed).forEach(([token, session]) => {
      const username = String(session?.username || "");
      const expiresAt = Number(session?.expiresAt || 0);
      if (token && username && expiresAt > now) {
        sessions.set(token, { username, expiresAt });
      }
    });

    persistSessions();
  } catch {
    sessions.clear();
  }
}

function persistSessions() {
  const payload = Object.fromEntries(sessions.entries());
  writeFile(sessionsPath, JSON.stringify(payload, null, 2)).catch(() => {});
}

function parseAuthUsers(raw) {
  if (!raw.trim()) {
    return new Map();
  }

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("AUTH_USERS_JSON must be an object");
    }

    return new Map(
      Object.entries(parsed)
        .map(([username, password]) => [String(username).trim(), String(password)])
        .filter(([username, password]) => username && password),
    );
  } catch (error) {
    throw new Error(`AUTH_USERS_JSON 설정을 읽지 못했습니다: ${error.message}`);
  }
}

function loadEnvFile(path) {
  if (!existsSync(path)) {
    return;
  }

  const lines = readFileSync(path, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const index = trimmed.indexOf("=");
    if (index === -1) {
      continue;
    }

    const key = trimmed.slice(0, index).trim();
    const value = unquoteEnvValue(trimmed.slice(index + 1).trim());
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

function unquoteEnvValue(value) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

async function ensureUserDirs(username) {
  const root = join(usersDir, username);
  const dirs = {
    root,
    uploads: join(root, "uploads"),
    converted: join(root, "converted"),
    documents: join(root, "documents"),
    assets: join(root, "assets"),
    analysis: join(root, "analysis"),
  };

  await Promise.all(Object.values(dirs).map((dir) => mkdir(dir, { recursive: true })));
  return dirs;
}

async function getLatestDocument(dirs) {
  const latestUpload = await getLatestUpload(dirs);
  if (!latestUpload) {
    return null;
  }

  return getDocument(dirs, latestUpload.id, latestUpload);
}

async function getDocument(dirs, id, fallbackMetadata = null) {
  const metadata = (await readMetadata(dirs, id)) || fallbackMetadata;
  if (!metadata) {
    return null;
  }

  const markdownPath = join(dirs.converted, `${metadata.id}.md`);

  if (!existsSync(markdownPath)) {
    return convertDocument(dirs, metadata);
  }

  const markdown = await readFile(markdownPath, "utf8");
  const markdownStat = await stat(markdownPath);
  const assets = await getOrExtractAssets(dirs, metadata);
  const analysis = await readAnalysis(dirs, metadata.id);

  return buildDocumentPayload({
    metadata,
    markdown,
    convertedAt: markdownStat.mtime.toISOString(),
    warnings: cleanWarningText(metadata.warnings || ""),
    assets,
    analysis,
  });
}

async function listDocuments(dirs, username) {
  const ids = new Set();
  const metadataFiles = (await readdir(dirs.documents)).filter((file) => file.endsWith(".json"));
  metadataFiles.forEach((file) => ids.add(file.replace(/\.json$/i, "")));

  const uploadFiles = (await readdir(dirs.uploads)).filter((file) => file.endsWith(".pdf"));
  uploadFiles.forEach((file) => ids.add(file.replace(/\.pdf$/i, "")));

  const documents = await Promise.all(
    [...ids].map(async (id) => {
      const metadata = (await readMetadata(dirs, id)) || {
        id,
        originalName: `${id}.pdf`,
        storedName: `${id}.pdf`,
      };
      const pdfPath = join(dirs.uploads, metadata.storedName || `${id}.pdf`);
      const pdfStat = existsSync(pdfPath) ? await stat(pdfPath) : null;
      const convertedPath = join(dirs.converted, `${id}.md`);
      const convertedStat = existsSync(convertedPath) ? await stat(convertedPath) : null;
      const analysis = await readAnalysis(dirs, id);
      const analysisJob = findActiveAnalysisJob(username, id);
      const summary = String(analysis?.overall?.summary || "").trim();

      return {
        id,
        originalName: metadata.originalName || `${id}.pdf`,
        size: metadata.size || pdfStat?.size || 0,
        uploadedAt: metadata.uploadedAt || pdfStat?.mtime?.toISOString() || "",
        convertedAt: metadata.convertedAt || convertedStat?.mtime?.toISOString() || "",
        hasAnalysis: Boolean(analysis),
        analysisStatus: analysis ? "succeeded" : analysisJob?.status || "idle",
        analysisProgress: analysisJob?.progress || null,
        activeAnalysisJobId: analysisJob?.id || "",
        summary: summary ? summary.slice(0, 220) : "",
        mtimeMs: Math.max(
          pdfStat?.mtimeMs || 0,
          convertedStat?.mtimeMs || 0,
          Date.parse(metadata.convertedAt || metadata.uploadedAt || "") || 0,
        ),
      };
    }),
  );

  documents.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return documents.map(({ mtimeMs, ...document }) => document);
}

function findActiveAnalysisJob(username, documentId) {
  const activeJobId = activeAnalysisJobs.get(`${username}:${documentId}`);
  return activeJobId ? analysisJobs.get(activeJobId) || null : null;
}

function attachDocumentAnalysisJob(document, username) {
  if (!document) {
    return document;
  }

  const analysisJob = findActiveAnalysisJob(username, document.id);
  return {
    ...document,
    analysisStatus: document.analysis ? "succeeded" : analysisJob?.status || "idle",
    analysisProgress: analysisJob?.progress || null,
    activeAnalysisJobId: analysisJob?.id || "",
  };
}

async function deleteDocument(dirs, username, id) {
  const metadata = await readMetadata(dirs, id);
  const uploadPath = join(dirs.uploads, metadata?.storedName || `${id}.pdf`);
  const fallbackUploadPath = join(dirs.uploads, `${id}.pdf`);
  const knownPaths = [
    uploadPath,
    fallbackUploadPath,
    join(dirs.converted, `${id}.md`),
    join(dirs.documents, `${id}.json`),
    join(dirs.analysis, `${id}.ko.json`),
  ];

  const existed = knownPaths.some((path) => existsSync(path)) || existsSync(join(dirs.assets, id));
  if (!existed) {
    return false;
  }

  await Promise.all(
    [...new Set(knownPaths)].map((path) => unlink(path).catch((error) => {
      if (error.code !== "ENOENT") {
        throw error;
      }
    })),
  );
  await rm(join(dirs.assets, id), { recursive: true, force: true });

  const activeKey = `${username}:${id}`;
  const activeJobId = activeAnalysisJobs.get(activeKey);
  if (activeJobId) {
    activeAnalysisJobs.delete(activeKey);
    const activeJob = analysisJobs.get(activeJobId);
    if (activeJob) {
      updateAnalysisJob(activeJob, {
        status: "failed",
        error: "문서가 삭제되었습니다.",
      });
    }
  }

  return true;
}

async function getLatestUpload(dirs) {
  const files = (await readdir(dirs.uploads)).filter((file) => file.endsWith(".pdf"));
  if (files.length === 0) {
    return null;
  }

  const candidates = await Promise.all(
    files.map(async (file) => {
      const pdfPath = join(dirs.uploads, file);
      const fileStat = await stat(pdfPath);
      return {
        id: file.replace(/\.pdf$/i, ""),
        originalName: file,
        size: fileStat.size,
        storedName: file,
        uploadedAt: fileStat.mtime.toISOString(),
        mtimeMs: fileStat.mtimeMs,
      };
    }),
  );

  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return candidates[0];
}

async function convertDocument(dirs, metadata) {
  const pdfPath = join(dirs.uploads, metadata.storedName);
  const markdownPath = join(dirs.converted, `${metadata.id}.md`);

  const { stderr } = await execFileAsync(markitdownBin, [pdfPath, "-o", markdownPath], {
    maxBuffer: 20 * 1024 * 1024,
  });

  const markdown = await readFile(markdownPath, "utf8");
  const markdownStat = await stat(markdownPath);
  const assets = await getOrExtractAssets(dirs, metadata);
  const savedMetadata = {
    ...metadata,
    convertedAt: markdownStat.mtime.toISOString(),
    warnings: cleanWarningText(stderr),
  };

  await writeFile(join(dirs.documents, `${metadata.id}.json`), JSON.stringify(savedMetadata, null, 2));

  return buildDocumentPayload({
    metadata: savedMetadata,
    markdown,
    convertedAt: savedMetadata.convertedAt,
    warnings: savedMetadata.warnings,
    assets,
    analysis: null,
  });
}

async function analyzeDocument(dirs, id, pageLimit, onProgress = () => {}) {
  const metadata = await readMetadata(dirs, id);
  const storedName = metadata?.storedName || `${id}.pdf`;
  const pdfPath = join(dirs.uploads, storedName);
  const markdownPath = join(dirs.converted, `${id}.md`);

  if (!existsSync(pdfPath) || !existsSync(markdownPath)) {
    throw new Error("분석할 문서를 찾지 못했습니다.");
  }

  const markdown = await readFile(markdownPath, "utf8");
  const pageTexts = markdown.split("\f");
  const effectivePageLimit =
    pageLimit > 0 ? Math.min(pageLimit, pageTexts.length) : pageTexts.length;
  const assets = await getOrExtractAssets(dirs, {
    id,
    storedName,
    originalName: metadata?.originalName || storedName,
  });
  const sourcePages = buildAnalysisSource(markdown, assets.charts || [], effectivePageLimit);
  const totalChunks = Math.max(1, Math.ceil(sourcePages.pages.length / analysisChunkPages));
  const totalSteps = effectivePageLimit > analysisChunkPages ? totalChunks + 1 : 1;
  onProgress({
    completed: 0,
    total: totalSteps,
    percent: 0,
    message: `전체 ${effectivePageLimit}페이지 번역 준비 중`,
  });
  const analysis =
    effectivePageLimit > analysisChunkPages
      ? await requestChunkedTranslationAnalysis(
          dirs,
          id,
          sourcePages,
          assets.charts || [],
          onProgress,
          totalSteps,
        )
      : await requestTranslationAnalysis(
          sourcePages,
          effectivePageLimit,
          getChartImagePaths(dirs, id, assets.charts || [], sourcePages.pages),
        );
  if (effectivePageLimit <= analysisChunkPages) {
    onProgress({
      completed: 1,
      total: 1,
      percent: 100,
      message: "번역 결과 정리 중",
    });
  }
  const savedAnalysis = {
    ...analysis,
    id,
    analysisVersion: 3,
    generatedAt: new Date().toISOString(),
    provider: "codex",
    model: codexModel || "codex-default",
    pageLimit: effectivePageLimit,
    isSample: effectivePageLimit < pageTexts.length,
  };

  await writeFile(join(dirs.analysis, `${id}.ko.json`), JSON.stringify(savedAnalysis, null, 2));
  return savedAnalysis;
}

function createAnalysisJob(username, dirs, documentId, pageLimit) {
  const activeKey = `${username}:${documentId}`;
  const activeJobId = activeAnalysisJobs.get(activeKey);
  const activeJob = activeJobId ? analysisJobs.get(activeJobId) : null;

  if (activeJob && ["queued", "running"].includes(activeJob.status)) {
    return activeJob;
  }

  const now = new Date().toISOString();
  const job = {
    id: randomUUID(),
    username,
    documentId,
    pageLimit,
    status: "queued",
    progress: {
      completed: 0,
      total: 1,
      percent: 0,
      message: "번역 대기 중",
    },
    createdAt: now,
    updatedAt: now,
    error: "",
    analysis: null,
  };

  analysisJobs.set(job.id, job);
  activeAnalysisJobs.set(activeKey, job.id);
  persistAnalysisJobs();
  setImmediate(() => runAnalysisJob(job.id, dirs));
  return job;
}

async function runAnalysisJob(jobId, dirs) {
  const job = analysisJobs.get(jobId);
  if (!job) {
    return;
  }

  updateAnalysisJob(job, { status: "running" });

  try {
    const analysis = await analyzeDocument(dirs, job.documentId, job.pageLimit, (progress) => {
      updateAnalysisJob(job, { progress });
    });
    updateAnalysisJob(job, {
      status: "succeeded",
      progress: {
        completed: job.progress?.total || 1,
        total: job.progress?.total || 1,
        percent: 100,
        message: "번역 완료",
      },
      analysis,
    });
  } catch (error) {
    updateAnalysisJob(job, {
      status: "failed",
      error: error.message || "번역 생성에 실패했습니다.",
    });
  } finally {
    const activeKey = `${job.username}:${job.documentId}`;
    if (activeAnalysisJobs.get(activeKey) === job.id) {
      activeAnalysisJobs.delete(activeKey);
    }
    persistAnalysisJobs();
  }
}

function updateAnalysisJob(job, patch) {
  Object.assign(job, patch, { updatedAt: new Date().toISOString() });
  persistAnalysisJobs();
}

function serializeAnalysisJob(job) {
  return {
    id: job.id,
    documentId: job.documentId,
    pageLimit: job.pageLimit,
    status: job.status,
    progress: job.progress || {
      completed: 0,
      total: 1,
      percent: 0,
      message: "",
    },
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    error: job.error,
    analysis: job.status === "succeeded" ? job.analysis : null,
  };
}

function normalizeJobProgress(progress) {
  const completed = Math.max(0, Number(progress?.completed || 0));
  const total = Math.max(1, Number(progress?.total || 1));
  return {
    completed: Math.min(completed, total),
    total,
    percent: Math.max(0, Math.min(100, Number(progress?.percent || 0))),
    message: String(progress?.message || ""),
  };
}

async function loadAnalysisJobs() {
  try {
    const raw = await readFile(analysisJobsPath, "utf8");
    const parsed = JSON.parse(raw);

    Object.entries(parsed).forEach(([jobId, job]) => {
      if (!job || typeof job !== "object") {
        return;
      }

      const restoredJob = {
        id: String(job.id || jobId),
        username: String(job.username || ""),
        documentId: String(job.documentId || ""),
        pageLimit: Number(job.pageLimit || 1),
        status: ["queued", "running"].includes(job.status) ? "queued" : String(job.status || "failed"),
        progress: normalizeJobProgress(job.progress),
        createdAt: String(job.createdAt || new Date().toISOString()),
        updatedAt: new Date().toISOString(),
        error: String(job.error || ""),
        analysis: job.analysis || null,
      };

      if (!restoredJob.username || !isValidDocumentId(restoredJob.documentId)) {
        return;
      }

      analysisJobs.set(restoredJob.id, restoredJob);
      if (restoredJob.status === "queued") {
        activeAnalysisJobs.set(`${restoredJob.username}:${restoredJob.documentId}`, restoredJob.id);
        setImmediate(async () => {
          const dirs = await ensureUserDirs(restoredJob.username);
          runAnalysisJob(restoredJob.id, dirs);
        });
      }
    });

    persistAnalysisJobs();
  } catch {
    analysisJobs.clear();
  }
}

function persistAnalysisJobs() {
  const keepAfterMs = 1000 * 60 * 60 * 24;
  const now = Date.now();

  for (const [jobId, job] of analysisJobs.entries()) {
    const updatedAtMs = Date.parse(job.updatedAt || "");
    if (
      ["succeeded", "failed"].includes(job.status) &&
      updatedAtMs &&
      now - updatedAtMs > keepAfterMs
    ) {
      analysisJobs.delete(jobId);
    }
  }

  const payload = Object.fromEntries(analysisJobs.entries());
  writeFile(analysisJobsPath, JSON.stringify(payload, null, 2)).catch(() => {});
}

function buildAnalysisSource(markdown, charts, pageLimit) {
  const pages = markdown
    .split("\f")
    .slice(0, pageLimit)
    .map((pageText, pageIndex) => {
      const pageNumber = pageIndex + 1;
      const paragraphs = pageText
        .split(/\n{2,}/)
        .map((part) => part.replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .filter((paragraph) => !isBoilerplateText(paragraph) || hasResearchSignal(paragraph))
        .map((paragraph) => ({
          text: paragraph,
          sentences: splitSentences(paragraph),
        }));

      return {
        page: pageNumber,
        paragraphs,
        charts: charts
          .filter((chart) => Number(chart.page) === pageNumber)
          .map((chart) => ({
            file: chart.file,
            page: chart.page,
            label: chart.label,
            y: chart.box?.y0 ?? null,
          })),
      };
    });

  return { pages };
}

async function requestChunkedTranslationAnalysis(dirs, id, source, charts, onProgress, totalSteps) {
  const chunks = chunkArray(source.pages, analysisChunkPages);
  const analyses = new Array(chunks.length);
  let completed = 0;

  await mapWithConcurrency(chunks, analysisConcurrency, async (chunk, index) => {
    const chunkSource = { pages: chunk };
    analyses[index] = await requestTranslationAnalysis(
      chunkSource,
      chunk.length,
      getChartImagePaths(dirs, id, charts, chunk),
    );
    completed += 1;
    onProgress({
      completed,
      total: totalSteps,
      percent: Math.round((completed / totalSteps) * 100),
      message: `${completed}/${chunks.length} 묶음 번역 완료`,
    });
  });

  onProgress({
    completed: chunks.length,
    total: totalSteps,
    percent: Math.round((chunks.length / totalSteps) * 100),
    message: "전체요약 정리 중",
  });

  const overall = await synthesizeOverallSummary(analyses).catch(() => mergeOverallSummaries(analyses));

  return {
    overall,
    pages: analyses.flatMap((analysis) => analysis.pages || []).sort((a, b) => a.page - b.page),
  };
}

async function synthesizeOverallSummary(analyses) {
  const prompt = `You are synthesizing a Korean whole-document summary from chunk summaries.

Return only JSON matching the schema. Fill "overall" with a concise whole-document Korean summary and interpretation bullets. Return "pages": [].

Input chunk summaries:
${JSON.stringify(
  analyses.map((analysis) => ({
    summary: analysis.overall?.summary || "",
    bullets: analysis.overall?.bullets || [],
    pages: (analysis.pages || []).map((page) => page.page),
  })),
  null,
  2,
)}
`;

  const raw = await runCodexTranslation(prompt, []);
  const parsed = parseJsonObject(raw);
  return {
    summary: String(parsed.overall?.summary || ""),
    bullets: Array.isArray(parsed.overall?.bullets)
      ? parsed.overall.bullets.map((item) => String(item)).filter(Boolean)
      : [],
  };
}

function mergeOverallSummaries(analyses) {
  return {
    summary: analyses
      .map((analysis) => analysis.overall?.summary)
      .filter(Boolean)
      .join(" "),
    bullets: analyses.flatMap((analysis) => analysis.overall?.bullets || []).slice(0, 10),
  };
}

function getChartImagePaths(dirs, id, charts, pages) {
  const pageSet = new Set(pages.map((page) => Number(page.page)));
  return charts
    .filter((chart) => pageSet.has(Number(chart.page)))
    .map((chart) => join(dirs.assets, id, chart.file))
    .filter((path) => existsSync(path));
}

function chunkArray(items, chunkSize) {
  const chunks = [];
  for (let index = 0; index < items.length; index += chunkSize) {
    chunks.push(items.slice(index, index + chunkSize));
  }
  return chunks;
}

async function mapWithConcurrency(items, concurrency, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function runNext() {
    const index = nextIndex;
    nextIndex += 1;
    if (index >= items.length) {
      return;
    }
    results[index] = await worker(items[index], index);
    await runNext();
  }

  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, () => runNext()),
  );
  return results;
}

async function requestTranslationAnalysis(source, pageLimit, chartImagePaths) {
  const raw = await runCodexTranslation(buildTranslationPrompt(source, pageLimit, chartImagePaths), chartImagePaths);
  return normalizeAnalysis(parseJsonObject(raw), source);
}

function buildTranslationPrompt(source, pageLimit, chartImagePaths) {
  return `You are translating a finance/macro research PDF into Korean for a side-by-side reading UI.

Return only JSON matching the supplied output schema. Do not use markdown fences.

Rules:
- Create semantic reading sections from the supplied source text. A section should group sentences that belong together conceptually.
- Preserve page order and source sentence order inside each page.
- Every important source sentence should appear once in sentencePairs.source. Do not invent source text.
- Use natural Korean while keeping finance terms precise.
- Section summaries should explain the meaning before the reader sees the sentence-by-sentence translation.
- Keep the source English in sentencePairs.source and translate only in sentencePairs.translation. Use the English source plus chart images together as context before translating a section.
- Chart interpretation is very important. Use the attached chart images and nearby page text. Explain axes/series if visible, direction/trend, key inflection points, and how the chart supports or complicates the surrounding argument.
- For each supplied chart file, return one charts item with the same file name.
- If a chart image is unreadable, say what is unreadable and still explain what can be inferred from nearby text.
- Ignore platform boilerplate, legal disclaimers, copyright notices, privacy/terms links, Substack comment/reaction areas, login prompts, share buttons, and empty UI/footer pages. Do not create section summaries for those areas unless they materially affect the research argument.
- If a heading would be "문서/저자", use "문서" instead.
- Only include the pages supplied in input.

Input page limit: ${pageLimit}
Attached chart images: ${chartImagePaths.length}

Input JSON:
${JSON.stringify(source, null, 2)}
`;
}

async function runCodexTranslation(prompt, imagePaths = []) {
  const outputPath = join(storageDir, `codex-${Date.now()}-${randomUUID()}.json`);
  const args = [
    "-a",
    "never",
    "exec",
    "--ephemeral",
    "--sandbox",
    "read-only",
    "--output-schema",
    analysisSchemaPath,
    "--output-last-message",
    outputPath,
  ];

  imagePaths.forEach((path) => {
    args.push("--image", path);
  });
  args.push("-");

  if (codexModel) {
    args.splice(0, 0, "--model", codexModel);
  }

  const { stderr } = await spawnWithInput(codexBin, args, prompt, {
    cwd: process.cwd(),
    timeoutMs: Number(process.env.CODEX_TRANSLATION_TIMEOUT_MS || 600000),
    maxOutputBytes: 3 * 1024 * 1024,
  });

  try {
    const result = await readFile(outputPath, "utf8");
    unlink(outputPath).catch(() => {});
    return result;
  } catch {
    throw new Error(stderr || "Codex 번역 결과 파일을 읽지 못했습니다.");
  }
}

function spawnWithInput(command, args, input, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      stdio: ["pipe", "pipe", "pipe"],
      env: process.env,
    });
    let stdout = "";
    let stderr = "";
    let settled = false;

    const fail = (error) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeout);
      reject(error);
    };

    const timeout = setTimeout(() => {
      child.kill("SIGTERM");
      fail(new Error("Codex 번역 시간이 초과되었습니다."));
    }, options.timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
      if (stdout.length > options.maxOutputBytes) {
        child.kill("SIGTERM");
        fail(new Error("Codex stdout이 너무 큽니다."));
      }
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
      if (stderr.length > options.maxOutputBytes) {
        child.kill("SIGTERM");
        fail(new Error("Codex stderr가 너무 큽니다."));
      }
    });
    child.on("error", (error) => {
      fail(error);
    });
    child.on("close", (code) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeout);
      if (code === 0) {
        resolve({ stdout, stderr });
        return;
      }
      reject(new Error(stderr || stdout || `Codex exited with code ${code}`));
    });
    child.stdin.end(input);
  });
}

function normalizeAnalysis(analysis, source) {
  const pages = source.pages.map((sourcePage, pageIndex) => {
    const page = analysis.pages?.find((item) => Number(item.page) === sourcePage.page) || analysis.pages?.[pageIndex] || {};
    if (Array.isArray(page.sections)) {
      return {
        page: sourcePage.page,
        sections: page.sections
          .map((section) => normalizeSection(section))
          .filter((section) => !isBoilerplateSection(section)),
        charts: sourcePage.charts.map((sourceChart, chartIndex) => {
          const chart =
            page.charts?.find((item) => item.file === sourceChart.file) || page.charts?.[chartIndex] || {};
          return {
            file: sourceChart.file,
            interpretation: String(chart.interpretation || ""),
          };
        }),
      };
    }

    return {
      page: sourcePage.page,
      paragraphs: sourcePage.paragraphs.map((sourceParagraph, paragraphIndex) => {
        const paragraph = page.paragraphs?.[paragraphIndex] || {};
        const translations = Array.isArray(paragraph.translations) ? paragraph.translations : [];
        return {
          summary: isBoilerplateText(paragraph.summary) ? "" : String(paragraph.summary || ""),
          translations: sourceParagraph.sentences.map((_, sentenceIndex) =>
            String(translations[sentenceIndex] || ""),
          ),
        };
      }),
      charts: sourcePage.charts.map((sourceChart, chartIndex) => {
        const chart =
          page.charts?.find((item) => item.file === sourceChart.file) || page.charts?.[chartIndex] || {};
        return {
          file: sourceChart.file,
          interpretation: String(chart.interpretation || ""),
        };
      }),
    };
  });

  return {
    overall: {
      summary: String(analysis.overall?.summary || ""),
      bullets: Array.isArray(analysis.overall?.bullets)
        ? analysis.overall.bullets.map((item) => String(item)).filter(Boolean)
        : [],
    },
    pages,
  };
}

function normalizeSection(section) {
  const sentencePairs = Array.isArray(section.sentencePairs)
    ? section.sentencePairs.map((pair) => ({
        source: String(pair.source || ""),
        translation: String(pair.translation || ""),
      }))
    : [];

  return {
    title: normalizeSectionTitle(section.title),
    summary: isBoilerplateText(section.summary) ? "" : String(section.summary || ""),
    sentencePairs,
  };
}

function normalizeSectionTitle(title) {
  const value = String(title || "").trim();
  if (/^문서\s*\/\s*저자$/.test(value)) {
    return "문서";
  }
  return value;
}

function isBoilerplateSection(section) {
  const combined = [
    section.title,
    section.summary,
    ...(section.sentencePairs || []).flatMap((pair) => [pair.source, pair.translation]),
  ].join(" ");
  return isBoilerplateText(combined) && !hasResearchSignal(combined);
}

function isBoilerplateText(value) {
  const text = String(value || "").toLowerCase();
  if (!text.trim()) {
    return false;
  }

  const boilerplatePatterns = [
    /substack/,
    /댓글|comment|reply|reaction|반응/,
    /개인정보|privacy|terms|약관/,
    /copyright|저작권|all rights reserved/,
    /투자 조언|investment advice|legal disclaimer|법적 고지|disclaimer/,
    /구독|subscribe|sign in|login|share|공유/,
    /게시물 말미|플랫폼 정보|platform footer|footer/,
  ];
  return boilerplatePatterns.some((pattern) => pattern.test(text));
}

function hasResearchSignal(value) {
  const text = String(value || "").toLowerCase();
  const researchPatterns = [
    /earnings|inflation|rates?|yield|curve|credit|equity|macro|fed|fomc|gdp|cpi|pce/,
    /valuation|positioning|liquidity|volatility|duration|spread|multiple|cycle/,
    /금리|인플레이션|물가|성장|경기|유동성|밸류에이션|실적|연준|신용|스프레드|변동성|포지셔닝/,
  ];
  return researchPatterns.some((pattern) => pattern.test(text));
}

function parseJsonObject(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    const start = raw.indexOf("{");
    const end = raw.lastIndexOf("}");
    if (start !== -1 && end !== -1 && end > start) {
      return JSON.parse(raw.slice(start, end + 1));
    }
    throw new Error("번역 모델 응답을 JSON으로 해석하지 못했습니다.");
  }
}

async function getOrExtractAssets(dirs, metadata) {
  const manifestPath = join(dirs.assets, metadata.id, "manifest.json");
  if (existsSync(manifestPath)) {
    return readAssetManifest(dirs, metadata.id);
  }

  return extractAssets(dirs, metadata);
}

async function extractAssets(dirs, metadata) {
  const pdfPath = join(dirs.uploads, metadata.storedName);
  const documentAssetsDir = join(dirs.assets, metadata.id);

  await mkdir(documentAssetsDir, { recursive: true });

  try {
    const { stdout } = await execFileAsync(pythonBin, [assetExtractorScript, pdfPath, documentAssetsDir], {
      maxBuffer: 30 * 1024 * 1024,
    });
    const manifest = JSON.parse(stdout);
    return normalizeAssetManifest(metadata.id, manifest);
  } catch (error) {
    return {
      pageCount: null,
      charts: [],
      pages: [],
      error: error.message || "이미지 추출에 실패했습니다.",
    };
  }
}

async function readAssetManifest(dirs, id) {
  try {
    const raw = await readFile(join(dirs.assets, id, "manifest.json"), "utf8");
    return normalizeAssetManifest(id, JSON.parse(raw));
  } catch {
    return {
      pageCount: null,
      charts: [],
      pages: [],
    };
  }
}

async function readMetadata(dirs, id) {
  try {
    const raw = await readFile(join(dirs.documents, `${id}.json`), "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function readAnalysis(dirs, id) {
  try {
    const raw = await readFile(join(dirs.analysis, `${id}.ko.json`), "utf8");
    const analysis = JSON.parse(raw);
    return analysis.analysisVersion === 3 ? analysis : null;
  } catch {
    return null;
  }
}

function buildDocumentPayload({ metadata, markdown, convertedAt, warnings, assets, analysis }) {
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

function isValidDocumentId(id) {
  return /^[a-zA-Z0-9-]+$/.test(id);
}

function isValidAssetFile(file) {
  return /^[^/\\]+$/.test(file);
}

function normalizeAssetManifest(id, manifest) {
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

function cleanWarningText(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.includes("Could not get FontBBox from font descriptor"))
    .join("\n");
}

function splitSentences(text) {
  return String(text || "")
    .replace(/\s+/g, " ")
    .trim()
    .match(/[^.!?。！？]+[.!?。！？]?/g)
    ?.map((sentence) => sentence.trim())
    .filter(Boolean) || [];
}
