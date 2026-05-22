// StickyAudioPlayer — landing-and-mode-orchestration-redesign decision 6.
//
// Single <audio> element mounted ONCE outside the router so audio survives
// page transitions (QueryPage ↔ TranscriptPage). All callers go through
// AudioPlayerContext.
//
// Public context shape (also documented in design.md Interfaces):
//   {
//     currentEpisodeId, currentTime, isPlaying, speed, episodeMeta,
//     playFromTime(episodeId, startSec, meta?),
//     pause(), seek(sec), setSpeed(num),
//   }
//
// Speed values restricted to 1.0 / 1.25 / 1.5 (decision 6 + task 8.3),
// persisted to localStorage['audio_speed'].

const _SPEED_VALUES = [1.0, 1.25, 1.5];
const _SPEED_LS_KEY = 'audio_speed';

const _readPersistedSpeed = () => {
  try {
    const raw = window.localStorage.getItem(_SPEED_LS_KEY);
    const n = parseFloat(raw);
    if (_SPEED_VALUES.indexOf(n) !== -1) return n;
  } catch (_) { /* ignore */ }
  return 1.0;
};

const AudioPlayerContext = React.createContext({
  currentEpisodeId: null,
  currentTime: 0,
  isPlaying: false,
  speed: 1.0,
  episodeMeta: null,
  playFromTime: () => {},
  pause: () => {},
  seek: () => {},
  setSpeed: () => {},
});

const useAudioPlayer = () => React.useContext(AudioPlayerContext);

const AudioPlayerProvider = ({ children }) => {
  const audioRef = React.useRef(null);
  const [currentEpisodeId, setCurrentEpisodeId] = React.useState(null);
  const [episodeMeta, setEpisodeMeta] = React.useState(null);  // { title, audio_url, show_title }
  const [currentTime, setCurrentTime] = React.useState(0);
  const [isPlaying, setIsPlaying] = React.useState(false);
  const [speed, setSpeedState] = React.useState(_readPersistedSpeed);

  // Push speed onto <audio> whenever it changes.
  React.useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = speed;
    try { window.localStorage.setItem(_SPEED_LS_KEY, String(speed)); } catch (_) { /* ignore */ }
  }, [speed]);

  const playFromTime = React.useCallback(async (episodeId, startSec, meta) => {
    if (!audioRef.current) return;
    if (!episodeId) return;
    const audio = audioRef.current;
    const sec = (typeof startSec === 'number' && startSec >= 0) ? startSec : 0;
    // If different episode, need to load audio_url. Caller MUST pass meta with
    // audio_url for first play of an episode; subsequent plays of same ep can
    // skip meta (we reuse cached src).
    if (currentEpisodeId !== episodeId) {
      if (meta && meta.audio_url) {
        audio.src = meta.audio_url;
        setEpisodeMeta(meta);
        setCurrentEpisodeId(episodeId);
      } else {
        // No audio_url available — fail silently (callers without an audio
        // source shouldn't try to play; they get a no-op).
        return;
      }
    }
    try {
      audio.currentTime = sec;
      audio.playbackRate = speed;
      await audio.play();
    } catch (_) {
      // Autoplay blocked / network error — swallow; user can click play in
      // the visible audio controls.
    }
  }, [currentEpisodeId, speed]);

  const pause = React.useCallback(() => {
    if (audioRef.current) audioRef.current.pause();
  }, []);

  const seek = React.useCallback((sec) => {
    if (audioRef.current && typeof sec === 'number' && sec >= 0) {
      audioRef.current.currentTime = sec;
    }
  }, []);

  const setSpeed = React.useCallback((nextOrCycle) => {
    // Two call modes:
    //   setSpeed(1.25)  → set exactly that value (no-op if not in allowed set)
    //   setSpeed()      → cycle to next allowed value
    setSpeedState(cur => {
      if (typeof nextOrCycle === 'number') {
        return _SPEED_VALUES.indexOf(nextOrCycle) !== -1 ? nextOrCycle : cur;
      }
      const idx = _SPEED_VALUES.indexOf(cur);
      return _SPEED_VALUES[(idx + 1) % _SPEED_VALUES.length];
    });
  }, []);

  // Wire audio element events.
  React.useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onTime = () => setCurrentTime(a.currentTime);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnded = () => setIsPlaying(false);
    a.addEventListener('timeupdate', onTime);
    a.addEventListener('play', onPlay);
    a.addEventListener('pause', onPause);
    a.addEventListener('ended', onEnded);
    return () => {
      a.removeEventListener('timeupdate', onTime);
      a.removeEventListener('play', onPlay);
      a.removeEventListener('pause', onPause);
      a.removeEventListener('ended', onEnded);
    };
  }, []);

  const ctxValue = {
    currentEpisodeId,
    currentTime,
    isPlaying,
    speed,
    episodeMeta,
    playFromTime,
    pause,
    seek,
    setSpeed,
  };

  return (
    <AudioPlayerContext.Provider value={ctxValue}>
      {/* The <audio> tag stays mounted regardless of episode state; visible
          control bar only appears once an episode has been loaded (decision 6
          risk-mitigation: avoid empty audio strip on first paint). */}
      <audio ref={audioRef} preload="metadata" style={{ display: 'none' }} />
      {children}
      <StickyAudioBar />
    </AudioPlayerContext.Provider>
  );
};

// Visible bottom-fixed control bar. Hidden when no episode loaded yet.
const StickyAudioBar = () => {
  const { currentEpisodeId, episodeMeta, currentTime, isPlaying, speed, pause, setSpeed } = useAudioPlayer();
  if (!currentEpisodeId) return null;
  const audio = document.querySelector('audio');  // we own the only <audio>
  const handlePlayPause = () => {
    if (!audio) return;
    if (isPlaying) audio.pause(); else audio.play().catch(() => {});
  };
  const fmt = (sec) => {
    if (typeof sec !== 'number' || !Number.isFinite(sec)) return '--:--';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };
  return (
    <div
      data-testid="sticky-audio-bar"
      style={{
        position: 'fixed',
        left: 0, right: 0, bottom: 0,
        zIndex: 90,
        background: TOKEN.surfaceRaised,
        borderTop: `1px solid ${TOKEN.surfaceBorder}`,
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        boxShadow: '0 -4px 16px rgba(0,0,0,0.3)',
      }}
    >
      <button
        type="button"
        onClick={handlePlayPause}
        aria-label={isPlaying ? 'Pause' : 'Play'}
        style={{
          width: 36, height: 36, borderRadius: 8,
          background: TOKEN.accent, color: '#fff',
          border: 'none', cursor: 'pointer', fontSize: 14, fontWeight: 700,
        }}
      >
        {isPlaying ? '⏸' : '▶'}
      </button>
      <div style={{ flex: 1, minWidth: 0, color: TOKEN.text, fontSize: 13 }}>
        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {(episodeMeta && episodeMeta.title) || ''}
        </div>
        <div style={{ color: TOKEN.textMuted, fontSize: 11, fontFamily: 'monospace' }}>
          {fmt(currentTime)}
        </div>
      </div>
      <button
        type="button"
        onClick={() => setSpeed()}
        data-testid="sticky-audio-speed"
        style={{
          padding: '6px 12px',
          borderRadius: 6,
          background: TOKEN.surface,
          border: `1px solid ${TOKEN.surfaceBorder}`,
          color: TOKEN.text,
          cursor: 'pointer',
          fontSize: 12, fontFamily: 'monospace',
        }}
      >
        {speed.toFixed(2)}x
      </button>
    </div>
  );
};

Object.assign(window, {
  AudioPlayerContext,
  AudioPlayerProvider,
  StickyAudioBar,
  useAudioPlayer,
});
