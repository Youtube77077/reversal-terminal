import SwiftUI
import UIKit
import WebKit

/// Full-screen native shell around the Reversal web app. The web UI is mobile-first
/// (Cash-App style, 5 tabs) so the app gets every feature and every update instantly
/// whenever the server is updated — no re-sideloading needed for UI changes.
struct WebShell: View {
    let serverURL: String
    @AppStorage("serverURL") private var storedURL: String = ""
    @StateObject private var model = WebModel()

    var body: some View {
        ZStack {
            (model.isLight ? Color.white : Color.black).ignoresSafeArea()
            WebView(url: URL(string: serverURL)!, model: model)
                .ignoresSafeArea(.container, edges: [.bottom])
                .opacity(model.loadedOnce ? 1 : 0)
                .animation(.easeOut(duration: 0.35), value: model.loadedOnce)
            if !model.loadedOnce && model.error == nil {
                Splash()
            }
            if let err = model.error {
                ErrorView(message: err, retry: { model.reload() }, change: { storedURL = "" })
                    .transition(.opacity)
            }
        }
        .preferredColorScheme(model.isLight ? .light : .dark)
        .statusBarHidden(false)
    }
}

final class WebModel: NSObject, ObservableObject {
    @Published var loadedOnce = false
    @Published var error: String?
    @Published var isLight = false
    weak var webView: WKWebView?
    func reload() { error = nil; webView?.reload() }
}

struct Splash: View {
    @State private var pulse = false
    var body: some View {
        RoundedRectangle(cornerRadius: 24, style: .continuous)
            .fill(cashGreen)
            .frame(width: 78, height: 78)
            .overlay(Text("$").font(.system(size: 44, weight: .black)).foregroundColor(.black))
            .scaleEffect(pulse ? 1.06 : 0.94)
            .animation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: pulse)
            .onAppear { pulse = true }
    }
}

struct ErrorView: View {
    let message: String
    let retry: () -> Void
    let change: () -> Void
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "wifi.exclamationmark").font(.system(size: 44)).foregroundColor(.gray)
            Text("Can't reach your server").font(.system(size: 22, weight: .bold))
            Text(message).font(.system(size: 14)).foregroundColor(.gray).multilineTextAlignment(.center).padding(.horizontal, 30)
            Button(action: retry) {
                Text("Try again").font(.system(size: 17, weight: .bold)).foregroundColor(.black)
                    .frame(maxWidth: 260).padding(.vertical, 15).background(cashGreen).clipShape(Capsule())
            }.buttonStyle(PressStyle()).padding(.top, 8)
            Button("Change server", action: change).font(.system(size: 15, weight: .semibold)).foregroundColor(.gray)
        }
    }
}

struct WebView: UIViewRepresentable {
    let url: URL
    let model: WebModel

    func makeCoordinator() -> Coordinator { Coordinator(model: model) }

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()                     // persistent login cookie
        cfg.allowsInlineMediaPlayback = true
        let ucc = WKUserContentController()
        ucc.add(context.coordinator, name: "native")
        // Bridge: haptics, theme sync, change server, Face ID toggle. Disable pinch zoom.
        let js = """
        window.ReversalNative = {
          haptic: function(k){ window.webkit.messageHandlers.native.postMessage({type:'haptic', kind:k||'light'}); },
          changeServer: function(){ window.webkit.messageHandlers.native.postMessage({type:'changeServer'}); },
          setFaceID: function(on){ window.webkit.messageHandlers.native.postMessage({type:'faceid', on:!!on}); }
        };
        new MutationObserver(function(){
          window.webkit.messageHandlers.native.postMessage({type:'theme', light: document.documentElement.classList.contains('light')});
        }).observe(document.documentElement, {attributes:true, attributeFilter:['class']});
        document.addEventListener('DOMContentLoaded', function(){
          window.webkit.messageHandlers.native.postMessage({type:'theme', light: document.documentElement.classList.contains('light')});
        });
        document.addEventListener('click', function(e){
          var t = e.target.closest && e.target.closest('a,button'); if (t) window.ReversalNative.haptic('light');
        }, true);
        """
        ucc.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        cfg.userContentController = ucc

        let wv = WKWebView(frame: .zero, configuration: cfg)
        wv.customUserAgent = nil
        wv.evaluateJavaScript("navigator.userAgent") { ua, _ in
            wv.customUserAgent = ((ua as? String) ?? "") + " ReversalTerminalApp/1.0"
            wv.load(URLRequest(url: url))
        }
        wv.navigationDelegate = context.coordinator
        wv.uiDelegate = context.coordinator
        wv.allowsBackForwardNavigationGestures = true
        wv.isOpaque = false
        wv.backgroundColor = .clear
        wv.scrollView.backgroundColor = .clear
        wv.scrollView.contentInsetAdjustmentBehavior = .never
        wv.scrollView.bounces = true
        let rc = UIRefreshControl()
        rc.tintColor = UIColor(red: 0, green: 0.84, blue: 0.29, alpha: 1)
        rc.addTarget(context.coordinator, action: #selector(Coordinator.refresh(_:)), for: .valueChanged)
        wv.scrollView.refreshControl = rc
        model.webView = wv
        return wv
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
        let model: WebModel
        init(model: WebModel) { self.model = model }

        @objc func refresh(_ rc: UIRefreshControl) {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            model.webView?.reload()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { rc.endRefreshing() }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            DispatchQueue.main.async { self.model.loadedOnce = true; self.model.error = nil }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            let ns = error as NSError
            if ns.code == NSURLErrorCancelled { return }
            DispatchQueue.main.async { self.model.error = error.localizedDescription }
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            // keep the app on our server; open external links (docs, GitHub) in Safari
            if let u = action.request.url, let host = u.host, let mine = webView.url?.host ?? URL(string: UserDefaults.standard.string(forKey: "serverURL") ?? "")?.host,
               host != mine, action.navigationType == .linkActivated {
                UIApplication.shared.open(u)
                decisionHandler(.cancel); return
            }
            decisionHandler(.allow)
        }

        // downloads (CSV/JSON/HTML exports) open in a share sheet
        func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                     decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            if let http = response.response as? HTTPURLResponse,
               let cd = http.value(forHTTPHeaderField: "Content-Disposition"), cd.contains("attachment"),
               let url = response.response.url {
                decisionHandler(.cancel)
                share(url: url, webView: webView)
                return
            }
            decisionHandler(.allow)
        }

        private func share(url: URL, webView: WKWebView) {
            webView.configuration.websiteDataStore.httpCookieStore.getAllCookies { cookies in
                var req = URLRequest(url: url)
                let mine = cookies.filter { c in url.host?.hasSuffix(c.domain.trimmingCharacters(in: CharacterSet(charactersIn: "."))) ?? false }
                for (name, value) in HTTPCookie.requestHeaderFields(with: mine) {
                    req.setValue(value, forHTTPHeaderField: name)
                }
                URLSession.shared.downloadTask(with: req) { tmp, resp, _ in
                    guard let tmp else { return }
                    let name = resp?.suggestedFilename ?? url.lastPathComponent
                    let dest = FileManager.default.temporaryDirectory.appendingPathComponent(name)
                    try? FileManager.default.removeItem(at: dest)
                    try? FileManager.default.moveItem(at: tmp, to: dest)
                    DispatchQueue.main.async {
                        let vc = UIActivityViewController(activityItems: [dest], applicationActivities: nil)
                        UIApplication.shared.connectedScenes.compactMap { ($0 as? UIWindowScene)?.keyWindow }.first?
                            .rootViewController?.present(vc, animated: true)
                    }
                }.resume()
            }
        }

        // window.confirm / alert support (used by reset & arm dialogs)
        func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
            let ac = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            ac.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
            ac.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
            present(ac, fallback: { completionHandler(false) })
        }

        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
            let ac = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            ac.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
            present(ac, fallback: completionHandler)
        }

        private func present(_ vc: UIViewController, fallback: @escaping () -> Void) {
            guard let root = UIApplication.shared.connectedScenes.compactMap({ ($0 as? UIWindowScene)?.keyWindow }).first?.rootViewController
            else { fallback(); return }
            root.present(vc, animated: true)
        }

        func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            switch type {
            case "haptic":
                let kind = body["kind"] as? String ?? "light"
                if kind == "success" { UINotificationFeedbackGenerator().notificationOccurred(.success) }
                else { UIImpactFeedbackGenerator(style: kind == "heavy" ? .heavy : .light).impactOccurred() }
            case "theme":
                DispatchQueue.main.async { self.model.isLight = (body["light"] as? Bool) ?? false }
            case "changeServer":
                DispatchQueue.main.async { UserDefaults.standard.set("", forKey: "serverURL") }
            case "faceid":
                UserDefaults.standard.set((body["on"] as? Bool) ?? false, forKey: "faceIDLock")
            default: break
            }
        }
    }
}
