import { useState } from 'react';
import { useChatApi } from './useChatApi';
import DataModal from './DataModal';

export default function ChatAssistant({ host }) {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState('');
  const [selectedData, setSelectedData] = useState(null);
  const { messages, loading, sendMessage } = useChatApi(host);

  const handleSend = () => {
    sendMessage(input);
    setInput('');
  };

  return (
    <>
      <div style={floatingContainer}>
        {isOpen && (
          <div style={chatBox}>
            <div style={chatHeader}>TADS AI 어시스턴트</div>
            <div style={msgArea}>
              {messages.length === 0 && (
                <div style={welcomeMsg}>안녕하세요! TADS 데이터에 대해 무엇이든 물어보세요.</div>
              )}
              {messages.map((m, i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: '10px' }}>
                  <div style={m.role === 'user' ? userMsgStyle : assistantMsgStyle}>
                    {m.content}
                    {m.dbData && m.dbData.length > 0 &&
                      !(m.dbData.length === 1 && Object.values(m.dbData[0])[0] === 0) && (
                        <button onClick={() => setSelectedData(m.dbData)} style={viewDataBtn}>
                          📊 상세 결과 표로 보기 ({m.dbData.length}건)
                        </button>
                    )}
                  </div>
                </div>
              ))}
              {loading && <div style={assistantMsgStyle}>분석 중...</div>}
            </div>
            <div style={inputArea}>
              <input
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyPress={e => e.key === 'Enter' && handleSend()}
                placeholder="질문을 입력하세요..."
                style={inputStyle}
              />
              <button onClick={handleSend} style={btnStyle}>전송</button>
            </div>
          </div>
        )}
        <button onClick={() => setIsOpen(!isOpen)} style={toggleBtn}>
          {isOpen ? '✖' : '💬'}
        </button>
      </div>

      <DataModal data={selectedData} onClose={() => setSelectedData(null)} />
    </>
  );
}

const floatingContainer = { position: 'fixed', bottom: '20px', right: '20px', zIndex: 9999 };
const chatBox = { width: '380px', height: '550px', background: '#0f172a', borderRadius: '12px', display: 'flex', flexDirection: 'column', border: '1px solid #334155', boxShadow: '0 10px 25px rgba(0,0,0,0.5)', overflow: 'hidden' };
const chatHeader = { padding: '15px', background: '#2563eb', color: '#fff', fontWeight: 'bold', fontSize: '16px' };
const msgArea = { flex: 1, overflowY: 'auto', padding: '15px', display: 'flex', flexDirection: 'column' };
const welcomeMsg = { textAlign: 'center', color: '#64748b', fontSize: '13px', marginTop: '20px', padding: '10px', border: '1px dashed #334155', borderRadius: '8px' };
const userMsgStyle = { background: '#2563eb', color: '#fff', padding: '10px 14px', borderRadius: '15px 15px 2px 15px', maxWidth: '85%', fontSize: '14px', lineHeight: '1.4' };
const assistantMsgStyle = { background: '#1e293b', color: '#e2e8f0', padding: '10px 14px', borderRadius: '15px 15px 15px 2px', maxWidth: '85%', fontSize: '14px', lineHeight: '1.4', border: '1px solid #334155' };
const viewDataBtn = { marginTop: '10px', padding: '6px 12px', background: '#3b82f6', border: 'none', color: '#fff', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', width: '100%', fontWeight: 'bold' };
const inputArea = { display: 'flex', padding: '15px', background: '#1e293b', gap: '8px' };
const inputStyle = { flex: 1, background: '#020617', border: '1px solid #334155', color: '#fff', padding: '10px', borderRadius: '6px', outline: 'none' };
const btnStyle = { background: '#2563eb', border: 'none', color: '#fff', padding: '0 15px', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' };
const toggleBtn = { width: '60px', height: '60px', borderRadius: '50%', background: '#2563eb', color: '#fff', fontSize: '24px', cursor: 'pointer', border: 'none', boxShadow: '0 4px 15px rgba(37,99,235,0.4)', transition: 'transform 0.2s' };