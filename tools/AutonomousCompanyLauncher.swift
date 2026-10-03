import AppKit
import Foundation
import WebKit

private enum LauncherError: LocalizedError {
    case missingTool(String)
    case serviceConflict(String)
    case serviceNotReady(String)

    var errorDescription: String? {
        switch self {
        case .missingTool(let name):
            return "Required local tool is missing: \(name)."
        case .serviceConflict(let service):
            return "Port for \(service) is already used by a different local service. No owner credential was sent to it."
        case .serviceNotReady(let service):
            return "The \(service) service did not become ready. Check ~/Library/Logs/Autonomous Company/."
        }
    }
}

private final class OwnerTokenFile {
    private let file = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Autonomous Company/owner-token")

    func load() throws -> String {
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        guard let permissions = attributes[.posixPermissions] as? NSNumber,
              permissions.intValue & 0o077 == 0 else {
            throw CocoaError(.fileReadNoPermission)
        }
        let token = try String(contentsOf: file, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let isHex = token.utf8.allSatisfy { byte in
            (48...57).contains(byte) || (97...102).contains(byte)
        }
        guard token.count == 64, isHex else { throw CocoaError(.fileReadCorruptFile) }
        return token
    }
}

private final class CompanyLauncher: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private let home = FileManager.default.homeDirectoryForCurrentUser
    private let fileManager = FileManager.default
    private var apiProcess: Process?
    private var webProcess: Process?
    private var window: NSWindow?
    private var webView: WKWebView?

    private var runtime: URL { home.appendingPathComponent("Library/Application Support/Autonomous Company/Runtime") }
    private var apiDir: URL { runtime.appendingPathComponent("api") }
    private var webDir: URL { runtime.appendingPathComponent("web") }
    private var logsDir: URL { home.appendingPathComponent("Library/Logs/Autonomous Company") }
    private let apiURL = URL(string: "http://127.0.0.1:8000")!
    private let webURL = URL(string: "http://localhost:3000")!
    private lazy var ephemeralSession: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        return URLSession(configuration: configuration)
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        Task { await bootstrap() }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let process = webProcess, process.isRunning { process.terminate() }
        if let process = apiProcess, process.isRunning { process.terminate() }
    }

    private func bootstrap() async {
        do {
            try fileManager.createDirectory(at: logsDir, withIntermediateDirectories: true)
            let token = try OwnerTokenFile().load()
            try await startAPIIfNeeded(token: token)
            try await startWebIfNeeded()
            try await showDashboard(token: token)
        } catch {
            showError(error.localizedDescription)
        }
    }

    private func startAPIIfNeeded(token: String) async throws {
        guard !portIsListening(8000) else { throw LauncherError.serviceConflict("API") }

        let python = apiDir.appendingPathComponent(".venv/bin/python")
        guard fileManager.isExecutableFile(atPath: python.path) else {
            throw LauncherError.missingTool("bundled Python runtime")
        }
        apiProcess = try start(
            executable: python,
            arguments: ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            directory: apiDir,
            environment: launchEnvironment(token: token),
            logName: "api.log"
        )
        guard await waitForAPI(token: token, timeout: 30) else {
            throw LauncherError.serviceNotReady("API")
        }
    }

    private func startWebIfNeeded() async throws {
        guard !portIsListening(3000) else { throw LauncherError.serviceConflict("dashboard") }
        guard fileManager.fileExists(atPath: webDir.appendingPathComponent("server.js").path) else {
            throw LauncherError.serviceNotReady("dashboard build")
        }
        let node = try resolveTool(named: "Node.js", candidates: [
            "/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node",
        ])
        webProcess = try start(
            executable: node,
            arguments: ["server.js"],
            directory: webDir,
            environment: [
                "HOSTNAME": "127.0.0.1",
                "NODE_ENV": "production",
                "PATH": toolPath,
                "PORT": "3000",
            ],
            logName: "web.log"
        )
        let deadline = Date().addingTimeInterval(30)
        while Date() < deadline {
            guard webProcess?.isRunning == true else { break }
            if await dashboardIsOurs() { return }
            try? await Task.sleep(for: .milliseconds(250))
        }
        throw LauncherError.serviceNotReady("dashboard")
    }

    private func showDashboard(token: String) async throws {
        let tokenData = try JSONEncoder().encode(token)
        guard let tokenJSON = String(data: tokenData, encoding: .utf8) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        await MainActor.run {
            let configuration = WKWebViewConfiguration()
            configuration.websiteDataStore = WKWebsiteDataStore.nonPersistent()
            let controller = WKUserContentController()
            controller.addUserScript(WKUserScript(
                source: "if (location.origin === 'http://localhost:3000') sessionStorage.setItem('ownerToken', \(tokenJSON));",
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            ))
            configuration.userContentController = controller
            let view = WKWebView(frame: .zero, configuration: configuration)
            view.navigationDelegate = self
            self.webView = view

            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                styleMask: [.titled, .closable, .miniaturizable, .resizable],
                backing: .buffered,
                defer: false
            )
            window.title = "Autonomous Company"
            window.minSize = NSSize(width: 900, height: 600)
            window.contentView = view
            window.center()
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            self.window = window
            view.load(URLRequest(url: self.webURL))
        }
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.scheme == "about" ||
           (url.scheme == "http" && url.host == "localhost" && url.port == 3000) {
            decisionHandler(.allow)
        } else {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    private var toolPath: String {
        "\(home.path)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    }

    private func launchEnvironment(token: String) -> [String: String] {
        [
            "APP_ENV": "development",
            "DATABASE_URL": "sqlite:///./autonomous_company.db",
            "OWNER_TOKEN": token,
            "REAL_MONEY_ENABLED": "false",
            "BUG_BOUNTY_EXTERNAL_ACTIONS_ENABLED": "false",
            "LLM_MODE": "mock",
            "QUEUE_MODE": "direct",
            "PATH": toolPath,
        ]
    }

    private func resolveTool(named name: String, candidates: [String]) throws -> URL {
        for candidate in candidates where fileManager.isExecutableFile(atPath: candidate) {
            return URL(fileURLWithPath: candidate)
        }
        throw LauncherError.missingTool(name)
    }

    private func start(
        executable: URL,
        arguments: [String],
        directory: URL,
        environment: [String: String],
        logName: String
    ) throws -> Process {
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.currentDirectoryURL = directory
        process.environment = ProcessInfo.processInfo.environment.merging(environment) { _, new in new }
        let logURL = logsDir.appendingPathComponent(logName)
        if !fileManager.fileExists(atPath: logURL.path) {
            fileManager.createFile(atPath: logURL.path, contents: nil)
        }
        let log = try FileHandle(forWritingTo: logURL)
        try log.seekToEnd()
        process.standardOutput = log
        process.standardError = log
        try process.run()
        return process
    }

    private func apiIsOurs(token: String) async -> Bool {
        guard processOwnsPort(apiProcess, 8000) else { return false }
        guard await responds(to: apiURL.appendingPathComponent("ready")) else { return false }
        var request = URLRequest(url: apiURL.appendingPathComponent("api/settings"))
        request.timeoutInterval = 1
        request.setValue(token, forHTTPHeaderField: "X-Owner-Token")
        return await responds(to: request)
    }

    private func waitForAPI(token: String, timeout: TimeInterval) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await apiIsOurs(token: token) { return true }
            try? await Task.sleep(for: .milliseconds(250))
        }
        return false
    }

    private func dashboardIsOurs() async -> Bool {
        guard processOwnsPort(webProcess, 3000) else { return false }
        var request = URLRequest(url: webURL)
        request.timeoutInterval = 1
        do {
            let (data, response) = try await ephemeralSession.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200,
                  let html = String(data: data, encoding: .utf8) else { return false }
            return html.contains("<title>Autonomous Company</title>")
        } catch {
            return false
        }
    }

    private func responds(to url: URL) async -> Bool {
        var request = URLRequest(url: url)
        request.timeoutInterval = 1
        return await responds(to: request)
    }

    private func responds(to request: URLRequest) async -> Bool {
        do {
            let (_, response) = try await ephemeralSession.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func portIsListening(_ port: Int) -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        process.arguments = ["-nP", "-iTCP:\(port)", "-sTCP:LISTEN", "-t"]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
            return process.terminationStatus == 0
        } catch {
            return true
        }
    }

    private func processOwnsPort(_ process: Process?, _ port: Int) -> Bool {
        guard let process, process.isRunning else { return false }
        let probe = Process()
        let output = Pipe()
        probe.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        probe.arguments = ["-nP", "-a", "-p", String(process.processIdentifier), "-iTCP:\(port)", "-sTCP:LISTEN", "-t"]
        probe.standardOutput = output
        probe.standardError = FileHandle.nullDevice
        do {
            try probe.run()
            probe.waitUntilExit()
            return probe.terminationStatus == 0 && !output.fileHandleForReading.readDataToEndOfFile().isEmpty
        } catch {
            return false
        }
    }

    private func showError(_ message: String) {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.alertStyle = .critical
            alert.messageText = "Autonomous Company could not start"
            alert.informativeText = message
            alert.addButton(withTitle: "OK")
            alert.runModal()
            NSApp.terminate(nil)
        }
    }
}

let app = NSApplication.shared
private let delegate = CompanyLauncher()
app.delegate = delegate
app.run()
