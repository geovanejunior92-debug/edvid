import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var output = Data()
    var origin: URL?
    var launched = false
    var log: FileHandle?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Encerrar Edvid Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        let edit = NSMenuItem(); menu.addItem(edit)
        let editMenu = NSMenu(title: "Editar"); edit.submenu = editMenu
        for (title, action, key) in [("Copiar", "copy:", "c"), ("Colar", "paste:", "v"), ("Recortar", "cut:", "x"), ("Selecionar tudo", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Edvid Studio"
        window.minSize = NSSize(width: 820, height: 600)
        window.setFrameAutosaveName("EdvidStudioMain")
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(self, name: "chooseFolder")
        configuration.userContentController.add(self, name: "chooseMedia")
        web = WKWebView(frame: .zero, configuration: configuration)
        web.navigationDelegate = self
        window.contentView = web
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        web.loadHTMLString("<body style='background:#10131b;color:#e9edf5;font:20px system-ui;padding:48px'><h1>Edvid Studio</h1><p>Iniciando o motor de edição…</p></body>", baseURL: nil)
        startServer()
    }

    func startServer() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let root = ProcessInfo.processInfo.environment["EDVID_ROOT"].map { URL(fileURLWithPath: $0) } ?? home.appendingPathComponent(".agents/skills/edvid")
        let python = root.appendingPathComponent(".venv/bin/python")
        let script = root.appendingPathComponent("helpers/studio_server.py")
        guard FileManager.default.isExecutableFile(atPath: python.path), FileManager.default.fileExists(atPath: script.path) else {
            fail("Motor local não encontrado. Consulte desktop/README.md na instalação compartilhada do edvid.")
            return
        }
        let support = ProcessInfo.processInfo.environment["EDVID_DATA_DIR"].map { URL(fileURLWithPath: $0) } ?? home.appendingPathComponent("Library/Application Support/Edvid Studio")
        do {
            try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
            let logURL = support.appendingPathComponent("server.log")
            if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
            log = try FileHandle(forWritingTo: logURL); log?.seekToEndOfFile()
            let process = Process(); let pipe = Pipe()
            process.executableURL = python
            process.arguments = [script.path, "--port", "0", "--data-dir", support.path]
            var env = ProcessInfo.processInfo.environment
            env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + (env["PATH"] ?? "")
            env["PYTHONUNBUFFERED"] = "1"
            process.environment = env
            process.standardOutput = pipe; process.standardError = log
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else { handle.readabilityHandler = nil; return }
                DispatchQueue.main.async { self?.received(data) }
            }
            process.terminationHandler = { [weak self] _ in
                DispatchQueue.main.async {
                    guard let self = self, self.server != nil else { return }
                    self.fail("O motor foi encerrado. Reabra o aplicativo. Diagnóstico: ~/Library/Application Support/Edvid Studio/server.log")
                }
            }
            server = process
            try process.run()
            DispatchQueue.main.asyncAfter(deadline: .now() + 25) { [weak self] in
                guard let self = self, !self.launched else { return }
                self.fail("O motor não respondeu em 25 segundos. Consulte o arquivo server.log e reabra o aplicativo.")
            }
        } catch { fail("Não foi possível iniciar: \(error.localizedDescription)") }
    }

    func received(_ data: Data) {
        guard !launched else { return }
        output.append(data)
        while let end = output.firstIndex(of: 10) {
            let line = output.prefix(upTo: end)
            output.removeSubrange(...end)
            guard let json = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                  let address = json["url"] as? String, let url = URL(string: address),
                  url.scheme == "http", url.host == "127.0.0.1" else { continue }
            launched = true; origin = url
            web.load(URLRequest(url: url))
        }
        if output.count > 65536 { output.removeAll() }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" || (url.scheme == "http" && url.host == origin?.host && url.port == origin?.port) { decisionHandler(.allow) }
        else { decisionHandler(.cancel) }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let url = message.frameInfo.request.url,
              url.host == origin?.host, url.port == origin?.port else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = message.name == "chooseFolder"
        panel.canChooseFiles = !panel.canChooseDirectories
        panel.allowsMultipleSelection = false
        if let body = message.body as? [String: Any], let path = body["projectPath"] as? String, !path.isEmpty {
            panel.directoryURL = URL(fileURLWithPath: path)
        }
        let requestedTarget = (message.body as? [String: Any])?["target"] as? String
        let finishingTargets: Set<String> = ["finish-music", "finish-insert", "finish-captions"]
        let target = requestedTarget.flatMap { finishingTargets.contains($0) ? $0 : nil }
        panel.prompt = "Selecionar"
        panel.beginSheetModal(for: window) { [weak self] response in
            guard response == .OK, let path = panel.url?.path else { return }
            let event = target != nil ? "edvid-finish-media" : (message.name == "chooseFolder" ? "edvid-folder" : "edvid-media")
            let detail: Any = target.map { ["path": path, "target": $0] } ?? path as Any
            guard let data = try? JSONSerialization.data(withJSONObject: [detail]),
                  let literal = String(data: data, encoding: .utf8) else { return }
            self?.web.evaluateJavaScript("window.dispatchEvent(new CustomEvent('\(event)', {detail: \(literal)[0]}));", completionHandler: nil)
        }
    }

    func fail(_ message: String) {
        let alert = NSAlert(); alert.messageText = "Edvid Studio precisa de atenção"; alert.informativeText = message
        alert.addButton(withTitle: "OK"); alert.runModal()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        let process = server; server = nil
        if process?.isRunning == true { process?.terminate() }
        try? log?.close()
    }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
