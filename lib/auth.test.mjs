import assert from "node:assert/strict";
import test from "node:test";

import { parseAuthUsers } from "./auth.mjs";

test("parseAuthUsers keeps configured accounts and trims usernames", () => {
  const users = parseAuthUsers('{" alice ":"secret","bob":"pw"}');
  assert.deepEqual([...users.entries()], [["alice", "secret"], ["bob", "pw"]]);
});

test("parseAuthUsers accepts an empty account setting", () => {
  assert.equal(parseAuthUsers("").size, 0);
});

test("parseAuthUsers rejects non-object JSON with the existing error", () => {
  assert.throws(
    () => parseAuthUsers("[]"),
    /AUTH_USERS_JSON 설정을 읽지 못했습니다: AUTH_USERS_JSON must be an object/,
  );
});

