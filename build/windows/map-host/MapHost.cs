// Small out-of-process WebView2 host. Python/Tk remains the only CRM data owner.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

class MapHost : Form {
    [DllImport("user32.dll")] static extern IntPtr SetParent(IntPtr child, IntPtr parent);
    [DllImport("user32.dll")] static extern IntPtr GetParent(IntPtr child);
    [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr hwnd, int index);
    [DllImport("user32.dll")] static extern int SetWindowLong(IntPtr hwnd, int index, int value);
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool MoveWindow(IntPtr hwnd, int x, int y, int width, int height, bool repaint);
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int left, top, right, bottom; }
    readonly IntPtr parentWindow;
    readonly string assets;
    readonly WebView2 view = new WebView2();
    readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024 };
    readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
    bool loaded;
    const string Origin = "https://turto-map.local/";

    void Emit(object data) { lock (Console.Out) { Console.WriteLine(json.Serialize(data)); } }
    static bool NetworkHost(Uri uri) {
        return uri.Scheme == "https" && (uri.Host == "tiles.openfreemap.org" || uri.Host.EndsWith(".tiles.openfreemap.org") ||
            (uri.Host == "ags.cuzk.gov.cz" && uri.AbsolutePath.StartsWith("/arcgis1/rest/services/ORTOFOTO_WM/MapServer/tile/", StringComparison.Ordinal)));
    }
    public MapHost(IntPtr parent, string folder) {
        parentWindow = parent; assets = folder;
        FormBorderStyle = FormBorderStyle.None; ShowInTaskbar = false;
        StartPosition = FormStartPosition.Manual; Location = new Point(0, 0);
        Width = 100; Height = 100; Opacity = 0;
        view.Dock = DockStyle.Fill; Controls.Add(view);
        timer.Interval = 200;
        timer.Tick += delegate {
            if (!IsWindow(parentWindow)) { Close(); return; }
            RECT r;
            if (GetClientRect(parentWindow, out r)) MoveWindow(Handle, 0, 0, Math.Max(1,r.right), Math.Max(1,r.bottom), true);
        };
        Shown += Initialize;
        FormClosed += delegate { timer.Stop(); view.Dispose(); };
    }
    async void Initialize(object sender, EventArgs args) {
        try {
            int style = GetWindowLong(Handle, -16);
            SetWindowLong(Handle, -16, (style & ~unchecked((int)0x80000000)) | 0x40000000);
            SetParent(Handle, parentWindow);
            if (GetParent(Handle) != parentWindow) throw new InvalidOperationException("Mapové okno nelze vložit do CRM.");
            Emit(new { type = "embedded" });
            Opacity = 1; timer.Start();
            string cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TURTO", "CRM-Maps", "webview");
            var env = await CoreWebView2Environment.CreateAsync(null, cache);
            await view.EnsureCoreWebView2Async(env);
            var core = view.CoreWebView2;
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;
            core.Settings.IsGeneralAutofillEnabled = false;
            core.SetVirtualHostNameToFolderMapping("turto-map.local", assets, CoreWebView2HostResourceAccessKind.DenyCors);
            core.NavigationStarting += delegate(object s, CoreWebView2NavigationStartingEventArgs e) {
                if (e.Uri != Origin + "index.html") e.Cancel = true;
            };
            core.NewWindowRequested += delegate(object s, CoreWebView2NewWindowRequestedEventArgs e) {
                e.Handled = true;
                Uri uri;
                if (Uri.TryCreate(e.Uri, UriKind.Absolute, out uri) && uri.Scheme == "https" &&
                    (uri.Host == "openfreemap.org" || uri.Host == "openmaptiles.org" ||
                     uri.Host == "www.openstreetmap.org" || uri.Host == "maplibre.org" || uri.Host == "geoportal.cuzk.gov.cz"))
                    Emit(new { type = "attribution", url = e.Uri });
            };
            core.PermissionRequested += delegate(object s, CoreWebView2PermissionRequestedEventArgs e) { e.State = CoreWebView2PermissionState.Deny; };
            core.DownloadStarting += delegate(object s, CoreWebView2DownloadStartingEventArgs e) { e.Cancel = true; };
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += delegate(object s, CoreWebView2WebResourceRequestedEventArgs e) {
                Uri uri;
                if (!Uri.TryCreate(e.Request.Uri, UriKind.Absolute, out uri) ||
                    !(uri.Scheme == "blob" || uri.Scheme == "data" || e.Request.Uri.StartsWith(Origin) || NetworkHost(uri))) {
                    e.Response = env.CreateWebResourceResponse(new MemoryStream(), 403, "Forbidden", "");
                }
            };
            core.WebMessageReceived += delegate(object s, CoreWebView2WebMessageReceivedEventArgs e) {
                if (e.Source != Origin + "index.html") return;
                lock(Console.Out) { Console.WriteLine(e.WebMessageAsJson); }
            };
            core.ProcessFailed += delegate { Emit(new { type = "error", message = "Mapové okno se přerušilo. Znovu otevřete CRM." }); };
            core.NavigationCompleted += delegate(object s, CoreWebView2NavigationCompletedEventArgs e) {
                if (!e.IsSuccess) Emit(new { type = "error", message = "Mapové okno se nepodařilo načíst." });
            };
            loaded = true;
            core.Navigate(Origin + "index.html");
            var reader = new Thread(ReadCommands); reader.IsBackground = true; reader.Start();
        } catch(Exception ex) { Emit(new { type = "error", message = "Mapa vyžaduje Microsoft Edge WebView2 Runtime. " + ex.Message }); Close(); }
    }
    void ReadCommands() {
        try {
            string line;
            while ((line = Console.ReadLine()) != null) {
                string command = line;
                if (command.Length > 32 * 1024 * 1024) continue;
                BeginInvoke(new Action(delegate {
                    try {
                        var data = json.Deserialize<Dictionary<string, object>>(command);
                        string type = data.ContainsKey("type") ? Convert.ToString(data["type"]) : "";
                        if (type == "close") { Close(); return; }
                        if (type == "visible") { Visible = Convert.ToBoolean(data["value"]); return; }
                        if (loaded) view.CoreWebView2.PostWebMessageAsJson(command);
                    } catch(Exception ex) { Emit(new { type = "error", message = ex.Message }); }
                }));
            }
        } catch(IOException) { }
        try { BeginInvoke(new Action(Close)); } catch(InvalidOperationException) { }
    }
    [STAThread] static void Main(string[] args) {
        Console.SetIn(new StreamReader(Console.OpenStandardInput(), Encoding.UTF8));
        Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
        if (args.Length != 2) return;
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MapHost(new IntPtr(long.Parse(args[0])), Path.GetFullPath(args[1])));
    }
}
