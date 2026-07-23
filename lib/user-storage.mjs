import { mkdir } from "node:fs/promises";
import { join } from "node:path";

export function createUserDirsResolver(usersDir) {
  return async function ensureUserDirs(username) {
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
      feedback: join(root, "feedback"),
      feedbackItems: join(root, "feedback", "items"),
      notes: join(root, "notes"),
      shares: join(root, "shares"),
    };

    await Promise.all(Object.values(dirs).map((dir) => mkdir(dir, { recursive: true })));
    return dirs;
  };
}

