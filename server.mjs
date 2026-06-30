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
const codexNoteFastModel = process.env.CODEX_NOTE_FAST_MODEL || "";
const codexNoteDeepModel = process.env.CODEX_NOTE_DEEP_MODEL || "gpt-5.5";
const analysisSchemaPath = join(schemasDir, "translation-analysis.schema.json");
const noteAnswerSchemaPath = join(schemasDir, "document-note-answer.schema.json");
const defaultAnalysisChunkPages = parsePositiveInteger(process.env.CODEX_ANALYSIS_CHUNK_PAGES, 4);
const defaultAnalysisConcurrency = parsePositiveInteger(process.env.CODEX_ANALYSIS_CONCURRENCY, 2);
const maxUploadMb = Number(process.env.MAX_UPLOAD_MB || 50);
const execFileAsync = promisify(execFile);
const users = parseAuthUsers(process.env.AUTH_USERS_JSON || "");
const sessions = new Map();
const sessionMaxAgeMs = 1000 * 60 * 60 * 24 * 14;
const analysisJobs = new Map();
const activeAnalysisJobs = new Map();
const analysisJobControllers = new Map();

await mkdir(usersDir, { recursive: true });
await loadSessions();
await loadAnalysisJobs();

const app = express();
app.use(express.json({ limit: "5mb" }));
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
app.use("/api/chats", requireAuth);
app.use((req, res, next) => {
  if (req.path === "/api/analysis-html" || req.path.startsWith("/api/analysis-html/")) {
    return requireAuth(req, res, next);
  }
  return next();
});
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

app.patch("/api/documents/:id", async (req, res) => {
  if (!isValidDocumentId(req.params.id)) {
    res.status(400).json({ ok: false, error: "Bad document id" });
    return;
  }

  const originalName = normalizeDocumentTitle(req.body?.originalName);
  if (!originalName) {
    res.status(400).json({ ok: false, error: "제목을 입력하세요." });
    return;
  }

  try {
    const document = attachDocumentAnalysisJob(
      await updateDocumentTitle(req.userDirs, req.params.id, originalName),
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
      error: error.message || "제목을 수정하지 못했습니다.",
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

app.post("/api/documents/:id/shares", async (req, res) => {
  if (!isValidDocumentId(req.params.id)) {
    res.status(400).json({ ok: false, error: "Bad document id" });
    return;
  }

  try {
    const share = await createDocumentShare(req.userDirs, req.user.username, req.params.id);
    res.json({
      ok: true,
      share: {
        id: share.id,
        token: share.token,
        documentId: share.documentId,
        createdAt: share.createdAt,
        sharePath: `#share-${share.token}`,
      },
    });
  } catch (error) {
    const status = error.code === "ENOENT" ? 404 : 500;
    res.status(status).json({
      ok: false,
      error: error.message || "공유 링크 생성에 실패했습니다.",
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
    const maxAnalysisPages = parsePositiveInteger(process.env.MAX_ANALYSIS_PAGES, 25);
    const requestedPages = Number(req.body?.pages || req.query.pages || 0);
    const pages =
      requestedPages > 0 ? Math.max(1, Math.min(maxAnalysisPages, requestedPages)) : 0;
    const document = await getDocument(req.userDirs, req.params.id);
    if (!document) {
      res.status(404).json({ ok: false, error: "문서를 찾지 못했습니다." });
      return;
    }
    if (document.analysis) {
      res.status(409).json({
        ok: false,
        error: "이미 번역된 문서입니다. 다시 번역은 별도 기능으로 처리해야 합니다.",
      });
      return;
    }
    const job = createAnalysisJob(req.user.username, req.userDirs, req.params.id, pages);
    res.status(202).json({ ok: true, job: serializeAnalysisJob(job) });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "번역 작업을 시작하지 못했습니다.",
    });
  }
});

app.get("/api/documents/:id/notes", async (req, res) => {
  if (!isValidDocumentId(req.params.id)) {
    res.status(400).json({ ok: false, error: "Bad document id" });
    return;
  }

  try {
    if (!(await getDocument(req.userDirs, req.params.id))) {
      res.status(404).json({ ok: false, error: "문서를 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true, notes: await readDocumentNotes(req.userDirs, req.params.id) });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "메모를 불러오지 못했습니다.",
    });
  }
});

app.post("/api/documents/:id/notes/ask", async (req, res) => {
  if (!isValidDocumentId(req.params.id)) {
    res.status(400).json({ ok: false, error: "Bad document id" });
    return;
  }

  try {
    const document = await getDocument(req.userDirs, req.params.id);
    if (!document) {
      res.status(404).json({ ok: false, error: "문서를 찾지 못했습니다." });
      return;
    }

    const note = await createPendingNote(req.userDirs, document, req.body);
    res.status(202).json({ ok: true, note });
    setImmediate(() => {
      runNoteAnswer(req.userDirs, document, note.id).catch((error) => {
        console.error("note answer job failed", error);
      });
    });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "질문 메모를 만들지 못했습니다.",
    });
  }
});

app.get("/api/documents/:id/notes/:noteId", async (req, res) => {
  if (!isValidDocumentId(req.params.id) || !isValidNoteId(req.params.noteId)) {
    res.status(400).json({ ok: false, error: "Bad note path" });
    return;
  }

  if (!(await getDocument(req.userDirs, req.params.id))) {
    res.status(404).json({ ok: false, error: "문서를 찾지 못했습니다." });
    return;
  }

  const note = (await readDocumentNotes(req.userDirs, req.params.id)).find(
    (item) => item.id === req.params.noteId,
  );
  if (!note) {
    res.status(404).json({ ok: false, error: "메모를 찾지 못했습니다." });
    return;
  }
  res.json({ ok: true, note });
});

app.post("/api/documents/:id/notes/:noteId/messages", async (req, res) => {
  if (!isValidDocumentId(req.params.id) || !isValidNoteId(req.params.noteId)) {
    res.status(400).json({ ok: false, error: "Bad note path" });
    return;
  }

  try {
    const document = await getDocument(req.userDirs, req.params.id);
    if (!document) {
      res.status(404).json({ ok: false, error: "문서를 찾지 못했습니다." });
      return;
    }
    const note = await appendPendingNoteQuestion(
      req.userDirs,
      document.id,
      req.params.noteId,
      req.body,
    );
    res.status(202).json({ ok: true, note });
    setImmediate(() => {
      runNoteAnswer(req.userDirs, document, note.id).catch((error) => {
        console.error("note answer job failed", error);
      });
    });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "후속 질문을 보내지 못했습니다.",
    });
  }
});

app.delete("/api/documents/:id/notes/:noteId", async (req, res) => {
  if (!isValidDocumentId(req.params.id) || !isValidNoteId(req.params.noteId)) {
    res.status(400).json({ ok: false, error: "Bad note path" });
    return;
  }

  if (!(await getDocument(req.userDirs, req.params.id))) {
    res.status(404).json({ ok: false, error: "문서를 찾지 못했습니다." });
    return;
  }

  const deleted = await deleteDocumentNote(req.userDirs, req.params.id, req.params.noteId);
  if (!deleted) {
    res.status(404).json({ ok: false, error: "메모를 찾지 못했습니다." });
    return;
  }
  res.json({ ok: true });
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

app.get("/api/chats", async (req, res) => {
  try {
    res.json({ ok: true, chats: await listChats(req.userDirs) });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "채팅 히스토리를 불러오지 못했습니다.",
    });
  }
});

app.post("/api/chats", async (req, res) => {
  try {
    const chat = await createChat(req.userDirs, req.body);
    res.json({ ok: true, chat });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "채팅을 만들지 못했습니다.",
    });
  }
});

app.get("/api/chats/:chatId", async (req, res) => {
  if (!isValidNoteId(req.params.chatId)) {
    res.status(400).json({ ok: false, error: "Bad chat id" });
    return;
  }

  try {
    const chat = await readChat(req.userDirs, req.params.chatId);
    if (!chat) {
      res.status(404).json({ ok: false, error: "채팅을 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true, chat });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "채팅을 불러오지 못했습니다.",
    });
  }
});

app.post("/api/chats/:chatId/messages", async (req, res) => {
  if (!isValidNoteId(req.params.chatId)) {
    res.status(400).json({ ok: false, error: "Bad chat id" });
    return;
  }

  try {
    const chat = await appendChatQuestion(req.userDirs, req.params.chatId, req.body);
    res.status(202).json({ ok: true, chat });
    setImmediate(() => {
      runChatAnswer(req.userDirs, req.params.chatId).catch((error) => {
        console.error("chat answer job failed", error);
      });
    });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "질문을 보내지 못했습니다.",
    });
  }
});

app.post("/api/chats/:chatId/messages/:messageId/ask", async (req, res) => {
  if (!isValidNoteId(req.params.chatId) || !isValidNoteId(req.params.messageId)) {
    res.status(400).json({ ok: false, error: "Bad chat message path" });
    return;
  }

  try {
    const chat = await appendChatMessageQuestion(
      req.userDirs,
      req.params.chatId,
      req.params.messageId,
      req.body,
    );
    res.status(202).json({ ok: true, chat });
    setImmediate(() => {
      runChatAnswer(req.userDirs, req.params.chatId).catch((error) => {
        console.error("chat message ask job failed", error);
      });
    });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "질문을 보내지 못했습니다.",
    });
  }
});

app.post("/api/chats/:chatId/message-notes/:noteId/messages", async (req, res) => {
  if (!isValidNoteId(req.params.chatId) || !isValidNoteId(req.params.noteId)) {
    res.status(400).json({ ok: false, error: "Bad chat note path" });
    return;
  }

  try {
    const chat = await appendChatMessageNoteQuestion(
      req.userDirs,
      req.params.chatId,
      req.params.noteId,
      req.body,
    );
    res.status(202).json({ ok: true, chat });
    setImmediate(() => {
      runChatAnswer(req.userDirs, req.params.chatId).catch((error) => {
        console.error("chat message note reply job failed", error);
      });
    });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "후속 질문을 보내지 못했습니다.",
    });
  }
});

app.delete("/api/chats/:chatId/message-notes/:noteId", async (req, res) => {
  if (!isValidNoteId(req.params.chatId) || !isValidNoteId(req.params.noteId)) {
    res.status(400).json({ ok: false, error: "Bad chat note path" });
    return;
  }

  try {
    const chat = await deleteChatMessageNote(req.userDirs, req.params.chatId, req.params.noteId);
    res.json({ ok: true, chat });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "서브 질문 삭제 실패",
    });
  }
});

app.delete("/api/chats/:chatId", async (req, res) => {
  if (!isValidNoteId(req.params.chatId)) {
    res.status(400).json({ ok: false, error: "Bad chat id" });
    return;
  }

  try {
    const deleted = await deleteChat(req.userDirs, req.params.chatId);
    if (!deleted) {
      res.status(404).json({ ok: false, error: "채팅을 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "채팅 삭제 실패",
    });
  }
});

app.get("/api/analysis-html", async (req, res) => {
  try {
    res.json({ ok: true, files: await listAnalysisHtmlFiles(req.userDirs) });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "분석 HTML 목록을 불러오지 못했습니다.",
    });
  }
});

app.post("/api/analysis-html/:file/shares", async (req, res) => {
  if (!isValidAnalysisHtmlFile(req.params.file)) {
    res.status(400).json({ ok: false, error: "Bad analysis HTML file" });
    return;
  }

  try {
    const share = await createAnalysisHtmlShare(req.userDirs, req.user.username, req.params.file);
    res.json({
      ok: true,
      share: {
        id: share.id,
        token: share.token,
        analysisFile: share.analysisFile,
        createdAt: share.createdAt,
        sharePath: `#analysis-share-${share.token}`,
      },
    });
  } catch (error) {
    const status = error.code === "ENOENT" ? 404 : 500;
    res.status(status).json({
      ok: false,
      error: error.message || "공유 링크 생성에 실패했습니다.",
    });
  }
});

app.get("/api/analysis-html/:file/chats", async (req, res) => {
  if (!isValidAnalysisHtmlFile(req.params.file)) {
    res.status(400).json({ ok: false, error: "Bad analysis HTML file" });
    return;
  }

  try {
    if (!existsSync(join(req.userDirs.analysisHtml, req.params.file))) {
      res.status(404).json({ ok: false, error: "분석 글을 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true, chat: await readAnalysisHtmlChat(req.userDirs, req.params.file) });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "LLM 대화를 불러오지 못했습니다.",
    });
  }
});

app.post("/api/analysis-html/:file/chats", async (req, res) => {
  if (!isValidAnalysisHtmlFile(req.params.file)) {
    res.status(400).json({ ok: false, error: "Bad analysis HTML file" });
    return;
  }

  try {
    if (!existsSync(join(req.userDirs.analysisHtml, req.params.file))) {
      res.status(404).json({ ok: false, error: "분석 글을 찾지 못했습니다." });
      return;
    }
    const thread = await createAnalysisHtmlChatThread(req.userDirs, req.params.file, req.body);
    res.json({ ok: true, thread });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "LLM 대화를 만들지 못했습니다.",
    });
  }
});

app.post("/api/analysis-html/:file/chats/:threadId/messages", async (req, res) => {
  if (!isValidAnalysisHtmlFile(req.params.file) || !isValidNoteId(req.params.threadId)) {
    res.status(400).json({ ok: false, error: "Bad analysis chat path" });
    return;
  }

  try {
    if (!existsSync(join(req.userDirs.analysisHtml, req.params.file))) {
      res.status(404).json({ ok: false, error: "분석 글을 찾지 못했습니다." });
      return;
    }
    const thread = await appendAnalysisHtmlChatQuestion(
      req.userDirs,
      req.params.file,
      req.params.threadId,
      req.body,
    );
    res.status(202).json({ ok: true, thread });
    setImmediate(() => {
      runAnalysisHtmlChatAnswer(req.userDirs, req.params.file, req.params.threadId).catch((error) => {
        console.error("analysis html chat job failed", error);
      });
    });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "질문을 보내지 못했습니다.",
    });
  }
});

app.delete("/api/analysis-html/:file/chats/:threadId", async (req, res) => {
  if (!isValidAnalysisHtmlFile(req.params.file) || !isValidNoteId(req.params.threadId)) {
    res.status(400).json({ ok: false, error: "Bad analysis chat path" });
    return;
  }

  try {
    const deleted = await deleteAnalysisHtmlChatThread(
      req.userDirs,
      req.params.file,
      req.params.threadId,
    );
    if (!deleted) {
      res.status(404).json({ ok: false, error: "대화를 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true });
  } catch (error) {
    const status = error.status || 500;
    res.status(status).json({
      ok: false,
      error: error.message || "대화를 삭제하지 못했습니다.",
    });
  }
});

app.delete("/api/analysis-html/:file", async (req, res) => {
  if (!isValidAnalysisHtmlFile(req.params.file)) {
    res.status(400).json({ ok: false, error: "Bad analysis HTML file" });
    return;
  }

  try {
    const deleted = await deleteAnalysisHtmlFile(req.userDirs, req.params.file);
    if (!deleted) {
      res.status(404).json({ ok: false, error: "분석 글을 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "분석 글 삭제에 실패했습니다.",
    });
  }
});

app.get("/api/analysis-html/:file", (req, res) => {
  if (!isValidAnalysisHtmlFile(req.params.file)) {
    res.status(400).send("Bad analysis HTML file");
    return;
  }

  res.sendFile(join(req.userDirs.analysisHtml, req.params.file), {
    headers: {
      "cache-control": "no-store",
      "content-type": "text/html; charset=utf-8",
    },
  });
});

app.get("/api/analysis-html-shares/:token", async (req, res) => {
  if (!isValidShareToken(req.params.token)) {
    res.status(400).send("Bad share token");
    return;
  }

  const shared = await findShareByToken(req.params.token);
  if (!shared || shared.share.type !== "analysis-html" || !isValidAnalysisHtmlFile(shared.share.analysisFile)) {
    res.status(404).send("Share not found");
    return;
  }

  res.sendFile(join(shared.dirs.analysisHtml, shared.share.analysisFile), {
    headers: {
      "cache-control": "no-store",
      "content-type": "text/html; charset=utf-8",
    },
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

app.get("/api/shares/:token", async (req, res) => {
  if (!isValidShareToken(req.params.token)) {
    res.status(400).json({ ok: false, error: "Bad share token" });
    return;
  }

  try {
    const shared = await getSharedDocument(req.params.token);
    if (!shared) {
      res.status(404).json({ ok: false, error: "공유 글을 찾지 못했습니다." });
      return;
    }
    res.json({ ok: true, document: shared.document });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message || "공유 글을 불러오지 못했습니다.",
    });
  }
});

app.get("/api/shares/:token/pdf", async (req, res) => {
  if (!isValidShareToken(req.params.token)) {
    res.status(400).send("Bad share token");
    return;
  }

  const shared = await findShareByToken(req.params.token);
  if (!shared) {
    res.status(404).send("Share not found");
    return;
  }

  const metadata = await readMetadata(shared.dirs, shared.share.documentId);
  const pdfPath = join(shared.dirs.uploads, metadata?.storedName || `${shared.share.documentId}.pdf`);
  if (!metadata || !existsSync(pdfPath)) {
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

app.get("/api/shares/:token/assets/:file", async (req, res) => {
  if (!isValidShareToken(req.params.token) || !isValidAssetFile(req.params.file)) {
    res.status(400).send("Bad asset path");
    return;
  }

  const shared = await findShareByToken(req.params.token);
  if (!shared) {
    res.status(404).send("Share not found");
    return;
  }

  const manifest = await readAssetManifest(shared.dirs, shared.share.documentId);
  const allowedFiles = [...(manifest.charts || []), ...(manifest.pages || [])].map((asset) => asset.file);
  if (!allowedFiles.includes(req.params.file)) {
    res.status(404).send("Asset not found");
    return;
  }

  res.sendFile(join(shared.dirs.assets, shared.share.documentId, req.params.file), {
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
    analysisHtml: join(root, "analysis-html"),
    analysisHtmlChats: join(root, "analysis-html-chats"),
    chats: join(root, "chats"),
    notes: join(root, "notes"),
    shares: join(root, "shares"),
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
  const analysis = getCompleteAnalysis(await readAnalysis(dirs, metadata.id), markdown);

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
      const markdown = existsSync(convertedPath) ? await readFile(convertedPath, "utf8").catch(() => "") : "";
      const analysis = getCompleteAnalysis(await readAnalysis(dirs, id), markdown);
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

async function updateDocumentTitle(dirs, id, originalName) {
  const metadata = await readMetadata(dirs, id);
  if (!metadata) {
    return null;
  }

  await writeMetadata(dirs, id, {
    ...metadata,
    originalName,
    updatedAt: new Date().toISOString(),
  });
  return getDocument(dirs, id);
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
    join(dirs.notes, `${id}.json`),
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
  await deleteSharesForDocument(dirs, id);

  const activeKey = `${username}:${id}`;
  const activeJobId = activeAnalysisJobs.get(activeKey);
  if (activeJobId) {
    activeAnalysisJobs.delete(activeKey);
    analysisJobControllers.get(activeJobId)?.abort();
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

async function readDocumentNotes(dirs, documentId) {
  try {
    const raw = await readFile(join(dirs.notes, `${documentId}.json`), "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed?.notes) ? parsed.notes.map(normalizeDocumentNote).filter(Boolean) : [];
  } catch {
    return [];
  }
}

async function writeDocumentNotes(dirs, documentId, notes) {
  await mkdir(dirs.notes, { recursive: true });
  await writeFile(
    join(dirs.notes, `${documentId}.json`),
    JSON.stringify({ documentId, notes }, null, 2),
  );
}

async function listAnalysisHtmlFiles(dirs) {
  await mkdir(dirs.analysisHtml, { recursive: true });
  const files = (await readdir(dirs.analysisHtml)).filter(isValidAnalysisHtmlFile);
  const items = await Promise.all(
    files.map(async (file) => {
      const filePath = join(dirs.analysisHtml, file);
      const [fileStat, html] = await Promise.all([
        stat(filePath),
        readFile(filePath, "utf8").catch(() => ""),
      ]);
      return {
        file,
        title: file.replace(/\.html?$/i, ""),
        summary: summarizeAnalysisHtml(html),
        size: fileStat.size,
        updatedAt: fileStat.mtime.toISOString(),
        url: `/api/analysis-html/${encodeURIComponent(file)}`,
      };
    }),
  );
  items.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  return items;
}

function summarizeAnalysisHtml(html) {
  const text = htmlToPlainText(html);
  if (!text) {
    return "";
  }
  return text.length > 160 ? `${text.slice(0, 160).trim()}...` : text;
}

function htmlToPlainText(html) {
  return String(html || "")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\s+/g, " ")
    .trim();
}

async function deleteAnalysisHtmlFile(dirs, file) {
  const filePath = join(dirs.analysisHtml, file);
  if (!existsSync(filePath)) {
    return false;
  }

  await unlink(filePath);
  await deleteSharesForAnalysisHtmlFile(dirs, file);
  await unlink(getAnalysisHtmlChatPath(dirs, file)).catch((error) => {
    if (error.code !== "ENOENT") {
      throw error;
    }
  });
  return true;
}

function getAnalysisHtmlChatPath(dirs, file) {
  return join(dirs.analysisHtmlChats, `${file}.json`);
}

function getChatIndexPath(dirs) {
  return join(dirs.chats, "index.json");
}

function getChatPath(dirs, chatId) {
  return join(dirs.chats, `${chatId}.json`);
}

async function listChats(dirs) {
  const index = await readChatIndex(dirs);
  index.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  return index;
}

async function readChatIndex(dirs) {
  try {
    const raw = await readFile(getChatIndexPath(dirs), "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed?.chats)
      ? parsed.chats.map(normalizeChatSummary).filter(Boolean)
      : [];
  } catch {
    return [];
  }
}

async function writeChatIndex(dirs, chats) {
  await mkdir(dirs.chats, { recursive: true });
  const normalized = Array.isArray(chats) ? chats.map(normalizeChatSummary).filter(Boolean) : [];
  await writeFile(getChatIndexPath(dirs), JSON.stringify({ chats: normalized }, null, 2));
}

async function readChat(dirs, chatId) {
  try {
    const raw = await readFile(getChatPath(dirs, chatId), "utf8");
    return normalizeChat(JSON.parse(raw));
  } catch {
    return null;
  }
}

async function writeChat(dirs, chat, options = {}) {
  await mkdir(dirs.chats, { recursive: true });
  const normalized = normalizeChat(chat);
  if (!normalized) {
    throw new Error("저장할 채팅 데이터가 올바르지 않습니다.");
  }
  await writeFile(getChatPath(dirs, normalized.id), JSON.stringify(normalized, null, 2));
  const index = await readChatIndex(dirs);
  const summary = createChatSummary(normalized);
  const existingIndex = index.findIndex((item) => item.id === normalized.id);
  const nextIndex = index.filter((item) => item.id !== normalized.id);
  if (options.moveToTop === false && existingIndex !== -1) {
    nextIndex.splice(existingIndex, 0, summary);
  } else {
    nextIndex.unshift(summary);
  }
  await writeChatIndex(dirs, nextIndex);
  return normalized;
}

async function createChat(dirs, body) {
  const now = new Date().toISOString();
  const chat = {
    id: randomUUID(),
    title: cleanChatText(body?.title, 80) || "새 채팅",
    status: "idle",
    messages: [],
    providers: ["openai"],
    thinkLevel: 1,
    artifacts: { layers: [] },
    error: "",
    createdAt: now,
    updatedAt: now,
  };
  return writeChat(dirs, chat);
}

async function appendChatQuestion(dirs, chatId, body) {
  const question = cleanChatText(body?.question, 4000);
  const providers = normalizeChatProviders(body?.providers);
  const thinkLevel = normalizeThinkLevel(body?.thinkLevel);
  if (!question) {
    const error = new Error("질문이 필요합니다.");
    error.status = 400;
    throw error;
  }
  if (!providers.length) {
    const error = new Error("하나 이상의 LLM을 선택하세요.");
    error.status = 400;
    throw error;
  }

  const chat = await readChat(dirs, chatId);
  if (!chat) {
    const error = new Error("채팅을 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  if (["pending", "running"].includes(chat.status)) {
    const error = new Error("이전 답변 생성이 끝난 뒤 다시 질문하세요.");
    error.status = 409;
    throw error;
  }

  const title = chat.messages.length ? chat.title : cleanChatText(question, 44) || chat.title;
  return writeChat(dirs, {
    ...chat,
    title,
    status: "pending",
    providers,
    thinkLevel,
    messages: [
      ...chat.messages,
      createChatMessage({
        role: "user",
        content: question,
        providers,
        thinkLevel,
      }),
    ],
    error: "",
    updatedAt: new Date().toISOString(),
  });
}

async function appendChatMessageQuestion(dirs, chatId, messageId, body) {
  const question = cleanChatText(body?.question, 4000);
  const modelMode = normalizeNoteModelMode(body?.modelMode);
  const model = getNoteModel(modelMode);
  if (!question) {
    const error = new Error("질문이 필요합니다.");
    error.status = 400;
    throw error;
  }

  const chat = await readChat(dirs, chatId);
  if (!chat) {
    const error = new Error("채팅을 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  const parent = chat.messages.find((message) => message.id === messageId);
  if (!parent) {
    const error = new Error("말풍선을 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  if (chat.messages.some((message) => message.status === "pending")) {
    const error = new Error("이전 답변 생성이 끝난 뒤 다시 질문하세요.");
    error.status = 409;
    throw error;
  }

  const now = new Date().toISOString();
  return writeChat(dirs, {
    ...chat,
    messageNotes: [
      ...(chat.messageNotes || []),
      {
        id: randomUUID(),
        parentMessageId: messageId,
        question,
        answer: "",
        status: "pending",
        modelMode,
        messages: [
          createNoteMessage({
            role: "user",
            content: question,
            model,
            modelMode,
          }),
        ],
        error: "",
        artifacts: {
          layers: [
            {
              name: "parent-message",
              data: {
                messageId,
                role: parent.role,
                content: parent.content,
                model,
                modelMode,
              },
              createdAt: now,
            },
          ],
        },
        createdAt: now,
        updatedAt: now,
      },
    ],
    error: "",
  }, { moveToTop: false });
}

async function appendChatMessageNoteQuestion(dirs, chatId, noteId, body) {
  const question = cleanChatText(body?.question, 4000);
  const modelMode = normalizeNoteModelMode(body?.modelMode);
  const model = getNoteModel(modelMode);
  if (!question) {
    const error = new Error("질문이 필요합니다.");
    error.status = 400;
    throw error;
  }

  const chat = await readChat(dirs, chatId);
  if (!chat) {
    const error = new Error("채팅을 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  const index = (chat.messageNotes || []).findIndex((note) => note.id === noteId);
  if (index === -1) {
    const error = new Error("서브 질문을 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  if (["pending", "running"].includes(chat.messageNotes[index].status)) {
    const error = new Error("이전 답변 생성이 끝난 뒤 다시 질문하세요.");
    error.status = 409;
    throw error;
  }

  const messageNotes = [...chat.messageNotes];
  messageNotes[index] = normalizeChatMessageNote({
    ...messageNotes[index],
    question,
    answer: "",
    status: "pending",
    modelMode,
    error: "",
    messages: [
      ...messageNotes[index].messages,
      createNoteMessage({
        role: "user",
        content: question,
        model,
        modelMode,
      }),
    ],
    updatedAt: new Date().toISOString(),
  });

  return writeChat(dirs, {
    ...chat,
    messageNotes,
    error: "",
  }, { moveToTop: false });
}

async function runChatAnswer(dirs, chatId) {
  try {
    const latest = await readChat(dirs, chatId);
    if (!latest) {
      return;
    }
    const noteIndex = (latest.messageNotes || []).findIndex((note) => ["pending", "running"].includes(note.status));
    if (noteIndex !== -1) {
      const messageNotes = [...latest.messageNotes];
      const note = messageNotes[noteIndex];
      const lastMessage = note.messages.at(-1) || {};
      messageNotes[noteIndex] = {
        ...note,
        status: "completed",
        answer: "test",
        messages: [
          ...note.messages,
          createNoteMessage({
            role: "assistant",
            content: "test",
            model: lastMessage.model || getNoteModel(lastMessage.modelMode || note.modelMode),
            modelMode: lastMessage.modelMode || note.modelMode,
            status: "completed",
          }),
        ],
        error: "",
        updatedAt: new Date().toISOString(),
      };
      await writeChat(dirs, {
        ...latest,
        messageNotes,
        error: "",
      }, { moveToTop: false });
      return;
    }
    const running = await updateChat(dirs, chatId, { status: "running", error: "" });
    if (!running) {
      return;
    }
    const active = await readChat(dirs, chatId);
    if (!active) {
      return;
    }
    const providers = active.providers;
    const thinkLevel = active.thinkLevel;
    const layers = createTestChatLayers(active);
    await writeChat(dirs, {
      ...active,
      status: "completed",
      messages: [
        ...active.messages,
        createChatMessage({
          role: "assistant",
          content: "test",
          providers,
          thinkLevel,
          artifacts: { layers },
          status: "completed",
        }),
      ],
      artifacts: {
        layers: [...active.artifacts.layers, ...layers],
      },
      error: "",
      updatedAt: new Date().toISOString(),
    });
  } catch (error) {
    const latest = await readChat(dirs, chatId);
    if (!latest) {
      return;
    }
    const noteIndex = (latest.messageNotes || []).findIndex((note) => ["pending", "running"].includes(note.status));
    if (noteIndex !== -1) {
      const messageNotes = [...latest.messageNotes];
      const note = messageNotes[noteIndex];
      const lastMessage = note.messages.at(-1) || {};
      messageNotes[noteIndex] = {
        ...note,
        status: "failed",
        messages: [
          ...note.messages,
          createNoteMessage({
            role: "assistant",
            content: "",
            model: lastMessage.model || getNoteModel(lastMessage.modelMode || note.modelMode),
            modelMode: lastMessage.modelMode || note.modelMode,
            status: "failed",
            error: error.message || "답변 생성에 실패했습니다.",
          }),
        ],
        error: error.message || "답변 생성에 실패했습니다.",
        updatedAt: new Date().toISOString(),
      };
      await writeChat(dirs, {
        ...latest,
        messageNotes,
        error: "",
      }, { moveToTop: false });
      return;
    }
    await writeChat(dirs, {
      ...latest,
      status: "failed",
      messages: [
        ...latest.messages,
        createChatMessage({
          role: "assistant",
          content: "",
          providers: latest.providers,
          thinkLevel: latest.thinkLevel,
          status: "failed",
          error: error.message || "답변 생성에 실패했습니다.",
        }),
      ],
      error: error.message || "답변 생성에 실패했습니다.",
      updatedAt: new Date().toISOString(),
    });
  }
}

async function deleteChatMessageNote(dirs, chatId, noteId) {
  const chat = await readChat(dirs, chatId);
  if (!chat) {
    const error = new Error("채팅을 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  const messageNotes = (chat.messageNotes || []).filter((note) => note.id !== noteId);
  if (messageNotes.length === (chat.messageNotes || []).length) {
    const error = new Error("서브 질문을 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  return writeChat(dirs, {
    ...chat,
    messageNotes,
  }, { moveToTop: false });
}

async function updateChat(dirs, chatId, patch) {
  const chat = await readChat(dirs, chatId);
  if (!chat) {
    return null;
  }
  return writeChat(dirs, {
    ...chat,
    ...patch,
    updatedAt: new Date().toISOString(),
  });
}

async function deleteChat(dirs, chatId) {
  const chat = await readChat(dirs, chatId);
  if (!chat) {
    return false;
  }
  if (["pending", "running"].includes(chat.status)) {
    const error = new Error("답변 생성 중인 채팅은 삭제할 수 없습니다.");
    error.status = 409;
    throw error;
  }
  await rm(getChatPath(dirs, chatId), { force: true });
  const index = await readChatIndex(dirs);
  await writeChatIndex(dirs, index.filter((item) => item.id !== chatId));
  return true;
}

function createTestChatLayers(chat) {
  const now = new Date().toISOString();
  const lastQuestion = [...chat.messages].reverse().find((message) => message.role === "user");
  return [
    {
      name: "layer1",
      data: {
        providers: chat.providers,
        thinkLevel: chat.thinkLevel,
        question: lastQuestion?.content || "",
      },
      createdAt: now,
    },
    {
      name: "layer2",
      data: {
        status: "placeholder",
      },
      createdAt: now,
    },
    {
      name: "layer3",
      data: {
        answerSeed: "test",
      },
      createdAt: now,
    },
  ];
}

function createChatSummary(chat) {
  return normalizeChatSummary({
    id: chat.id,
    title: chat.title,
    status: chat.status,
    messageCount: chat.messages.length,
    providers: chat.providers,
    thinkLevel: chat.thinkLevel,
    createdAt: chat.createdAt,
    updatedAt: chat.updatedAt,
  });
}

function normalizeChatSummary(summary) {
  if (!summary?.id || !isValidNoteId(summary.id)) {
    return null;
  }
  return {
    id: String(summary.id),
    title: cleanChatText(summary.title, 80) || "새 채팅",
    status: normalizeChatStatus(summary.status, "idle"),
    messageCount: Math.max(0, Math.floor(Number(summary.messageCount || 0))),
    providers: normalizeChatProviders(summary.providers),
    thinkLevel: normalizeThinkLevel(summary.thinkLevel),
    createdAt: String(summary.createdAt || new Date().toISOString()),
    updatedAt: String(summary.updatedAt || summary.createdAt || new Date().toISOString()),
  };
}

function normalizeChat(chat) {
  if (!chat?.id || !isValidNoteId(chat.id)) {
    return null;
  }
  const providers = normalizeChatProviders(chat.providers);
  const thinkLevel = normalizeThinkLevel(chat.thinkLevel);
  return {
    id: String(chat.id),
    title: cleanChatText(chat.title, 80) || "새 채팅",
    status: normalizeChatStatus(chat.status, "idle"),
    messages: normalizeChatMessages(chat.messages, providers, thinkLevel),
    messageNotes: normalizeChatMessageNotes(chat.messageNotes),
    providers,
    thinkLevel,
    artifacts: normalizeChatArtifacts(chat.artifacts),
    error: cleanChatText(chat.error, 1000),
    createdAt: String(chat.createdAt || new Date().toISOString()),
    updatedAt: String(chat.updatedAt || chat.createdAt || new Date().toISOString()),
  };
}

function normalizeChatMessageNotes(notes) {
  return Array.isArray(notes)
    ? notes
        .map(normalizeChatMessageNote)
        .filter(Boolean)
    : [];
}

function normalizeChatMessageNote(note) {
  if (!note?.id || !isValidNoteId(note.id) || !isValidNoteId(note.parentMessageId)) {
    return null;
  }
  const modelMode = normalizeNoteModelMode(note.modelMode);
  const model = String(note.model || getNoteModel(modelMode) || "codex-default");
  const question = cleanChatText(note.question, 4000);
  const answer = cleanChatText(note.answer, 12000);
  const messages = normalizeNoteMessages(note.messages, {
    question,
    answer,
    model,
    modelMode,
    createdAt: note.createdAt,
  });
  return {
    id: String(note.id),
    parentMessageId: String(note.parentMessageId),
    question,
    answer,
    status: ["pending", "running", "completed", "failed"].includes(note.status)
      ? note.status
      : "failed",
    model,
    modelMode,
    messages,
    error: cleanChatText(note.error, 1000),
    artifacts: normalizeChatArtifacts(note.artifacts),
    createdAt: String(note.createdAt || new Date().toISOString()),
    updatedAt: String(note.updatedAt || note.createdAt || new Date().toISOString()),
  };
}

function normalizeChatMessages(messages, fallbackProviders, fallbackThinkLevel) {
  return Array.isArray(messages)
    ? messages
        .map((message) => {
          const role = message?.role === "assistant" ? "assistant" : "user";
          const content = cleanChatText(message?.content, role === "assistant" ? 12000 : 4000);
          if (!content && message?.status !== "failed") {
            return null;
          }
          return {
            id: isValidNoteId(message?.id) ? String(message.id) : randomUUID(),
            role,
            content,
            providers: normalizeChatProviders(message?.providers).length
              ? normalizeChatProviders(message.providers)
              : fallbackProviders,
            thinkLevel: normalizeThinkLevel(message?.thinkLevel || fallbackThinkLevel),
            artifacts: normalizeChatArtifacts(message?.artifacts),
            parentMessageId: isValidNoteId(message?.parentMessageId) ? String(message.parentMessageId) : "",
            modelMode: message?.modelMode ? normalizeNoteModelMode(message.modelMode) : "",
            status: ["pending", "completed", "failed"].includes(message?.status)
              ? message.status
              : "completed",
            error: cleanChatText(message?.error, 1000),
            createdAt: String(message?.createdAt || new Date().toISOString()),
          };
        })
        .filter(Boolean)
    : [];
}

function createChatMessage({
  role,
  content,
  providers = ["openai"],
  thinkLevel = 1,
  artifacts = { layers: [] },
  parentMessageId = "",
  modelMode = "",
  status = "completed",
  error = "",
}) {
  return {
    id: randomUUID(),
    role: role === "assistant" ? "assistant" : "user",
    content: cleanChatText(content, role === "assistant" ? 12000 : 4000),
    providers: normalizeChatProviders(providers),
    thinkLevel: normalizeThinkLevel(thinkLevel),
    artifacts: normalizeChatArtifacts(artifacts),
    parentMessageId: isValidNoteId(parentMessageId) ? String(parentMessageId) : "",
    modelMode: modelMode ? normalizeNoteModelMode(modelMode) : "",
    status: ["pending", "completed", "failed"].includes(status) ? status : "completed",
    error: cleanChatText(error, 1000),
    createdAt: new Date().toISOString(),
  };
}

function normalizeChatArtifacts(artifacts) {
  const layers = Array.isArray(artifacts?.layers)
    ? artifacts.layers
        .map((layer) => ({
          name: cleanChatText(layer?.name, 80),
          data: layer?.data && typeof layer.data === "object" && !Array.isArray(layer.data)
            ? layer.data
            : {},
          createdAt: String(layer?.createdAt || new Date().toISOString()),
        }))
        .filter((layer) => layer.name)
    : [];
  return { layers };
}

function normalizeChatProviders(providers) {
  const allowed = new Set(["anthropic", "openai", "grok"]);
  const values = Array.isArray(providers) ? providers : [];
  return [...new Set(values.map((value) => String(value || "")).filter((value) => allowed.has(value)))];
}

function normalizeThinkLevel(value) {
  const number = Math.floor(Number(value || 1));
  if (number <= 1) {
    return 1;
  }
  if (number >= 3) {
    return 3;
  }
  return 2;
}

function normalizeChatStatus(value, fallback) {
  return ["idle", "pending", "running", "completed", "failed"].includes(value) ? value : fallback;
}

async function readAnalysisHtmlChat(dirs, file) {
  try {
    const raw = await readFile(getAnalysisHtmlChatPath(dirs, file), "utf8");
    const parsed = JSON.parse(raw);
    return normalizeAnalysisHtmlChat(parsed, file);
  } catch {
    return { file, threads: [] };
  }
}

async function writeAnalysisHtmlChat(dirs, file, chat) {
  await mkdir(dirs.analysisHtmlChats, { recursive: true });
  await writeFile(
    getAnalysisHtmlChatPath(dirs, file),
    JSON.stringify(normalizeAnalysisHtmlChat(chat, file), null, 2),
  );
}

async function createAnalysisHtmlChatThread(dirs, file, body) {
  const chat = await readAnalysisHtmlChat(dirs, file);
  const now = new Date().toISOString();
  const title = cleanNoteText(body?.title, 80) || `질문 ${chat.threads.length + 1}`;
  const thread = {
    id: randomUUID(),
    file,
    title,
    status: "idle",
    messages: [],
    error: "",
    createdAt: now,
    updatedAt: now,
  };
  chat.threads.unshift(thread);
  await writeAnalysisHtmlChat(dirs, file, chat);
  return thread;
}

async function appendAnalysisHtmlChatQuestion(dirs, file, threadId, body) {
  const question = cleanNoteText(body?.question, 4000);
  const modelMode = normalizeNoteModelMode(body?.modelMode);
  const model = getNoteModel(modelMode);
  if (!question) {
    const error = new Error("질문이 필요합니다.");
    error.status = 400;
    throw error;
  }

  const chat = await readAnalysisHtmlChat(dirs, file);
  const index = chat.threads.findIndex((thread) => thread.id === threadId);
  if (index === -1) {
    const error = new Error("대화를 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  if (["pending", "running"].includes(chat.threads[index].status)) {
    const error = new Error("이전 답변 생성이 끝난 뒤 다시 질문하세요.");
    error.status = 409;
    throw error;
  }

  const title = chat.threads[index].messages.length
    ? chat.threads[index].title
    : cleanNoteText(question, 44) || chat.threads[index].title;
  chat.threads[index] = normalizeAnalysisHtmlThread({
    ...chat.threads[index],
    title,
    status: "pending",
    error: "",
    messages: [
      ...chat.threads[index].messages,
      createNoteMessage({
        role: "user",
        content: question,
        model,
        modelMode,
      }),
    ],
    updatedAt: new Date().toISOString(),
  }, file);
  await writeAnalysisHtmlChat(dirs, file, chat);
  return chat.threads[index];
}

async function runAnalysisHtmlChatAnswer(dirs, file, threadId) {
  await updateAnalysisHtmlChatThread(dirs, file, threadId, { status: "running", error: "" });
  const chat = await readAnalysisHtmlChat(dirs, file);
  const thread = chat.threads.find((item) => item.id === threadId);
  if (!thread) {
    return;
  }

  try {
    const html = await readFile(join(dirs.analysisHtml, file), "utf8");
    const answer = await requestAnalysisHtmlChatAnswer(file, html, thread);
    const messages = [
      ...thread.messages,
      createNoteMessage({
        role: "assistant",
        content: answer,
        model: thread.messages.at(-1)?.model || getNoteModel(thread.messages.at(-1)?.modelMode),
        modelMode: thread.messages.at(-1)?.modelMode || "fast",
        status: "completed",
      }),
    ];
    await updateAnalysisHtmlChatThread(dirs, file, threadId, {
      status: "completed",
      messages,
      error: "",
    });
  } catch (error) {
    const latest = (await readAnalysisHtmlChat(dirs, file)).threads.find((item) => item.id === threadId);
    await updateAnalysisHtmlChatThread(dirs, file, threadId, {
      status: "failed",
      messages: latest
        ? [
            ...latest.messages,
            createNoteMessage({
              role: "assistant",
              content: "",
              model: latest.messages.at(-1)?.model || "",
              modelMode: latest.messages.at(-1)?.modelMode || "fast",
              status: "failed",
              error: error.message || "답변 생성에 실패했습니다.",
            }),
          ]
        : undefined,
      error: error.message || "답변 생성에 실패했습니다.",
    });
  }
}

async function updateAnalysisHtmlChatThread(dirs, file, threadId, patch) {
  const chat = await readAnalysisHtmlChat(dirs, file);
  const index = chat.threads.findIndex((thread) => thread.id === threadId);
  if (index === -1) {
    return null;
  }
  chat.threads[index] = normalizeAnalysisHtmlThread({
    ...chat.threads[index],
    ...patch,
    updatedAt: new Date().toISOString(),
  }, file);
  await writeAnalysisHtmlChat(dirs, file, chat);
  return chat.threads[index];
}

async function deleteAnalysisHtmlChatThread(dirs, file, threadId) {
  const chat = await readAnalysisHtmlChat(dirs, file);
  const target = chat.threads.find((thread) => thread.id === threadId);
  if (!target) {
    return false;
  }
  if (["pending", "running"].includes(target.status)) {
    const error = new Error("답변 생성 중인 대화는 삭제할 수 없습니다.");
    error.status = 409;
    throw error;
  }
  chat.threads = chat.threads.filter((thread) => thread.id !== threadId);
  await writeAnalysisHtmlChat(dirs, file, chat);
  return true;
}

async function requestAnalysisHtmlChatAnswer(file, html, thread) {
  const modelMode = thread.messages.at(-1)?.modelMode || "fast";
  const model = thread.messages.at(-1)?.model || getNoteModel(modelMode);
  const raw = await runCodexNote(buildAnalysisHtmlChatPrompt(file, html, thread), model);
  const parsed = parseJsonObject(raw);
  return cleanNoteText(parsed.answer, 6000) || "답변을 생성하지 못했습니다.";
}

function buildAnalysisHtmlChatPrompt(file, html, thread) {
  const fullText = cleanPromptText(htmlToPlainText(html), 120000);
  const conversation = thread.messages
    .map((message) => `${message.role === "assistant" ? "A" : "Q"}: ${message.content}`)
    .join("\n\n");
  return `You are helping a Korean reader study an HTML research note.

Return only JSON matching the schema. Do not use markdown fences.

Rules:
- Answer in Korean.
- Use the current HTML note text as the source of truth.
- Use the conversation history to understand follow-up questions.
- Be concise but specific.
- If the note does not contain enough information, say what is missing and separate it from your inference.

HTML file:
${file}

Conversation:
${conversation}

Current HTML note text:
${fullText}
`;
}

function normalizeAnalysisHtmlChat(chat, file) {
  const threads = Array.isArray(chat?.threads)
    ? chat.threads.map((thread) => normalizeAnalysisHtmlThread(thread, file)).filter(Boolean)
    : [];
  threads.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  return {
    file,
    threads,
  };
}

function normalizeAnalysisHtmlThread(thread, file) {
  if (!thread?.id || !isValidNoteId(thread.id)) {
    return null;
  }
  return {
    id: String(thread.id),
    file,
    title: cleanNoteText(thread.title, 80) || "새 질문",
    status: ["idle", "pending", "running", "completed", "failed"].includes(thread.status)
      ? thread.status
      : "idle",
    messages: normalizeNoteMessages(thread.messages || [], {
      question: "",
      answer: "",
      model: getNoteModel("fast") || "codex-default",
      modelMode: "fast",
      createdAt: thread.createdAt,
    }),
    error: cleanNoteText(thread.error, 1000),
    createdAt: String(thread.createdAt || new Date().toISOString()),
    updatedAt: String(thread.updatedAt || thread.createdAt || new Date().toISOString()),
  };
}

async function createPendingNote(dirs, document, body) {
  const anchorText = cleanNoteText(body?.anchorText, 1200);
  const question = cleanNoteText(body?.question, 2000);
  const modelMode = normalizeNoteModelMode(body?.modelMode);
  const model = getNoteModel(modelMode);
  const page = Math.max(1, Math.floor(Number(body?.page || 1)));
  if (!anchorText || !question) {
    const error = new Error("선택 텍스트와 질문이 필요합니다.");
    error.status = 400;
    throw error;
  }

  const context = buildNoteContext(document.markdown || "", page, anchorText, {
    paragraph: body?.paragraph,
    before: body?.contextBefore,
    after: body?.contextAfter,
  });
  const now = new Date().toISOString();
  const note = {
    id: randomUUID(),
    documentId: document.id,
    page,
    anchorText,
    question,
    answer: "",
    status: "pending",
    context,
    messages: [
      createNoteMessage({
        role: "user",
        content: question,
        model,
        modelMode,
      }),
    ],
    provider: "codex",
    model,
    modelMode,
    error: "",
    createdAt: now,
    updatedAt: now,
  };

  const notes = await readDocumentNotes(dirs, document.id);
  notes.push(note);
  await writeDocumentNotes(dirs, document.id, notes);
  return note;
}

async function appendPendingNoteQuestion(dirs, documentId, noteId, body) {
  const question = cleanNoteText(body?.question, 2000);
  const modelMode = normalizeNoteModelMode(body?.modelMode);
  const model = getNoteModel(modelMode);
  if (!question) {
    const error = new Error("질문이 필요합니다.");
    error.status = 400;
    throw error;
  }

  const notes = await readDocumentNotes(dirs, documentId);
  const index = notes.findIndex((note) => note.id === noteId);
  if (index === -1) {
    const error = new Error("메모를 찾지 못했습니다.");
    error.status = 404;
    throw error;
  }
  if (["pending", "running"].includes(notes[index].status)) {
    const error = new Error("이전 답변 생성이 끝난 뒤 다시 질문하세요.");
    error.status = 409;
    throw error;
  }

  notes[index] = normalizeDocumentNote({
    ...notes[index],
    question,
    answer: "",
    status: "pending",
    model,
    modelMode,
    error: "",
    messages: [
      ...notes[index].messages,
      createNoteMessage({
        role: "user",
        content: question,
        model,
        modelMode,
      }),
    ],
    updatedAt: new Date().toISOString(),
  });
  await writeDocumentNotes(dirs, documentId, notes);
  return notes[index];
}

async function runNoteAnswer(dirs, document, noteId) {
  await updateDocumentNote(dirs, document.id, noteId, { status: "running", error: "" });
  const note = (await readDocumentNotes(dirs, document.id)).find((item) => item.id === noteId);
  if (!note) {
    return;
  }

  try {
    const answer = await requestNoteAnswer(document, note);
    const messages = [
      ...note.messages,
      createNoteMessage({
        role: "assistant",
        content: answer,
        model: note.model,
        modelMode: note.modelMode,
        status: "completed",
      }),
    ];
    await updateDocumentNote(dirs, document.id, noteId, {
      status: "completed",
      answer,
      messages,
      error: "",
    });
  } catch (error) {
    const failedNote = (await readDocumentNotes(dirs, document.id)).find((item) => item.id === noteId);
    await updateDocumentNote(dirs, document.id, noteId, {
      status: "failed",
      messages: failedNote
        ? [
            ...failedNote.messages,
            createNoteMessage({
              role: "assistant",
              content: "",
              model: failedNote.model,
              modelMode: failedNote.modelMode,
              status: "failed",
              error: error.message || "답변 생성에 실패했습니다.",
            }),
          ]
        : undefined,
      error: error.message || "답변 생성에 실패했습니다.",
    });
  }
}

async function updateDocumentNote(dirs, documentId, noteId, patch) {
  const notes = await readDocumentNotes(dirs, documentId);
  const index = notes.findIndex((note) => note.id === noteId);
  if (index === -1) {
    return null;
  }
  notes[index] = normalizeDocumentNote({
    ...notes[index],
    ...patch,
    updatedAt: new Date().toISOString(),
  });
  await writeDocumentNotes(dirs, documentId, notes);
  return notes[index];
}

async function deleteDocumentNote(dirs, documentId, noteId) {
  const notes = await readDocumentNotes(dirs, documentId);
  const nextNotes = notes.filter((note) => note.id !== noteId);
  if (nextNotes.length === notes.length) {
    return false;
  }
  await writeDocumentNotes(dirs, documentId, nextNotes);
  return true;
}

function buildNoteContext(markdown, page, anchorText, provided = {}) {
  const cleanProvided = {
    paragraph: cleanNoteText(provided.paragraph, 6000),
    before: cleanNoteText(provided.before, 6000),
    after: cleanNoteText(provided.after, 6000),
  };
  if (cleanProvided.paragraph) {
    return { sourceLanguage: "en", ...cleanProvided };
  }

  const pageText = String(markdown || "").split("\f")[page - 1] || "";
  const paragraphs = pageText
    .split(/\n{2,}/)
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const normalizedAnchor = anchorText.replace(/\s+/g, " ").trim();
  const index = Math.max(0, paragraphs.findIndex((paragraph) => paragraph.includes(normalizedAnchor)));

  return {
    sourceLanguage: "en",
    paragraph: cleanNoteText(paragraphs[index] || normalizedAnchor, 6000),
    before: cleanNoteText(paragraphs[index - 1] || "", 6000),
    after: cleanNoteText(paragraphs[index + 1] || "", 6000),
  };
}

async function requestNoteAnswer(document, note) {
  const raw = await runCodexNote(buildNotePrompt(document, note), note.model);
  const parsed = parseJsonObject(raw);
  return cleanNoteText(parsed.answer, 6000) || "답변을 생성하지 못했습니다.";
}

function buildNotePrompt(document, note) {
  const fullDocumentText = note.modelMode === "deep"
    ? cleanPromptText(document.markdown || "", 120000)
    : "";
  const conversation = note.messages
    .map((message) => `${message.role === "assistant" ? "A" : "Q"}: ${message.content}`)
    .join("\n\n");
  return `You are helping a Korean reader understand an English document.

Return only JSON matching the schema. Do not use markdown fences.

Rules:
- Answer in Korean.
- For fast mode, use the selected text, local context, and conversation as the source of truth.
- For deep mode, use the full English document, selected text, local context, and conversation as the source of truth.
- Be concise but specific. If the user asks for comparison, compare the selected text with the requested target.
- If the document is insufficient, say what is uncertain and answer from the provided document only.

Document title:
${document.originalName || ""}

Page:
${note.page}

Selected text:
${note.anchorText}

User question:
${note.question}

Conversation so far:
${conversation}

Context before:
${note.context.before || ""}

Context paragraph:
${note.context.paragraph || ""}

Context after:
${note.context.after || ""}

${note.modelMode === "deep" ? `Full English document:\n${fullDocumentText}` : ""}
`;
}

async function runCodexNote(prompt, model) {
  try {
    return await runCodexNoteOnce(prompt, model);
  } catch (error) {
    if (model) {
      return runCodexNoteOnce(prompt, "");
    }
    throw error;
  }
}

async function runCodexNoteOnce(prompt, model) {
  const outputPath = join(storageDir, `codex-note-${Date.now()}-${randomUUID()}.json`);
  const args = [
    "-a",
    "never",
    "exec",
    "--ephemeral",
    "--sandbox",
    "read-only",
    "--output-schema",
    noteAnswerSchemaPath,
    "--output-last-message",
    outputPath,
    "-",
  ];

  if (model) {
    args.splice(0, 0, "--model", model);
  }

  const { stderr } = await spawnWithInput(codexBin, args, prompt, {
    cwd: process.cwd(),
    timeoutMs: Number(process.env.CODEX_NOTE_TIMEOUT_MS || 180000),
    maxOutputBytes: 1024 * 1024,
  });

  try {
    const result = await readFile(outputPath, "utf8");
    unlink(outputPath).catch(() => {});
    return result;
  } catch {
    throw new Error(stderr || "Codex 메모 결과 파일을 읽지 못했습니다.");
  }
}

function cleanNoteText(value, maxLength) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
}

function cleanChatText(value, maxLength) {
  return String(value || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .trim()
    .slice(0, maxLength);
}

function createNoteMessage({ role, content, model = "", modelMode = "fast", status = "completed", error = "" }) {
  return {
    id: randomUUID(),
    role,
    content: cleanNoteText(content, role === "assistant" ? 6000 : 2000),
    model: String(model || ""),
    modelMode: normalizeNoteModelMode(modelMode),
    status,
    error: cleanNoteText(error, 1000),
    createdAt: new Date().toISOString(),
  };
}

function cleanPromptText(value, maxLength) {
  return String(value || "").replace(/\f/g, "\n\n--- PAGE BREAK ---\n\n").slice(0, maxLength);
}

function normalizeNoteModelMode(value) {
  return value === "deep" ? "deep" : "fast";
}

function getNoteModel(modelMode) {
  if (modelMode === "deep") {
    return codexNoteDeepModel || codexModel || "";
  }
  return codexNoteFastModel || codexModel || "";
}

function normalizeDocumentNote(note) {
  if (!note?.id || !isValidNoteId(note.id)) {
    return null;
  }
  const modelMode = normalizeNoteModelMode(note.modelMode);
  const model = String(note.model || getNoteModel(modelMode) || "codex-default");
  const question = cleanNoteText(note.question, 2000);
  const answer = cleanNoteText(note.answer, 6000);
  const messages = normalizeNoteMessages(note.messages, {
    question,
    answer,
    model,
    modelMode,
    createdAt: note.createdAt,
  });
  return {
    id: String(note.id),
    documentId: String(note.documentId || ""),
    page: Math.max(1, Math.floor(Number(note.page || 1))),
    anchorText: cleanNoteText(note.anchorText, 1200),
    question,
    answer,
    status: ["pending", "running", "completed", "failed"].includes(note.status)
      ? note.status
      : "failed",
    context: {
      sourceLanguage: "en",
      paragraph: cleanNoteText(note.context?.paragraph, 6000),
      before: cleanNoteText(note.context?.before, 6000),
      after: cleanNoteText(note.context?.after, 6000),
    },
    messages,
    provider: String(note.provider || "codex"),
    model,
    modelMode,
    error: cleanNoteText(note.error, 1000),
    createdAt: String(note.createdAt || new Date().toISOString()),
    updatedAt: String(note.updatedAt || note.createdAt || new Date().toISOString()),
  };
}

function normalizeNoteMessages(messages, fallback) {
  const normalized = Array.isArray(messages)
    ? messages
        .map((message) => {
          const role = message?.role === "assistant" ? "assistant" : "user";
          const content = cleanNoteText(message?.content, role === "assistant" ? 6000 : 2000);
          if (!content && message?.status !== "failed") {
            return null;
          }
          return {
            id: isValidNoteId(message?.id) ? String(message.id) : randomUUID(),
            role,
            content,
            model: String(message?.model || fallback.model || ""),
            modelMode: normalizeNoteModelMode(message?.modelMode || fallback.modelMode),
            status: ["pending", "completed", "failed"].includes(message?.status)
              ? message.status
              : "completed",
            error: cleanNoteText(message?.error, 1000),
            createdAt: String(message?.createdAt || fallback.createdAt || new Date().toISOString()),
          };
        })
        .filter(Boolean)
    : [];

  if (normalized.length === 0 && fallback.question) {
    normalized.push({
      id: randomUUID(),
      role: "user",
      content: fallback.question,
      model: fallback.model,
      modelMode: fallback.modelMode,
      status: "completed",
      error: "",
      createdAt: String(fallback.createdAt || new Date().toISOString()),
    });
  }
  if (normalized.length === 1 && fallback.answer) {
    normalized.push({
      id: randomUUID(),
      role: "assistant",
      content: fallback.answer,
      model: fallback.model,
      modelMode: fallback.modelMode,
      status: "completed",
      error: "",
      createdAt: String(fallback.createdAt || new Date().toISOString()),
    });
  }
  return normalized;
}

async function createDocumentShare(dirs, username, documentId) {
  const metadata = await readMetadata(dirs, documentId);
  const markdownPath = join(dirs.converted, `${documentId}.md`);
  if (!metadata || !existsSync(markdownPath)) {
    const error = new Error("공유할 글을 찾지 못했습니다.");
    error.code = "ENOENT";
    throw error;
  }

  const existing = await findShareForDocument(dirs, documentId);
  if (existing) {
    return existing;
  }

  const share = {
    id: randomUUID(),
    token: randomUUID(),
    username,
    documentId,
    enabled: true,
    createdAt: new Date().toISOString(),
  };
  await writeShare(dirs, share);
  return share;
}

async function createAnalysisHtmlShare(dirs, username, analysisFile) {
  if (!existsSync(join(dirs.analysisHtml, analysisFile))) {
    const error = new Error("공유할 분석 글을 찾지 못했습니다.");
    error.code = "ENOENT";
    throw error;
  }

  const existing = await findShareForAnalysisHtmlFile(dirs, analysisFile);
  if (existing) {
    return existing;
  }

  const share = {
    id: randomUUID(),
    token: randomUUID(),
    type: "analysis-html",
    username,
    analysisFile,
    enabled: true,
    createdAt: new Date().toISOString(),
  };
  await writeShare(dirs, share);
  return share;
}

async function findShareForDocument(dirs, documentId) {
  const shares = await listShares(dirs);
  return shares.find((share) => share.enabled !== false && share.documentId === documentId) || null;
}

async function findShareForAnalysisHtmlFile(dirs, analysisFile) {
  const shares = await listShares(dirs);
  return shares.find(
    (share) =>
      share.enabled !== false &&
      share.type === "analysis-html" &&
      share.analysisFile === analysisFile,
  ) || null;
}

async function getSharedDocument(token) {
  const shared = await findShareByToken(token);
  if (!shared) {
    return null;
  }

  const document = await getDocument(shared.dirs, shared.share.documentId);
  if (!document) {
    return null;
  }

  return {
    share: shared.share,
    document: buildSharedDocumentPayload(document, shared.share.token),
  };
}

async function findShareByToken(token) {
  const usernames = await readdir(usersDir).catch(() => []);
  for (const username of usernames) {
    const dirs = await ensureUserDirs(username);
    const shares = await listShares(dirs);
    const share = shares.find((item) => item.enabled !== false && item.token === token);
    if (share) {
      return { username, dirs, share };
    }
  }
  return null;
}

async function listShares(dirs) {
  const files = (await readdir(dirs.shares).catch(() => [])).filter((file) => file.endsWith(".json"));
  const shares = await Promise.all(
    files.map(async (file) => {
      try {
        const raw = await readFile(join(dirs.shares, file), "utf8");
        return JSON.parse(raw);
      } catch {
        return null;
      }
    }),
  );
  return shares.filter(
    (share) =>
      share?.id &&
      share?.token &&
      (share?.documentId || (share?.type === "analysis-html" && share?.analysisFile)),
  );
}

async function writeShare(dirs, share) {
  await mkdir(dirs.shares, { recursive: true });
  await writeFile(join(dirs.shares, `${share.id}.json`), JSON.stringify(share, null, 2));
}

async function deleteSharesForDocument(dirs, documentId) {
  const shares = await listShares(dirs);
  await Promise.all(
    shares
      .filter((share) => share.documentId === documentId)
      .map((share) => unlink(join(dirs.shares, `${share.id}.json`)).catch((error) => {
        if (error.code !== "ENOENT") {
          throw error;
        }
      })),
  );
}

async function deleteSharesForAnalysisHtmlFile(dirs, analysisFile) {
  const shares = await listShares(dirs);
  await Promise.all(
    shares
      .filter((share) => share.type === "analysis-html" && share.analysisFile === analysisFile)
      .map((share) => unlink(join(dirs.shares, `${share.id}.json`)).catch((error) => {
        if (error.code !== "ENOENT") {
          throw error;
        }
      })),
  );
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

async function analyzeDocument(dirs, id, pageLimit, options = {}) {
  const onProgress = options.onProgress || (() => {});
  const assertActive = options.assertActive || (() => {});
  const signal = options.signal;
  const metadata = await readMetadata(dirs, id);
  const storedName = metadata?.storedName || `${id}.pdf`;
  const pdfPath = join(dirs.uploads, storedName);
  const markdownPath = join(dirs.converted, `${id}.md`);

  assertActive();
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
  const analysisPlan = getAnalysisExecutionPlan(effectivePageLimit, assets.charts || []);
  const totalChunks = Math.max(1, Math.ceil(sourcePages.pages.length / analysisPlan.chunkPages));
  const totalSteps = effectivePageLimit > analysisPlan.chunkPages ? totalChunks + 1 : 1;
  onProgress({
    completed: 0,
    total: totalSteps,
    percent: 0,
    message: `전체 ${effectivePageLimit}페이지 번역 준비 중 · ${analysisPlan.chunkPages}페이지씩 ${analysisPlan.concurrency}개 병렬`,
  });
  assertActive();
  const analysis =
    effectivePageLimit > analysisPlan.chunkPages
      ? await requestChunkedTranslationAnalysis(
          dirs,
          id,
          sourcePages,
          assets.charts || [],
          analysisPlan,
          onProgress,
          totalSteps,
          assertActive,
          signal,
        )
      : await requestTranslationAnalysis(
          sourcePages,
          effectivePageLimit,
          getChartImagePaths(dirs, id, assets.charts || [], sourcePages.pages),
          signal,
        );
  assertActive();
  if (effectivePageLimit <= analysisPlan.chunkPages) {
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

  assertActive();
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

  const controller = new AbortController();
  analysisJobControllers.set(job.id, controller);
  updateAnalysisJob(job, { status: "running" });

  try {
    const assertActive = () => {
      if (job.status !== "running") {
        throw new Error(job.error || "번역 작업이 중단되었습니다.");
      }
      const activeKey = `${job.username}:${job.documentId}`;
      if (activeAnalysisJobs.get(activeKey) !== job.id) {
        throw new Error("번역 작업이 중단되었습니다.");
      }
    };
    const analysis = await analyzeDocument(dirs, job.documentId, job.pageLimit, {
      signal: controller.signal,
      assertActive,
      onProgress: (progress) => {
        assertActive();
        updateAnalysisJob(job, { progress });
      },
    });
    assertActive();
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
    if (job.status === "failed" && job.error) {
      return;
    }
    updateAnalysisJob(job, {
      status: "failed",
      error: error.message || "번역 생성에 실패했습니다.",
    });
  } finally {
    analysisJobControllers.delete(job.id);
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

function getAnalysisExecutionPlan(pageCount, charts) {
  const chartCount = (charts || []).filter((chart) => Number(chart.page || 0) <= pageCount).length;
  const hasManyPages = pageCount >= 48;
  const hasMediumPages = pageCount >= 24;
  const hasVeryDenseCharts = chartCount >= pageCount;

  if (hasManyPages && !hasVeryDenseCharts) {
    return {
      chunkPages: Math.max(defaultAnalysisChunkPages, 6),
      concurrency: defaultAnalysisConcurrency,
    };
  }

  if (hasMediumPages) {
    return {
      chunkPages: Math.max(defaultAnalysisChunkPages, 5),
      concurrency: defaultAnalysisConcurrency,
    };
  }

  return {
    chunkPages: defaultAnalysisChunkPages,
    concurrency: defaultAnalysisConcurrency,
  };
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
        pageLimit: Number(job.pageLimit ?? 0),
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

async function requestChunkedTranslationAnalysis(
  dirs,
  id,
  source,
  charts,
  analysisPlan,
  onProgress,
  totalSteps,
  assertActive,
  signal,
) {
  const chunks = chunkArray(source.pages, analysisPlan.chunkPages);
  const analyses = new Array(chunks.length);
  let completed = 0;

  await mapWithConcurrency(chunks, analysisPlan.concurrency, async (chunk, index) => {
    assertActive();
    const chunkSource = { pages: chunk };
    analyses[index] = await requestTranslationAnalysis(
      chunkSource,
      chunk.length,
      getChartImagePaths(dirs, id, charts, chunk),
      signal,
    );
    assertActive();
    completed += 1;
    onProgress({
      completed,
      total: totalSteps,
      percent: Math.round((completed / totalSteps) * 100),
      message: `${completed}/${totalSteps} 단계 완료 · 번역 묶음 ${completed}/${chunks.length}`,
    });
  });

  assertActive();
  onProgress({
    completed: chunks.length,
    total: totalSteps,
    percent: Math.round((chunks.length / totalSteps) * 100),
    message: `${chunks.length}/${totalSteps} 단계 완료 · 전체요약 정리 중`,
  });

  const overall = await synthesizeOverallSummary(analyses, signal).catch(() =>
    mergeOverallSummaries(analyses),
  );

  return {
    overall,
    pages: analyses.flatMap((analysis) => analysis.pages || []).sort((a, b) => a.page - b.page),
  };
}

async function synthesizeOverallSummary(analyses, signal) {
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

  const raw = await runCodexTranslation(prompt, [], signal);
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

async function requestTranslationAnalysis(source, pageLimit, chartImagePaths, signal) {
  const raw = await runCodexTranslation(
    buildTranslationPrompt(source, pageLimit, chartImagePaths),
    chartImagePaths,
    signal,
  );
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
- Translate the supplied source text in sentencePairs so the reader can still inspect the full document flow.
- Content-bearing rule for summaries only: overall bullets, page/section summaries, and paragraph summaries should include only material that contributes to the document's thesis, evidence, data interpretation, method, conclusion, assumptions, or risk analysis. Do not summarize document chrome, navigation, publishing metadata, attribution/profile, legal/compliance boilerplate, rights/terms/privacy notice, account/action controls, audience interaction controls, empty UI, references without interpretation, or repeated headers/footers. A risk/disclaimer sentence belongs in a summary only if the author uses it as a substantive analytical point.
- Do not add a summary saying excluded material is boilerplate. Leave that summary empty instead.
- Do not use headings such as "문서/저자", "문서 및 저자", "저자", "작성자", "필자", or "프로필". If that metadata context needs a section heading, use "문서".
- Only include the pages supplied in input.

Input page limit: ${pageLimit}
Attached chart images: ${chartImagePaths.length}

Input JSON:
${JSON.stringify(source, null, 2)}
`;
}

async function runCodexTranslation(prompt, imagePaths = [], signal) {
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
    signal,
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
    if (options.signal?.aborted) {
      reject(new Error("번역 작업이 중단되었습니다."));
      return;
    }

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
      options.signal?.removeEventListener("abort", abort);
      reject(error);
    };

    const abort = () => {
      child.kill("SIGTERM");
      fail(new Error("번역 작업이 중단되었습니다."));
    };

    options.signal?.addEventListener("abort", abort, { once: true });

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
      options.signal?.removeEventListener("abort", abort);
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
          .map((section) => normalizeSection(section)),
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
          summary: isContentBearingText(paragraph.summary) ? String(paragraph.summary || "") : "",
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
      summary: isContentBearingText(analysis.overall?.summary)
        ? String(analysis.overall?.summary || "")
        : "",
      bullets: Array.isArray(analysis.overall?.bullets)
        ? analysis.overall.bullets
            .map((item) => String(item))
            .filter((item) => item && isContentBearingText(item))
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
    summary: isContentBearingText(section.summary) ? String(section.summary || "") : "",
    sentencePairs,
  };
}

function normalizeSectionTitle(title) {
  const value = String(title || "").trim();
  if (isDocumentAttributionHeading(value)) {
    return "문서";
  }
  return value;
}

function isDocumentAttributionHeading(value) {
  return /^(?:문서\s*(?:\/|및|와|과|·|,|\+|&)\s*)?(?:저자|작성자|필자|글쓴이|프로필|출처)(?:\s*(?:\/|및|와|과|·|,|\+|&)\s*문서)?$/i.test(
    String(value || "").trim(),
  );
}

function isContentBearingText(value) {
  const text = String(value || "").toLowerCase();
  if (!text.trim()) {
    return true;
  }

  return !isAdministrativeText(text) || hasAnalyticalSignal(text);
}

function isAdministrativeText(text) {
  const administrativePatterns = [
    /published by|posted by|written by|edited by|about the author|author profile/,
    /reply|respond|comment|reaction|like this|share this|sign in|log in|subscribe|unsubscribe/,
    /privacy policy|terms of use|terms and conditions|cookie preferences|manage preferences/,
    /copyright|all rights reserved|©/,
    /not .*advice|for informational purposes only|legal disclaimer|disclaimer/,
    /navigation|menu|table of contents|page header|page footer|view in browser|download app|open app/,
    /contact us|all trademarks|rights reserved/,
    /작성자 소개|저자 소개|프로필|댓글|답글|반응|좋아요|공유|구독|로그인|회원가입/,
    /개인정보|처리방침|약관|쿠키|저작권|권리 보유|고지|면책|정보 제공 목적/,
    /목차|페이지 상단|페이지 하단|머리말|꼬리말|앱에서 열기|문의하기/,
  ];
  return administrativePatterns.some((pattern) => pattern.test(text));
}

function hasAnalyticalSignal(text) {
  const analyticalPatterns = [
    /earnings|inflation|rates?|yield|curve|credit|equity|macro|fed|fomc|gdp|cpi|pce/,
    /valuation|positioning|liquidity|volatility|duration|spread|multiple|cycle/,
    /estimate|forecast|assumption|scenario|risk|catalyst|sensitivity|drawdown|upside|downside/,
    /therefore|because|implies|suggests|driven by|supported by|evidence|data shows/,
    /금리|인플레이션|물가|성장|경기|유동성|밸류에이션|실적|연준|신용|스프레드|변동성|포지셔닝/,
    /가정|전망|시나리오|리스크|촉매|민감도|하방|상방|근거|데이터|의미|시사|때문|따라서/,
  ];
  return analyticalPatterns.some((pattern) => pattern.test(text));
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

async function writeMetadata(dirs, id, metadata) {
  await writeFile(join(dirs.documents, `${id}.json`), JSON.stringify(metadata, null, 2));
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

function getCompleteAnalysis(analysis, markdown) {
  if (!analysis) {
    return null;
  }

  const pageCount = String(markdown || "").split("\f").length;
  const analysisPageLimit = Number(analysis.pageLimit || 0);
  const translatedPages = Array.isArray(analysis.pages) ? analysis.pages.length : 0;
  if (analysis.isSample || analysisPageLimit < pageCount || translatedPages < pageCount) {
    return null;
  }
  return analysis;
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

function buildSharedDocumentPayload(document, token) {
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

function isValidDocumentId(id) {
  return /^[a-zA-Z0-9-]+$/.test(id);
}

function normalizeDocumentTitle(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= 180 ? text : "";
}

function isValidNoteId(id) {
  return /^[a-zA-Z0-9-]+$/.test(id);
}

function isValidShareToken(token) {
  return /^[a-zA-Z0-9-]+$/.test(token);
}

function isValidAssetFile(file) {
  return /^[^/\\]+$/.test(file);
}

function isValidAnalysisHtmlFile(file) {
  return /^[^/\\]+\.html?$/i.test(file);
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
