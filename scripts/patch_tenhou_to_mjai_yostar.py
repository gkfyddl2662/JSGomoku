from __future__ import annotations

import argparse
from pathlib import Path

PATCH_MARKER = "MORTAL_ROGS_YOSTAR_EN_PATCH_V2"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source marker, found {count}")
    return text.replace(old, new, 1)


def patch_rpc(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        return

    oauth_builders = r'''
    // MORTAL_ROGS_YOSTAR_EN_PATCH_V2
    /// Build the EN/KR Yostar redirect-token exchange observed on the live web client.
    pub fn build_oauth2_auth_request(
        oauth_type: u64,
        code: &str,
        uid: &str,
        version: &str,
    ) -> Vec<u8> {
        let mut buf = Vec::new();
        encode_varint_field(&mut buf, 1, oauth_type);
        encode_string(&mut buf, 2, code);
        encode_string(&mut buf, 3, uid);
        encode_string(&mut buf, 4, &format!("WebGL_2022-{}", version));
        buf
    }

    pub fn build_oauth2_check_request(oauth_type: u64, access_token: &str) -> Vec<u8> {
        let mut buf = Vec::new();
        encode_varint_field(&mut buf, 1, oauth_type);
        encode_string(&mut buf, 2, access_token);
        buf
    }

    pub fn build_oauth2_login_request(
        oauth_type: u64,
        access_token: &str,
        random_key: &str,
        version: &str,
        locale: &str,
    ) -> Vec<u8> {
        let mut buf = Vec::new();
        encode_varint_field(&mut buf, 1, oauth_type);
        encode_string(&mut buf, 2, access_token);

        let device = build_yostar_device(random_key, locale);
        encode_bytes_field(&mut buf, 4, &device);
        encode_string(&mut buf, 5, random_key);

        let mut client_version = Vec::new();
        encode_string(&mut client_version, 1, version);
        encode_string(&mut client_version, 2, "4.0.12");
        encode_bytes_field(&mut buf, 6, &client_version);

        for platform in [1_u64, 4, 5, 9] {
            encode_varint_field(&mut buf, 8, platform);
        }
        encode_string(&mut buf, 10, &format!("WebGL_2022-{}", version));
        encode_string(&mut buf, 11, locale);
        buf
    }

'''
    text = _replace_once(
        text,
        "    /// Build loginBeat request\n",
        oauth_builders + "    /// Build loginBeat request\n",
        "rpc oauth builders",
    )

    device_helpers = r'''
    fn encode_bytes_field(buf: &mut Vec<u8>, field: u32, value: &[u8]) {
        let tag = (field << 3) | 2;
        encode_varint(buf, tag as u64);
        encode_varint(buf, value.len() as u64);
        buf.extend_from_slice(value);
    }

    fn build_yostar_device(random_key: &str, locale: &str) -> Vec<u8> {
        let mut buf = Vec::new();
        encode_string(&mut buf, 1, "pc");
        encode_string(&mut buf, 2, "pc");
        encode_string(&mut buf, 3, "windows");
        encode_string(&mut buf, 4, "win10");
        encode_bool(&mut buf, 5, true);
        encode_string(&mut buf, 6, "Chrome");
        encode_string(&mut buf, 7, &format!("{}_web", locale));
        encode_varint_field(&mut buf, 10, 1305);
        encode_varint_field(&mut buf, 11, 1305);
        encode_string(
            &mut buf,
            12,
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36",
        );
        encode_bool(&mut buf, 13, true);
        encode_string(&mut buf, 14, random_key);
        buf
    }

'''
    text = _replace_once(
        text,
        "    /// Encode device message with just is_browser = true (for native login)\n",
        device_helpers + "    /// Encode device message with just is_browser = true (for native login)\n",
        "rpc Yostar device helpers",
    )

    login_yostar = r'''
    /// Login through the EN/KR Yostar web OAuth flow.
    ///
    /// `code` is the short-lived Yostar redirect token paired with `uid`.
    pub async fn login_yostar(
        &self,
        uid: &str,
        code: &str,
        version: &str,
        route_id: &str,
        oauth_type: u64,
        locale: &str,
    ) -> Result<()> {
        self.route_connect(route_id).await?;

        debug!("Sending heartbeat before Yostar OAuth");
        let hb_response = self.call(".lq.Lobby.heatbeat", &[0x08, 0x00]).await?;
        debug!("Heartbeat response: {} bytes", hb_response.len());

        let auth_request =
            requests::build_oauth2_auth_request(oauth_type, code, uid, version);
        let auth_response = self.call(".lq.Lobby.oauth2Auth", &auth_request).await?;
        if let Some(error_code) = Self::extract_error_code(&auth_response) {
            if error_code != 0 {
                anyhow::bail!("Yostar oauth2Auth failed with error code: {}", error_code);
            }
        }
        let access_token = Self::extract_string_field(&auth_response, 2)
            .filter(|token| !token.is_empty())
            .context("Yostar oauth2Auth did not return an access token")?;

        let check_request = requests::build_oauth2_check_request(oauth_type, &access_token);
        let check_response = self.call(".lq.Lobby.oauth2Check", &check_request).await?;
        if let Some(error_code) = Self::extract_error_code(&check_response) {
            if error_code != 0 {
                anyhow::bail!("Yostar oauth2Check failed with error code: {}", error_code);
            }
        }
        if Self::extract_varint_field(&check_response, 2) != Some(1) {
            anyhow::bail!("Yostar OAuth token is not bound to an existing Mahjong Soul account");
        }

        let random_key = Uuid::new_v4().to_string();
        let login_request = requests::build_oauth2_login_request(
            oauth_type,
            &access_token,
            &random_key,
            version,
            locale,
        );
        let login_response = self.call(".lq.Lobby.oauth2Login", &login_request).await?;
        if let Some(error_code) = Self::extract_error_code(&login_response) {
            if error_code != 0 {
                anyhow::bail!("Yostar oauth2Login failed with error code: {}", error_code);
            }
        }

        let contract = "DF2vkXCnfeXp4WoGrBGNcJBufZiMN3uP";
        let beat_req = requests::build_login_beat_request(contract);
        self.call(".lq.Lobby.loginBeat", &beat_req).await?;
        self.call(".lq.Lobby.loginSuccess", &[]).await?;

        debug!("Yostar OAuth login successful");
        Ok(())
    }

'''
    text = _replace_once(
        text,
        "    /// Extract error code from protobuf response\n",
        login_yostar + "    /// Extract error code from protobuf response\n",
        "rpc Yostar login",
    )

    varint_helper = r'''
    fn extract_varint_field(data: &[u8], target_field: u32) -> Option<u64> {
        let mut pos = 0;
        while pos < data.len() {
            let tag = data[pos];
            pos += 1;
            let field_num = (tag >> 3) as u32;
            let wire_type = tag & 0x07;

            if wire_type == 0 {
                let (value, consumed) = wrapper::decode_varint(&data[pos..]).ok()?;
                if field_num == target_field {
                    return Some(value);
                }
                pos += consumed;
            } else if wire_type == 2 {
                let (len, consumed) = wrapper::decode_varint(&data[pos..]).ok()?;
                let next = pos.checked_add(consumed)?.checked_add(len as usize)?;
                if next > data.len() {
                    return None;
                }
                pos = next;
            } else {
                return None;
            }
        }
        None
    }

'''
    text = _replace_once(
        text,
        "    /// Extract string field from protobuf response by field number\n",
        varint_helper + "    /// Extract string field from protobuf response by field number\n",
        "rpc varint helper",
    )

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_raw_download(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "rpc.login_yostar" in text and "MORTAL_ROGS_MAJSOUL_YOSTAR_OAUTH_TYPE" in text:
        return

    text = _replace_once(
        text,
        "    route_id: String,\n    rx: Arc<Mutex<mpsc::Receiver<String>>>,\n",
        "    route_id: String,\n    server: String,\n    rx: Arc<Mutex<mpsc::Receiver<String>>>,\n",
        "raw worker server argument",
    )

    old_login = '''    if let Err(e) = rpc.login_native(&username, &password, &version, &route_id).await {\n        debug!("[{}] Login failed for {}: {}", worker_id, username, e);\n        stats.login_failed.fetch_add(1, Ordering::Relaxed);\n        let _ = rpc.close().await;\n        return;\n    }\n\n    stats.logged_in.fetch_add(1, Ordering::Relaxed);\n\n    let client_version = format!("web-{}", version);\n'''
    new_login = '''    let login_result = if server == "en" {\n        let oauth_type = std::env::var("MORTAL_ROGS_MAJSOUL_YOSTAR_OAUTH_TYPE")\n            .ok()\n            .and_then(|value| value.parse::<u64>().ok())\n            .unwrap_or(23);\n        let locale = std::env::var("MORTAL_ROGS_MAJSOUL_YOSTAR_LOCALE")\n            .unwrap_or_else(|_| "kr".to_string());\n        debug!("[{}] Yostar OAuth routing type={} locale={}", worker_id, oauth_type, locale);\n        rpc.login_yostar(&username, &password, &version, &route_id, oauth_type, &locale).await\n    } else {\n        rpc.login_native(&username, &password, &version, &route_id).await\n    };\n    if let Err(e) = login_result {\n        debug!("[{}] Login failed (server={}): {}", worker_id, server, e);\n        stats.login_failed.fetch_add(1, Ordering::Relaxed);\n        let _ = rpc.close().await;\n        return;\n    }\n\n    stats.logged_in.fetch_add(1, Ordering::Relaxed);\n\n    let client_version = if server == "en" {\n        format!("WebGL_2022-{}", version)\n    } else {\n        format!("web-{}", version)\n    };\n'''
    text = _replace_once(text, old_login, new_login, "raw EN login routing")

    text = _replace_once(
        text,
        "            route_id.clone(),\n            Arc::clone(&uuid_rx),\n",
        "            route_id.clone(),\n            server.to_string(),\n            Arc::clone(&uuid_rx),\n",
        "raw worker server call",
    )

    path.write_text(text, encoding="utf-8", newline="\n")


def patch(root: Path) -> None:
    root = root.expanduser().resolve()
    rpc = root / "src" / "majsoul" / "rpc.rs"
    raw = root / "src" / "majsoul" / "raw_download.rs"
    if not rpc.is_file() or not raw.is_file():
        raise RuntimeError(f"pinned tenhou-to-mjai source layout missing under {root}")
    patch_rpc(rpc)
    patch_raw_download(raw)
    print(f"MAJSOUL_YOSTAR_SOURCE_PATCH_OK root={root}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch pinned tenhou-to-mjai for EN Yostar OAuth.")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    patch(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
