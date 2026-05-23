// run: node src/utils/stripHtml.test.js

const assert = require('node:assert/strict');
const stripHtml = require('./stripHtml.js');

assert.equal(stripHtml(null), '', 'null → ""');
assert.equal(stripHtml(undefined), '', 'undefined → ""');
assert.equal(stripHtml(42), '', 'non-string → ""');
assert.equal(stripHtml(''), '', 'empty string → ""');

assert.equal(stripHtml('<p>hi<br />world</p>'), 'hi\nworld', '<br /> → \\n + tags stripped');
assert.equal(stripHtml('A<br>B<BR/>C<br />D'), 'A\nB\nC\nD', 'all <br> variants case-insensitive → \\n');

assert.equal(stripHtml('Tom &amp; Jerry'), 'Tom & Jerry', '&amp; → &');
assert.equal(stripHtml('&lt;script&gt;'), '<script>', '&lt; &gt; decoded after tag strip');
assert.equal(stripHtml('It&#39;s fine &#x27;ok&#x27;'), "It's fine 'ok'", 'numeric &#39; / hex &#x27; → \'');
assert.equal(stripHtml('&nbsp;A'), ' A', '&nbsp; → U+00A0 non-breaking space');

assert.equal(stripHtml('<a href="https://x.com" target="_blank">link</a>'), 'link', 'nested <a> stripped');
assert.equal(
  stripHtml('<p>各種生活中的小事隨便聊，<br />合作邀約｜<a href="mailto:x@y">x@y</a></p>'),
  '各種生活中的小事隨便聊，\n合作邀約｜x@y',
  'real RSS-feed shape'
);

assert.equal(stripHtml('<!-- comment --> text'), ' text', 'HTML comment removed');

console.log('All stripHtml tests passed ✓');
