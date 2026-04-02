/* eslint-disable */
import { useState, useEffect, useRef } from 'react';
import Swal from 'sweetalert2';
import axios from 'axios';
import { useMapMarkers } from './useMapMarkers';

export function useAnomalyDetection(socket, activeTab, setActiveTab, setVideoUrl, host, adminName) {
  const [isEmergency, setIsEmergency] = useState(false);
  const [pendingAlerts, setPendingAlerts] = useState([]);
  const [logs, setLogs] = useState([]);
  const mapRef = useRef(null);
  const pendingAlertsRef = useRef([]);

  const { markersRef, createMarker, removeMarker } = useMapMarkers(mapRef);

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
    pendingAlerts.forEach(alert => createMarker(alert, () => resolveEmergency(alert.id, alert.type, alert.address, alert.origin, alert.isSimulation)));
  }, [pendingAlerts]);

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
      setActiveTab("sim");
      const syncUrl = `http://${host}:5000/api/video_feed?type=${data.type}&v=${Date.now()}`;
      setVideoUrl(syncUrl);
      // if (data.lat && mapRef.current) mapRef.current.panTo(new window.kakao.maps.LatLng(data.lat, data.lng));
    };

    const handleAnomaly = (data) => {
      if (!window.kakao || !window.kakao.maps) {
        console.warn("⚠️ 카카오 맵 API가 아직 로드되지 않았습니다.");
        return;
      }
      if (pendingAlertsRef.current.some(a => String(a.id) === String(data.alert_id))) return;

      const time = new Date().toLocaleTimeString();
      let coord;
      try {
        coord = new window.kakao.maps.LatLng(data.lat, data.lng);
      } catch (e) {
        console.error("❌ 좌표 생성 실패:", e);
        return;
      }

      // ✅ 수정: is_simulation 명시값 우선, 없으면 video_origin으로 판단
      // webcam도 실제상황이므로 realtime_its와 webcam 둘 다 제외
      const isSimulationValue = data.hasOwnProperty('is_simulation')
        ? Boolean(data.is_simulation)
        : (!data.video_origin.includes('realtime_its') && !data.video_origin.includes('webcam'));

      const processAlert = (finalAddress) => {
        // video_origin 기준으로 주소 업데이트 여부 결정 (원본 로직 유지)
        if (!data.video_origin.includes('realtime_its')) {
          axios.post(`http://${host}:5000/api/update_address`, { 
            alertId: data.alert_id, 
            address: finalAddress 
          }).then(() => {
            console.log("✅ DB 주소 업데이트 완료:", finalAddress);
          }).catch(err => {
            console.error("❌ DB 주소 업데이트 실패:", err);
          });
        } else {
          console.log("🛡️ [보호] ITS 공공 데이터이므로 주소 업데이트를 수행하지 않습니다:", finalAddress);
        }

        const newAlert = { 
          id: data.alert_id, 
          type: data.type, 
          address: finalAddress, 
          time, 
          origin: data.video_origin, 
          isSimulation: isSimulationValue,
          lat: data.lat, 
          lng: data.lng,
          imageUrl: data.image_url 
        };

        setPendingAlerts(prev => [newAlert, ...prev]);
        setIsEmergency(true);
        setLogs(prev => [`[${time}] 🚨 감지: ${data.type}`, ...prev]);

        if (mapRef.current && typeof mapRef.current.panTo === 'function') {
          mapRef.current.panTo(coord);
        }

        Swal.fire({
          title: `🚨 ${data.type} 감지`,
          html: `위치: ${finalAddress}`,
          icon: 'error',
          timer: 2000
        });
      };

      if (data.video_origin.includes('realtime_its') && data.address) {
        // 공공 ITS 데이터 — 주소 확정값 그대로 사용
        processAlert(data.address);
      } else {
        // 웹캠(실제) or 시뮬레이션 — 좌표 → 주소 변환
        if (!window.kakao.maps.services || !window.kakao.maps.services.Geocoder) {
          processAlert(data.address || data.video_origin || "위치 정보 확인 불가");
          return;
        }
        const geocoder = new window.kakao.maps.services.Geocoder();
        geocoder.coord2Address(coord.getLng(), coord.getLat(), (result, status) => {
          const convertedAddress = status === window.kakao.maps.services.Status.OK 
            ? result[0].address.address_name 
            : (data.address || data.video_origin || "위치 정보 확인 불가");
          processAlert(convertedAddress);
        });
      }
    };

    const handleRemoteResolve = (data) => {
      if (data.senderId === socket.id) return;

      removeMarker(data.alertId);
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
  }, [socket, host]);

  return { isEmergency, pendingAlerts, logs, mapRef, resolveEmergency, resolveAllAlertsAction, moveToAlert: (a) => mapRef.current?.panTo(new window.kakao.maps.LatLng(a.lat, a.lng)) };
}
