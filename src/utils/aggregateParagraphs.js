// aggregateParagraphs — client-side segment → paragraph aggregation.
//
// Pure function shared by TranscriptPage and SourceCard so paragraph cuts
// are identical in both contexts (decision 7 in
// landing-and-mode-orchestration-redesign/design.md).
//
// Rules (per design decision 7 + landing-redesign-hotfix-transcript-and-audio D1):
//   - Adjacent segments are merged into the same paragraph by default.
//   - A new paragraph starts when (first-match-wins, evaluated in order):
//       (a) start_time(next) - end_time(prev) >= gap_threshold_seconds (default 1.5s)
//       (b) speaker field changes between adjacent segments (both non-null)
//       (c) cumulative paragraph duration >= max_paragraph_seconds (default 45s, hard ceiling)
//       (d) current paragraph_text ends in [。！？.!?] AND duration >= min_paragraph_seconds (default 15s)
//   - (c) + (d) added to handle Whisper word-level ASR output that has no
//     speaker labels and gap=0 between every segment (would otherwise collapse
//     an 80-minute episode into a single paragraph).
//   - Empty / null input returns [].
//   - Missing end_time falls back to start_time (defensive; never throws).
//
// Output paragraph shape:
//   { paragraph_text, start_time, end_time, speaker, segment_ids: string[] }
//
// Exported via window.aggregateParagraphs so it can be consumed from any
// JSX file (project loads as raw script tags, no module system).

(function () {
  function aggregateParagraphs(segments, opts) {
    if (!Array.isArray(segments) || segments.length === 0) return [];
    const gapThreshold = (opts && typeof opts.gap_threshold_seconds === 'number')
      ? opts.gap_threshold_seconds
      : 1.5;
    const maxParagraphSec = (opts && typeof opts.max_paragraph_seconds === 'number')
      ? opts.max_paragraph_seconds
      : 45;
    const minParagraphSec = (opts && typeof opts.min_paragraph_seconds === 'number')
      ? opts.min_paragraph_seconds
      : 15;
    const SENTENCE_END_RE = /[。！？.!?]$/;

    const paragraphs = [];
    let cur = null;

    const flush = () => {
      if (cur) {
        paragraphs.push(cur);
        cur = null;
      }
    };

    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i] || {};
      const text = (seg.text == null ? '' : String(seg.text));
      const start = typeof seg.start_time === 'number' ? seg.start_time : null;
      const end = typeof seg.end_time === 'number' ? seg.end_time : start;
      const speaker = seg.speaker == null ? null : seg.speaker;
      const segId = seg.id != null ? String(seg.id) : String(i);

      if (!cur) {
        cur = {
          paragraph_text: text,
          start_time: start,
          end_time: end,
          speaker,
          segment_ids: [segId],
        };
        continue;
      }

      const prevEnd = cur.end_time != null ? cur.end_time : cur.start_time;
      const gap = (start != null && prevEnd != null) ? (start - prevEnd) : 0;
      const speakerChanged = (cur.speaker != null && speaker != null && cur.speaker !== speaker);
      const curDuration = (cur.end_time != null && cur.start_time != null)
        ? (cur.end_time - cur.start_time)
        : 0;
      const exceedsMax = curDuration >= maxParagraphSec;
      const sentenceEndSplit = SENTENCE_END_RE.test(cur.paragraph_text) && curDuration >= minParagraphSec;

      if ((gap != null && gap >= gapThreshold) || speakerChanged || exceedsMax || sentenceEndSplit) {
        flush();
        cur = {
          paragraph_text: text,
          start_time: start,
          end_time: end,
          speaker,
          segment_ids: [segId],
        };
      } else {
        // Append. Insert a single space only when the previous text does
        // not end with whitespace AND neither side is CJK (which has no
        // word boundaries).
        const prevTail = cur.paragraph_text.slice(-1);
        const isCjkBoundary = /[　-鿿]/.test(prevTail) || /[　-鿿]/.test(text.charAt(0));
        const needsSpace = prevTail && !/\s/.test(prevTail) && !isCjkBoundary;
        cur.paragraph_text = needsSpace ? cur.paragraph_text + ' ' + text : cur.paragraph_text + text;
        if (end != null) cur.end_time = end;
        cur.segment_ids.push(segId);
        // If the existing paragraph had no speaker but this seg has one,
        // adopt it (defensive — most inputs are uniform).
        if (cur.speaker == null && speaker != null) cur.speaker = speaker;
      }
    }
    flush();
    return paragraphs;
  }

  // Make available to React components (no module system in browser build).
  if (typeof window !== 'undefined') {
    window.aggregateParagraphs = aggregateParagraphs;
  }
  // Node smoke-test friendly export.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = aggregateParagraphs;
  }
})();
