import os
from fastapi.testclient import TestClient

os.environ['ADMIN_KEY'] = 'a' * 32
os.environ['FLEET_KEY'] = 'b' * 32
os.environ['ALLOW_VOLATILE'] = '1'

from app import app


def test_health_and_dashboard_login():
    with TestClient(app) as client:
        assert client.get('/health').json()['movement_enabled'] is False
        assert client.get('/api/turtles').status_code == 401
        assert client.get('/api/turtles', headers={'X-Admin-Key': 'a'*32}).json()['connected'] == 0


def test_auth_and_websocket_telemetry():
    with TestClient(app) as client:
        try:
            with client.websocket_connect('/ws/turtle',headers={'X-Fleet-Key':'bad'}) as ws:
                ws.receive_json()
        except Exception:
            pass
        assert client.get('/api/turtles', headers={'X-Admin-Key': 'a'*32}).json()['connected'] == 0
        with client.websocket_connect('/ws/turtle', headers={'X-Fleet-Key':'b'*32}) as ws:
            ws.send_json({'type':'hello','id':42,'label':'Diamond Miner'})
            assert ws.receive_json()['type']=='welcome'
            ws.send_json({'type':'status', 'fuel':5120,'slots':3,'pos':{'x':1,'y':-54,'z':9}})
            # status may race with the request; retry briefly
            import time
            for _ in range(30):
                data=client.get('/api/turtles', headers={'X-Admin-Key': 'a'*32}).json()
                if data['turtles'][0].get('fuel') == 5120:break
                time.sleep(.02)
            assert data['connected']==1
            assert data['turtles'][0]['pos'] == {'x':1,'y':-54,'z':9}
        assert client.get('/api/turtles', headers={'X-Admin-Key': 'a'*32}).json()['connected']==0


def test_no_remote_control_endpoint():
    with TestClient(app) as client:
        assert client.post('/api/turtles/42/move',headers={'X-Admin-Key':'a'*32}).status_code==404
