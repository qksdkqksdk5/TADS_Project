/* eslint-disable */
import { useState, useEffect, useRef } from 'react';
import Swal from 'sweetalert2';
import axios from 'axios';
import { useMapMarkers } from './useMapMarkers';
import { useLocation } from 'react-router-dom';

export function useAnomalyDetection(socket, activeTab, setActiveTab, setVideoUrl, host, adminName) {
  const location = useLocation();

  const [isEmergency, setIsEmergency] = useState(false);
  const [pendingAlerts, setPendingAlerts] = useState([]);
  const [logs, setLogs] = useState([]);
  const mapRef = useRef(null);
  const pendingAlertsRef = useRef([]);
  const { markersRef, createMarker, removeMarker, clearMarkersRef } = useMapMarkers(mapRef);


  const activeTabRef = useRef(activeTab);
  useEffect(() => { pendingAlertsRef.current = pendingAlerts; }, [pendingAlerts]);

  // 초기 미조치 데이터 불러오기
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        const response = await axios.get(`http://${host}:5000/api/pending_alerts`);
        if (response.data.length > 0) {
          setPendingAlerts(response.data);
          setIsEmergency(true);
        }
      } catch (err) { console.error("❌ 데이터 로드 실패:", err); }
    };
    fetchInitialData();
  }, [host]);

  // 알림 목록 변경 시 마커 그리기
  useEffect(() => {
    // 🚩 중요: 카카오맵 SDK와 지도 객체가 존재하는지 먼저 확인
    if (!window.kakao || !window.kakao.maps || !mapRef.current) return;

    pendingAlerts.forEach(alert => {
      // 이미 마커가 있는지 체크하는 로직이 useMapMarkers에 없다면 여기서 필터링 가능
      createMarker(alert, () => 
        resolveEmergency(alert.id, alert.type, alert.address, alert.origin, alert.isSimulation)
      );
    });
  }, [pendingAlerts, mapRef.current]); // 👈 mapRef.current를 의존성에 추가

  const resolveEmergency = async (alertId, type, address, originType, isSimulation = false) => {
    try {
      const result = await Swal.fire({
        title: '조치 및 상황 확인',
        text: `[${type}] 상황이 실제 상황입니까?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: '✅ 실제상황 (정탐)',
        cancelButtonText: '❌ 알람오류 (오탐)',
        confirmButtonColor: '#2563eb',
        cancelButtonColor: '#f87171',
        reverseButtons: true
      });

      const isCorrect = result.isConfirmed ? 1 : 0;

      await axios.post(`http://${host}:5000/api/resolve_alert_db`, { 
        alertId, isCorrect, adminName: adminName, is_simulation: isSimulation ? 1 : 0 
      });

      removeMarker(alertId);
      setPendingAlerts(prev => {
        const updated = prev.filter(a => String(a.id) !== String(alertId));
        if (updated.length === 0) setIsEmergency(false);
        return updated;
      });

      const statusLabel = isCorrect ? "정탐" : "오탐";
      setLogs(prev => [`[${new Date().toLocaleTimeString()}] ✅ ${statusLabel} 조치: ${type}`, ...prev]);
      if (socket) {
        socket.emit("resolve_emergency", { alertId, type, address, isCorrect, adminName: adminName, isSimulation, senderId: socket.id });
      }
      Swal.fire({ title: `${statusLabel} 완료`, icon: 'success', timer: 1000, showConfirmButton: false });
    } catch (err) { console.error(err); }
  };

  const resolveAllAlertsAction = async (alerts, isSimulation = false) => {
    const result = await Swal.fire({
      title: '일괄 조치',
      text: `${alerts.length}건을 모두 정탐 처리하시겠습니까?`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: '네, 모두 처리',
      cancelButtonText: '취소'
    });

    if (result.isConfirmed) {
      try {
        const alertIds = alerts.map(a => a.id);
        const isSim = alerts[0]?.isSimulation || false;
        await axios.post(`http://${host}:5000/api/resolve_alerts_bulk`, { 
          alertIds: alertIds, 
          isCorrect: 1, 
          adminName: adminName
        });

        alertIds.forEach(id => removeMarker(id));
        setPendingAlerts([]);
        setIsEmergency(false);

        if (socket) {
          alerts.forEach(alert => {
            socket.emit("resolve_emergency", { 
              alertId: alert.id, 
              type: alert.type, 
              isCorrect: 1, 
              isSimulation, 
              senderId: socket.id 
            });
          });
        }

        setPendingAlerts([]);
        setIsEmergency(false);
        setLogs(prev => [`[${new Date().toLocaleTimeString()}] 📦 일괄 조치 완료 (${alerts.length}건)`, ...prev]);
        Swal.fire('일괄 처리 완료', '', 'success');

      } catch (err) {
        console.error("일괄 처리 중 에러:", err);
        Swal.fire('처리 실패', 'DB 업데이트 중 오류가 발생했습니다.', 'error');
      }
    }
  };

  useEffect(() => {
    if (!socket) return;

    const handleForceStart = (data) => {
      // 본인이 emit한 거면 무시 (본인은 startSim에서 직접 처리)
      // if (data.senderId === socket.id) return;

      // 다른 접속자는 바로 sim 탭으로 이동 + 영상 세팅
      // setActiveTab("sim");
      setTimeout(() => {
        const syncUrl = `https://${host}/api/video_feed?type=${data.type}&v=${Date.now()}`;
        // const syncUrl = `http://${host}:5000/api/video_feed?type=${data.type}&v=${Date.now()}`;
        setVideoUrl(syncUrl);
      }, 1500);
    };

    const handleAnomaly = async (data) => {

      // 1. 중복 알림 방지 체크
      if (pendingAlertsRef.current.some(a => String(a.id) === String(data.alert_id))) return;

      const time = new Date().toLocaleTimeString();

      // 2. 좌표 생성 (지도가 있는 경우에만 시도, 에러 방지)
      let coord = null;
      if (window.kakao && window.kakao.maps) {
        try {
          coord = new window.kakao.maps.LatLng(data.lat, data.lng);
        } catch (e) {
          console.warn("⚠️ 좌표 생성 생략 (지도가 없는 탭)");
        }
      }

      // 3. 시뮬레이션 여부 판단
      const isSimulationValue = data.hasOwnProperty('is_simulation')
        ? Boolean(data.is_simulation)
        : (!data.video_origin.includes('realtime_its') && !data.video_origin.includes('webcam'));

      const processAlert = async (finalAddress) => {

        const isCurrTabSim = location.pathname.includes('/sim');

        // DB 주소 업데이트 (기존 로직 유지)
        if (!data.video_origin.includes('realtime_its')) {
          // axios.post(`http://${host}:5000/api/update_address`, { 
          axios.post(`https://${host}/api/update_address`, { 
            alertId: data.alert_id, 
            address: finalAddress 
          }).catch(err => console.error("❌ DB 주소 업데이트 실패:", err));
        }

        const newAlert = { 
          id: data.alert_id, type: data.type, address: finalAddress, time, 
          origin: data.video_origin, isSimulation: isSimulationValue,
          lat: data.lat, lng: data.lng, imageUrl: data.image_url 
        };

        setPendingAlerts(prev => [newAlert, ...prev]);
        setIsEmergency(true);
        setLogs(prev => [`[${time}] 🚨 감지: ${data.type}`, ...prev]);

        // 지도 이동 (지도가 로드된 상태이고 panTo 함수가 있을 때만)
        if (mapRef.current && coord) {
          try {
            // 지도가 화면에 보이지 않는 탭(예: plate 탭)에 있을 때는 panTo를 건너뛰거나
            // 지도가 렌더링된 후에 실행되도록 처리
            if (typeof mapRef.current.relayout === 'function') {
                mapRef.current.relayout(); // 지도 크기 재계정 (안 뜨는 문제 해결 핵심)
            }
            mapRef.current.panTo(coord);
          } catch (e) {
            console.warn("⚠️ 지도 이동 중 오류 발생:", e);
          }
        }

        const displayAddress = finalAddress && finalAddress !== "undefined" ? finalAddress : "위치 정보 없음";
        
        let alertHtml = "";
        if (isCurrTabSim) {
          alertHtml = `<b>${data.type}</b> 이(가) 감지되었습니다.`;
        } else if (isSimulationValue) {
          alertHtml = `<b>시뮬레이션 화면</b>에서 <b>${data.type}</b> 감지<br/><br/>확인을 위해 화면을 이동하시겠습니까?`;
        } else {
          alertHtml = `<b>위치:</b> ${displayAddress}<br/><br/>확인을 위해 해당 화면으로 이동하시겠습니까?`;
        }

        const result = await Swal.fire({
          title: `🚨 ${data.type} 감지`,
          html: alertHtml,
          icon: 'error',
          showCancelButton: !isCurrTabSim,
          confirmButtonText: isCurrTabSim ? '확인' : '이동 및 확인',
          cancelButtonText: '머무르기',
          confirmButtonColor: '#d33',
          cancelButtonColor: '#3085d6',
          reverseButtons: true,
          timer: 15000,
          timerProgressBar: true
        });

        // sim 탭에 없는 사람만 탭 이동
        if (result.isConfirmed && !isCurrTabSim) {
          const targetTab = isSimulationValue ? "sim" : "cctv";
          setActiveTab(targetTab);

          if (isSimulationValue && typeof setVideoUrl === 'function') {
            const select_type = data.type === "화재" ? "fire" : (data.type === "역주행" ? "reverse" : "unknown");
            setTimeout(() => {
              const syncUrl = `https://${host}/api/video_feed?type=${select_type}&v=${Date.now()}`;
              // const syncUrl = `http://${host}:5000/api/video_feed?type=${select_type}&v=${Date.now()}`;
              setVideoUrl(syncUrl);
            }, 1000);
          }
        }
      };

      // 6. 주소 변환 및 알림 프로세스 실행

      // [Case 1] ITS CCTV인 경우: 변환 없이 바로 전달된 주소(이름) 사용
      if (data.video_origin.includes('realtime_its')) {
        const cctvName = data.address || data.video_origin || "알 수 없는 CCTV";
        await processAlert(cctvName);
      } 
      // [Case 2] 그 외(시뮬레이션 등): 좌표가 있다면 주소 변환 시도
      else if (window.kakao?.maps?.services?.Geocoder && coord) {
        const geocoder = new window.kakao.maps.services.Geocoder();
        
        geocoder.coord2Address(coord.getLng(), coord.getLat(), (result, status) => {
          if (status === window.kakao.maps.services.Status.OK) {
            const convertedAddress = result[0].address.address_name;
            processAlert(convertedAddress);
          } else {
            // 변환 실패 시 (좌표가 산이나 바다 등 주소가 없는 곳일 때)
            const fallback = data.address || "위치 정보 없음(좌표 오류)";
            console.warn("⚠️ 주소 변환 실패 (Status 확인):", status);
            processAlert(fallback);
          }
        });
      } 
      // [Case 3] 좌표도 없고 Geocoder도 없는 경우
      else {
        await processAlert(data.address || data.video_origin || "위치 정보 없음");
      }
    };

    const handleRemoteResolve = (data) => {
      if (data.senderId === socket.id) return;

      if (typeof removeMarker === 'function') {
        removeMarker(data.alertId);
      }

      setPendingAlerts(prev => {
        const updated = prev.filter(a => String(a.id) !== String(data.alertId));
        if (updated.length === 0) setIsEmergency(false);
        return updated;
      });

      const statusLabel = data.isCorrect ? "실제상황 정탐" : "알람오류 오탐";
      
      Swal.fire({
        title: '타 관리자 조치 완료',
        text: `[${data.type}] 상황을 다른 관리자가 ${statusLabel}으로 처리하였습니다.`,
        icon: 'info',
        toast: true,
        position: 'top-end',
        showConfirmButton: false,
        timer: 3000,
        timerProgressBar: true,
        width: '600px'
      });

      setLogs(prev => [`[${new Date().toLocaleTimeString()}] ℹ️ 타 관리자 조치: ${data.type}`, ...prev]);
    };

    socket.on("force_video_start", handleForceStart);
    socket.on("anomaly_detected", handleAnomaly);
    socket.on("emergency_resolved", handleRemoteResolve);

    return () => {
      socket.off("force_video_start", handleForceStart);
      socket.off("anomaly_detected", handleAnomaly);
      socket.off("emergency_resolved", handleRemoteResolve);
    };
  }, [socket, host, location.pathname]);

  return { isEmergency, pendingAlerts, logs, mapRef, resolveEmergency, resolveAllAlertsAction, moveToAlert: (a) => mapRef.current?.panTo(new window.kakao.maps.LatLng(a.lat, a.lng)), createMarker, clearMarkersRef };
}