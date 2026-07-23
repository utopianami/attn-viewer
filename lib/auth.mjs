import { randomUUID, timingSafeEqual } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";

const DEFAULT_SESSION_MAX_AGE_MS = 1000 * 60 * 60 * 24 * 14;

export function parseAuthUsers(raw) {
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

export function createAuth({
  users,
  sessionsPath,
  ensureUserDirs,
  sessionMaxAgeMs = DEFAULT_SESSION_MAX_AGE_MS,
}) {
  const sessions = new Map();

  function persistSessions() {
    const payload = Object.fromEntries(sessions.entries());
    writeFile(sessionsPath, JSON.stringify(payload, null, 2)).catch(() => {});
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

  function safeEqual(first, second) {
    const firstBuffer = Buffer.from(String(first));
    const secondBuffer = Buffer.from(String(second));
    return firstBuffer.length === secondBuffer.length && timingSafeEqual(firstBuffer, secondBuffer);
  }

  function isValidLogin(username, password) {
    const expected = users.get(username);
    return Boolean(expected) && safeEqual(password, expected);
  }

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

  function registerRoutes(app) {
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
  }

  return { loadSessions, registerRoutes, requireAuth };
}

