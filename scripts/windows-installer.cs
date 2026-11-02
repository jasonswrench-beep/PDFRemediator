using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class InternalInstaller {
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode,
        SetLastError = true, EntryPoint = "CreateDirectoryW")]
    [return: System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.Bool)]
    static extern bool CreateFreshDirectory(string path, IntPtr securityAttributes);
    const string PayloadHash = "__PAYLOAD_SHA256__";
    const string PythonVersion = "__PYTHON_VERSION__";
    const string PythonAbi = "__PYTHON_ABI__";
    const string RuntimeLockHash = "__RUNTIME_LOCK_SHA256__";
    const bool OcrEnabled = "__OCR_ENABLED__" == "true";
    const string OcrRuntimeLockHash = "__OCR_RUNTIME_LOCK_SHA256__";
    const long Limit = 2147483648;
    static readonly HashSet<string> Reserved = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
        "CON","PRN","AUX","NUL","COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
        "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9" };
    sealed class RuntimeMissing : InvalidOperationException { public RuntimeMissing(string message) : base(message) { } }
    static string Hex(byte[] data) { return BitConverter.ToString(data).Replace("-", "").ToLowerInvariant(); }
    static string Hash(Stream stream) { using (var hash = SHA256.Create()) return Hex(hash.ComputeHash(stream)); }
    static string HashFile(string path) { using (var file = File.OpenRead(path)) return Hash(file); }
    static void Need(bool ok, string message) { if (!ok) throw new InvalidOperationException(message); }
    static string Name(string name) {
        Need(!String.IsNullOrEmpty(name) && !name.StartsWith("/") && name.IndexOf('\\') < 0, "Unsafe package path.");
        name = name.TrimEnd('/');
        foreach (string part in name.Split('/')) {
            Need(part.Length > 0 && part != "." && part != ".." && !part.EndsWith(".") && !part.EndsWith(" "), "Unsafe package path.");
            foreach (char value in part) Need(value >= 32 && "<>:\"|?*".IndexOf(value) < 0, "Unsafe package path.");
            Need(!Reserved.Contains(part.Split('.')[0]), "Reserved package path.");
        }
        return name;
    }
    static void CheckParents(string path) {
        string current = path;
        while (!String.IsNullOrEmpty(current)) {
            if (File.Exists(current) || Directory.Exists(current))
                Need((File.GetAttributes(current) & FileAttributes.ReparsePoint) == 0, "Install location cannot use links or redirected folders.");
            current = Path.GetDirectoryName(current);
        }
    }
    internal static string PrepareTarget(string requested, bool createParent) {
        string target = Path.GetFullPath(requested).TrimEnd(Path.DirectorySeparatorChar);
        Need(!target.StartsWith("\\") && target.Length <= 100 && target.Length > 3, "Choose a short local installation folder (at most 100 characters).");
        Need(!Directory.Exists(target) && !File.Exists(target), "That folder already exists. Choose a fresh folder; existing installations and reviews are never replaced.");
        CheckParents(target);
        string parent = Path.GetDirectoryName(target);
        if (createParent) Directory.CreateDirectory(parent);
        Need(Directory.Exists(parent), "The parent folder must already exist.");
        return target;
    }
    static string Install(string requested) {
        Need(Environment.Is64BitOperatingSystem && IntPtr.Size == 8, "This trial requires 64-bit Windows.");
        string runtime = VcRuntime.Problem();
        if (runtime != null) throw new RuntimeMissing(runtime);
        string target = PrepareTarget(requested, false);
        // Reserve the final path exclusively. No cleanup removes files after any failure.
        using (var mutex = new System.Threading.Mutex(false, "Local\\PDFRemediatorInternalInstall-" +
            Hex(SHA256.Create().ComputeHash(Encoding.UTF8.GetBytes(target.ToUpperInvariant()))))) {
            Need(mutex.WaitOne(0), "Another installation is using that folder.");
            try {
                Need(!Directory.Exists(target) && !File.Exists(target), "Install folder appeared during preparation.");
                using (var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip")) {
                    Need(payload != null && Hash(payload) == PayloadHash, "The embedded package failed its integrity check.");
                    payload.Position = 0;
                    using (var archive = new ZipArchive(payload, ZipArchiveMode.Read, false)) {
                        Need(archive.Entries.Count <= 20000, "Package exceeds its file limit.");
                        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                        long bytes = 0;
                        foreach (var entry in archive.Entries) {
                            Need(!entry.FullName.EndsWith("/"), "Explicit directory entries are unsupported.");
                            string name = Name(entry.FullName);
                            Need(names.Add(name), "Package contains conflicting file names.");
                            int mode = (entry.ExternalAttributes >> 16) & 0xf000;
                            Need(mode == 0 || mode == 0x8000 || mode == 0x4000, "Package contains a nonregular member.");
                            bytes += entry.Length;
                            Need(bytes <= Limit && entry.Length <= Limit && Path.Combine(target, name).Length <= 240,
                                "Choose a shorter install location; a package path exceeds the supported limit.");
                        }
                        var manifestEntry = archive.GetEntry("package-manifest.json");
                        Need(manifestEntry != null && manifestEntry.Length <= 8 * 1024 * 1024, "Package manifest is missing or too large.");
                        Dictionary<string,object> manifest;
                        using (var reader = new StreamReader(manifestEntry.Open(), Encoding.UTF8)) {
                            var serializer = new JavaScriptSerializer(); serializer.MaxJsonLength = 8 * 1024 * 1024;
                            manifest = serializer.Deserialize<Dictionary<string,object>>(reader.ReadToEnd());
                        }
                        Need((string)manifest["release_status"] == "internal-unqualified" && !(bool)manifest["redistribution_cleared"], "This installer only supports its internal draft.");
                        Need((string)manifest["schema"] == "windows-internal-package-1" && (string)manifest["architecture"] == "x64" &&
                            (string)manifest["python_version"] == PythonVersion && (string)manifest["python_abi"] == PythonAbi &&
                            (string)manifest["runtime_lock_sha256"] == RuntimeLockHash && !(bool)manifest["ai_enabled"] && (bool)manifest["ocr_enabled"] == OcrEnabled,
                            "Package identity or optional-runtime policy does not match this installer.");
                        string ocrLock = manifest.ContainsKey("ocr_runtime_lock_sha256") ? (string)manifest["ocr_runtime_lock_sha256"] : "";
                        Need(OcrEnabled ? ocrLock == OcrRuntimeLockHash && System.Text.RegularExpressions.Regex.IsMatch(ocrLock, "^[0-9a-f]{64}$") : ocrLock == "",
                            "The optional OCR runtime lock does not match this installer.");
                        var files = (Dictionary<string,object>)manifest["files"];
                        Need(files.Count + 1 == archive.Entries.Count, "Manifest inventory does not match the package.");
                        Need(!names.Contains(".installation-complete.json"), "Package contains an installation completion marker.");
                        var exactNames = new HashSet<string>(StringComparer.Ordinal);
                        foreach (var entry in archive.Entries) exactNames.Add(entry.FullName);
                        Need(!files.ContainsKey("package-manifest.json"), "Manifest cannot list itself.");
                        var expectedNames = new HashSet<string>(files.Keys, StringComparer.Ordinal);
                        expectedNames.Add("package-manifest.json");
                        Need(expectedNames.SetEquals(exactNames), "Manifest and package members differ.");
                        foreach (var pair in files) Need(exactNames.Contains(Name(pair.Key)) && pair.Value is string &&
                            System.Text.RegularExpressions.Regex.IsMatch((string)pair.Value, "^[0-9a-f]{64}$"), "Manifest file or digest is invalid.");
                        Need(files.ContainsKey("runtime-baseline.json") && (string)files["runtime-baseline.json"] == RuntimeLockHash,
                            "The exact runtime lock is missing or differs from this installer.");
                        if (OcrEnabled) {
                            Need(files.ContainsKey("ocr-runtime-baseline.json") && (string)files["ocr-runtime-baseline.json"] == OcrRuntimeLockHash,
                                "The exact OCR runtime lock is missing or differs from this installer.");
                            string ocrStem = "runtime/ocr/python" + PythonAbi.Substring(2);
                            foreach (string required in new string[] { "runtime/ocr/python.exe", ocrStem + ".dll", ocrStem + "._pth", ocrStem + ".zip",
                                "runtime/tesseract/tesseract.exe", "runtime/tesseract/tessdata/pdf.ttf", "runtime/tesseract/doc/LICENSE",
                                "runtime/tesseract/tessdata/eng.traineddata", "runtime/tesseract/tessdata/osd.traineddata",
                                "runtime/tesseract/tessdata/LICENSE", "runtime/tesseract/tessdata/README.md" })
                                Need(files.ContainsKey(required), "The package is missing a required OCR component.");
                        } else {
                            foreach (string name in files.Keys) Need(name != "ocr-runtime-baseline.json" && !name.StartsWith("runtime/ocr/", StringComparison.OrdinalIgnoreCase) &&
                                !name.StartsWith("runtime/tesseract/", StringComparison.OrdinalIgnoreCase), "Disabled OCR package contains optional runtime files.");
                        }
                        string pythonStem = "runtime/python/python" + PythonAbi.Substring(2);
                        foreach (string required in new string[] { "runtime/python/python.exe", pythonStem + ".dll", pythonStem + "._pth", pythonStem + ".zip",
                            "runtime/java/bin/java.exe", "runtime/odl/jar/opendataloader-pdf-cli.jar", "runtime/verapdf/verapdf.bat",
                            "runtime/verapdf/bin/cli-1.30.3.jar", "src/pdf_remediator/__init__.py", "PDF Remediator.exe", "launch_portable.py", "local-runtime.toml" })
                            Need(files.ContainsKey(required), "The package is missing a required application component.");
                        CheckParents(target);
                        Need(!Directory.Exists(target) && !File.Exists(target), "Install folder is no longer fresh.");
                        Need(CreateFreshDirectory(target, IntPtr.Zero), "The installation folder could not be reserved. Choose a new writable folder.");
                        foreach (var entry in archive.Entries) {
                            Need(!entry.FullName.EndsWith("/"), "Explicit directory entries are unsupported.");
                            string destination = Path.Combine(target, Name(entry.FullName).Replace('/', Path.DirectorySeparatorChar));
                            CheckParents(destination);
                            Directory.CreateDirectory(Path.GetDirectoryName(destination));
                            using (var source = entry.Open()) using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None)) source.CopyTo(output);
                            if (entry.FullName != "package-manifest.json") Need(HashFile(destination) == (string)files[entry.FullName], "An installed file failed verification.");
                        }
                        Need(Directory.GetFiles(target, "*", SearchOption.AllDirectories).Length == files.Count + 1, "Installed inventory changed.");
                        using (var file = new FileStream(Path.Combine(target, ".installation-complete.json"), FileMode.CreateNew))
                        using (var writer = new StreamWriter(file, new UTF8Encoding(false)))
                            writer.Write(new JavaScriptSerializer().Serialize(new { status = "installed-internal-unqualified", payload_sha256 = PayloadHash }));
                        return target;
                    }
                }
            } finally { mutex.ReleaseMutex(); }
        }
    }
    // A shortcut (.lnk) that starts the installed program and shows its own icon. Made through Windows' own scripting object, so no extra files or
    // administrator access are needed. A failure here never undoes the installation.
    static void MakeShortcut(string folder, string installDir) {
        Need(Directory.Exists(folder), "The shortcut folder does not exist.");
        string program = Path.Combine(installDir, "PDF Remediator.exe");
        Need(File.Exists(program), "The installed program was not found.");
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        Need(shellType != null, "Windows' shortcut maker is not available.");
        object shell = Activator.CreateInstance(shellType);
        object link = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { Path.Combine(folder, "PDF Remediator.lnk") });
        Type linkType = link.GetType();
        linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { program });
        linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { installDir });
        linkType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { program + ",0" });
        linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "PDF Remediator: drafts accessibility repairs for PDFs" });
        linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
    }
    [STAThread]
    static int Main(string[] args) {
        string result = null;
        bool resultWritable = false;
        try {
            if (args.Length > 0) {
                Need((args.Length == 5 || (args.Length == 7 && args[5] == "--shortcuts-in")) && args[0] == "--install-dir" && args[2] == "--no-launch" && args[3] == "--result",
                    "Supported internal test arguments: --install-dir PATH --no-launch --result NEWFILE [--shortcuts-in EXISTINGFOLDER]");
                result = Path.GetFullPath(args[4]);
                Need(!File.Exists(result) && !Directory.Exists(result), "Result file already exists.");
                CheckParents(result);
                Need(Directory.Exists(Path.GetDirectoryName(result)), "Result parent folder must already exist.");
                resultWritable = true;
                string installed = Install(args[1]);
                if (args.Length == 7) MakeShortcut(Path.GetFullPath(args[6]), installed);
                using (var file = new FileStream(result, FileMode.CreateNew)) using (var writer = new StreamWriter(file, new UTF8Encoding(false)))
                    writer.Write(new JavaScriptSerializer().Serialize(new { status = "installed-internal-unqualified", install_dir = installed, payload_sha256 = PayloadHash, launched = false }));
                return 0;
            }
            Application.EnableVisualStyles();
            string early = VcRuntime.Problem();
            if (early != null) { VcRuntime.OfferDownload(early); return 1; }
            var form = new Form { Text = "PDF Remediator — internal trial", Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath), ClientSize = new Size(580, 300), StartPosition = FormStartPosition.CenterScreen, FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false };
            var label = new Label { Left = 20, Top = 20, Width = 540, Height = 85, Text = "Install this private trial in a new folder on this computer. The local workspace opens in its own window, not in your browser.\n\nExisting installations and saved reviews stay in place. This internal trial is not ready to share." };
            var field = new TextBox { Left = 20, Top = 115, Width = 540, AccessibleName = "Installation folder", Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PDFRemediator", "Trial-0.3") };
            var install = new Button { Left = 425, Top = 160, Width = 135, Height = 32, Text = "Install trial" };
            var icons = new CheckBox { Left = 20, Top = 168, Width = 380, Height = 24, Checked = true, Text = "Put a PDF Remediator icon on my desktop and in the Start menu" };
            var note = new Label { Left = 20, Top = 245, Width = 540, Height = 40, Text = "No administrator access, AI/OCR downloads, or automatic updates.\nKeep the entire installation folder to preserve saved work." };
            form.Controls.AddRange(new Control[] { label, field, icons, install, note });
            install.Click += delegate {
                install.Enabled = false; field.Enabled = false; icons.Enabled = false;
                try {
                    string target = Install(PrepareTarget(field.Text, true));
                    string where = "Open PDF Remediator.exe in this folder:\n" + target;
                    if (icons.Checked) {
                        try {
                            MakeShortcut(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), target);
                            MakeShortcut(Environment.GetFolderPath(Environment.SpecialFolder.Programs), target);
                            where = "A PDF Remediator icon is now on your desktop and in the Start menu.\n\nThe program itself is in:\n" + target;
                        } catch (Exception) { where = "The icon could not be made, but the program is installed. Open PDF Remediator.exe in this folder:\n" + target; }
                    }
                    bool openNow = MessageBox.Show("Installed.\n\n" + where + "\n\nOpen PDF Remediator now?", "PDF Remediator", MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes;
                    if (openNow) { try { Process.Start(new ProcessStartInfo(Path.Combine(target, "PDF Remediator.exe")) { WorkingDirectory = target, UseShellExecute = false }); } catch (Exception) { } }
                    form.Close();
                } catch (RuntimeMissing missing) {
                    VcRuntime.OfferDownload(missing.Message);
                    install.Enabled = true; field.Enabled = true; icons.Enabled = true;
                } catch (Exception error) {
                    MessageBox.Show(error.Message + "\n\nAny partial installation stays in place for inspection. Choose a new folder to retry.", "Installation needs attention", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    install.Enabled = true; field.Enabled = true; icons.Enabled = true;
                }
            };
            Application.Run(form); return 0;
        } catch (Exception error) {
            if (resultWritable) {
                try {
                    CheckParents(result);
                    using (var file = new FileStream(result, FileMode.CreateNew)) using (var writer = new StreamWriter(file, new UTF8Encoding(false)))
                        writer.Write(new JavaScriptSerializer().Serialize(new { status = "installation-refused", message = error.Message,
                            requested_dir = args[1], partial_files_preserved = true, payload_sha256 = PayloadHash, launched = false }));
                } catch { /* Never replace an existing diagnostic or installation file. */ }
            }
            if (args.Length == 0) MessageBox.Show(error.Message, "Installation needs attention", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
