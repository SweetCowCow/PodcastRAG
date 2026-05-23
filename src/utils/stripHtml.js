// stripHtml — plain-text sanitizer.
//
// Purpose: convert RSS-feed-style HTML (used in show / episode description)
// into clean plain text for display.
//
//   stripHtml('<p>嗨<br />世界 &amp; co.</p>')  →  '嗨\n世界 & co.'
//
// IMPORTANT: this is NOT an XSS-safe sanitizer. It strips visible tags so they
// don't leak into UI as literal `<p>` / `<br />` strings, but it MUST NOT be
// used as a guard before `dangerouslySetInnerHTML` or any HTML-injection sink.
// If you need to render rich HTML safely, use DOMPurify or similar.
//
// Behavior:
//   - null / undefined / non-string input → ''
//   - <br>, <br/>, <br /> (any case)      → '\n'
//   - any other <tag ...>                 → removed
//   - HTML entities (named + numeric)     → decoded
//
// Exposed as window.stripHtml so any JSX file can use it without imports
// (project loads files as raw script tags, no module system).

(function () {
  const NAMED_ENTITIES = {
    amp: '&',
    lt: '<',
    gt: '>',
    quot: '"',
    apos: "'",
    nbsp: ' ',
  };

  function decodeEntities(s) {
    return s.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, body) => {
      if (body[0] === '#') {
        const isHex = body[1] === 'x' || body[1] === 'X';
        const code = parseInt(isHex ? body.slice(2) : body.slice(1), isHex ? 16 : 10);
        if (Number.isFinite(code) && code >= 0 && code <= 0x10FFFF) {
          try { return String.fromCodePoint(code); } catch (_) { return match; }
        }
        return match;
      }
      const lower = body.toLowerCase();
      if (NAMED_ENTITIES[lower] != null) return NAMED_ENTITIES[lower];
      // 還有 #39 之類已被上方 branch 處理；其餘未知命名實體保留原樣
      return match;
    });
  }

  function stripHtml(input) {
    if (input == null || typeof input !== 'string') return '';
    let out = input;
    // <br>, <br/>, <br />  → \n (any case)
    out = out.replace(/<br\s*\/?>/gi, '\n');
    // Remove every other tag (including HTML comments and self-closing tags)
    out = out.replace(/<[^>]*>/g, '');
    // Decode entities AFTER tag removal so &lt;script&gt; doesn't get treated as a tag
    out = decodeEntities(out);
    return out;
  }

  if (typeof window !== 'undefined') {
    window.stripHtml = stripHtml;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = stripHtml;
  }
})();
