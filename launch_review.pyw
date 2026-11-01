"""Windows double-click entry point; the helper stays out of the user's way."""
from pathlib import Path
import sys


def _startup_error_message(error):
    message = str(error)
    if (getattr(error, 'winerror', None) == 206 or
            any(part in message.casefold() for part in
                ('filename or extension is too long', 'file name or extension is too long',
                 'path is too long', 'path too long'))):
        return ('Windows could not load the application from this folder because a path is too long.\n\n'
                'Create a fresh installation in a shorter local folder and run Setup PDF Remediator.cmd there. '
                'Leave this installation, original PDFs and saved reviews in place. '
                'A new installation does not automatically transfer saved reviews.\n\n'
                'See START-HERE.md for installation recovery instructions.\n\nTechnical detail: ' + message)
    if isinstance(error, ImportError):
        return (message + '\n\nRun Setup PDF Remediator.cmd to check the application environment. '
                'See START-HERE.md for setup instructions.')
    return message + '\n\nOpen START-HERE.md for setup instructions.'


try:
    from pdf_remediator.launcher import launch
    launch(Path(__file__).resolve().parent/'output/review-app')
except Exception as exc:
    import tkinter as tk
    from tkinter import messagebox
    root=tk.Tk();root.withdraw()
    messagebox.showerror('PDF Remediator could not start', _startup_error_message(exc))
    root.destroy()
