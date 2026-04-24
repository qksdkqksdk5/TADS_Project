/* eslint-disable */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

// ✅ 모바일 감지 훅 (768px 이하)
function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' ? window.innerWidth <= breakpoint : false
  );
  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth <= breakpoint);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, [breakpoint]);
  return isMobile;
}

export default function LandingPage() {
  const navigate = useNavigate();
  const [scrollY, setScrollY] = useState(0);
  const [activeSection, setActiveSection] = useState('home');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false); // ✅ 햄버거 메뉴
  const heroRef = useRef(null);
  const isMobile = useIsMobile(); // ✅

  useEffect(() => {
    const handleScroll = () => setScrollY(window.scrollY);
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // ✅ 모바일 메뉴 열렸을 때 body 스크롤 잠금
  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [mobileMenuOpen]);

  const stats = [
    { value: '94.2%', label: 'mAP @50-95', desc: '탐지 정확도' },
    { value: '0.8초', label: '감지 지연율', desc: '실시간 반응' },
    { value: '24/7', label: '운영 시간', desc: '무중단 모니터링' },
    { value: '4개+', label: '감지 모듈', desc: '통합 분석 엔진' },
  ];

  const features = [
    {
      icon: '📡',
      title: 'CCTV Anomaly Detection',
      desc: '역주행 감지는 YOLOv11과 ByteTrack, FlowMap을 활용하여 차량의 이동 궤적을 분석하여 역주행 여부를 판단합니다. 화재 감지는 YOLOv8로 연속 프레임 검증을 통해 오탐 없는 알람을 생성합니다.',
      tags: ['YOLOv11', 'ByteTrack', 'FlowMap', 'Judge', 'Logger', 'YOLOv8'],
      color: '#ef4444',
    },
    {
      icon: '🚦',
      title: 'Traffic Flow Monitoring',
      desc: '도로의 속도와 밀도를 집계하여 실시간 교통 흐름을 분석합니다. 혼잡 구간과 시간대를 시각화하여 관제 센터에서 효율적인 교통 관리와 사고 예방에 활용할 수 있습니다.',
      tags: ['YOLOv11', 'ByteTrack', 'FlowMap', 'Judge', 'Logger', 'Traffic Analyzer'],
      color: '#f97316',
    },
    {
      icon: (
        <img
          src="/tunnel.jpg"
          alt="Tunnel Icon"
          style={{ width: '20px', height: '20px', verticalAlign: 'middle' }}
        />
      ),
      title: 'Smart Tunnel System',
      desc: '터널 CCTV 영상을 기반으로 YOLO11n 모델을 활용해 차량 객체탐지, 추적, ROI 자동설정, 차선추정, 교통상태 분석, 사고탐지, 센서리스 기반 환기대응지원을 통합 수행하는 스마트 터널 관제 시스템입니다. 실시간 영상 분석 결과를 웹 대시보드에 시각화하여 운영자가 터널 내 교통흐름과 위험상황을 직관적으로 모니터링할 수 있도록 지원합니다.',
      tags: ['YOLO11n', 'ByteTrack', 'ROI Estimation', 'Lane Estimation', 'State Logic', 'Accident Logic', 'Ventilation Logic'],
      color: '#10b981',
    },
    {
      icon: '🖥️',
      title: 'Raspberry Pi CCTV',
      desc: 'Raspberry Pi와 3D Printer로 제작한 저비용 DIY CCTV로, 침입자 및 화재를 실시간으로 자동 추적(Pan/Tilt)하고 녹화하는 시스템입니다.',
      tags: ['Raspberry Pi', '3D Printing', 'Pan/Tilt', 'Auto-Tracking'],
      color: '#22c55e',
    },
    {
      icon: '🔍',
      title: 'Auto License Plate Recognition',
      desc: 'YOLOv11으로 번호판을 탐지한 후, Custom-OCR 모델로 글자를 인식합니다. Vote 알고리즘으로 여러 프레임의 결과를 종합하여 최종 번호판을 결정하여 오인식률을 대폭 줄였습니다.',
      tags: ['YOLOv11', 'Custom-OCR', 'Vote', 'preprocessing'],
      color: '#6366f1',
    },
    {
      icon: '📊',
      title: 'Statistics & Reports',
      desc: '교통 이상 징후 이벤트를 실시간으로 집계하여 대시보드에 시각화합니다. 시간대별, 위치별 분석을 통해 관제 센터에서 데이터 기반 의사결정을 지원하는 통계 모듈입니다.',
      tags: ['Data Aggregation', 'Chart.js', 'Dashboard', 'Report Generation'],
      color: '#3b82f6',
    },
  ];

  const techStack = [
    { category: 'AI / ML',   items: ['YOLOv8', 'YOLOv11', 'ByteTrack', 'OpenVINO', 'CustomOCR', 'FlowMap'] },
    { category: 'Backend',   items: ['Flask', 'Socket.IO', 'MySQL', 'SQLAlchemy', 'Gevent'] },
    { category: 'Frontend',  items: ['React', 'Vite', 'Kakao Maps', 'Chart.js', 'Hls.js'] },
    { category: 'Infra',     items: ['Docker', 'AWS EC2', 'RDS', 'Nginx', 'GitHub Actions'] },
  ];

  const scrollTo = (id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
    setMobileMenuOpen(false);
  };

  return (
    <div style={styles.root}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@300;400;500;600&display=swap');

        * { box-sizing: border-box; margin: 0; padding: 0; }

        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(24px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.5; transform: scale(1.3); }
        }
        @keyframes scanline {
          0%   { top: -10%; }
          100% { top: 110%; }
        }
        @keyframes float {
          0%, 100% { transform: translateY(0px); }
          50%       { transform: translateY(-8px); }
        }
        @keyframes grid-fade {
          from { opacity: 0; }
          to   { opacity: 0.15; }
        }

        .fade-up { animation: fadeUp 0.7s ease both; }
        .fade-up-1 { animation-delay: 0.1s; }
        .fade-up-2 { animation-delay: 0.25s; }
        .fade-up-3 { animation-delay: 0.4s; }
        .fade-up-4 { animation-delay: 0.55s; }

        .feature-card {
          background: rgba(15,23,42,0.6);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 16px;
          padding: 28px;
          transition: all 0.3s ease;
          cursor: default;
          position: relative;
          overflow: hidden;
        }
        .feature-card::before {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(135deg, rgba(99,102,241,0.05), transparent);
          opacity: 0;
          transition: opacity 0.3s;
        }
        .feature-card:hover {
          border-color: rgba(99,102,241,0.3);
          transform: translateY(-4px);
          box-shadow: 0 20px 40px rgba(0,0,0,0.4);
        }
        .feature-card:hover::before { opacity: 1; }

        .stat-card {
          background: rgba(15,23,42,0.5);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 12px;
          padding: 24px;
          text-align: center;
          transition: all 0.3s;
        }
        .stat-card:hover {
          border-color: rgba(99,102,241,0.4);
          background: rgba(99,102,241,0.05);
        }

        .nav-link {
          color: rgba(255,255,255,0.6);
          text-decoration: none;
          font-size: 14px;
          font-weight: 500;
          transition: color 0.2s;
          cursor: pointer;
        }
        .nav-link:hover { color: #fff; }

        .btn-primary {
          background: linear-gradient(135deg, #6366f1, #4f46e5);
          color: white;
          border: none;
          padding: 14px 32px;
          border-radius: 10px;
          font-size: 14px;
          font-weight: 700;
          letter-spacing: 0.5px;
          cursor: pointer;
          transition: all 0.2s;
          font-family: 'Space Grotesk', sans-serif;
        }
        .btn-primary:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(99,102,241,0.4);
        }
        .btn-primary:active { transform: translateY(0); }

        .btn-ghost {
          background: transparent;
          color: rgba(255,255,255,0.7);
          border: 1px solid rgba(255,255,255,0.15);
          padding: 14px 32px;
          border-radius: 10px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
          font-family: 'Space Grotesk', sans-serif;
        }
        .btn-ghost:hover {
          border-color: rgba(255,255,255,0.4);
          color: white;
          background: rgba(255,255,255,0.05);
        }

        .tag {
          display: inline-block;
          background: rgba(99,102,241,0.12);
          color: #818cf8;
          border: 1px solid rgba(99,102,241,0.2);
          border-radius: 4px;
          padding: 3px 8px;
          font-size: 11px;
          font-family: 'IBM Plex Mono', monospace;
          font-weight: 500;
          margin: 2px;
        }

        .grid-bg {
          position: absolute;
          inset: 0;
          background-image:
            linear-gradient(rgba(99,102,241,0.08) 1px, transparent 1px),
            linear-gradient(90deg, rgba(99,102,241,0.08) 1px, transparent 1px);
          background-size: 48px 48px;
          animation: grid-fade 1.5s ease both;
        }

        /* ✅ 햄버거 버튼 */
        .hamburger {
          display: none;
          flex-direction: column;
          gap: 5px;
          cursor: pointer;
          padding: 4px;
          background: none;
          border: none;
        }
        .hamburger span {
          display: block;
          width: 22px;
          height: 2px;
          background: rgba(255,255,255,0.7);
          border-radius: 2px;
          transition: all 0.2s;
        }

        /* ✅ 모바일 오버레이 메뉴 */
        .mobile-menu {
          display: none;
          position: fixed;
          inset: 0;
          z-index: 200;
          background: rgba(2,6,23,0.97);
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 36px;
        }
        .mobile-menu.open { display: flex; }
        .mobile-menu .nav-link { font-size: 22px; font-weight: 600; }

        /* ✅ 반응형 미디어쿼리 */
        @media (max-width: 768px) {
          .hamburger { display: flex !important; }
          .desktop-nav { display: none !important; }
          .desktop-login { display: none !important; }
          .hero-br { display: none; }
        }
      `}</style>

      {/* ── NAV ── */}
      <nav style={styles.nav}>
        <div style={styles.navInner}>
          {/* 로고 */}
          <div style={styles.logo} onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
            <div style={styles.logoDot} />
            <span style={styles.logoText}>TADS</span>
            <span style={styles.logoBadge}>v1.0</span>
          </div>

          {/* 데스크톱 메뉴 */}
          <div className="desktop-nav" style={styles.navLinks}>
            <span className="nav-link" onClick={() => scrollTo('features')}>기능</span>
            <span className="nav-link" onClick={() => scrollTo('tech')}>기술</span>
            <span className="nav-link" onClick={() => scrollTo('about')}>소개</span>
          </div>
          <button
            className="btn-primary desktop-login"
            onClick={() => navigate('/login')}
            style={{ padding: '10px 24px', fontSize: '13px' }}
          >
            관리자 로그인 →
          </button>

          {/* ✅ 모바일 햄버거 */}
          <button className="hamburger" onClick={() => setMobileMenuOpen(true)} aria-label="메뉴 열기">
            <span /><span /><span />
          </button>
        </div>
      </nav>

      {/* ✅ 모바일 풀스크린 메뉴 */}
      <div className={`mobile-menu${mobileMenuOpen ? ' open' : ''}`}>
        {/* 닫기 버튼 */}
        <button
          onClick={() => setMobileMenuOpen(false)}
          style={{ position: 'absolute', top: '20px', right: '24px', background: 'none', border: 'none', color: 'rgba(255,255,255,0.5)', fontSize: '28px', cursor: 'pointer' }}
          aria-label="메뉴 닫기"
        >
          ✕
        </button>
        <span className="nav-link" onClick={() => scrollTo('features')}>기능</span>
        <span className="nav-link" onClick={() => scrollTo('tech')}>기술</span>
        <span className="nav-link" onClick={() => scrollTo('about')}>소개</span>
        <button
          className="btn-primary"
          onClick={() => { navigate('/login'); setMobileMenuOpen(false); }}
          style={{ padding: '14px 40px', fontSize: '16px', marginTop: '8px' }}
        >
          관리자 로그인 →
        </button>
      </div>

      {/* ── HERO ── */}
      <section ref={heroRef} style={styles.hero}>
        <div className="grid-bg" />
        <div style={styles.heroBg1} />
        <div style={styles.heroBg2} />

        <div style={styles.heroContent}>
          <div className="fade-up fade-up-1" style={styles.heroBadge}>
            <span style={styles.heroBadgeDot} />
            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '1px' }}>
              {/* ✅ 모바일에서 짧게 */}
              {isMobile ? 'TRAFFIC ANOMALY DETECTION' : 'REAL-TIME TRAFFIC ANOMALY DETECTION SYSTEM'}
            </span>
          </div>

          <h1 className="fade-up fade-up-2" style={styles.heroTitle}>
            TRAFFIC ANOMALY<br className="hero-br" />
            <span style={styles.heroTitleAccent}>DETECTION SYSTEM</span>
          </h1>

          <p className="fade-up fade-up-3" style={styles.heroDesc}>
            딥러닝 기반 실시간 역주행·화재 감지부터 번호판 인식,<br className="hero-br" />
            열화상 CCTV까지 통합된 교통 안전 관제 플랫폼입니다.
          </p>

          {/* ✅ 모바일: 2열, 데스크톱: 4열 */}
          <div className="fade-up fade-up-4" style={isMobile ? styles.statsRowMobile : styles.statsRow}>
            {stats.map((s, i) => (
              <div key={i} className="stat-card">
                <div style={{ fontSize: isMobile ? '22px' : '28px', fontWeight: '800', fontFamily: 'Space Grotesk, sans-serif', color: '#818cf8', marginBottom: '4px' }}>
                  {s.value}
                </div>
                <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.5px', textTransform: 'uppercase' }}>
                  {s.label}
                </div>
                <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)', marginTop: '2px' }}>
                  {s.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── FEATURES ── */}
      <section id="features" style={isMobile ? styles.sectionMobile : styles.section}>
        <div style={styles.sectionHeader}>
          <div style={styles.sectionTag}>CORE MODULES</div>
          <h2 style={styles.sectionTitle}>핵심 감지 모듈</h2>
          <p style={styles.sectionDesc}>설계하고 구현한 AI 기반 교통 관제 핵심 기능들입니다.</p>
        </div>

        {/* ✅ 모바일: 1열, 데스크톱: 3열 */}
        <div style={isMobile ? styles.featureGridMobile : styles.featureGrid}>
          {features.map((f, i) => (
            <div key={i} className="feature-card">
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
                <div style={{ ...styles.featureIcon, background: `${f.color}15`, border: `1px solid ${f.color}30` }}>
                  <span style={{ fontSize: '22px' }}>{f.icon}</span>
                </div>
                <h3 style={styles.featureTitle}>{f.title}</h3>
              </div>
              <p style={styles.featureDesc}>{f.desc}</p>
              <div style={{ marginTop: '16px' }}>
                {f.tags.map((tag, j) => <span key={j} className="tag">{tag}</span>)}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── TECH STACK ── */}
      <section id="tech" style={{ ...(isMobile ? styles.sectionMobile : styles.section), background: 'rgba(15,23,42,0.3)' }}>
        <div style={styles.sectionHeader}>
          <div style={styles.sectionTag}>TECH STACK</div>
          <h2 style={styles.sectionTitle}>기술 스택</h2>
        </div>

        {/* ✅ 모바일: 2열, 데스크톱: 4열 */}
        <div style={isMobile ? styles.techGridMobile : styles.techGrid}>
          {techStack.map((t, i) => (
            <div key={i} style={styles.techCard}>
              <div style={styles.techCategory}>{t.category}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '12px' }}>
                {t.items.map((item, j) => (
                  <span key={j} style={styles.techItem}>{item}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── ABOUT ── */}
      <section id="about" style={isMobile ? styles.sectionMobile : styles.section}>
        {/* ✅ 모바일: 세로, 데스크톱: 2열 그리드 */}
        <div style={isMobile ? styles.aboutBoxMobile : styles.aboutBox}>
          <div style={styles.aboutLeft}>
            <div style={styles.sectionTag}>PROJECT</div>
            <h2 style={{ ...styles.sectionTitle, textAlign: 'left', marginBottom: '16px' }}>
              AI-X<br />프로젝트 성과물
            </h2>
            <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: '15px', lineHeight: '1.8', marginBottom: '24px' }}>
              실제 교통 관제 시스템을 목표로 설계된 풀스택 AI 프로젝트입니다.
              공공 ITS API 연동, 커스텀 YOLO 모델 학습, 실시간 소켓 통신,
              도커 기반 배포까지 전 과정을 구현했습니다.
            </p>
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              <a href="https://github.com/qksdkqksdk5/TADS_Project" target="_blank" rel="noreferrer">
                <button className="btn-ghost">GitHub →</button>
              </a>
            </div>
          </div>
          <div style={styles.aboutRight}>
            {[
              { label: '역주행 감지 모델', value: 'YOLOv11 + ByteTrack + FlowMap' },
              { label: '화재 감지 모델', value: 'YOLOv8 (OpenVINO 경량화)' },
              { label: '번호판 OCR', value: 'Custom YOLO-OCR + Vote 알고리즘' },
              { label: '실시간 통신', value: 'Flask-SocketIO + Gevent' },
              { label: '배포 환경', value: 'Docker + AWS EC2 + RDS' },
            ].map((item, i) => (
              <div key={i} style={styles.aboutItem}>
                <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.35)', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.5px', textTransform: 'uppercase', marginBottom: '4px' }}>
                  {item.label}
                </div>
                <div style={{ fontSize: '14px', color: 'rgba(255,255,255,0.8)', fontFamily: 'IBM Plex Mono, monospace' }}>
                  {item.value}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section style={isMobile ? styles.ctaSectionMobile : styles.ctaSection}>
        <div style={styles.ctaBg} />
        <div style={{ position: 'relative', zIndex: 1, textAlign: 'center' }}>
          <h2 style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: 'clamp(28px,4vw,48px)', fontWeight: '800', color: '#fff', marginBottom: '16px', letterSpacing: '-1px' }}>
            관제 센터 접속
          </h2>
          <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: isMobile ? '14px' : '16px', marginBottom: '32px', lineHeight: '1.7' }}>
            본 시스템은 인가된 관리자만 접근할 수 있습니다.<br />
            관리자 코드를 발급받은 후 로그인하세요.
          </p>
          <button
            className="btn-primary"
            onClick={() => navigate('/login')}
            style={{ padding: isMobile ? '14px 32px' : '16px 48px', fontSize: isMobile ? '14px' : '16px' }}
          >
            관제 센터 입장 →
          </button>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer style={styles.footer}>
        <div style={isMobile ? styles.footerInnerMobile : styles.footerInner}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div style={styles.logoDot} />
            <span style={{ fontFamily: 'Space Grotesk, sans-serif', fontWeight: '700', fontSize: '16px', color: 'rgba(255,255,255,0.8)' }}>TADS</span>
          </div>
          <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.25)', fontFamily: 'IBM Plex Mono, monospace', textAlign: isMobile ? 'center' : 'left' }}>
            © 2026 TADS Project. Traffic Anomaly Detection System.
          </div>
          <div style={{ display: 'flex', gap: '20px' }} />
        </div>
      </footer>
    </div>
  );
}

const styles = {
  root: {
    minHeight: '100vh',
    background: '#020617',
    color: '#fff',
    fontFamily: 'Inter, sans-serif',
  },

  // ── NAV ──
  nav: {
    position: 'fixed',
    top: 0, left: 0, right: 0,
    zIndex: 100,
    background: 'rgba(2,6,23,0.8)',
    backdropFilter: 'blur(20px)',
    borderBottom: '1px solid rgba(255,255,255,0.05)',
  },
  navInner: {
    maxWidth: '1200px',
    margin: '0 auto',
    padding: '0 24px',
    height: '64px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  logo:      { display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' },
  logoDot:   { width: '8px', height: '8px', borderRadius: '50%', background: '#6366f1', boxShadow: '0 0 8px #6366f1', animation: 'pulse-dot 2s infinite' },
  logoText:  { fontFamily: 'Space Grotesk, sans-serif', fontWeight: '800', fontSize: '20px', letterSpacing: '-0.5px' },
  logoBadge: { fontSize: '10px', color: 'rgba(255,255,255,0.3)', fontFamily: 'IBM Plex Mono, monospace', background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px' },
  navLinks:  { display: 'flex', gap: '32px' },

  // ── HERO ──
  hero: {
    position: 'relative',
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    paddingTop: '64px',
  },
  heroBg1: {
    position: 'absolute',
    top: '20%', left: '50%',
    transform: 'translateX(-50%)',
    width: '600px', height: '600px',
    background: 'radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  heroBg2: {
    position: 'absolute',
    bottom: '0', right: '10%',
    width: '400px', height: '400px',
    background: 'radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  heroContent: {
    position: 'relative', zIndex: 1,
    maxWidth: '900px',
    margin: '0 auto',
    padding: '80px 20px',
    textAlign: 'center',
  },
  heroBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '8px',
    background: 'rgba(99,102,241,0.08)',
    border: '1px solid rgba(99,102,241,0.2)',
    borderRadius: '100px',
    padding: '6px 14px',
    marginBottom: '32px',
  },
  heroBadgeDot: { width: '6px', height: '6px', borderRadius: '50%', background: '#6366f1', animation: 'pulse-dot 1.5s infinite' },
  heroTitle: {
    fontFamily: 'Space Grotesk, sans-serif',
    fontSize: 'clamp(32px, 7vw, 90px)',
    fontWeight: '800',
    lineHeight: '1.1',
    letterSpacing: '-2px',
    marginBottom: '24px',
    color: '#fff',
  },
  heroTitleAccent: {
    background: 'linear-gradient(135deg, #818cf8, #6366f1)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
  },
  heroDesc: {
    fontSize: 'clamp(14px, 2vw, 18px)',
    color: 'rgba(255,255,255,0.45)',
    lineHeight: '1.8',
    marginBottom: '40px',
    fontWeight: '400',
  },

  // ✅ Stats 그리드: 데스크톱 4열
  statsRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: '16px',
    marginTop: '64px',
  },
  // ✅ Stats 그리드: 모바일 2열
  statsRowMobile: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: '10px',
    marginTop: '40px',
  },

  // ── SECTIONS ──
  section: {
    maxWidth: '1200px',
    margin: '0 auto',
    padding: '100px 24px',
  },
  // ✅ 모바일 섹션: 패딩 줄임
  sectionMobile: {
    maxWidth: '100%',
    margin: '0 auto',
    padding: '60px 16px',
  },
  sectionHeader: { textAlign: 'center', marginBottom: '60px' },
  sectionTag: {
    display: 'inline-block',
    fontSize: '11px',
    fontFamily: 'IBM Plex Mono, monospace',
    color: '#6366f1',
    letterSpacing: '2px',
    textTransform: 'uppercase',
    marginBottom: '12px',
    background: 'rgba(99,102,241,0.08)',
    border: '1px solid rgba(99,102,241,0.2)',
    padding: '4px 12px',
    borderRadius: '4px',
  },
  sectionTitle: {
    fontFamily: 'Space Grotesk, sans-serif',
    fontSize: 'clamp(24px, 4vw, 44px)',
    fontWeight: '800',
    letterSpacing: '-1px',
    color: '#fff',
    marginBottom: '12px',
    textAlign: 'center',
  },
  sectionDesc: { fontSize: '16px', color: 'rgba(255,255,255,0.4)', maxWidth: '560px', margin: '0 auto' },

  // ── FEATURES ──
  // ✅ 데스크톱 3열
  featureGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: '20px',
  },
  // ✅ 모바일 1열
  featureGridMobile: {
    display: 'grid',
    gridTemplateColumns: '1fr',
    gap: '16px',
  },
  featureIcon: {
    width: '44px', height: '44px',
    borderRadius: '10px',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    flexShrink: 0,
  },
  featureTitle: { fontFamily: 'Space Grotesk, sans-serif', fontSize: '17px', fontWeight: '700', color: '#fff' },
  featureDesc:  { fontSize: '14px', color: 'rgba(255,255,255,0.45)', lineHeight: '1.7' },

  // ── TECH STACK ──
  // ✅ 데스크톱 4열
  techGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: '20px',
    maxWidth: '1200px',
    margin: '0 auto',
    padding: '0 24px',
  },
  // ✅ 모바일 2열
  techGridMobile: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: '12px',
  },
  techCard: {
    background: 'rgba(15,23,42,0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '12px',
    padding: '20px',
  },
  techCategory: {
    fontSize: '11px',
    fontFamily: 'IBM Plex Mono, monospace',
    color: '#6366f1',
    letterSpacing: '1px',
    textTransform: 'uppercase',
    fontWeight: '600',
  },
  techItem: {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '6px',
    padding: '6px 10px',
    fontSize: '12px',
    color: 'rgba(255,255,255,0.6)',
    fontFamily: 'IBM Plex Mono, monospace',
  },

  // ── ABOUT ──
  // ✅ 데스크톱 2열
  aboutBox: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '60px',
    alignItems: 'center',
    background: 'rgba(15,23,42,0.4)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '20px',
    padding: '60px',
  },
  // ✅ 모바일 1열
  aboutBoxMobile: {
    display: 'flex',
    flexDirection: 'column',
    gap: '32px',
    background: 'rgba(15,23,42,0.4)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '28px 20px',
  },
  aboutLeft:  {},
  aboutRight: { display: 'flex', flexDirection: 'column', gap: '0' },
  aboutItem: {
    padding: '16px 0',
    borderBottom: '1px solid rgba(255,255,255,0.05)',
  },

  // ── CTA ──
  ctaSection: {
    position: 'relative',
    padding: '120px 24px',
    overflow: 'hidden',
    textAlign: 'center',
    borderTop: '1px solid rgba(255,255,255,0.05)',
  },
  // ✅ 모바일 CTA
  ctaSectionMobile: {
    position: 'relative',
    padding: '72px 20px',
    overflow: 'hidden',
    textAlign: 'center',
    borderTop: '1px solid rgba(255,255,255,0.05)',
  },
  ctaBg: {
    position: 'absolute',
    top: '50%', left: '50%',
    transform: 'translate(-50%, -50%)',
    width: '600px', height: '400px',
    background: 'radial-gradient(ellipse, rgba(99,102,241,0.12) 0%, transparent 70%)',
    pointerEvents: 'none',
  },

  // ── FOOTER ──
  footer: {
    borderTop: '1px solid rgba(255,255,255,0.05)',
    padding: '32px 24px',
    background: 'rgba(0,0,0,0.3)',
  },
  // ✅ 데스크톱 footer
  footerInner: {
    maxWidth: '1200px',
    margin: '0 auto',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: '16px',
  },
  // ✅ 모바일 footer: 세로 중앙 정렬
  footerInnerMobile: {
    maxWidth: '1200px',
    margin: '0 auto',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '12px',
  },
};