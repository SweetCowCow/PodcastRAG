// run: node src/utils/aggregateParagraphs.test.js
//
// Fixtures cover:
//   A. No speaker + gap=0 + sentence-end → split via (d)
//   B. Speaker transitions → split via (b)
//   C. No speaker + gap=0 + no sentence end → split via (c) hard ceiling
//   D. Empty / null input → []
//   E. 2512-segment Whisper regression → ≥ 20 paragraphs (was 1 before hotfix)

const assert = require('node:assert/strict');
const aggregateParagraphs = require('./aggregateParagraphs.js');

// Fixture A: 5 segments, all speaker null, gap=0, third ends with 。 at ~30s
{
  const segs = [
    { id: 'a1', start_time: 0,  end_time: 10, speaker: null, text: '嗨大家' },
    { id: 'a2', start_time: 10, end_time: 20, speaker: null, text: '今天聊一下' },
    { id: 'a3', start_time: 20, end_time: 30, speaker: null, text: '一個有趣的主題。' },
    { id: 'a4', start_time: 30, end_time: 45, speaker: null, text: '先從背景講起' },
    { id: 'a5', start_time: 45, end_time: 60, speaker: null, text: '這個故事' },
  ];
  const out = aggregateParagraphs(segs);
  assert.ok(out.length >= 2, `Fixture A: expected ≥ 2 paragraphs, got ${out.length}`);
  // Boundary should fall after the 。-ending segment a3
  const firstPara = out[0];
  assert.ok(firstPara.segment_ids.includes('a3'), `Fixture A: first paragraph SHALL include a3 (sentence-end)`);
  assert.ok(!firstPara.segment_ids.includes('a4'), `Fixture A: split SHALL occur after a3, before a4`);
  console.log(`✓ Fixture A: ${out.length} paragraphs, boundary after sentence-end`);
}

// Fixture B: 3 segments with speaker transitions A → B → A
{
  const segs = [
    { id: 'b1', start_time: 0, end_time: 5,  speaker: 'A', text: '你今天好嗎' },
    { id: 'b2', start_time: 5, end_time: 10, speaker: 'B', text: '我很好' },
    { id: 'b3', start_time: 10, end_time: 15, speaker: 'A', text: '那就好' },
  ];
  const out = aggregateParagraphs(segs);
  assert.equal(out.length, 3, `Fixture B: expected 3 paragraphs, got ${out.length}`);
  for (const p of out) {
    assert.equal(p.segment_ids.length, 1, `Fixture B: each paragraph SHALL have exactly 1 segment`);
  }
  console.log(`✓ Fixture B: 3 paragraphs from speaker transitions`);
}

// Fixture C: 30 segments, 200 seconds total, no speaker, no gap, no sentence end
{
  const segs = [];
  for (let i = 0; i < 30; i++) {
    segs.push({
      id: `c${i}`,
      start_time: i * (200 / 30),
      end_time: (i + 1) * (200 / 30),
      speaker: null,
      text: `片段${i}`,  // no sentence-end punctuation
    });
  }
  const out = aggregateParagraphs(segs);
  assert.ok(out.length >= 4, `Fixture C: expected ≥ 4 paragraphs (200s / 45s ceiling), got ${out.length}`);
  // Each paragraph cumulative duration ≤ maxParagraphSec + one-segment overshoot
  for (const p of out) {
    const dur = p.end_time - p.start_time;
    assert.ok(dur <= 45 + (200 / 30) + 0.01, `Fixture C: paragraph duration ${dur} SHALL be ≤ max + 1 segment`);
  }
  console.log(`✓ Fixture C: ${out.length} paragraphs from max-duration ceiling`);
}

// Fixture D: empty / null / weird input
{
  assert.deepEqual(aggregateParagraphs([]), [], 'Fixture D: [] → []');
  assert.deepEqual(aggregateParagraphs(null), [], 'Fixture D: null → []');
  assert.deepEqual(aggregateParagraphs(undefined), [], 'Fixture D: undefined → []');
  console.log(`✓ Fixture D: empty / null / undefined return []`);
}

// Fixture E: 2512-segment Whisper regression (80 min, all null speaker, gap=0)
{
  const N = 2512;
  const totalSec = 4800;  // 80 min
  const segs = [];
  for (let i = 0; i < N; i++) {
    segs.push({
      id: `e${i}`,
      start_time: i * (totalSec / N),
      end_time: (i + 1) * (totalSec / N),
      speaker: null,
      text: i % 100 === 99 ? '段落結尾。' : '繼續說話',  // sprinkle sentence-ends
    });
  }
  const out = aggregateParagraphs(segs);
  assert.ok(out.length >= 20, `Fixture E (regression): expected ≥ 20 paragraphs for 80-min Whisper input, got ${out.length}`);
  assert.notEqual(out.length, 1, `Fixture E (regression): MUST NOT collapse to single paragraph`);
  console.log(`✓ Fixture E (regression): ${out.length} paragraphs from 2512-segment Whisper input`);
}

// Sentence-end below min duration should NOT split (boundary test)
{
  const segs = [
    { id: 'n1', start_time: 0, end_time: 3, speaker: null, text: '對。' },
    { id: 'n2', start_time: 3, end_time: 8, speaker: null, text: '然後呢' },
  ];
  const out = aggregateParagraphs(segs, { min_paragraph_seconds: 15 });
  assert.equal(out.length, 1, `Sentence-end below min duration SHALL NOT split: got ${out.length}`);
  console.log(`✓ Sentence-end below min_paragraph_seconds SHALL NOT split`);
}

console.log('\nAll fixtures passed ✓');
