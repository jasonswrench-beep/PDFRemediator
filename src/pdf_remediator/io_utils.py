"""Bounded retries for transient Windows file-sharing conflicts."""
import os,time

def atomic_replace(source,destination):
    for attempt in range(7):
        try:
            os.replace(source,destination);return
        except OSError as exc:
            if getattr(exc,'winerror',None) not in (5,32,33) or attempt==6:raise
            time.sleep(min(.025*2**attempt,.4))
