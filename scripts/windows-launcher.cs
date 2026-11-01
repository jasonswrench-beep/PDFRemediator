using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class RemediatorLauncher {
    static void AppendBounded(StringBuilder output, string line) {
        if (line == null) return;
        lock(output) {
            int remaining = 32768 - output.Length;
            if (remaining <= 0) return;
            output.Append(line.Length > remaining ? line.Substring(0, remaining) : line);
            remaining = 32768 - output.Length;
            if (remaining > 0) output.Append('\n');
        }
    }
    static string FailureDetail(string detail) {
        try {
            string folder = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "output", "review-app");
            Directory.CreateDirectory(folder);
            string log = Path.Combine(folder, "startup-error-" + Guid.NewGuid().ToString("N") + ".txt");
            byte[] data = new UTF8Encoding(false).GetBytes(detail.Length > 32768 ? detail.Substring(0, 32768) : detail);
            using (var file = new FileStream(log, FileMode.CreateNew)) file.Write(data, 0, Math.Min(data.Length, 32768));
            return "The local workspace could not start.\n\nDetails were saved here:\n" + log;
        } catch { return "The local workspace could not start. Check the installation files and START-HERE.txt."; }
    }
    // Runs the packaged Python on launch_portable.py (argument: "", "--no-open" or "--stop") and waits for it to finish.
    static void RunPython(string root, string python, string argument, int waitMilliseconds, string slowMessage) {
        var info = new ProcessStartInfo(python, "-B -X utf8 \"" + Path.Combine(root, "launch_portable.py") + "\"" + (argument.Length == 0 ? "" : " " + argument));
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.EnvironmentVariables.Remove("PYTHONHOME");
        info.EnvironmentVariables.Remove("PYTHONPATH");
        var output = new StringBuilder();
        using (var process = new Process()) {
            process.StartInfo = info;
            process.OutputDataReceived += (s,e) => AppendBounded(output, e.Data);
            process.ErrorDataReceived += (s,e) => AppendBounded(output, e.Data);
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            if (!process.WaitForExit(waitMilliseconds)) throw new InvalidOperationException(slowMessage);
            process.WaitForExit();
            if (process.ExitCode != 0) throw new InvalidOperationException(FailureDetail(output.ToString()));
        }
    }
    static bool TakeOwnership(Mutex mutex) {
        try { return mutex.WaitOne(0); } catch (AbandonedMutexException) { return true; }
    }
    [STAThread]
    static int Main(string[] args) {
        try {
            if (args.Length != 0) throw new InvalidOperationException("Open PDF Remediator without command-line arguments.");
            string runtime = VcRuntime.Problem();
            if (runtime != null) { VcRuntime.OfferDownload(runtime); return 1; }
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "python", "python.exe");
            if (!File.Exists(python) || !File.Exists(Path.Combine(root, "local-runtime.toml")) ||
                !File.Exists(Path.Combine(root, ".installation-complete.json")))
                throw new InvalidOperationException("This installation is incomplete. Keep the existing folder and saved reviews, then install a fresh copy.");
            // The page is shown in its own window (Microsoft Edge or Chrome without tabs or address bar) when one can be found;
            // otherwise Python opens the default browser, as before.
            string browser = AppWindow.Find();
            string slow = "The local workspace did not finish opening. Check output/review-app/application.log before trying again. Saved work stays in place.";
            if (browser == null) { RunPython(root, python, "", 30000, slow); return 0; }
            // One launcher per installation waits for the window and stops the service when it closes; a second launch only opens another window.
            string name = "Local\\PDFRemediatorWindow-" + Convert.ToBase64String(SHA256.Create().ComputeHash(Encoding.UTF8.GetBytes(root.ToUpperInvariant()))).Replace('/', '_').Replace('+', '-').TrimEnd('=');
            using (var mutex = new Mutex(false, name)) {
                bool host = TakeOwnership(mutex);
                try {
                    RunPython(root, python, "--no-open", 30000, slow);
                    string url = AppWindow.SessionUrl(root);
                    if (url == null) throw new InvalidOperationException("The local workspace started, but its address could not be read. Check output/review-app/application.log.");
                    using (Process window = AppWindow.Open(browser, url, Path.Combine(root, "output", "review-app", "window-profile"))) {
                        if (host && window != null) window.WaitForExit();
                    }
                    if (host) {
                        // The window is closed: stop the service the way the Stop application button does. Failing here is not worth an error box.
                        try { RunPython(root, python, "--stop", 20000, "The local workspace is still stopping."); } catch (Exception) { }
                    }
                } finally { if (host) mutex.ReleaseMutex(); }
            }
            return 0;
        } catch (Exception error) {
            MessageBox.Show("PDF Remediator could not open.\n\n" + error.Message +
                "\n\nKeep this installation and saved reviews in place. See START-HERE.txt.",
                "PDF Remediator", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}

// Shows the private local page in its own window by using the Chromium browser that comes with Windows (Microsoft Edge) or Chrome in "app"
// mode, with a profile of its own so that it never touches the person's browsing. Nothing is installed or downloaded.
internal static class AppWindow {
    static string FromRegistry(RegistryKey hive, string leaf) {
        try {
            using (var key = hive.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\" + leaf)) {
                string path = key == null ? null : key.GetValue(null) as string;
                return path != null && File.Exists(path) ? path : null;
            }
        } catch (Exception) { return null; }
    }
    internal static string Find() {
        string found = FromRegistry(Registry.LocalMachine, "msedge.exe") ?? FromRegistry(Registry.CurrentUser, "msedge.exe");
        if (found != null) return found;
        foreach (string path in new string[] {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Microsoft", "Edge", "Application", "msedge.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Microsoft", "Edge", "Application", "msedge.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Google", "Chrome", "Application", "chrome.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Google", "Chrome", "Application", "chrome.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Google", "Chrome", "Application", "chrome.exe") })
            if (File.Exists(path)) return path;
        return null;
    }
    // The private address that the service saved, accepted only if it points at this computer's own service.
    internal static string SessionUrl(string root) {
        try {
            string text = File.ReadAllText(Path.Combine(root, "output", "review-app", ".private-session.json"), Encoding.UTF8);
            Match match = Regex.Match(text, "\"url\"\\s*:\\s*\"(http://127\\.0\\.0\\.1:[0-9]{1,5}/#[A-Za-z0-9_-]{16,128})\"");
            return match.Success ? match.Groups[1].Value : null;
        } catch (Exception) { return null; }
    }
    internal static string Arguments(string url, string profile) {
        return "--app=" + url + " \"--user-data-dir=" + profile + "\" --no-first-run --no-default-browser-check --disable-sync";
    }
    internal static Process Open(string browser, string url, string profile) {
        var info = new ProcessStartInfo(browser, Arguments(url, profile));
        info.UseShellExecute = false;
        return Process.Start(info);
    }
}
