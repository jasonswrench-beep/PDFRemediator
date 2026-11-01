"""Desktop launch and setup readiness boundaries; no browser is opened."""
import json
import os
from pathlib import Path
import socket
import time
import pytest
from pdf_remediator import cli,doctor,launcher,pipeline
from test_pipeline import input_pdf, fast_validator, tagged_control
from test_web import application, http_app


@pytest.mark.parametrize('url',['https://example.com/#secret','file:///C:/secret.pdf','http://localhost:9999/#secret',
    'http://127.0.0.1:9999/other#secret','http://name:password@127.0.0.1:9999/#secret','http://127.0.0.1:9999/'])
def test_session_file_cannot_redirect_launcher_to_another_destination(tmp_path,monkeypatch,url):
    path=tmp_path/'session.json';path.write_text(json.dumps({'url':url}))
    monkeypatch.setattr(launcher.http.client,'HTTPConnection',lambda *a,**k:pytest.fail('Unsafe session reached the network'))
    assert launcher._running(path) is None


def test_launcher_reuses_the_existing_private_service(tmp_path,monkeypatch):
    opened=[]
    monkeypatch.setattr(launcher,'_running',lambda path,*args:'http://127.0.0.1:9999/#fixture-token')
    monkeypatch.setattr(launcher.webbrowser,'open',opened.append)
    monkeypatch.setattr(launcher.subprocess,'Popen',lambda *a,**k:pytest.fail('A second service was started'))
    assert 'Reopened' in launcher.launch(tmp_path)
    assert opened==['http://127.0.0.1:9999/#fixture-token']


def test_launcher_creates_a_hidden_bounded_startup_helper(tmp_path,monkeypatch):
    seen=[];opened=[];probes=iter([None,'http://127.0.0.1:9999/#fixture-token'])
    monkeypatch.setattr(launcher,'_running',lambda path,*args:next(probes))
    monkeypatch.setattr(launcher.webbrowser,'open',opened.append)
    class Child:
        def poll(self):return None
    def start(command,**kwargs):seen.append((command,kwargs));return Child()
    monkeypatch.setattr(launcher.subprocess,'Popen',start)
    assert 'Opened' in launcher.launch(tmp_path)
    assert seen[0][0][1:4]==['-m','pdf_remediator','serve']
    assert '--no-open' in seen[0][0]
    if os.name=='nt':assert seen[0][1]['creationflags']==launcher.subprocess.CREATE_NO_WINDOW
    assert opened==['http://127.0.0.1:9999/#fixture-token']


@pytest.mark.parametrize('explicit',[False,True])
def test_launcher_forwards_validated_local_config_from_project_not_working_directory(tmp_path,monkeypatch,explicit):
    from pdf_remediator.config import RuntimeConfig
    project=tmp_path/'project';project.mkdir()
    config=project/'local-runtime.toml'
    config.write_text('[runtime]\nvalidator_cli = "native/verapdf"\nocr_mode = "off"\n')
    monkeypatch.setattr(launcher,'RuntimeConfig',lambda:RuntimeConfig(project_root=project))
    monkeypatch.chdir(tmp_path)
    probes=iter([None,'http://127.0.0.1:9999/#fixture-token']);seen=[]
    monkeypatch.setattr(launcher,'_running',lambda path,*args:next(probes))
    monkeypatch.setattr(launcher.webbrowser,'open',lambda url:None)
    class Child:
        def poll(self):return None
    monkeypatch.setattr(launcher.subprocess,'Popen',lambda command,**kwargs:seen.append(command) or Child())
    launcher.launch(tmp_path/'review',**({'config_path':config} if explicit else {}))
    command=seen[0]
    assert command[command.index('--config')+1]==str(config.resolve())
    assert config.read_text().endswith('ocr_mode = "off"\n')


@pytest.mark.parametrize('contents',[None,'not valid TOML','[runtime]\nocr_mode="forced"\n'])
def test_launcher_never_falls_back_from_missing_or_invalid_explicit_config(tmp_path,monkeypatch,contents):
    config=tmp_path/'settings.toml'
    if contents is not None:config.write_text(contents)
    monkeypatch.setattr(launcher.subprocess,'Popen',lambda *a,**kw:pytest.fail('Invalid settings started a child'))
    with pytest.raises((OSError,ValueError)):
        launcher.launch(tmp_path/'review',config_path=config)


@pytest.mark.parametrize('command',['doctor','engines'])
@pytest.mark.parametrize('status',['incomplete','missing','failed','error'])
def test_setup_cannot_report_ready_when_the_tool_inventory_is_incomplete(monkeypatch,capsys,command,status):
    monkeypatch.setattr(doctor,'inventory',lambda **kwargs:{'status':status,'capabilities':{'tagging':False,'validation':False}})
    assert cli.main([command])==1
    capsys.readouterr()


def test_serve_rejects_an_invalid_port_before_starting_a_service(capsys):
    assert cli.main(['serve','--port','65536','--no-open'])==1
    assert 'valid local port' in capsys.readouterr().err


def test_accepted_sidecar_changed_while_queued_never_starts_processing(input_pdf,tmp_path,fast_validator):
    original=pipeline.process_file(input_pdf,tmp_path/'first',__import__('pdf_remediator.config',fromlist=['RuntimeConfig']).RuntimeConfig())
    decisions=Path(original['bundle_path'])/'decisions.json';copied=tmp_path/'accepted.json';copied.write_bytes(decisions.read_bytes())
    expected=pipeline.sha(copied);copied.write_bytes(copied.read_bytes()+b'\n')
    calls=len(fast_validator)
    with pytest.raises(ValueError,match='Accepted decisions changed while waiting'):
        pipeline.process_file(input_pdf,tmp_path/'next',__import__('pdf_remediator.config',fromlist=['RuntimeConfig']).RuntimeConfig(),sidecar=copied,expected_sidecar_sha256=expected)
    assert len(fast_validator)==calls and not (tmp_path/'next').exists()


def test_service_session_records_startup_identity_without_configuration_values(tmp_path,monkeypatch,capsys):
    from pdf_remediator import web
    from pdf_remediator.config import RuntimeConfig
    config=RuntimeConfig(project_root=tmp_path)
    class Server:
        origin='http://127.0.0.1:9999'
        def __init__(self,*a):pass
        def serve_forever(self,**kw):pass
        def server_close(self):pass
    monkeypatch.setattr(web,'ReviewServer',Server)
    session=tmp_path/'session.json'
    web.serve(tmp_path/'service',config,open_browser=False,session_file=session)
    saved=json.loads(session.read_text())
    assert saved['settings_digest']==config.digest()
    assert saved['implementation_digest']==pipeline.implementation_digest(config)
    assert set(saved)=={'url','origin','pid','implementation_digest','settings_digest'}
    assert saved['url'] not in capsys.readouterr().out


# --- the packaged program opens its page in its own window and stops the service when that window closes -----------

def test_launcher_can_leave_opening_the_page_to_its_caller(tmp_path,monkeypatch):
    opened=[];probes=iter([None,'http://127.0.0.1:9999/#fixture-token'])
    monkeypatch.setattr(launcher,'_running',lambda path,*args:next(probes))
    monkeypatch.setattr(launcher.webbrowser,'open',opened.append)
    class Child:
        def poll(self):return None
    monkeypatch.setattr(launcher.subprocess,'Popen',lambda command,**kwargs:Child())
    assert 'Opened' in launcher.launch(tmp_path,open_browser=False)
    assert opened==[]


def test_reopening_can_also_leave_the_page_to_its_caller(tmp_path,monkeypatch):
    opened=[]
    monkeypatch.setattr(launcher,'_running',lambda path,*args:'http://127.0.0.1:9999/#fixture-token')
    monkeypatch.setattr(launcher.webbrowser,'open',opened.append)
    assert 'Reopened' in launcher.launch(tmp_path,open_browser=False)
    assert opened==[]


def test_stop_asks_the_running_service_the_way_the_stop_button_does(http_app,tmp_path):
    app,server=http_app
    (tmp_path/'.private-session.json').write_text(json.dumps({'url':server.origin+'/#'+app.token}))
    assert launcher.stop(tmp_path)=='Stopped the local review workspace.'
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        try:
            socket.create_connection(('127.0.0.1',server.server_port),timeout=.3).close()
        except OSError:break
        time.sleep(.05)
    else:pytest.fail('The service kept accepting connections after the stop request')


def test_stop_with_a_wrong_token_is_refused_by_the_service(http_app,tmp_path):
    app,server=http_app
    (tmp_path/'.private-session.json').write_text(json.dumps({'url':server.origin+'/#not-the-token'}))
    assert launcher.stop(tmp_path)=='The local review workspace did not accept the stop request.'
    socket.create_connection(('127.0.0.1',server.server_port),timeout=2).close()


@pytest.mark.parametrize('contents',[None,'not json','{"url":"http://127.0.0.1:1/#secret"}'])
def test_stop_of_a_service_that_is_not_running_is_not_an_error(tmp_path,contents):
    if contents is not None:(tmp_path/'.private-session.json').write_text(contents)
    assert launcher.stop(tmp_path)=='The local review workspace is not running.'


@pytest.mark.parametrize('url',['https://example.com/#secret','file:///C:/secret.pdf','http://localhost:9999/#secret',
    'http://127.0.0.1:9999/other#secret','http://name:password@127.0.0.1:9999/#secret','http://127.0.0.1:9999/'])
def test_stop_never_contacts_a_session_that_points_elsewhere(tmp_path,monkeypatch,url):
    (tmp_path/'.private-session.json').write_text(json.dumps({'url':url}))
    monkeypatch.setattr(launcher.http.client,'HTTPConnection',lambda *a,**k:pytest.fail('Unsafe session reached the network'))
    assert launcher.stop(tmp_path)=='The local review workspace is not running.'


def test_stop_button_closes_an_own_window_after_the_service_has_stopped():
    script=(Path(__file__).resolve().parents[1]/'src/pdf_remediator/web_assets/app.js').read_text(encoding='utf-8')
    handler=script[script.index("$('stop').addEventListener"):]
    assert handler.index("await api('/api/stop',{})")<handler.index('stopped=true;')<handler.index('window.close()')
