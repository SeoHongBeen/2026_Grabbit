# Grabbit 로그 서버 (Django)

폰 릴레이 앱이 받은 알림을 핫스팟 LAN으로 전송받아 저장하는 미니 백엔드.

## 실행 방법 (노트북)

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate        # 최초 1회 — DB(SQLite) 생성
python manage.py runserver 0.0.0.0:8000
```

## 확인

- 브라우저에서 `http://localhost:8000/` → 로그 대시보드 (3초 자동 갱신)
- 폰 앱의 `LogUploader.SERVER_URL`에 노트북 IP를 넣어야 함
  - 핫스팟 연결 후 노트북에서 `ipconfig` (Windows) → IPv4 주소 확인
  - 예: `http://192.168.137.1:8000/logs`

## API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | `/logs` | 알림 1건 저장. JSON: `{"class","direction","danger","timestamp"}` |
| GET | `/logs.json?limit=50` | 최근 로그 JSON |
| GET | `/` | 대시보드 (심사 시연용) |

서버가 꺼져 있어도 폰 알림 경로에는 영향 없음 (fire-and-forget).
