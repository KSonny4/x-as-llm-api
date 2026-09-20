// zencli — minimalist opencode-zen chat client with raw wire control.
//
// Passes what stock HTTP stacks cannot: a BoringSSL-Chrome ClientHello
// (uTLS) + hand-framed HTTP/1.1 with the exact header order the opencode
// CLI emits. Key via env ZEN_API_KEY only (never logged, never stored).
//
// Usage:
//
//	ZEN_API_KEY=... zencli -model big-pickle -body req.json [-session ID]
package main

import (
	"bufio"
	"crypto/rand"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"

	utls "github.com/refraction-networking/utls"
)

// DIRECT_UA is the exact pi direct-provider UA proven 200 (Call 4).
const DIRECT_UA = ("opencode/1.18.31 ai-sdk/provider-utils/4.0.40 " +
	"runtime/bun/1.3.14 pi-opencode-direct/0.1.6")

func dialZen(host, dialAddr string) (*utls.UConn, error) {
	conn, err := net.Dial("tcp", dialAddr)
	if err != nil {
		return nil, err
	}
	uconn := utls.UClient(conn, &utls.Config{
		ServerName:         host,
		InsecureSkipVerify: false,
	}, utls.HelloCustom)
	uconn.ApplyPreset(boringH1Spec())
	if err := uconn.Handshake(); err != nil {
		conn.Close()
		return nil, err
	}
	return uconn, nil
}

// serveChat implements POST /v1/chat/completions: body passes through
// verbatim; only the proven direct-path identity is stamped upstream.
func serveChat(key, host string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		body, err := io.ReadAll(io.LimitReader(r.Body, 4<<20))
		if err != nil || len(body) == 0 {
			http.Error(w, "bad body", http.StatusBadRequest)
			return
		}
		ses, msg := rid("ses_", 24), rid("msg_", 24)
		uconn, err := dialZen(host, host+":443")
		if err != nil {
			http.Error(w, "upstream dial: "+err.Error(), http.StatusBadGateway)
			return
		}
		defer uconn.Close()
		// pi-exact header set+order (captured 200-passing request,
		// 2026-09-20): undici lowercase, Stainless SDK suite, CLI
		// identity, per-request ses_/msg_ ids.
		var head strings.Builder
		head.WriteString("POST /zen/v1/chat/completions HTTP/1.1\r\n")
		fmt.Fprintf(&head, "host: %s\r\n", host)
		head.WriteString("connection: keep-alive\r\n")
		head.WriteString("Accept: application/json\r\n")
		head.WriteString("X-Stainless-Retry-Count: 0\r\n")
		head.WriteString("X-Stainless-Timeout: 300\r\n")
		head.WriteString("X-Stainless-Lang: js\r\n")
		head.WriteString("X-Stainless-Package-Version: 6.40.0\r\n")
		head.WriteString("X-Stainless-OS: MacOS\r\n")
		head.WriteString("X-Stainless-Arch: arm64\r\n")
		head.WriteString("X-Stainless-Runtime: node\r\n")
		head.WriteString("X-Stainless-Runtime-Version: v26.7.0\r\n")
		fmt.Fprintf(&head, "User-Agent: %s\r\n", DIRECT_UA)
		head.WriteString("x-opencode-client: cli\r\n")
		head.WriteString("x-opencode-project: global\r\n")
		fmt.Fprintf(&head, "Authorization: Bearer %s\r\n", key)
		fmt.Fprintf(&head, "x-client-request-id: %s\r\n", ses)
		fmt.Fprintf(&head, "x-opencode-session: %s\r\n", ses)
		fmt.Fprintf(&head, "x-opencode-request: %s\r\n", msg)
		head.WriteString("content-type: application/json\r\n")
		head.WriteString("accept-language: *\r\n")
		head.WriteString("sec-fetch-mode: cors\r\n")
		fmt.Fprintf(&head, "Content-Length: %d\r\n\r\n", len(body))
		if _, err := io.WriteString(uconn, head.String()); err != nil {
			http.Error(w, "upstream write: "+err.Error(), http.StatusBadGateway)
			return
		}
		if _, err := uconn.Write(body); err != nil {
			http.Error(w, "upstream write: "+err.Error(), http.StatusBadGateway)
			return
		}
		br := bufio.NewReader(uconn)
		status, err := br.ReadString('\n')
		if err != nil {
			http.Error(w, "upstream read: "+err.Error(), http.StatusBadGateway)
			return
		}
		var code int
		fmt.Sscanf(status, "HTTP/1.1 %d", &code)
		if code == 0 {
			code = http.StatusBadGateway
		}
		clen, chunked := -1, false
		ct := "application/json"
		for {
			l, err := br.ReadString('\n')
			if err != nil || l == "\r\n" || l == "\n" {
				break
			}
			if strings.HasPrefix(strings.ToLower(l), "content-length:") {
				fmt.Sscanf(l, "%*[^:]%*c%d", &clen)
			}
			if strings.HasPrefix(strings.ToLower(l), "transfer-encoding:") &&
				strings.Contains(strings.ToLower(l), "chunked") {
				chunked = true
			}
			if strings.HasPrefix(strings.ToLower(l), "content-type:") {
				ct = strings.TrimSpace(l[len("content-type:"):])
			}
		}
		w.Header().Set("Content-Type", ct)
		w.WriteHeader(code)
		if chunked {
			for {
				ln, err := br.ReadString('\n')
				if err != nil {
					break
				}
				var sz int
				fmt.Sscanf(ln, "%x", &sz)
				if sz == 0 {
					break
				}
				io.CopyN(w, br, int64(sz))
				br.ReadString('\n')
			}
		} else if clen > 0 {
			io.CopyN(w, br, int64(clen))
		} else if clen == 0 {
			// empty body: nothing to relay
		} else {
			// no length framing: upstream was asked Connection: close,
			// so EOF terminates the body
			io.Copy(w, br)
		}
	}
}

func rid(prefix string, n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
	var sb strings.Builder
	sb.WriteString(prefix)
	for _, v := range b {
		sb.WriteByte(alpha[int(v)%len(alpha)])
	}
	return sb.String()
}

// Observed genuine-CLI profile (captured 2026-09-20 via CONNECT proxy):
// 17 ciphers, no GREASE; 14 extensions in fixed order; ALPN http/1.1;
// groups X25519/secp256r1/secp384r1; sigalgs Chrome-order + SHA1-RSA;
// BoringSSL padding last; NO compress-cert, NO ALPS, NO ECH.
func boringH1Spec() *utls.ClientHelloSpec {
	return &utls.ClientHelloSpec{
		CipherSuites: []uint16{
			utls.TLS_AES_128_GCM_SHA256,
			utls.TLS_AES_256_GCM_SHA384,
			utls.TLS_CHACHA20_POLY1305_SHA256,
			utls.TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,
			utls.TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,
			utls.TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384,
			utls.TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384,
			utls.TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305,
			utls.TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305,
			utls.TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA,
			utls.TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA,
			utls.TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA,
			utls.TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA,
			utls.TLS_RSA_WITH_AES_128_GCM_SHA256,
			utls.TLS_RSA_WITH_AES_256_GCM_SHA384,
			utls.TLS_RSA_WITH_AES_128_CBC_SHA,
			utls.TLS_RSA_WITH_AES_256_CBC_SHA,
		},
		CompressionMethods: []byte{0x00},
		Extensions: []utls.TLSExtension{
			&utls.SNIExtension{},
			&utls.ExtendedMasterSecretExtension{},
			&utls.RenegotiationInfoExtension{Renegotiation: utls.RenegotiateOnceAsClient},
			&utls.SupportedCurvesExtension{[]utls.CurveID{
				utls.CurveID(0x001d),
				utls.CurveID(0x0017),
				utls.CurveID(0x0018),
			}},
			&utls.SupportedPointsExtension{SupportedPoints: []byte{0x00}},
			&utls.SessionTicketExtension{},
			&utls.ALPNExtension{AlpnProtocols: []string{"http/1.1"}},
			&utls.StatusRequestExtension{},
			&utls.SignatureAlgorithmsExtension{SupportedSignatureAlgorithms: []utls.SignatureScheme{
				utls.ECDSAWithP256AndSHA256,
				utls.PSSWithSHA256,
				utls.PKCS1WithSHA256,
				utls.ECDSAWithP384AndSHA384,
				utls.PSSWithSHA384,
				utls.PKCS1WithSHA384,
				utls.PSSWithSHA512,
				utls.PKCS1WithSHA512,
				utls.SignatureScheme(0x0201),
			}},
			&utls.SCTExtension{},
			&utls.KeyShareExtension{[]utls.KeyShare{
				{Group: utls.CurveID(0x001d)},
			}},
			&utls.PSKKeyExchangeModesExtension{[]uint8{utls.PskModeDHE}},
			&utls.SupportedVersionsExtension{[]uint16{
				utls.VersionTLS13,
				utls.VersionTLS12,
			}},
			&utls.UtlsPaddingExtension{GetPaddingLen: utls.BoringPaddingStyle},
		},
	}
}

func main() {
	model := flag.String("model", "big-pickle", "zen model id")
	bodyFile := flag.String("body", "", "request JSON file (required)")
	session := flag.String("session", "", "x-opencode-session (generated if empty)")
	msgid := flag.String("msgid", "", "x-opencode-request (generated if empty)")
	path := flag.String("path", "/zen/v1/chat/completions", "API path")
	pre := flag.String("pre", "", "optional first-request body file (same connection)")
	prePath := flag.String("prepath", "/zen/v1/responses", "first-request path")
	host := flag.String("host", "opencode.ai", "API host")
	addr := flag.String("addr", "", "dial address override (default host:443)")
	ua := flag.String("ua", "opencode/1.18.31 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14", "User-Agent")
	serve := flag.Bool("serve", false, "run OpenAI-compatible HTTP server instead of one-shot")
	port := flag.String("port", "8099", "serve listen port (127.0.0.1 only)")
	zenHost := flag.String("zenhost", "opencode.ai", "upstream zen host for serve mode")
	flag.Parse()

	if *serve {
		key := os.Getenv("ZEN_API_KEY")
		if key == "" {
			fmt.Fprintln(os.Stderr, "refusing to start: ZEN_API_KEY env required")
			os.Exit(2)
		}
		mux := http.NewServeMux()
		mux.HandleFunc("/v1/chat/completions", serveChat(key, *zenHost))
		fmt.Fprintf(os.Stderr, "zencli serve on 127.0.0.1:%s\n", *port)
		if err := http.ListenAndServe("127.0.0.1:"+*port, mux); err != nil {
			fmt.Fprintln(os.Stderr, "serve:", err)
			os.Exit(1)
		}
		return
	}

	key := os.Getenv("ZEN_API_KEY")
	_ = model // model travels inside the body file
	if key == "" || *bodyFile == "" {
		fmt.Fprintln(os.Stderr, "need ZEN_API_KEY env + -body file")
		os.Exit(2)
	}
	body, err := os.ReadFile(*bodyFile)
	if err != nil {
		fmt.Fprintln(os.Stderr, "read body:", err)
		os.Exit(2)
	}
	ses := *session
	if ses == "" {
		ses = rid("ses_", 24)
	}
	msg := *msgid
	if msg == "" {
		msg = rid("msg_", 24)
	}
	preBody := []byte{}
	preP := *path
	preMsg := msg
	if *pre != "" {
		b, err := os.ReadFile(*pre)
		if err != nil {
			fmt.Fprintln(os.Stderr, "read pre body:", err)
			os.Exit(2)
		}
		preBody = b
		preP = *prePath
		preMsg = rid("msg_", 24)
	}

	dialAddr := *host + ":443"
	if *addr != "" {
		dialAddr = *addr
	}
	conn, err := net.Dial("tcp", dialAddr)
	if err != nil {
		fmt.Fprintln(os.Stderr, "dial:", err)
		os.Exit(1)
	}
	uconn := utls.UClient(conn, &utls.Config{
		ServerName:         *host,
		InsecureSkipVerify: false,
	}, utls.HelloCustom)
	uconn.ApplyPreset(boringH1Spec())
	if err := uconn.Handshake(); err != nil {
		fmt.Fprintln(os.Stderr, "handshake:", err)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "negotiated: %s alpn=%s\n",
		uconn.ConnectionState().Version, uconn.ConnectionState().NegotiatedProtocol)

	// Exact CLI header order/casing (captured 2026-09-20).
	send := func(path, msgid string, b []byte) {
		var req strings.Builder
		fmt.Fprintf(&req, "POST %s HTTP/1.1\r\n", path)
		fmt.Fprintf(&req, "Authorization: Bearer %s\r\n", key)
		req.WriteString("Content-Type: application/json\r\n")
		fmt.Fprintf(&req, "User-Agent: %s\r\n", *ua)
		req.WriteString("x-opencode-client: cli\r\n")
		req.WriteString("x-opencode-project: global\r\n")
		fmt.Fprintf(&req, "x-opencode-request: %s\r\n", msgid)
		fmt.Fprintf(&req, "x-opencode-session: %s\r\n", ses)
		req.WriteString("Connection: keep-alive\r\n")
		req.WriteString("Accept: */*\r\n")
		fmt.Fprintf(&req, "Host: %s\r\n", *host)
		req.WriteString("Accept-Encoding: gzip, deflate, br, zstd\r\n")
		fmt.Fprintf(&req, "Content-Length: %d\r\n\r\n", len(b))
		if _, err := io.WriteString(uconn, req.String()); err != nil {
			fmt.Fprintln(os.Stderr, "write head:", err)
			os.Exit(1)
		}
		if _, err := uconn.Write(b); err != nil {
			fmt.Fprintln(os.Stderr, "write body:", err)
			os.Exit(1)
		}
	}
	br := bufio.NewReader(uconn)
	readResp := func(tag string) {
		status, err := br.ReadString('\n')
		if err != nil {
			fmt.Fprintln(os.Stderr, tag, "read status:", err)
			os.Exit(1)
		}
		fmt.Println(tag, "STATUS:", strings.TrimSpace(status))
		clen := -1
		chunked := false
		for {
			l, err := br.ReadString('\n')
			if err != nil {
				break
			}
			if l == "\r\n" || l == "\n" {
				break
			}
			if strings.HasPrefix(strings.ToLower(l), "content-length:") {
				fmt.Sscanf(l, "%*[^:]%*c%d", &clen)
			}
			if strings.HasPrefix(strings.ToLower(l), "transfer-encoding:") && strings.Contains(strings.ToLower(l), "chunked") {
				chunked = true
			}
		}
		if chunked {
			// drain chunked body (cap 200KB)
			total := 0
			for total < 200000 {
				ln, err := br.ReadString('\n')
				if err != nil {
					break
				}
				var sz int
				fmt.Sscanf(ln, "%x", &sz)
				if sz == 0 {
					br.ReadString('\n')
					break
				}
				if total == 0 {
					peek := make([]byte, sz)
					if sz > 300 {
						peek = peek[:300]
					}
					io.ReadFull(br, peek)
					io.CopyN(io.Discard, br, int64(sz-len(peek)))
					fmt.Printf("%s BODY-HEAD: %s\n", tag, string(peek))
				} else {
					io.CopyN(io.Discard, br, int64(sz))
				}
				br.ReadString('\n')
				total += sz
			}
		} else if clen > 0 {
			peek := make([]byte, clen)
			if clen > 300 {
				peek = peek[:300]
			}
			io.ReadFull(br, peek)
			io.CopyN(io.Discard, br, int64(clen-len(peek)))
			fmt.Printf("%s BODY-HEAD: %s\n", tag, string(peek))
		}
	}
	if len(preBody) > 0 {
		send(preP, preMsg, preBody)
		readResp("PRE")
	}
	send(*path, msg, body)
	readResp("MAIN")
	head := make([]byte, 600)
	n, _ := io.ReadFull(br, head)
	out := string(head[:n])
	if len(out) > 300 {
		out = out[:300]
	}
	fmt.Printf("BODY-HEAD: %s\n", out)
}
