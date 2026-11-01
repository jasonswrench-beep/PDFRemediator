"""Start or reopen the user's private desktop review service."""
from __future__ import annotations
import http.client
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from .config import RuntimeConfig, load_config
from .pipeline import implementation_digest


def _target(session):
    """The saved private address, only if it points at this computer's own service; anything else is never contacted."""
    saved=json.loads(session.read_text(encoding='utf-8'));url=urllib.parse.urlsplit(saved['url'])
    if url.scheme!='http' or url.hostname!='127.0.0.1' or url.path!='/' or not url.fragment or url.username or url.password:return None
    return saved,url


def _running(session,expected=None):
    try:
        target=_target(session)
        if target is None:return None
        saved,url=target
        connection=http.client.HTTPConnection('127.0.0.1',url.port,timeout=2)
        try:
            connection.request('GET','/api/dashboard',headers={'X-Review-Token':url.fragment})
            response=connection.getresponse();response.read(1024**2)
            if response.status!=200:return None
            if expected is not None and any(saved.get(key)!=value for key,value in expected.items()):
                raise RuntimeError('PDF Remediator is still running with older code or different settings. '
                    'Open its existing window or browser page and click Stop application, then start it again. '
                    'Your PDFs and saved reviews stay in place.')
            return saved['url']
        finally:connection.close()
    except (OSError,ValueError,KeyError,http.client.HTTPException):return None


def stop(data_dir=None):
    """Ask the running private service to stop, as the page's Stop application button does. A service that is not running is not an error."""
    root=Path(data_dir or RuntimeConfig().project_root/'output/review-app').resolve()
    try:
        target=_target(root/'.private-session.json')
        if target is None:return 'The local review workspace is not running.'
        saved,url=target
        connection=http.client.HTTPConnection('127.0.0.1',url.port,timeout=5)
        try:
            connection.request('POST','/api/stop',body=b'{}',headers={'Content-Type':'application/json','X-Review-Token':url.fragment})
            response=connection.getresponse();response.read(1024**2)
            return 'Stopped the local review workspace.' if response.status==200 else 'The local review workspace did not accept the stop request.'
        finally:connection.close()
    except (OSError,ValueError,KeyError,http.client.HTTPException):return 'The local review workspace is not running.'


def launch(data_dir=None,config_path=None,open_browser=True):
    """Start or reopen the service. With open_browser false the caller (the packaged launcher's own window) shows the page."""
    candidate=Path(config_path).resolve() if config_path is not None else RuntimeConfig().project_root/'local-runtime.toml'
    selected=candidate if config_path is not None or candidate.exists() else None
    config=load_config(selected) if selected is not None else RuntimeConfig()
    expected={'implementation_digest':implementation_digest(config),'settings_digest':config.digest()}
    root=Path(data_dir or RuntimeConfig().project_root/'output/review-app').resolve();root.mkdir(parents=True,exist_ok=True)
    session=root/'.private-session.json';url=_running(session,expected)
    if url:
        if open_browser:webbrowser.open(url)
        return 'Reopened the local review workspace.'
    session.unlink(missing_ok=True)
    python=Path(sys.executable)
    if python.name.lower()=='pythonw.exe':python=python.with_name('python.exe')
    command=[str(python),'-m','pdf_remediator','serve','--data-dir',str(root),'--no-open','--session-file',str(session)]
    if selected is not None:command.extend(['--config',str(selected.resolve())])
    with (root/'application.log').open('ab') as log:
        child=subprocess.Popen(command,stdout=log,stderr=log,stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
    for _ in range(100):
        if child.poll() is not None:raise RuntimeError('The review application could not start. See '+str(root/'application.log'))
        url=_running(session,expected)
        if url:
            if open_browser:webbrowser.open(url)
            return 'Opened the local review workspace.'
        time.sleep(.1)
    raise RuntimeError('The local review service did not become ready. See '+str(root/'application.log'))
