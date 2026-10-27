//! Sends Spotify Connect commands to speakers the Web API won't control.
//!
//! Spotify marks some Connect speakers (Sonos above all) as restricted: the
//! Web API refuses every player command aimed at one. Spotify's own apps steer
//! those speakers through the Connect state service instead, which a librespot
//! session can call too. This helper signs in with the login Raspotify already
//! saved on the box, then reads one JSON request per line on stdin and answers
//! one JSON line on stdout:
//!
//!   {"op": "command", "to": "<device id>", "body": {"command": {...}}}
//!   {"op": "volume",  "to": "<device id>", "percent": 40}
//!   {"op": "transfer", "to": "<device id>"}
//!   {"op": "ping"}
//!
//! → {"ok": true} or {"ok": false, "error": "..."}
//!
//! The command bodies are built by the Python side (spotifactory/connect.py),
//! so this stays a thin pipe to Spotify.

use std::path::PathBuf;

use http::Method;
use librespot_core::cache::Cache;
use librespot_core::{Session, SessionConfig};
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

const USAGE: &str = "usage: spotifactory-connect --cache <librespot cache dir> [--from <device id>]";

struct Args {
    cache: PathBuf,
    from: Option<String>,
}

fn parse_args() -> Result<Args, String> {
    let mut cache = None;
    let mut from = None;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--cache" => cache = args.next().map(PathBuf::from),
            "--from" => from = args.next(),
            "-h" | "--help" => return Err(USAGE.into()),
            other => return Err(format!("unknown argument {other:?}\n{USAGE}")),
        }
    }
    Ok(Args {
        cache: cache.ok_or(USAGE)?,
        from,
    })
}

async fn connect(cache_dir: &PathBuf) -> Result<Session, String> {
    let cache = Cache::new(Some(cache_dir), None, None, None).map_err(|e| e.to_string())?;
    let credentials = cache.credentials().ok_or_else(|| {
        format!(
            "no saved Spotify login in {} (pick Spotifactory in the Spotify app once)",
            cache_dir.display()
        )
    })?;
    let session = Session::new(SessionConfig::default(), Some(cache));
    session
        .connect(credentials, false)
        .await
        .map_err(|e| format!("Spotify sign-in failed: {e}"))?;
    Ok(session)
}

async fn handle(session: &Session, from: &str, request: &Value) -> Result<(), String> {
    let op = request["op"].as_str().unwrap_or_default();
    if op == "ping" {
        return Ok(());
    }
    let to = request["to"]
        .as_str()
        .filter(|to| !to.is_empty())
        .ok_or("missing \"to\" device id")?;
    let spclient = session.spclient();
    let result = match op {
        "command" => {
            let body = request["body"].to_string();
            let path = format!("/connect-state/v1/player/command/from/{from}/to/{to}");
            spclient
                .request(&Method::POST, &path, None, Some(body.as_bytes()))
                .await
        }
        "volume" => {
            let percent = request["percent"].as_u64().unwrap_or(0).min(100);
            let body = json!({ "volume": percent * 65535 / 100 }).to_string();
            let path = format!("/connect-state/v1/connect/volume/from/{from}/to/{to}");
            spclient
                .request(&Method::PUT, &path, None, Some(body.as_bytes()))
                .await
        }
        // `to` as the source too means "from whichever device is active";
        // with nothing active, transfer from this session instead.
        "transfer" => match spclient.transfer(to, to, None).await {
            Ok(bytes) => Ok(bytes),
            Err(_) => spclient.transfer(from, to, None).await,
        },
        other => return Err(format!("unknown op {other:?}")),
    };
    result.map(drop).map_err(|e| e.to_string())
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args = match parse_args() {
        Ok(args) => args,
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(2);
        }
    };
    let mut stdout = tokio::io::stdout();
    let session = match connect(&args.cache).await {
        Ok(session) => session,
        Err(error) => {
            // Tell the caller why on its first read, then stop.
            let line = json!({ "ok": false, "error": error }).to_string() + "\n";
            let _ = stdout.write_all(line.as_bytes()).await;
            let _ = stdout.flush().await;
            std::process::exit(1);
        }
    };
    let from = args.from.unwrap_or_else(|| session.device_id().to_string());

    let mut lines = BufReader::new(tokio::io::stdin()).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        if line.trim().is_empty() {
            continue;
        }
        let reply = match serde_json::from_str::<Value>(&line) {
            Ok(request) => match handle(&session, &from, &request).await {
                Ok(()) => json!({ "ok": true }),
                Err(error) => json!({ "ok": false, "error": error }),
            },
            Err(error) => json!({ "ok": false, "error": format!("bad request: {error}") }),
        };
        let line = reply.to_string() + "\n";
        if stdout.write_all(line.as_bytes()).await.is_err() || stdout.flush().await.is_err() {
            break;
        }
    }
}
