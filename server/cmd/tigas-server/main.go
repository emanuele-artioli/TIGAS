package main

import (
	"context"
	"crypto/tls"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/quic-go/quic-go/http3"
	webtransport "github.com/quic-go/webtransport-go"
)

type controlMessage struct {
	Payload []byte
	At      time.Time
}

type controlStore struct {
	mu       sync.Mutex
	messages []controlMessage
}

func (s *controlStore) append(msg []byte) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.messages = append(s.messages, controlMessage{Payload: append([]byte{}, msg...), At: time.Now()})
}

func main() {
	addr := flag.String("addr", ":4433", "HTTP/3 listen address")
	certFile := flag.String("cert", "", "TLS certificate path")
	keyFile := flag.String("key", "", "TLS key path")
	staticDir := flag.String("static", "../client", "Static assets path")
	segmentsDir := flag.String("segments", "../artifacts/test_mode", "DASH segments path")
	movementDir := flag.String("movement", "../movement_traces", "Movement traces path")
	controlLog := flag.String("control-log", "../artifacts/test_mode/control_messages.bin", "Datagram log output path")
	flag.Parse()

	if *certFile == "" || *keyFile == "" {
		log.Fatal("--cert and --key are required")
	}

	if err := os.MkdirAll(*segmentsDir, 0o755); err != nil {
		log.Fatalf("unable to create segments dir: %v", err)
	}
	if err := os.MkdirAll(filepath.Dir(*controlLog), 0o755); err != nil {
		log.Fatalf("unable to create control log dir: %v", err)
	}
	logFile, err := os.Create(*controlLog)
	if err != nil {
		log.Fatalf("unable to open control log: %v", err)
	}
	defer logFile.Close()

	store := &controlStore{}

	mux := http.NewServeMux()
	mux.Handle("/", http.FileServer(http.Dir(*staticDir)))
	mux.Handle("/dash/", http.StripPrefix("/dash/", http.FileServer(http.Dir(*segmentsDir))))
	mux.Handle("/movement_traces/", http.StripPrefix("/movement_traces/", http.FileServer(http.Dir(*movementDir))))

	wt := &webtransport.Server{H3: http3.Server{}}
	mux.HandleFunc("/wt", func(w http.ResponseWriter, r *http.Request) {
		sess, err := wt.Upgrade(w, r)
		if err != nil {
			log.Printf("webtransport upgrade failed: %v", err)
			return
		}
		log.Printf("webtransport session opened from %s", r.RemoteAddr)

		go func() {
			defer sess.CloseWithError(0, "bye")
			ctx := context.Background()
			for {
				msg, err := sess.ReceiveDatagram(ctx)
				if err != nil {
					if err != io.EOF {
						log.Printf("datagram receive ended: %v", err)
					}
					return
				}
				store.append(msg)
				if _, err := logFile.Write(msg); err == nil {
					_, _ = logFile.Write([]byte("\n"))
				}
			}
		}()
	})

	tlsConf := &tls.Config{MinVersion: tls.VersionTLS13}
	h3 := &http3.Server{
		Addr:      *addr,
		Handler:   mux,
		TLSConfig: tlsConf,
	}

	log.Printf("serving TIGAS over HTTP/3 on %s", *addr)
	log.Printf("static root: %s", filepath.Clean(*staticDir))
	log.Printf("dash root: %s", filepath.Clean(*segmentsDir))

	if err := h3.ListenAndServeTLS(*certFile, *keyFile); err != nil {
		fmt.Fprintf(os.Stderr, "server failed: %v\n", err)
		os.Exit(1)
	}
}
