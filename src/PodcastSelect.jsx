// Podcast Selection Page — Layer 1
const MOCK_SHOWS = [
  {
    id: 'tsmc-era',
    name: '台積電時代',
    nameEn: 'TSMC Era',
    host: '陳文茜',
    hostEn: 'Chen Wenxi',
    desc: '深度解析半導體產業趨勢與台積電的全球布局策略。',
    descEn: 'Deep dives into semiconductor trends and TSMC\'s global strategy.',
    episodes: 142,
    transcribed: 138,
    lastUpdate: '2026-04-18',
    rss: 'https://feeds.example.com/tsmc-era',
    cover: null,
    tags: ['科技', '財經'],
    tagsEn: ['Tech', 'Finance'],
    color: '#6366f1',
  },
  {
    id: 'ai-frontiers',
    name: 'AI 前沿報告',
    nameEn: 'AI Frontiers',
    host: '李開復 & 王慧文',
    hostEn: 'Kai-Fu Lee & Wang Huiwen',
    desc: '每週追蹤最新 AI 研究突破，邀請業界領袖深度對談。',
    descEn: 'Weekly tracking of AI research breakthroughs with industry leaders.',
    episodes: 89,
    transcribed: 89,
    lastUpdate: '2026-04-17',
    rss: 'https://feeds.example.com/ai-frontiers',
    cover: null,
    tags: ['AI', '研究'],
    tagsEn: ['AI', 'Research'],
    color: '#22d3ee',
  },
  {
    id: 'startup-island',
    name: '創業島嶼',
    nameEn: 'Startup Island',
    host: '鄭志凱',
    hostEn: 'Chih-Kai Cheng',
    desc: '台灣新創生態系的真實故事：失敗、轉型與成功的第一手紀錄。',
    descEn: 'Real stories from Taiwan\'s startup ecosystem — failures, pivots, and wins.',
    episodes: 210,
    transcribed: 195,
    lastUpdate: '2026-04-15',
    rss: 'https://feeds.example.com/startup-island',
    cover: null,
    tags: ['創業', '商業'],
    tagsEn: ['Startup', 'Business'],
    color: '#f59e0b',
  },
  {
    id: 'deep-science',
    name: '深科學',
    nameEn: 'Deep Science',
    host: '寒波',
    hostEn: 'Han Bo',
    desc: '把最艱深的科學論文，轉化成你聽得懂的中文故事。',
    descEn: 'Translating the most complex scientific papers into understandable stories.',
    episodes: 67,
    transcribed: 40,
    lastUpdate: '2026-04-10',
    rss: 'https://feeds.example.com/deep-science',
    cover: null,
    tags: ['科學', '教育'],
    tagsEn: ['Science', 'Education'],
    color: '#22c55e',
  },
];

const PodcastSelect = ({ lang, onSelect }) => {
  const t = lang === 'zh';
  const [search, setSearch] = React.useState('');
  const [hovered, setHovered] = React.useState(null);

  const filtered = MOCK_SHOWS.filter(s => {
    const q = search.toLowerCase();
    return (s.name + s.nameEn + s.host + s.hostEn + s.desc).toLowerCase().includes(q);
  });

  return (
    <div style={{ flex: 1, overflowY: 'auto', background: TOKEN.bg }}>
      {/* Header */}
      <div style={{ padding: '36px 40px 24px', borderBottom: `1px solid ${TOKEN.surfaceBorder}` }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <p style={{ color: TOKEN.accent, fontSize: 12, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', margin: '0 0 6px' }}>
              {t ? '節目庫' : 'Show Library'}
            </p>
            <h1 style={{ color: TOKEN.text, fontSize: 28, fontWeight: 700, margin: 0, lineHeight: 1.2 }}>
              {t ? '選擇 Podcast 節目' : 'Select a Podcast Show'}
            </h1>
            <p style={{ color: TOKEN.textSecondary, fontSize: 14, margin: '8px 0 0' }}>
              {t ? `共 ${MOCK_SHOWS.length} 個節目，${MOCK_SHOWS.reduce((a,s)=>a+s.transcribed,0)} 集已轉錄完成` : `${MOCK_SHOWS.length} shows, ${MOCK_SHOWS.reduce((a,s)=>a+s.transcribed,0)} episodes transcribed`}
            </p>
          </div>
          <div style={{ width: 280 }}>
            <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={t ? '搜尋節目名稱...' : 'Search shows...'} icon="search" />
          </div>
        </div>
      </div>

      {/* Grid */}
      <div style={{ padding: '28px 40px 40px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 20 }}>
          {filtered.map(show => (
            <ShowCard key={show.id} show={show} lang={lang} hovered={hovered === show.id}
              onMouseEnter={() => setHovered(show.id)} onMouseLeave={() => setHovered(null)}
              onClick={() => onSelect(show)} />
          ))}
        </div>
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: TOKEN.textMuted }}>
            <Icon name="search" size={40} color={TOKEN.textMuted} />
            <p style={{ marginTop: 12 }}>{t ? '找不到符合的節目' : 'No matching shows found'}</p>
          </div>
        )}
      </div>
    </div>
  );
};

const ShowCard = ({ show, lang, hovered, onMouseEnter, onMouseLeave, onClick }) => {
  const t = lang === 'zh';
  const pct = Math.round((show.transcribed / show.episodes) * 100);

  return (
    <div onClick={onClick} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}
      style={{ background: TOKEN.surface, border: `1px solid ${hovered ? show.color + '55' : TOKEN.surfaceBorder}`, borderRadius: 14, padding: 24, cursor: 'pointer', transition: 'all 0.18s', transform: hovered ? 'translateY(-2px)' : 'none', boxShadow: hovered ? `0 8px 30px rgba(0,0,0,0.3), 0 0 0 1px ${show.color}33` : 'none', display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Cover placeholder + tags */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        <div style={{ width: 64, height: 64, borderRadius: 12, background: show.color + '22', border: `1px solid ${show.color}44`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <Icon name="mic" size={28} color={show.color} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: TOKEN.text, fontWeight: 700, fontSize: 16, lineHeight: 1.3, marginBottom: 4 }}>
            {t ? show.name : show.nameEn}
          </div>
          <div style={{ color: TOKEN.textSecondary, fontSize: 13 }}>{t ? show.host : show.hostEn}</div>
          <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
            {(t ? show.tags : show.tagsEn).map(tag => (
              <Badge key={tag} variant="muted">{tag}</Badge>
            ))}
          </div>
        </div>
      </div>

      {/* Desc */}
      <p style={{ color: TOKEN.textSecondary, fontSize: 13, lineHeight: 1.6, margin: 0 }}>
        {t ? show.desc : show.descEn}
      </p>

      {/* Stats */}
      <div style={{ display: 'flex', gap: 16, fontSize: 13 }}>
        <div style={{ color: TOKEN.textSecondary }}>
          <span style={{ color: TOKEN.text, fontWeight: 600 }}>{show.episodes}</span> {t ? '集' : 'eps'}
        </div>
        <div style={{ color: TOKEN.textSecondary }}>
          <span style={{ color: '#4ade80', fontWeight: 600 }}>{show.transcribed}</span> {t ? '已轉錄' : 'transcribed'}
        </div>
        <div style={{ color: TOKEN.textMuted, marginLeft: 'auto', fontSize: 12 }}>
          {t ? '更新' : 'Updated'} {show.lastUpdate}
        </div>
      </div>

      {/* Progress bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: TOKEN.textMuted, marginBottom: 5 }}>
          <span>{t ? '轉錄進度' : 'Transcription'}</span>
          <span style={{ color: pct === 100 ? '#4ade80' : TOKEN.textSecondary, fontWeight: 600 }}>{pct}%</span>
        </div>
        <div style={{ height: 4, background: TOKEN.surfaceBorder, borderRadius: 99, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: pct === 100 ? '#22c55e' : show.color, borderRadius: 99, transition: 'width 0.4s' }} />
        </div>
      </div>

      {/* CTA */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: TOKEN.textMuted }}>
          <Icon name="rss" size={13} color={TOKEN.textMuted} />
          RSS Feed
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: hovered ? show.color : TOKEN.textMuted, fontSize: 13, fontWeight: 500, transition: 'color 0.15s' }}>
          {t ? '進入節目' : 'Open Show'} <Icon name="chevronRight" size={16} color="currentColor" />
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { MOCK_SHOWS, PodcastSelect });
