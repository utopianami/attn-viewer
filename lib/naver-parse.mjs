// 네이버 블로그 모바일 HTML → 제목·메타·본문(Markdown 파츠) 파싱.
// crawl_naver_blog.mjs와 재파싱 스크립트가 공유한다.
// 컴포넌트 분리는 시작 위치 기반 — 정규식 lookahead 방식은 컴포넌트가 하나뿐인 글
// (닫힘 패턴 불일치)에서 전부 버리는 버그가 있었다 (2026-07-10 수정).

export function decodeHtml(value = "") {
  const named = { amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: " ", "#034": "\"", "#039": "'" };
  return String(value)
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, decimal) => String.fromCodePoint(parseInt(decimal, 10)))
    .replace(/&([a-zA-Z]+|#034|#039);/g, (match, name) => named[name] ?? match);
}

export function stripTags(value = "") {
  return decodeHtml(value.replace(/<br\s*\/?\s*>/gi, "\n").replace(/<[^>]+>/g, ""))
    .replace(/​/g, "")
    .trim();
}

function attr(tag, name) {
  const match = tag.match(new RegExp(`${name}=["']([^"']*)["']`, "i"));
  return match ? decodeHtml(match[1]) : "";
}

export function anchorAwareText(html) {
  const withLinks = html.replace(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi, (match, attrs, inner) => {
    const href = attr(attrs, "href");
    const text = stripTags(inner);
    return href && text ? `[${text}](${href})` : text;
  });
  return stripTags(withLinks).replace(/\s+/g, " ").trim();
}

export function firstMatch(html, regex) {
  return stripTags(html.match(regex)?.[1] ?? "");
}

export function metaProperty(html, prop) {
  const match = html.match(
    new RegExp(`<meta[^>]+property=["']${prop}["'][^>]+content=["']([^"']*)["'][^>]*>`, "i"),
  );
  return decodeHtml(match?.[1] ?? "");
}

export function extractMainContainer(html) {
  return (
    html.match(
      /<div class="se-main-container">([\s\S]*?)<\/div>\s*<\/div>\s*<\/div>\s*\n\s*\t\t\n\s*\t\t\n\s*\t<\/div>/,
    )?.[1] ??
    html.match(/<div class="se-main-container">([\s\S]*?)<div class="social_plugin_property"/i)?.[1] ??
    null
  );
}

// 컴포넌트 분리 — "<div class="se-component " 시작 위치 기준으로 자른다.
// 각 세그먼트에 다음 컴포넌트 이전까지의 내용이 담긴다 (마지막은 main 끝까지).
export function splitComponents(main) {
  const marks = [...main.matchAll(/<div class="se-component /g)].map((match) => match.index);
  return marks.map((start, index) => main.slice(start, marks[index + 1] ?? main.length));
}

// 본문 파싱 → { mdParts, images } (images: {src} 목록, placeholder 치환은 호출부 몫)
export function parseBody(main, articleId) {
  const components = splitComponents(main);
  const images = [];
  const mdParts = [];

  for (const component of components) {
    if (component.includes("se-component se-text") || component.includes("se-module se-module-text")) {
      const paragraphs = [...component.matchAll(/<p\b[^>]*class="se-text-paragraph[^"]*"[^>]*>([\s\S]*?)<\/p>/gi)]
        .map((match) => anchorAwareText(match[1]))
        .filter(Boolean);
      if (paragraphs.length) {
        mdParts.push(paragraphs.join("\n\n"));
      }
      continue;
    }

    if (component.includes("se-component se-oglink")) {
      const link =
        component.match(/<a\b[^>]*href="([^"]+)"[^>]*class="se-oglink-info"/i)?.[1] ||
        component.match(/<a\b[^>]*href="([^"]+)"/i)?.[1] ||
        "";
      const ogTitle = stripTags(
        component.match(/<strong class="se-oglink-title">([\s\S]*?)<\/strong>/i)?.[1] ?? "",
      );
      const summary = stripTags(
        component.match(/<p class="se-oglink-summary">([\s\S]*?)<\/p>/i)?.[1] ?? "",
      );
      if (link || ogTitle) {
        mdParts.push(
          `> 링크: ${ogTitle || link}${link ? `\n> ${decodeHtml(link)}` : ""}${summary ? `\n> ${summary}` : ""}`,
        );
      }
      continue;
    }

    if (component.includes("se-component se-image")) {
      const lazy = decodeHtml(component.match(/data-lazy-src="([^"]+)"/i)?.[1] ?? "");
      const srcFromData = decodeHtml(component.match(/"src"\s*:\s*"([^"]+)"/i)?.[1] ?? "");
      const src = lazy || srcFromData;
      if (!src) {
        continue;
      }
      images.push({ src });
      const n = images.length;
      const caption = stripTags(
        component.match(/<div class="se-module se-module-text se-caption">([\s\S]*?)<\/div>/i)?.[1] ?? "",
      );
      mdParts.push(
        `![image ${n}](assets/${articleId}/image-${String(n).padStart(2, "0")})${
          caption ? `\n\n_${caption}_` : ""
        }`,
      );
    }
  }

  return { mdParts, images };
}

export function parseHeader(html, listItem = {}) {
  const title =
    firstMatch(html, /<title>(.*?)\s*:\s*네이버 블로그<\/title>/is) ||
    metaProperty(html, "og:title") ||
    decodeHtml(listItem.titleWithInspectMessage || listItem.title || "Untitled");
  const author =
    firstMatch(html, /<strong class="ell">([\s\S]*?)<\/strong>/is) ||
    metaProperty(html, "naverblog:nickname") ||
    listItem.nickName ||
    "";
  const publishedAtText = firstMatch(html, /<p class="blog_date">\s*([\s\S]*?)\s*<\/p>/i).replace(/\s+/g, " ");
  const category = firstMatch(html, /<div class="blog_category">\s*<a[^>]*>([\s\S]*?)<\/a>/is);
  return { title, author, publishedAtText, category };
}
