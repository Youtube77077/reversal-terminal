import SwiftUI
import UIKit

@main
struct ReversalApp: App {
    @AppStorage("serverURL") private var serverURL: String = ""
    @AppStorage("faceIDLock") private var faceIDLock: Bool = false
    @Environment(\.scenePhase) private var phase
    @State private var locked = true

    var body: some Scene {
        WindowGroup {
            ZStack {
                if serverURL.isEmpty {
                    SetupView()
                        .transition(.opacity)
                } else {
                    WebShell(serverURL: serverURL)
                        .transition(.opacity)
                }
                if faceIDLock && locked && !serverURL.isEmpty {
                    LockView(unlocked: { withAnimation(.easeOut(duration: 0.25)) { locked = false } })
                        .transition(.opacity)
                }
            }
            .animation(.easeInOut(duration: 0.3), value: serverURL)
            .onChange(of: phase) { p in
                if p == .background && faceIDLock { locked = true }
            }
        }
    }
}
