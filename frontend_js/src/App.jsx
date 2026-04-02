/* eslint-disable */
import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { io } from "socket.io-client";
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

// ✅ 변경: 모듈화된 경로로 import
import Login    from './modules/member/Login';
import Register from './modules/member/Register';
import TrafficDashboard from './modules/traffic';   // traffic 모듈 진입점

function App() {
  const [user, setUser] = useState(() => {
    const savedUser = sessionStorage.getItem('user');
    try {
      return savedUser && savedUser !== "undefined" ? JSON.parse(savedUser) : null;
    } catch { return null; }
  });

  const [socket, setSocket] = useState(null);

  const handleLogout = () => {
    sessionStorage.removeItem('user');
    setUser(null);
    if (socket) socket.disconnect();
  };

  useEffect(() => {
    if (user) {
      const host = window.location.hostname;
      const newSocket = io(`http://${host}:5000`, {
        transports: ["polling", "websocket"],
        forceNew: true,
        reconnectionAttempts: 3,
        timeout: 5000,
      });

      newSocket.on("connect", () => {
        console.log(`✅ 서버(${host}:5000)와 소켓 연결 성공!`);
      });

      newSocket.on("disconnect", (reason) => {
        console.warn("⚠️ 서버와 연결이 끊어졌습니다:", reason);
        if (reason === "transport close" || reason === "io server disconnect") {
          toast.error("서버 세션이 만료되었습니다. 다시 로그인해주세요.");
          handleLogout();
        }
      });

      newSocket.on("connect_error", (error) => {
        console.error("❌ 서버 연결 실패:", error);
        toast.error("서버에 연결할 수 없습니다. 다시 로그인해 주세요.");
        handleLogout();
      });

      setSocket(newSocket);
      return () => { if (newSocket) newSocket.close(); };
    } else {
      setSocket(null);
    }
  }, [user]);

  return (
    <Router>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
        body {
          margin: 0; padding: 0;
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
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
          {/* ✅ Dashboard → TrafficDashboard (모듈 진입점) */}
          <Route
            path="/"
            element={user
              ? <TrafficDashboard socket={socket} user={user} setUser={setUser} onLogout={handleLogout} />
              : <Navigate to="/login" />}
          />
          <Route
            path="/login"
            element={user ? <Navigate to="/" /> :
              <Login setUser={(u) => {
                setUser(u);
                sessionStorage.setItem('user', JSON.stringify(u));
              }} />
            }
          />
          <Route path="/register" element={user ? <Navigate to="/" /> : <Register />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
