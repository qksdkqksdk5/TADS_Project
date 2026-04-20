# tests/test_stream_probe.py
# 교통 모니터링 팀 — 스트림 URL 탐침(probe) 진단 함수 TDD 테스트
# pytest 실행: backend_flask/ 에서 `pytest tests/test_stream_probe.py -v`

import sys
import os
from unittest.mock import patch, MagicMock, call

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, _BACKEND_DIR)


# ── 헬퍼: 가짜 requests.get 응답 생성 ────────────────────────────────────────

def _mock_response(status=200, content_type='video/MP2T',
                   first_bytes=b'\x47\x40\x11\x10', raise_exc=None):
    """
    requests.get() 이 반환할 가짜 Response 객체를 만든다.
    raise_exc 가 주어지면 requests.get() 자체가 그 예외를 일으킨다.
    """
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {
        'Content-Type': content_type,
        'Content-Length': str(len(first_bytes)),
        'Server': 'FakeServer/1.0',
    }
    # iter_content 는 이터레이터를 반환해야 한다
    resp.iter_content.return_value = iter([first_bytes])
    resp.close = MagicMock()
    return resp


# ── 테스트 클래스 ──────────────────────────────────────────────────────────────

class TestProbeStreamUrl:
    """
    its_helper.probe_stream_url() 의 동작을 검증한다.
    실제 ITS 서버에 접속하지 않도록 requests.get 을 모킹한다.
    """

    def test_결과에_url_키가_포함됨(self):
        """반환 딕셔너리에 입력 URL 이 그대로 들어있어야 한다."""
        from modules.monitoring.its_helper import probe_stream_url
        target = 'http://cctvsec.ktict.co.kr/test/abc'
        with patch('modules.monitoring.its_helper.requests.get',
                   return_value=_mock_response()):
            result = probe_stream_url(target)
        assert result['url'] == target

    def test_HTTP_200_시_status_포함(self):
        """HTTP 200 응답이면 http_status=200 이 들어있어야 한다."""
        from modules.monitoring.its_helper import probe_stream_url
        with patch('modules.monitoring.its_helper.requests.get',
                   return_value=_mock_response(status=200)):
            result = probe_stream_url('http://example.com/stream')
        assert result['http_status'] == 200

    def test_HTTP_403_시_status_포함(self):
        """HTTP 403(토큰 만료 등) 이면 http_status=403 이 들어있어야 한다."""
        from modules.monitoring.its_helper import probe_stream_url
        with patch('modules.monitoring.its_helper.requests.get',
                   return_value=_mock_response(status=403, first_bytes=b'')):
            result = probe_stream_url('http://example.com/stream')
        assert result['http_status'] == 403

    def test_콘텐츠_타입이_포함됨(self):
        """응답 Content-Type 헤더 값이 결과에 포함되어야 한다."""
        from modules.monitoring.its_helper import probe_stream_url
        with patch('modules.monitoring.its_helper.requests.get',
                   return_value=_mock_response(content_type='application/x-mpegURL')):
            result = probe_stream_url('http://example.com/stream')
        assert result['content_type'] == 'application/x-mpegURL'

    def test_첫_바이트_hex_포함됨(self):
        """
        응답 첫 바이트를 16진수 문자열로 포함해야 한다.
        0x47 (MPEG-TS sync byte) 이면 '47...' 로 시작한다.
        """
        from modules.monitoring.its_helper import probe_stream_url
        with patch('modules.monitoring.its_helper.requests.get',
                   return_value=_mock_response(first_bytes=b'\x47\x40\x11\x10')):
            result = probe_stream_url('http://example.com/stream')
        assert result['first_bytes_hex'].startswith('47')

    def test_m3u8_포맷_판별(self):
        """
        첫 바이트가 '#EXTM3U' 이면 stream_format 이 'm3u8' 이어야 한다.
        """
        from modules.monitoring.its_helper import probe_stream_url
        with patch('modules.monitoring.its_helper.requests.get',
                   return_value=_mock_response(
                       content_type='application/x-mpegURL',
                       first_bytes=b'#EXTM3U\n')):
            result = probe_stream_url('http://example.com/stream')
        assert result['stream_format'] == 'm3u8'

    def test_mpegts_포맷_판별(self):
        """
        첫 바이트가 0x47 (MPEG-TS sync byte) 이면 stream_format 이 'mpegts' 이어야 한다.
        """
        from modules.monitoring.its_helper import probe_stream_url
        with patch('modules.monitoring.its_helper.requests.get',
                   return_value=_mock_response(first_bytes=b'\x47\x40\x11\x10')):
            result = probe_stream_url('http://example.com/stream')
        assert result['stream_format'] == 'mpegts'

    def test_HTTP_연결_실패_시_http_error_포함(self):
        """
        requests.get 이 예외를 던지면 결과에 http_error 키가 있어야 한다.
        http_status / content_type 키는 없어도 된다.
        """
        from modules.monitoring.its_helper import probe_stream_url
        with patch('modules.monitoring.its_helper.requests.get',
                   side_effect=Exception('Connection refused')):
            result = probe_stream_url('http://dead.host/stream')
        assert 'http_error' in result
        assert 'Connection refused' in result['http_error']
        # HTTP 실패이므로 status 키 없음
        assert 'http_status' not in result

    def test_알수없는_포맷은_unknown(self):
        """
        첫 바이트가 알려진 시그니처와 다르면 stream_format 이 'unknown' 이어야 한다.
        """
        from modules.monitoring.its_helper import probe_stream_url
        with patch('modules.monitoring.its_helper.requests.get',
                   return_value=_mock_response(first_bytes=b'\x00\x01\x02\x03')):
            result = probe_stream_url('http://example.com/stream')
        assert result['stream_format'] == 'unknown'


class TestProbeBatch:
    """
    its_helper.probe_batch() 의 동작을 검증한다.
    여러 카메라를 한 번에 탐침해 패턴을 파악하는 함수다.
    """

    def _make_cameras(self):
        """테스트용 가짜 카메라 목록 (3대)"""
        return [
            {'camera_id': 'road_cam_A', 'name': 'A카메라', 'url': 'http://host/A'},
            {'camera_id': 'road_cam_B', 'name': 'B카메라', 'url': 'http://host/B'},
            {'camera_id': 'road_cam_C', 'name': 'C카메라', 'url': 'http://host/C'},
        ]

    def test_반환값에_cameras_리스트_포함(self):
        """결과 딕셔너리에 'cameras' 키가 있어야 한다."""
        from modules.monitoring.its_helper import probe_batch
        cams = self._make_cameras()
        with patch('modules.monitoring.its_helper.probe_stream_url',
                   return_value={'url': '', 'http_status': 200,
                                 'stream_format': 'mpegts', 'content_type': 'video/MP2T'}):
            result = probe_batch(cams)
        assert 'cameras' in result

    def test_cameras_개수가_입력과_일치(self):
        """탐침 대상 카메라 수만큼 결과가 나와야 한다."""
        from modules.monitoring.its_helper import probe_batch
        cams = self._make_cameras()
        with patch('modules.monitoring.its_helper.probe_stream_url',
                   return_value={'url': '', 'http_status': 200,
                                 'stream_format': 'mpegts', 'content_type': 'video/MP2T'}):
            result = probe_batch(cams)
        assert len(result['cameras']) == 3

    def test_반환값에_summary_포함(self):
        """결과에 포맷별 집계인 'summary' 키가 있어야 한다."""
        from modules.monitoring.its_helper import probe_batch
        cams = self._make_cameras()
        with patch('modules.monitoring.its_helper.probe_stream_url',
                   return_value={'url': '', 'http_status': 200,
                                 'stream_format': 'mpegts', 'content_type': 'video/MP2T'}):
            result = probe_batch(cams)
        assert 'summary' in result

    def test_summary_포맷_집계_정확성(self):
        """
        카메라 2대 mpegts, 1대 m3u8 이면
        summary['mpegts']==2, summary['m3u8']==1 이어야 한다.
        """
        from modules.monitoring.its_helper import probe_batch
        cams = self._make_cameras()

        # 카메라 A, B → mpegts / 카메라 C → m3u8
        _formats = ['mpegts', 'mpegts', 'm3u8']
        _idx = [0]

        def _side_effect(url):
            fmt = _formats[_idx[0] % len(_formats)]
            _idx[0] += 1
            return {'url': url, 'http_status': 200,
                    'stream_format': fmt, 'content_type': 'video/MP2T'}

        with patch('modules.monitoring.its_helper.probe_stream_url',
                   side_effect=_side_effect):
            result = probe_batch(cams)

        assert result['summary'].get('mpegts', 0) == 2
        assert result['summary'].get('m3u8',   0) == 1

    def test_각_카메라_결과에_camera_id_포함(self):
        """카메라별 결과 항목에 camera_id 가 들어있어야 한다."""
        from modules.monitoring.its_helper import probe_batch
        cams = self._make_cameras()
        with patch('modules.monitoring.its_helper.probe_stream_url',
                   return_value={'url': '', 'http_status': 200,
                                 'stream_format': 'mpegts', 'content_type': 'video/MP2T'}):
            result = probe_batch(cams)
        ids = [c['camera_id'] for c in result['cameras']]
        assert 'road_cam_A' in ids
        assert 'road_cam_B' in ids
        assert 'road_cam_C' in ids

    def test_http_오류_카메라도_결과에_포함(self):
        """
        HTTP 접근 자체가 실패한 카메라도 결과 목록에 포함되어야 한다.
        stream_format 이 'error' 로 집계되어야 한다.
        """
        from modules.monitoring.its_helper import probe_batch
        cams = self._make_cameras()[:1]   # 카메라 1대

        with patch('modules.monitoring.its_helper.probe_stream_url',
                   return_value={'url': '', 'http_error': 'Connection refused'}):
            result = probe_batch(cams)

        assert len(result['cameras']) == 1
        assert result['summary'].get('error', 0) == 1
