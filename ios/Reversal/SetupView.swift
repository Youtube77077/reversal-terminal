import SwiftUI
import LocalAuthentication

let cashGreen = Color(red: 0, green: 214 / 255, blue: 75 / 255)

/// First-run screen: enter the address of your Reversal server (cloud or PC).
struct SetupView: View {
    @AppStorage("serverURL") private var serverURL: String = ""
    @State private var input: String = "https://"
    @State private var checking = false
    @State private var error: String?
    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 0) {
                Spacer()
                RoundedRectangle(cornerRadius: 26, style: .continuous)
                    .fill(cashGreen)
                    .frame(width: 84, height: 84)
                    .overlay(Text("$").font(.system(size: 48, weight: .black)).foregroundColor(.black))
                    .shadow(color: cashGreen.opacity(0.45), radius: 24, y: 8)
                Text("Reversal")
                    .font(.system(size: 34, weight: .bold))
                    .foregroundColor(.white)
                    .padding(.top, 22)
                Text("Connect to your bot server")
                    .font(.system(size: 16))
                    .foregroundColor(.gray)
                    .padding(.top, 4)

                HStack(spacing: 10) {
                    Image(systemName: "server.rack").foregroundColor(.gray)
                    TextField("https://your-server.com", text: $input)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focused)
                        .foregroundColor(.white)
                        .font(.system(size: 17))
                        .submitLabel(.go)
                        .onSubmit(connect)
                }
                .padding(.horizontal, 20).padding(.vertical, 18)
                .background(Color(white: 0.11))
                .clipShape(Capsule())
                .padding(.top, 36)

                if let error {
                    Text(error).font(.system(size: 14)).foregroundColor(.red).multilineTextAlignment(.center).padding(.top, 12)
                }

                Button(action: connect) {
                    HStack {
                        if checking { ProgressView().tint(.black) }
                        Text(checking ? "Connecting…" : "Continue").font(.system(size: 17, weight: .bold))
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 17)
                    .background(cashGreen).foregroundColor(.black).clipShape(Capsule())
                }
                .buttonStyle(PressStyle())
                .disabled(checking)
                .padding(.top, 18)

                Spacer()
                Text("Your password is entered on the next screen and stored only as a secure session cookie.")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(Color(white: 0.45))
                    .multilineTextAlignment(.center)
                    .padding(.bottom, 12)
            }
            .padding(.horizontal, 28)
        }
        .onAppear { focused = true }
    }

    private func connect() {
        var s = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if !s.hasPrefix("http") { s = "https://" + s }
        while s.hasSuffix("/") { s.removeLast() }
        guard let url = URL(string: s + "/api/auth/status") else { error = "That doesn't look like an address."; return }
        checking = true; error = nil
        URLSession.shared.dataTask(with: url) { data, resp, err in
            DispatchQueue.main.async {
                checking = false
                if let http = resp as? HTTPURLResponse, http.statusCode == 200, data != nil {
                    UIImpactFeedbackGenerator(style: .medium).impactOccurred()
                    serverURL = s
                } else {
                    error = err?.localizedDescription ?? "No Reversal server found at that address."
                    UINotificationFeedbackGenerator().notificationOccurred(.error)
                }
            }
        }.resume()
    }
}

struct PressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(response: 0.25, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

/// Optional Face ID lock (toggle from the app menu inside the web UI).
struct LockView: View {
    var unlocked: () -> Void
    @State private var failed = false
    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 18) {
                Image(systemName: "faceid").font(.system(size: 56)).foregroundColor(cashGreen)
                Text("Reversal is locked").font(.system(size: 22, weight: .bold)).foregroundColor(.white)
                Button("Unlock") { auth() }
                    .font(.system(size: 17, weight: .bold)).foregroundColor(.black)
                    .padding(.horizontal, 40).padding(.vertical, 14).background(cashGreen).clipShape(Capsule())
                if failed { Text("Authentication failed").foregroundColor(.red).font(.footnote) }
            }
        }
        .onAppear(perform: auth)
    }
    private func auth() {
        let ctx = LAContext()
        var e: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &e) else { unlocked(); return }
        ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Unlock Reversal") { ok, _ in
            DispatchQueue.main.async { if ok { unlocked() } else { failed = true } }
        }
    }
}
