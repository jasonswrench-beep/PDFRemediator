// PDF Remediator's own program window (PDF Remediator.exe in the installed folder).
//
// It starts the private local service with the packaged Python (launch_portable.py --no-open), shows the service's page in a
// window of its own, and stops the service when that window closes (launch_portable.py --stop). The page is drawn by
// Microsoft's WebView2, the same Windows component the other OpenStage-family programs use; no browser window, browser
// profile or browser tab is involved. The window and the service end together: closing the window stops the service, and
// when the service stops (the page's Stop application button) the window closes.
#![windows_subsystem = "windows"]

use std::ffi::c_void;
use std::io::Read;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tao::dpi::LogicalSize;
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tao::platform::run_return::EventLoopExtRunReturn;
use tao::platform::windows::{IconExtWindows, WindowBuilderExtWindows, WindowExtWindows};
use tao::window::{Icon, WindowBuilder};
use windows::core::{w, HSTRING, PCWSTR, PWSTR};
use windows::Win32::Foundation::{CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HWND};
use windows::Win32::Storage::FileSystem::{GetFileVersionInfoSizeW, GetFileVersionInfoW, VerQueryValueW, VS_FIXEDFILEINFO};
use windows::Win32::System::SystemInformation::GetSystemDirectoryW;
use windows::Win32::System::Threading::{CreateMutexW, OpenProcess, WaitForSingleObject, INFINITE, PROCESS_SYNCHRONIZE};
use windows::Win32::UI::Controls::Dialogs::{
    GetSaveFileNameW, OFN_EXPLORER, OFN_NOCHANGEDIR, OFN_OVERWRITEPROMPT, OFN_PATHMUSTEXIST, OPENFILENAMEW,
};
use windows::Win32::UI::Shell::ShellExecuteW;
use windows::Win32::UI::WindowsAndMessaging::{
    FindWindowW, IsIconic, MessageBoxW, SetForegroundWindow, ShowWindow, IDYES, MB_DEFBUTTON2, MB_ICONERROR, MB_ICONINFORMATION,
    MB_ICONWARNING, MB_OK, MB_YESNO, MESSAGEBOX_STYLE, SW_RESTORE, SW_SHOWNORMAL,
};
use wry::{NewWindowResponse, WebContext, WebViewBuilder};

const TITLE: &str = "PDF Remediator";
const WINDOW_CLASS: &str = "PDFRemediatorProgramWindow";
const MIN_VC_RUNTIME: &str = env!("PDFR_MIN_VC_RUNTIME");
const VC_RUNTIME_PAGE: &str = "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist";
const WEBVIEW_PAGE: &str = "https://developer.microsoft.com/en-us/microsoft-edge/webview2/";
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const OUTPUT_LIMIT: usize = 32768;

fn message(owner: Option<HWND>, text: &str, style: MESSAGEBOX_STYLE) -> bool {
    unsafe { MessageBoxW(owner, &HSTRING::from(text), &HSTRING::from(TITLE), style) == IDYES }
}

// Notes a problem in output/review-app/program-window.log beside the service's own log, so it can be found after the message is closed.
fn note_problem(text: &str) {
    let Some(root) = std::env::current_exe().ok().and_then(|program| program.parent().map(Path::to_path_buf)) else { return };
    let folder = root.join("output").join("review-app");
    let log = folder.join("program-window.log");
    if std::fs::metadata(&log).map(|data| data.len() > 1_000_000).unwrap_or(false) {
        return;
    }
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH).map(|time| time.as_secs()).unwrap_or(0);
    let _ = std::fs::create_dir_all(&folder).and_then(|_| {
        let mut file = std::fs::OpenOptions::new().create(true).append(true).open(&log)?;
        std::io::Write::write_all(&mut file, format!("{stamp} (seconds since 1970) {}\r\n", text.replace('\n', " ")).as_bytes())
    });
}

fn could_not_open(text: &str) -> i32 {
    note_problem(text);
    message(
        None,
        &format!("PDF Remediator could not open.\n\n{text}\n\nKeep this installation and saved reviews in place. See START-HERE.txt."),
        MB_OK | MB_ICONERROR,
    );
    1
}

// Opens a web address in the person's own browser. Only http and https addresses are ever passed on.
fn open_outside(address: &str) {
    if address.starts_with("https://") || address.starts_with("http://") {
        unsafe {
            ShellExecuteW(None, w!("open"), &HSTRING::from(address), PCWSTR::null(), PCWSTR::null(), SW_SHOWNORMAL);
        }
    }
}

// An address of the program's own private service, or a blob: address that service's page made.
fn is_own_address(address: &str, origin: &str) -> bool {
    address == origin || address.starts_with(&format!("{origin}/")) || address.starts_with(&format!("blob:{origin}/"))
}

// Shows the message and, if the person agrees, opens Microsoft's page in their browser. Nothing is downloaded by this program.
fn offer_page(text: &str, page: &str) -> i32 {
    note_problem(text);
    if message(None, &format!("{text}\n\nOpen Microsoft's page now?"), MB_YESNO | MB_ICONINFORMATION) {
        open_outside(page);
    }
    1
}

fn system_folder() -> PathBuf {
    let mut buffer = [0u16; 512];
    let length = unsafe { GetSystemDirectoryW(Some(&mut buffer)) } as usize;
    PathBuf::from(String::from_utf16_lossy(&buffer[..length.min(buffer.len())]))
}

fn file_version(path: &Path) -> Option<[u32; 4]> {
    let name = HSTRING::from(path.as_os_str());
    unsafe {
        let size = GetFileVersionInfoSizeW(&name, None);
        if size == 0 {
            return None;
        }
        let mut data = vec![0u8; size as usize];
        GetFileVersionInfoW(&name, None, size, data.as_mut_ptr() as *mut c_void).ok()?;
        let mut found: *mut c_void = std::ptr::null_mut();
        let mut length = 0u32;
        if !VerQueryValueW(data.as_ptr() as *const c_void, w!("\\"), &mut found, &mut length).as_bool()
            || found.is_null()
            || (length as usize) < std::mem::size_of::<VS_FIXEDFILEINFO>()
        {
            return None;
        }
        let info = &*(found as *const VS_FIXEDFILEINFO);
        Some([info.dwFileVersionMS >> 16, info.dwFileVersionMS & 0xffff, info.dwFileVersionLS >> 16, info.dwFileVersionLS & 0xffff])
    }
}

fn version_text(version: &[u32; 4]) -> String {
    version.iter().map(|part| part.to_string()).collect::<Vec<_>>().join(".")
}

// The package does not carry Microsoft's Visual C++ runtime files (Microsoft limits who may pass them on). The programs in it use
// the copy Microsoft's own free Redistributable puts in the Windows system folder, so this checks that it is there and recent enough.
// None when the computer is ready, otherwise a plain-language message.
fn vc_runtime_problem() -> Option<String> {
    let folder = system_folder();
    if !folder.join("ucrtbase.dll").is_file() {
        return Some("The required Windows C runtime is missing. Update Windows, then try again.".to_string());
    }
    let parts: Vec<u32> = MIN_VC_RUNTIME.split('.').map(|part| part.parse().unwrap_or(0)).collect();
    let minimum = [parts[0], parts[1], parts[2], parts[3]];
    let mut detail = None;
    for name in ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"] {
        let path = folder.join(name);
        if !path.is_file() {
            detail = Some(format!("{name} is missing."));
            break;
        }
        let found = file_version(&path).unwrap_or([0, 0, 0, 0]);
        if found < minimum {
            detail = Some(format!("{name} is version {}, which is older than {}.", version_text(&found), version_text(&minimum)));
            break;
        }
    }
    detail.map(|detail| {
        format!(
            "PDF Remediator needs Microsoft's free \"Visual C++ Redistributable\" (version {}) or newer, and this computer doesn't have it yet.\n\n\
             {detail}\n\nIt is not included in this package because Microsoft's licence does not let us pass it on. Install the current x64 \
             version from Microsoft, then try again.\n\nMicrosoft's page: {VC_RUNTIME_PAGE}",
            version_text(&minimum)
        )
    })
}

fn keep_end(text: &mut Vec<u8>, more: &[u8]) {
    let room = OUTPUT_LIMIT.saturating_sub(text.len());
    text.extend_from_slice(&more[..more.len().min(room)]);
}

fn startup_error(root: &Path, detail: &str) -> String {
    let folder = root.join("output").join("review-app");
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH).map(|time| time.as_nanos()).unwrap_or(0);
    let log = folder.join(format!("startup-error-{}-{stamp}.txt", std::process::id()));
    let saved = std::fs::create_dir_all(&folder).is_ok()
        && std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&log)
            .and_then(|mut file| std::io::Write::write_all(&mut file, detail.as_bytes()))
            .is_ok();
    if saved {
        format!("The local workspace could not start.\n\nDetails were saved here:\n{}", log.display())
    } else {
        "The local workspace could not start. Check the installation files and START-HERE.txt.".to_string()
    }
}

// Runs the packaged Python on launch_portable.py (argument: --no-open or --stop) and waits for it to finish.
fn run_python(root: &Path, python: &Path, argument: &str, wait: Duration, slow: &str) -> Result<(), String> {
    let mut child = Command::new(python)
        .arg("-B")
        .arg("-X")
        .arg("utf8")
        .arg(root.join("launch_portable.py"))
        .arg(argument)
        .current_dir(root)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|error| startup_error(root, &format!("The packaged Python could not be started: {error}")))?;
    let mut readers = Vec::new();
    for mut stream in [child.stdout.take().map(|s| Box::new(s) as Box<dyn Read + Send>), child.stderr.take().map(|s| Box::new(s) as Box<dyn Read + Send>)]
        .into_iter()
        .flatten()
    {
        readers.push(std::thread::spawn(move || {
            let mut kept = Vec::new();
            let mut block = [0u8; 4096];
            while let Ok(count) = stream.read(&mut block) {
                if count == 0 {
                    break;
                }
                keep_end(&mut kept, &block[..count]);
            }
            kept
        }));
    }
    let deadline = Instant::now() + wait;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            Ok(None) => return Err(slow.to_string()),
            Err(error) => return Err(startup_error(root, &format!("Waiting for the packaged Python failed: {error}"))),
        }
    };
    let mut output = Vec::new();
    for reader in readers {
        if let Ok(kept) = reader.join() {
            keep_end(&mut output, &kept);
        }
    }
    if status.success() {
        Ok(())
    } else {
        Err(startup_error(root, &String::from_utf8_lossy(&output)))
    }
}

// The private address and process number that the service saved, accepted only if the address points at this computer's own service.
struct Session {
    url: String,
    origin: String,
    pid: u32,
}

fn json_value<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    let after = &text[text.find(&format!("\"{key}\""))? + key.len() + 2..];
    let after = after.trim_start().strip_prefix(':')?.trim_start();
    if let Some(quoted) = after.strip_prefix('"') {
        Some(&quoted[..quoted.find('"')?])
    } else {
        Some(&after[..after.find(|c: char| !c.is_ascii_digit()).unwrap_or(after.len())])
    }
}

fn read_session(root: &Path) -> Option<Session> {
    let text = std::fs::read_to_string(root.join("output").join("review-app").join(".private-session.json")).ok()?;
    let url = json_value(&text, "url")?.to_string();
    let rest = url.strip_prefix("http://127.0.0.1:")?;
    let (port, token) = rest.split_once("/#")?;
    let port_ok = !port.is_empty() && port.len() <= 5 && port.chars().all(|c| c.is_ascii_digit());
    let token_ok = (16..=128).contains(&token.len()) && token.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_');
    if !port_ok || !token_ok {
        return None;
    }
    let pid = json_value(&text, "pid")?.parse().ok()?;
    Some(Session { origin: format!("http://127.0.0.1:{port}"), url, pid })
}

// One name per installation folder, so a second start of the same installation brings its window forward instead of starting again.
fn instance_name(root: &Path) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in root.display().to_string().to_uppercase().bytes() {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("Local\\PDFRemediatorProgram-{hash:016x}")
}

fn bring_forward_existing_window() {
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        if let Ok(window) = unsafe { FindWindowW(&HSTRING::from(WINDOW_CLASS), PCWSTR::null()) } {
            unsafe {
                if IsIconic(window).as_bool() {
                    let _ = ShowWindow(window, SW_RESTORE);
                }
                let _ = SetForegroundWindow(window);
            }
            return;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

// Asks where to save a file the page offers (a result, a review record), the way a desktop program does.
fn ask_where_to_save(owner: isize, suggested: &mut PathBuf) -> bool {
    let name = suggested.file_name().map(|name| name.to_string_lossy().into_owned()).unwrap_or_else(|| "download".to_string());
    let folder = suggested.parent().map(|folder| folder.to_path_buf());
    let extension = Path::new(&name).extension().map(|extension| extension.to_string_lossy().into_owned()).unwrap_or_default();
    let mut file: Vec<u16> = name.encode_utf16().collect();
    file.resize(32768, 0);
    let mut filter: Vec<u16> = Vec::new();
    if !extension.is_empty() {
        for part in [format!("{} file (*.{extension})", extension.to_uppercase()), format!("*.{extension}")] {
            filter.extend(part.encode_utf16());
            filter.push(0);
        }
    }
    for part in ["All files (*.*)", "*.*"] {
        filter.extend(part.encode_utf16());
        filter.push(0);
    }
    filter.push(0);
    let folder_text: Option<HSTRING> = folder.as_ref().map(|folder| HSTRING::from(folder.as_os_str()));
    let extension_text = HSTRING::from(extension.as_str());
    let mut dialog = OPENFILENAMEW {
        lStructSize: std::mem::size_of::<OPENFILENAMEW>() as u32,
        hwndOwner: HWND(owner as *mut c_void),
        lpstrFilter: PCWSTR(filter.as_ptr()),
        lpstrFile: PWSTR(file.as_mut_ptr()),
        nMaxFile: file.len() as u32,
        lpstrInitialDir: folder_text.as_ref().map(|text| PCWSTR(text.as_ptr())).unwrap_or(PCWSTR::null()),
        lpstrDefExt: if extension.is_empty() { PCWSTR::null() } else { PCWSTR(extension_text.as_ptr()) },
        Flags: OFN_EXPLORER | OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR,
        ..Default::default()
    };
    if !unsafe { GetSaveFileNameW(&mut dialog) }.as_bool() {
        return false;
    }
    let length = file.iter().position(|&unit| unit == 0).unwrap_or(file.len());
    *suggested = PathBuf::from(String::from_utf16_lossy(&file[..length]));
    true
}

enum Note {
    CloseAnswer(u32, bool),
    ServiceEnded,
}

fn main() {
    std::process::exit(run());
}

fn run() -> i32 {
    if std::env::args_os().len() > 1 {
        return could_not_open("Open PDF Remediator without command-line arguments.");
    }
    if let Some(problem) = vc_runtime_problem() {
        return offer_page(&problem, VC_RUNTIME_PAGE);
    }
    let root = match std::env::current_exe().ok().and_then(|program| program.parent().map(Path::to_path_buf)) {
        Some(root) => root,
        None => return could_not_open("The program could not find its own folder."),
    };
    let python = root.join("runtime").join("python").join("python.exe");
    if !python.is_file() || !root.join("local-runtime.toml").is_file() || !root.join(".installation-complete.json").is_file() {
        return could_not_open("This installation is incomplete. Keep the existing folder and saved reviews, then install a fresh copy.");
    }
    if wry::webview_version().is_err() {
        return offer_page(
            "PDF Remediator shows its window with Microsoft's \"WebView2 Runtime\", which comes with Windows 11 and current Windows 10. \
             This computer doesn't have it. Install the free Evergreen version from Microsoft, then try again.",
            WEBVIEW_PAGE,
        );
    }

    // One program per installation owns the window and the service; a second start only brings that window forward.
    let _instance = unsafe { CreateMutexW(None, false, &HSTRING::from(instance_name(&root))) };
    if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
        bring_forward_existing_window();
        return 0;
    }

    let slow = "The local workspace did not finish opening. Check output/review-app/application.log before trying again. Saved work stays in place.";
    if let Err(problem) = run_python(&root, &python, "--no-open", Duration::from_secs(30), slow) {
        return could_not_open(&problem);
    }
    let session = match read_session(&root) {
        Some(session) => session,
        None => return could_not_open("The local workspace started, but its address could not be read. Check output/review-app/application.log."),
    };
    let service = match unsafe { OpenProcess(PROCESS_SYNCHRONIZE, false, session.pid) } {
        Ok(handle) => handle.0 as isize,
        Err(_) => return could_not_open("The local workspace stopped before its window opened. Check output/review-app/application.log."),
    };

    let mut events = EventLoopBuilder::<Note>::with_user_event().build();
    let proxy = events.create_proxy();
    let icon = Icon::from_resource(1, None).ok();
    let window = match WindowBuilder::new()
        .with_title(TITLE)
        .with_window_classname(WINDOW_CLASS)
        .with_window_icon(icon.clone())
        .with_taskbar_icon(icon)
        .with_inner_size(LogicalSize::new(1280.0, 860.0))
        .with_min_inner_size(LogicalSize::new(720.0, 520.0))
        .with_visible(false)
        .build(&events)
    {
        Ok(window) => window,
        Err(error) => return could_not_open(&format!("Its window could not be made: {error}")),
    };
    let owner = window.hwnd() as isize;
    let mut context = WebContext::new(Some(root.join("output").join("review-app").join("program-window")));
    let origin = session.origin.clone();
    let navigation_origin = session.origin.clone();
    let built = WebViewBuilder::new_with_web_context(&mut context)
        .with_url(&session.url)
        .with_focused(true)
        // Only the program's own pages (and the files they hand over as blob: addresses) are shown in this window. Links to other web
        // sites (help pages, licences) open in the person's own browser; any other kind of address (file:, data: and so on) is refused.
        .with_navigation_handler(move |address| {
            if is_own_address(&address, &navigation_origin) || address == "about:blank" {
                true
            } else {
                open_outside(&address);
                false
            }
        })
        .with_new_window_req_handler(move |address, _features| {
            if is_own_address(&address, &origin) {
                NewWindowResponse::Allow
            } else {
                open_outside(&address);
                NewWindowResponse::Deny
            }
        })
        .with_download_started_handler(move |_address, path| ask_where_to_save(owner, path))
        .build(&window);
    let webview = match built {
        Ok(webview) => webview,
        Err(error) => {
            let _ = run_python(&root, &python, "--stop", Duration::from_secs(20), "");
            return could_not_open(&format!("Its window could not show the workspace: {error}"));
        }
    };
    window.set_visible(true);

    // When the service ends (the page's Stop application button, or anything else), the window closes too.
    let ended = proxy.clone();
    std::thread::spawn(move || {
        unsafe {
            let handle = windows::Win32::Foundation::HANDLE(service as *mut c_void);
            WaitForSingleObject(handle, INFINITE);
            let _ = CloseHandle(handle);
        }
        let _ = ended.send_event(Note::ServiceEnded);
    });

    let mut asking = false;
    let mut question = 0u32;
    events.run_return(|event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } if !asking => {
                // A review with changes that are not saved asks first, as it did before.
                asking = true;
                question += 1;
                let asked = question;
                let answer = proxy.clone();
                let late = proxy.clone();
                let script = "(typeof reviewHasUnsavedFields==='function'&&reviewHasUnsavedFields())?'unsaved':'clean'";
                if webview.evaluate_script_with_callback(script, move |result| {
                    let _ = answer.send_event(Note::CloseAnswer(asked, result.contains("unsaved")));
                })
                .is_err()
                {
                    *control_flow = ControlFlow::Exit;
                }
                // A page that does not answer does not keep the window open.
                std::thread::spawn(move || {
                    std::thread::sleep(Duration::from_secs(3));
                    let _ = late.send_event(Note::CloseAnswer(asked, false));
                });
            }
            Event::UserEvent(Note::CloseAnswer(asked, unsaved)) if asking && asked == question => {
                let close = !unsaved
                    || message(
                        Some(HWND(owner as *mut c_void)),
                        "The open review has changes that are not saved.\n\nClose PDF Remediator anyway? Those changes will be lost.",
                        MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2,
                    );
                if close {
                    window.set_visible(false);
                    *control_flow = ControlFlow::Exit;
                } else {
                    asking = false;
                }
            }
            Event::UserEvent(Note::ServiceEnded) => {
                note_problem("The local service ended, so the window closed with it.");
                window.set_visible(false);
                *control_flow = ControlFlow::Exit;
            }
            Event::WindowEvent { event: WindowEvent::Destroyed, .. } => *control_flow = ControlFlow::Exit,
            _ => {}
        }
    });
    drop(webview);
    drop(window);
    // The window is closed: stop the service the way the Stop application button does. Failing here is not worth an error box.
    let _ = run_python(&root, &python, "--stop", Duration::from_secs(20), "");
    0
}
