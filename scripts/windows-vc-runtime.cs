// Added to the end of the installer and of the launcher by package-windows.py, which fills in the minimum version below.
// There are no using lines: names are fully qualified so this text can follow the other source in one compilation.
//
// The package does not carry Microsoft's Visual C++ runtime files (Microsoft limits who may pass them on). The programs in it use the
// copy Microsoft's own free Redistributable puts in the Windows system folder, so this checks that it is there and recent enough.
internal static class VcRuntime {
    const string Minimum = "__MIN_VC_RUNTIME__";
    internal const string DownloadPage = "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist";
    static readonly string[] Files = new string[] { "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll" };

    // null when the computer is ready, otherwise a plain-language message.
    internal static string Problem() {
        string folder = System.Environment.SystemDirectory;
        if (!System.IO.File.Exists(System.IO.Path.Combine(folder, "ucrtbase.dll")))
            return "The required Windows C runtime is missing. Update Windows, then try again.";
        System.Version minimum = new System.Version(Minimum);
        string detail = null;
        foreach (string name in Files) {
            string path = System.IO.Path.Combine(folder, name);
            if (!System.IO.File.Exists(path)) { detail = name + " is missing."; break; }
            System.Diagnostics.FileVersionInfo info = System.Diagnostics.FileVersionInfo.GetVersionInfo(path);
            System.Version found = new System.Version(info.FileMajorPart, info.FileMinorPart, info.FileBuildPart, info.FilePrivatePart);
            if (found < minimum) { detail = name + " is version " + found + ", which is older than " + minimum + "."; break; }
        }
        if (detail == null) return null;
        return "PDF Remediator needs Microsoft's free \"Visual C++ Redistributable\" (version " + minimum + " or newer), and this computer doesn't have it yet.\n\n" +
            detail + "\n\nIt is not included in this package because Microsoft's licence does not let us pass it on. Install the current x64 version from Microsoft, " +
            "then try again.\n\nMicrosoft's page: " + DownloadPage;
    }

    // Shows the message and, if the person agrees, opens Microsoft's page in their browser. Nothing is downloaded by this program.
    internal static void OfferDownload(string message) {
        System.Windows.Forms.DialogResult answer = System.Windows.Forms.MessageBox.Show(message + "\n\nOpen Microsoft's page now?", "PDF Remediator",
            System.Windows.Forms.MessageBoxButtons.YesNo, System.Windows.Forms.MessageBoxIcon.Information);
        if (answer != System.Windows.Forms.DialogResult.Yes) return;
        try { System.Diagnostics.Process.Start(DownloadPage); } catch (System.Exception) { /* the address is in the message above */ }
    }
}
