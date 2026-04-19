// Transcript Page — Layer 3: Timeline + Keyword highlight + Summary
const MOCK_TRANSCRIPT = [
  { time: '00:00', speaker: '主持人', speakerEn: 'Host', text: '歡迎收聽台積電時代，我是陳文茜。今天我們要深度解析一個在 AI 浪潮中越來越關鍵的技術：CoWoS 先進封裝。' },
  { time: '01:23', speaker: '主持人', speakerEn: 'Host', text: '在開始之前，我想先讓聽眾朋友們了解一個背景：為什麼封裝技術突然變得這麼重要？這其實和摩爾定律走到盡頭有關。' },
  { time: '03:45', speaker: '來賓', speakerEn: 'Guest', text: '是的，當我們無法再靠縮小電晶體來提升效能，封裝就成了下一個戰場。台積電的 CoWoS 技術，簡單說就是把多個晶片像堆積木一樣疊在一起，讓它們能高速溝通。' },
  { time: '06:12', speaker: '來賓', speakerEn: 'Guest', text: '輝達的 H100 和 H200，每一顆都需要台積電的 CoWoS 封裝才能把 GPU 和 HBM 記憶體整合在一起。這就是為什麼輝達的產能完全受制於台積電的 CoWoS 產線。' },
  { time: '09:33', speaker: '主持人', speakerEn: 'Host', text: '所以我們可以說，台積電不只是晶圓代工廠，在 AI 晶片這個領域，它實際上是整個供應鏈的咽喉要道？' },
  { time: '11:05', speaker: '來賓', speakerEn: 'Guest', text: '這個描述非常準確。而且更重要的是，CoWoS 的技術壁壘非常高。三星嘗試了很多年，良率始終追不上台積電。這不是設備問題，而是製程Know-how的長期積累。' },
  { time: '14:28', speaker: '來賓', speakerEn: 'Guest', text: '台積電內部有一個說法：CoWoS 的良率秘密藏在幾十個製程參數的精細調控之中，這些都是台積電花了二十年建立起來的護城河。' },
  { time: '17:50', speaker: '主持人', speakerEn: 'Host', text: '那英特爾的 EMIB 技術和台積電的 CoWoS 差距大概在哪裡？外界很多人說英特爾其實也有不錯的封裝技術。' },
  { time: '19:22', speaker: '來賓', speakerEn: 'Guest', text: '英特爾的 EMIB 確實不差，但問題在於規模和客戶群。台積電 CoWoS 已經有輝達、AMD、博通、Marvell 等大量客戶，生態系完整，而且每年產能在快速擴張。' },
  { time: '23:10', speaker: '主持人', speakerEn: 'Host', text: '我們來談台積電在亞利桑那的 CoWoS 產能。之前報導說良率有問題，這會不會影響輝達的出貨？' },
  { time: '25:44', speaker: '來賓', speakerEn: 'Guest', text: '亞利桑那廠的 CoWoS 良率確實低於台灣，目前大概只有台灣的七到八成。主要原因是工程師在台灣訓練的經驗還沒有完全移轉，以及環境控制方面的差異。' },
  { time: '30:15', speaker: '來賓', speakerEn: 'Guest', text: '但台積電不會讓這個問題持續太久。他們有一套嚴格的製程轉移協議，預計在 2026 年底前，亞利桑那廠的 CoWoS 良率應該可以追到台灣廠的九成以上。' },
  { time: '34:02', speaker: '主持人', speakerEn: 'Host', text: '最後一個問題：對於投資人來說，台積電的 CoWoS 業務未來幾年的成長曲線會是什麼樣子？' },
  { time: '35:30', speaker: '來賓', speakerEn: 'Guest', text: '我認為 CoWoS 相關業務在 2026 到 2028 年會是台積電成長最快的部門之一。需求端完全由 AI 訓練和推論驅動，而供給端台積電正在桃園、高雄大規模擴廠。年複合成長率估計在 40% 以上。' },
  { time: '40:18', speaker: '主持人', speakerEn: 'Host', text: '非常感謝今天的深度分享。這一集的重點是：CoWoS 不只是封裝技術，它是台積電在 AI 時代最重要的競爭武器，也是輝達產能的天花板。下集見。' },
];

const TranscriptPage = ({ lang, show, episode, onBack, initSearch }) => {
  const t = lang === 'zh';
  const [search, setSearch] = React.useState(initSearch || '');
  const [activeTime, setActiveTime] = React.useState(null);
  const [showSummary, setShowSummary] = React.useState(true);
  const listRef = React.useRef(null);

  const highlight = (text) => {
    if (!search.trim()) return text;
    const parts = text.split(new RegExp(`(${search.trim()})`, 'gi'));
    return parts.map((p, i) =>
      p.toLowerCase() === search.trim().toLowerCase()
        ? <mark key={i} style={{ background: '#fbbf24aa', color: '#fef3c7', borderRadius: 3, padding: '0 2px' }}>{p}</mark>
        : p
    );
  };

  const matchCount = search.trim()
    ? MOCK_TRANSCRIPT.filter(s => s.text.toLowerCase().includes(search.trim().toLowerCase())).length
    : 0;

  const timeToSec = t => {
    const [m, s] = t.split(':').map(Number);
    return m * 60 + s;
  };
  const totalSec = timeToSec('40:18') + 90;
  const pct = activeTime ? (timeToSec(activeTime) / totalSec) * 100 : 0;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: TOKEN.bg }}>
      {/* Top bar */}
      <div style={{ padding: '14px 32px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Btn variant="ghost" size="sm" icon="arrowLeft" onClick={onBack}>{t ? '返回查詢' : 'Back'}</Btn>
        <div style={{ width: 1, height: 20, background: TOKEN.surfaceBorder }} />
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14 }}>EP{episode.num} · {t ? episode.title : episode.titleEn}</div>
          <div style={{ display: 'flex', gap: 12, marginTop: 3, fontSize: 12, color: TOKEN.textMuted }}>
            <span>{episode.date}</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}><Icon name="clock" size={11} />{episode.duration}</span>
          </div>
        </div>
        {/* Search bar */}
        <div style={{ width: 260 }}>
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={t ? '關鍵字高亮搜尋...' : 'Highlight keywords...'} icon="search" />
        </div>
        {search && <span style={{ fontSize: 12, color: TOKEN.textMuted, whiteSpace: 'nowrap' }}>{matchCount} {t ? '個匹配' : 'matches'}</span>}
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Summary + Timeline bar */}
        <div style={{ width: 280, borderRight: `1px solid ${TOKEN.surfaceBorder}`, display: 'flex', flexDirection: 'column', overflowY: 'auto', flexShrink: 0 }}>
          {/* Summary */}
          <div style={{ padding: '16px 16px 0' }}>
            <button onClick={() => setShowSummary(v => !v)} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', color: TOKEN.textSecondary, cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: 0, marginBottom: 10, fontFamily: 'inherit' }}>
              <Icon name="fileText" size={14} /> {t ? '本集摘要' : 'Summary'} <Icon name={showSummary ? 'chevronLeft' : 'chevronRight'} size={13} style={{ transform: showSummary ? 'rotate(-90deg)' : 'rotate(90deg)', transition: 'transform 0.15s' }} />
            </button>
            {showSummary && (
              <div style={{ background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10, padding: 14, marginBottom: 16 }}>
                <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 12.5, lineHeight: 1.7 }}>
                  {t ? episode.summary : episode.summaryEn}
                </p>
              </div>
            )}
          </div>

          {/* Timeline */}
          <div style={{ padding: '0 16px 16px' }}>
            <div style={{ fontSize: 12, color: TOKEN.textSecondary, fontWeight: 600, marginBottom: 10 }}>{t ? '時間軸' : 'Timeline'}</div>
            {/* Progress bar */}
            <div style={{ position: 'relative', height: 4, background: TOKEN.surfaceBorder, borderRadius: 99, marginBottom: 14, cursor: 'pointer' }}>
              {MOCK_TRANSCRIPT.map((seg, i) => (
                <div key={i} title={seg.time} onClick={() => setActiveTime(seg.time)}
                  style={{ position: 'absolute', top: -4, width: 12, height: 12, borderRadius: '50%', background: activeTime === seg.time ? TOKEN.accent : TOKEN.surfaceBorder, border: `2px solid ${activeTime === seg.time ? TOKEN.accent : TOKEN.textMuted}`, left: `${(timeToSec(seg.time) / totalSec) * 100}%`, transform: 'translateX(-50%)', cursor: 'pointer', transition: 'all 0.12s', zIndex: 1 }} />
              ))}
              <div style={{ height: '100%', width: `${pct}%`, background: TOKEN.accent, borderRadius: 99 }} />
            </div>
            {/* Segment list */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {MOCK_TRANSCRIPT.map((seg, i) => {
                const matched = search && seg.text.toLowerCase().includes(search.toLowerCase());
                return (
                  <div key={i} onClick={() => setActiveTime(seg.time)}
                    style={{ display: 'flex', gap: 8, padding: '6px 8px', borderRadius: 7, cursor: 'pointer', background: activeTime === seg.time ? TOKEN.accentDim : matched ? '#fbbf2422' : 'transparent', border: `1px solid ${activeTime === seg.time ? TOKEN.accent + '44' : matched ? '#fbbf2444' : 'transparent'}`, transition: 'all 0.1s' }}>
                    <span style={{ color: TOKEN.accent, fontSize: 11, fontFamily: 'monospace', minWidth: 38, paddingTop: 1 }}>{seg.time}</span>
                    <span style={{ color: TOKEN.textSecondary, fontSize: 11, lineHeight: 1.4 }}>
                      {t ? seg.speaker : seg.speakerEn}
                      {matched && <span style={{ marginLeft: 4 }}><Badge variant="warning">●</Badge></span>}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right: Full transcript */}
        <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: '20px 32px' }}>
          <div style={{ maxWidth: 720, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 0 }}>
            {MOCK_TRANSCRIPT.map((seg, i) => {
              const matched = search.trim() && seg.text.toLowerCase().includes(search.trim().toLowerCase());
              const active = activeTime === seg.time;
              return (
                <div key={i} id={`seg-${i}`}
                  style={{ display: 'flex', gap: 20, padding: '16px 14px', borderRadius: 10, background: active ? TOKEN.accentDim : matched ? '#fbbf2411' : 'transparent', border: `1px solid ${active ? TOKEN.accent + '44' : matched ? '#fbbf2433' : 'transparent'}`, marginBottom: 4, transition: 'all 0.15s', cursor: 'pointer' }}
                  onClick={() => setActiveTime(seg.time)}>
                  {/* Left column: time + speaker */}
                  <div style={{ minWidth: 80, textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ color: TOKEN.accent, fontSize: 12, fontFamily: 'monospace', fontWeight: 600 }}>{seg.time}</div>
                    <div style={{ color: TOKEN.textMuted, fontSize: 11, marginTop: 3 }}>{t ? seg.speaker : seg.speakerEn}</div>
                  </div>
                  {/* Divider */}
                  <div style={{ width: 1, background: active ? TOKEN.accent + '55' : TOKEN.surfaceBorder, flexShrink: 0, borderRadius: 99 }} />
                  {/* Text */}
                  <p style={{ margin: 0, color: active ? TOKEN.text : TOKEN.textSecondary, fontSize: 14, lineHeight: 1.8, flex: 1 }}>
                    {highlight(seg.text)}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { TranscriptPage, MOCK_TRANSCRIPT });
