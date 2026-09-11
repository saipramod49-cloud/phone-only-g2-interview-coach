from fastapi.testclient import TestClient
from app.main import app
from app import storage


def test_upload_profile_retrieval_and_removal(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_TOKEN','prep-test-token')
    monkeypatch.setattr(storage,'DB',tmp_path/'prep.sqlite3')
    headers={'X-App-Token':'prep-test-token','Origin':'null'}
    with TestClient(app) as client:
        assert client.get('/api/state').status_code==401
        preflight=client.options('/api/state',headers={'Origin':'null','Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'X-App-Token'})
        assert preflight.status_code==200
        profile=client.post('/api/profiles',headers=headers,data={'name':'GCP practice','job_description':'BigQuery and Airflow'}).json()['id']
        response=client.post(f'/api/profiles/{profile}/documents',headers=headers,data={'kind':'resume'},files={'file':('resume.txt',b'Built Airflow CDC pipelines with MySQL and BigQuery.','text/plain')})
        assert response.status_code==200
        doc=response.json()['id']
        assert response.headers['access-control-allow-origin']=='*'
        with storage.connect() as db:
            assert storage.active_profile(db)['id']==profile
            assert any('MySQL' in c.text for c in storage.chunks_for(db,profile))
        state=client.get('/api/state',headers=headers).json()
        assert state['profiles'][0]['documents'][0]['id']==doc
        assert client.post(f'/api/profiles/{profile}/documents',headers=headers,data={'kind':'notes'},files={'file':('empty.txt',b'','text/plain')}).status_code==422
        assert client.post(f'/api/profiles/{profile}/documents',headers=headers,data={'kind':'notes'},files={'file':('broken.pdf',b'not a PDF','application/pdf')}).status_code==422
        assert client.delete('/api/documents/'+doc,headers=headers).status_code==200
        with storage.connect() as db:
            assert not any('MySQL' in c.text for c in storage.chunks_for(db,profile))
