/* eslint-disable */
import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { io } from "socket.io-client";
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

import Login       from './modules/member/Login';
import Register    from './modules/member/Register';
import Dashboard   from './modules/dashboard';
import LandingPage from './modules/home/LandingPage';

function App() {
  const [user, setUser] = useState(() => {
    const savedUser = sessionStorage.getItem('user');
    try {
      return savedUser && savedUser !== "undefined" ? JSON.parse(savedUser) : null;
    } catch { return null; }
  });

  const [socket, setSocket] = useState(null);
  const [outsideSocket, setOutsideSocket] = useState(null);

  const handleLogout = () => {
    sessionStorage.removeItem('user');
    setUser(null);
    // ✅ 두 소켓 모두 연결 끊기
    if (socket) socket.disconnect();
    if (outsideSocket) outsideSocket.disconnect();
  };

  useEffect(() => {
    if (user) {
      const host = window.location.hostname;
      const mainSocket = io(`http://${host}:5000`, {
        transports: ["websocket"],
        forceNew: true,
        reconnectionAttempts: 3,
        timeout: 5000,
      });

      const cloudSocket = io("https://itsras.illit.kr", {
        transports: ["websocket"], // 터널 서버도 웹소켓 강제
        forceNew: true,
      });

      mainSocket.on("connect", () => console.log("✅ EC2 메인 소켓 연결 성공!"));
      cloudSocket.on("connect", () => console.log("✅ Cloudflare 터널 소켓 연결 성공!"));

      const forceLogout = (reason) => {
        console.warn(`🚨 서버와 연결이 끊어졌습니다 (${reason}). 로그아웃합니다.`);
        handleLogout(); // 👈 기존에 선언된 handleLogout 함수 호출
      };

      // 연결 에러 발생 시
      mainSocket.on("connect_error", () => forceLogout("Connect Error"));
      
      // 서버에 의해 연결이 끊기거나 네트워크 문제로 끊겼을 때
      mainSocket.on("disconnect", (reason) => {
        // 사용자가 직접 끊은 경우('io client disconnect')가 아닐 때만 로그아웃
        if (reason !== "io client disconnect") {
          forceLogout(reason);
        }
      });

      setSocket(mainSocket);
      setOutsideSocket(cloudSocket);

      // ✅ 클린업 함수: 언마운트 시 두 소켓 모두 닫기
      return () => { 
        if (mainSocket) mainSocket.close(); 
        if (cloudSocket) cloudSocket.close(); 
      };
    } else {
      setSocket(null);
      setOutsideSocket(null);
    }
  }, [user]);

  return (
    <Router>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
        body {
          margin: 0; padding: 0;
          font-family: 'Inter', sans-serif;
          background-color: #020617; color: #ffffff;
          overflow-x: hidden; overflow-y: auto;
        }
        .Toastify__toast-container { width: 550px !important; }
        .Toastify__toast-body { white-space: nowrap !important; }
        @media (min-width: 1024px) {
          *::-webkit-scrollbar { display: none !important; }
          * { -ms-overflow-style: none !important; scrollbar-width: none !important; }
        }
      `}</style>

      <ToastContainer position="top-right" autoClose={2000} theme="dark" pauseOnFocusLoss={false} />

      <div style={{ minHeight: '100dvh', background: '#020617' }}>
        <Routes>
          <Route path="/" element={user ? <Navigate to="/dashboard" /> : <LandingPage />} />

          <Route
            path="/dashboard/:tab"
            element={user
              ? <Dashboard socket={socket} outsideSocket={outsideSocket} user={user} setUser={setUser} onLogout={handleLogout} />
              : <Navigate to="/" />}
          />
          <Route
            path="/dashboard"
            element={user ? <Navigate to="/dashboard/cctv" replace /> : <Navigate to="/" />}
          />

          <Route
            path="/login"
            element={user ? <Navigate to="/dashboard" /> :
              <Login setUser={(u) => {
                setUser(u);
                sessionStorage.setItem('user', JSON.stringify(u));
              }} />}
          />
          <Route path="/register" element={user ? <Navigate to="/dashboard" /> : <Register />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;