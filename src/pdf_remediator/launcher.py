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


# What Windows means by the codes a program that crashed ends with. A program that ended by itself, however it was meant to, ends with a small number.
_CRASH_CODES = {
    0xC0000005: 'an access violation (the program touched memory it may not use)',
    0xC0000409: 'a stack buffer overrun, which Windows stops a program for at once',
    0xC000013A: 'Ctrl+C, or its window being closed',
    0xC0000142: 'a library that would not start',
    0xC0000135: 'a library it needs was not found',
    0xC00000FD: 'a stack overflow',
    0xC0000374: 'damage to the program\'s memory (a corrupted heap)',
}


def describe_exit_code(code):
    """In plain words, how a program that has ended did so, from the number it ended with. An unrecognised number is still given, in the form Windows' own messages use."""
    if code is None:return 'It was still running.'
    if code == 0:return 'It ended normally, with code 0.'
    unsigned=code & 0xFFFFFFFF
    if unsigned in _CRASH_CODES:return 'It crashed: Windows reports %s (code 0x%08X).'%(_CRASH_CODES[unsigned],unsigned)
    if unsigned >= 0xC0000000:return 'It crashed: Windows reports an error it has no short name for (code 0x%08X).'%unsigned
    return 'It ended with code %d.'%code


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
        ended=child.poll()
        if ended is not None:raise RuntimeError('The review application could not start: it ended at once. '+describe_exit_code(ended)+' See '+str(root/'application.log')+' for what it printed.')
        url=_running(session,expected)
        if url:
            if open_browser:webbrowser.open(url)
            return 'Opened the local review workspace.'
        time.sleep(.1)
    raise RuntimeError('The local review service did not become ready. See '+str(root/'application.log'))
